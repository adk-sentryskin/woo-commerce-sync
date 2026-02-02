#!/bin/bash
set -e

# =============================================================================
# Cloud Run Deployment Script for WooCommerce Sync Service
# =============================================================================

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${GREEN}=== WooCommerce Sync Service - Cloud Run Deployment ===${NC}"

# Load environment variables from .env file
if [ -f .env ]; then
    echo -e "${YELLOW}Loading environment variables from .env file...${NC}"
    set -a
    source <(grep -v '^#' .env | grep -v '^$' | sed 's/\r$//')
    set +a
else
    echo -e "${RED}Error: .env file not found. Please create one from .env.example${NC}"
    exit 1
fi

# Configuration
SERVICE_NAME="${SERVICE_NAME:-woocommerce-sync}"
IMAGE_NAME="gcr.io/${GCP_PROJECT_ID}/${SERVICE_NAME}"

# Cloud Run settings
MIN_INSTANCES="${MIN_INSTANCES:-0}"
MAX_INSTANCES="${MAX_INSTANCES:-10}"
MEMORY="${MEMORY:-512Mi}"
CPU="${CPU:-1}"
TIMEOUT="${TIMEOUT:-300}"
CONCURRENCY="${CONCURRENCY:-80}"

# Check if gcloud is installed
if ! command -v gcloud &> /dev/null; then
    echo -e "${RED}Error: gcloud CLI is not installed. Please install it first.${NC}"
    echo "Visit: https://cloud.google.com/sdk/docs/install"
    exit 1
fi

# Check if user is authenticated
if ! gcloud auth list --filter=status:ACTIVE --format="value(account)" &> /dev/null; then
    echo -e "${YELLOW}Not authenticated. Running gcloud auth login...${NC}"
    gcloud auth login
fi

# Set the project
echo -e "${YELLOW}Setting project to: ${GCP_PROJECT_ID}${NC}"
gcloud config set project ${GCP_PROJECT_ID}

# Enable required APIs
echo -e "${YELLOW}Enabling required APIs...${NC}"
gcloud services enable cloudbuild.googleapis.com
gcloud services enable run.googleapis.com
gcloud services enable containerregistry.googleapis.com

# Build the Docker image using Cloud Build
echo -e "${YELLOW}Building Docker image using Cloud Build...${NC}"
gcloud builds submit --tag ${IMAGE_NAME}:latest .

# Create a temporary env vars file for Cloud Run (handles special characters)
ENV_FILE=$(mktemp)
cat > ${ENV_FILE} << EOF
ENVIRONMENT: production
DEBUG: "false"
LOG_LEVEL: "${LOG_LEVEL}"
APP_HOST: "${APP_HOST}"
APP_PORT: "${APP_PORT}"
DB_DSN: "${DB_DSN}"
API_KEY: "${API_KEY}"
ENCRYPTION_KEY: "${ENCRYPTION_KEY}"
ENABLE_SCHEDULER: "${ENABLE_SCHEDULER}"
RECONCILIATION_HOUR: "${RECONCILIATION_HOUR}"
RECONCILIATION_MINUTE: "${RECONCILIATION_MINUTE}"
WC_API_VERSION: "${WC_API_VERSION}"
WC_PRODUCTS_PER_PAGE: "${WC_PRODUCTS_PER_PAGE}"
WC_REQUEST_TIMEOUT: "${WC_REQUEST_TIMEOUT}"
WEBHOOK_SECRET_LENGTH: "${WEBHOOK_SECRET_LENGTH}"
ENABLE_EMBEDDINGS: "${ENABLE_EMBEDDINGS}"
GCP_PROJECT_ID: "${GCP_PROJECT_ID}"
GCP_REGION: "${GCP_REGION}"
EOF

# Deploy to Cloud Run
echo -e "${YELLOW}Deploying to Cloud Run...${NC}"
gcloud run deploy ${SERVICE_NAME} \
    --image ${IMAGE_NAME}:latest \
    --platform managed \
    --region ${GCP_REGION} \
    --port ${APP_PORT} \
    --memory ${MEMORY} \
    --cpu ${CPU} \
    --timeout ${TIMEOUT} \
    --concurrency ${CONCURRENCY} \
    --min-instances ${MIN_INSTANCES} \
    --max-instances ${MAX_INSTANCES} \
    --allow-unauthenticated \
    --env-vars-file ${ENV_FILE}

# Clean up temp file
rm -f ${ENV_FILE}

# Get the service URL
SERVICE_URL=$(gcloud run services describe ${SERVICE_NAME} --region ${GCP_REGION} --format 'value(status.url)')

# Update APP_URL with the deployed service URL
echo -e "${YELLOW}Updating APP_URL with deployed service URL...${NC}"
gcloud run services update ${SERVICE_NAME} \
    --region ${GCP_REGION} \
    --update-env-vars "APP_URL=${SERVICE_URL}"

echo -e "${GREEN}"
echo "=============================================="
echo "Deployment Complete!"
echo "=============================================="
echo "Service URL: ${SERVICE_URL}"
echo "Project: ${GCP_PROJECT_ID}"
echo "Region: ${GCP_REGION}"
echo "=============================================="
echo -e "${NC}"
