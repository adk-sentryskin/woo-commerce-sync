#!/bin/bash
set -e

# =============================================================================
# Cloud Run Deployment Script for WooCommerce Sync Service
# Usage: ./deploy.sh [staging|production]
# =============================================================================

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Get environment from argument (default: staging)
ENVIRONMENT="${1:-staging}"

# Validate environment
if [ "$ENVIRONMENT" != "staging" ] && [ "$ENVIRONMENT" != "production" ]; then
    echo -e "${RED}Error: Invalid environment '$ENVIRONMENT'${NC}"
    echo "Usage: $0 [staging|production]"
    exit 1
fi

echo -e "${BLUE}=== WooCommerce Sync Service - Cloud Run Deployment ===${NC}"
echo -e "${YELLOW}Environment: ${ENVIRONMENT}${NC}"
echo ""

# =============================================================================
# Load Environment Variables
# =============================================================================

if [ -f .env ]; then
    echo -e "${YELLOW}Loading environment variables from .env file...${NC}"
    set -a
    source <(grep -v '^#' .env | grep -v '^$' | sed 's/\r$//')
    set +a
else
    echo -e "${RED}Error: .env file not found. Please create one from .env.example${NC}"
    exit 1
fi

# =============================================================================
# Configuration
# =============================================================================

PROJECT_ID="${GCP_PROJECT_ID:-shopify-473015}"
REGION="${GCP_REGION:-us-central1}"

# Environment-specific configuration
if [ "$ENVIRONMENT" = "staging" ]; then
    SERVICE_NAME="woocommerce-sync-staging"
    MEMORY="512Mi"
    CPU="1"
    MIN_INSTANCES="0"
    MAX_INSTANCES="5"
    TIMEOUT="300"
    CONCURRENCY="80"
    LOG_LEVEL="INFO"
    DEBUG="true"
else  # production
    SERVICE_NAME="woocommerce-sync"
    MEMORY="1Gi"
    CPU="2"
    MIN_INSTANCES="1"
    MAX_INSTANCES="20"
    TIMEOUT="300"
    CONCURRENCY="80"
    LOG_LEVEL="WARNING"
    DEBUG="false"
fi

IMAGE_NAME="gcr.io/${PROJECT_ID}/${SERVICE_NAME}"
APP_PORT="${APP_PORT:-8080}"

# =============================================================================
# Production Confirmation
# =============================================================================

if [ "$ENVIRONMENT" = "production" ]; then
    echo -e "${RED}WARNING: You are about to deploy to PRODUCTION!${NC}"
    echo ""
    read -p "Type 'yes' to confirm production deployment: " -r
    echo
    if [[ ! $REPLY =~ ^[Yy][Ee][Ss]$ ]]; then
        echo -e "${YELLOW}Deployment cancelled.${NC}"
        exit 0
    fi
fi

# =============================================================================
# Pre-deployment Checks
# =============================================================================

# Check if gcloud is installed
if ! command -v gcloud &> /dev/null; then
    echo -e "${RED}Error: gcloud CLI is not installed.${NC}"
    echo "Visit: https://cloud.google.com/sdk/docs/install"
    exit 1
fi

# Check authentication
if ! gcloud auth list --filter=status:ACTIVE --format="value(account)" &> /dev/null; then
    echo -e "${YELLOW}Not authenticated. Running gcloud auth login...${NC}"
    gcloud auth login
fi

# =============================================================================
# Deployment Summary
# =============================================================================

echo ""
echo -e "${BLUE}Deployment Configuration:${NC}"
echo "   Environment:    $ENVIRONMENT"
echo "   Service Name:   $SERVICE_NAME"
echo "   Project:        $PROJECT_ID"
echo "   Region:         $REGION"
echo "   Resources:      ${MEMORY} RAM, ${CPU} CPU"
echo "   Scaling:        ${MIN_INSTANCES}-${MAX_INSTANCES} instances"
echo "   Log Level:      $LOG_LEVEL"
echo ""

# =============================================================================
# Build and Deploy
# =============================================================================

# Set project
echo -e "${YELLOW}Setting project to: ${PROJECT_ID}${NC}"
gcloud config set project ${PROJECT_ID}

# Enable required APIs
echo -e "${YELLOW}Enabling required APIs...${NC}"
gcloud services enable cloudbuild.googleapis.com run.googleapis.com containerregistry.googleapis.com

# Build the Docker image using Cloud Build
echo -e "${YELLOW}Building Docker image using Cloud Build...${NC}"
gcloud builds submit --tag ${IMAGE_NAME}:latest .

# Create a temporary env vars file for Cloud Run
ENV_FILE=$(mktemp)
cat > ${ENV_FILE} << EOF
ENVIRONMENT: ${ENVIRONMENT}
DEBUG: "${DEBUG}"
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
GCP_PROJECT_ID: "${PROJECT_ID}"
GCP_REGION: "${REGION}"
EOF

trap "rm -f $ENV_FILE" EXIT

# Deploy to Cloud Run
echo -e "${YELLOW}Deploying to Cloud Run...${NC}"
gcloud run deploy ${SERVICE_NAME} \
    --image ${IMAGE_NAME}:latest \
    --platform managed \
    --region ${REGION} \
    --port ${APP_PORT} \
    --memory ${MEMORY} \
    --cpu ${CPU} \
    --timeout ${TIMEOUT} \
    --concurrency ${CONCURRENCY} \
    --min-instances ${MIN_INSTANCES} \
    --max-instances ${MAX_INSTANCES} \
    --allow-unauthenticated \
    --env-vars-file ${ENV_FILE}

# =============================================================================
# Post-deployment
# =============================================================================

# Get the service URL
SERVICE_URL=$(gcloud run services describe ${SERVICE_NAME} --region ${REGION} --format 'value(status.url)')

# Update APP_URL with the deployed service URL
echo -e "${YELLOW}Updating APP_URL with deployed service URL...${NC}"
gcloud run services update ${SERVICE_NAME} \
    --region ${REGION} \
    --update-env-vars "APP_URL=${SERVICE_URL}"

# Health check
echo -e "${YELLOW}Testing health endpoint...${NC}"
sleep 5
if curl -sf "${SERVICE_URL}/health" > /dev/null 2>&1; then
    echo -e "${GREEN}Health check passed!${NC}"
elif curl -sf "${SERVICE_URL}/" > /dev/null 2>&1; then
    echo -e "${GREEN}Service is responding!${NC}"
else
    echo -e "${YELLOW}Warning: Health check failed - service may still be starting${NC}"
fi

# Print summary
echo ""
echo -e "${GREEN}=============================================="
echo "Deployment Complete!"
echo "=============================================="
echo "Environment:  ${ENVIRONMENT}"
echo "Service:      ${SERVICE_NAME}"
echo "URL:          ${SERVICE_URL}"
echo "Project:      ${PROJECT_ID}"
echo "Region:       ${REGION}"
echo "==============================================${NC}"
