from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.openapi.utils import get_openapi
from app.database import engine, Base
from app.routers import connection, products, webhooks, sync
from app.config import settings
from app.services.scheduler import start_scheduler, stop_scheduler
from sqlalchemy import text
import logging
import secrets

logging.basicConfig(
    level=getattr(logging, settings.LOG_LEVEL),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

def init_database():
    """Initialize database schema and extensions."""
    try:
        with engine.connect() as conn:
            conn.execute(text("CREATE SCHEMA IF NOT EXISTS woocommerce_sync"))
            conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
            conn.commit()
        Base.metadata.create_all(bind=engine)
        logger.info("Database initialized successfully")
    except Exception as e:
        logger.warning(f"Database initialization skipped or failed: {e}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting WooCommerce Sync Service")
    init_database()
    if settings.ENABLE_SCHEDULER:
        start_scheduler()
    yield
    stop_scheduler()
    logger.info("WooCommerce Sync Service stopped")


app = FastAPI(
    title="WooCommerce Sync API",
    description="Microservice for syncing WooCommerce products",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
    swagger_ui_parameters={"persistAuthorization": True}
)


def custom_openapi():
    if app.openapi_schema:
        return app.openapi_schema

    openapi_schema = get_openapi(
        title=app.title,
        version=app.version,
        description=app.description,
        routes=app.routes,
    )

    openapi_schema["components"]["securitySchemes"] = {
        "ApiKeyAuth": {
            "type": "apiKey",
            "in": "header",
            "name": "X-API-Key",
            "description": "API Key for authentication"
        },
        "MerchantIdAuth": {
            "type": "apiKey",
            "in": "header",
            "name": "X-Merchant-Id",
            "description": "Merchant ID for multi-tenant operations"
        }
    }

    public_paths = {
        "/", "/health",
        "/api/webhooks/product/created",
        "/api/webhooks/product/updated",
        "/api/webhooks/product/deleted",
        "/api/webhooks/product/restored",
    }

    for path, path_item in openapi_schema.get("paths", {}).items():
        for operation in path_item.values():
            if isinstance(operation, dict) and "operationId" in operation:
                if path not in public_paths:
                    if "/api/connection" in path:
                        operation["security"] = [{"ApiKeyAuth": []}]
                    else:
                        operation["security"] = [{"ApiKeyAuth": [], "MerchantIdAuth": []}]

    app.openapi_schema = openapi_schema
    return app.openapi_schema


app.openapi = custom_openapi

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"],
    allow_headers=[
        "Content-Type", "X-API-Key", "X-Merchant-Id", "Authorization", "Accept",
        "X-WC-Webhook-Signature", "X-WC-Webhook-Source", "X-WC-Webhook-Topic",
        "X-WC-Webhook-Resource", "X-WC-Webhook-Event", "X-WC-Webhook-ID", "X-WC-Webhook-Delivery-ID"
    ],
    expose_headers=["Content-Type"],
    max_age=600,
)


@app.middleware("http")
async def api_key_middleware(request: Request, call_next):
    public_paths = ["/", "/health", "/docs", "/redoc", "/openapi.json"]
    webhook_paths = [
        "/api/webhooks/product/created",
        "/api/webhooks/product/updated",
        "/api/webhooks/product/deleted",
        "/api/webhooks/product/restored",
    ]

    path = request.url.path

    if request.method == "OPTIONS":
        return await call_next(request)

    if path in public_paths or path in webhook_paths:
        return await call_next(request)

    api_key = request.headers.get("x-api-key")

    if not api_key:
        return JSONResponse(status_code=401, content={"detail": "Missing X-API-Key header"})

    if not secrets.compare_digest(api_key, settings.API_KEY):
        return JSONResponse(status_code=403, content={"detail": "Invalid API Key"})

    return await call_next(request)


app.include_router(connection.router)
app.include_router(products.router)
app.include_router(webhooks.router)
app.include_router(sync.router)


@app.get("/")
async def root():
    return {"service": "WooCommerce Sync API", "version": "1.0.0", "status": "running", "docs": "/docs"}


@app.get("/health")
async def health_check():
    return {"status": "healthy", "service": "woocommerce-sync-api"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host=settings.APP_HOST, port=settings.APP_PORT, reload=settings.DEBUG)
