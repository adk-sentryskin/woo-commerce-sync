from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from sqlalchemy.orm import Session
from app.database import get_db
from app.models import WooCommerceStore, Product
from app.schemas import ConnectionSetup, ConnectionVerify, ConnectionStatus, WooCommerceStoreResponse
from app.services.woocommerce_client import WooCommerceClient
from app.middleware.auth import verify_api_key
from app.config import settings
from datetime import datetime, timezone
import logging

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/connection", tags=["Connection"])


@router.post("/setup", response_model=WooCommerceStoreResponse)
async def setup_connection(
    data: ConnectionSetup,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    _: str = Depends(verify_api_key)
):
    store_url = data.store_url.rstrip('/')

    existing_store = db.query(WooCommerceStore).filter(
        (WooCommerceStore.merchant_id == data.merchant_id) |
        (WooCommerceStore.store_url == store_url)
    ).first()

    if existing_store:
        if existing_store.merchant_id == data.merchant_id:
            raise HTTPException(status_code=409, detail=f"Merchant {data.merchant_id} already has a connected store")
        else:
            raise HTTPException(status_code=409, detail=f"Store {store_url} is already connected to another merchant")

    client = WooCommerceClient(store_url=store_url, consumer_key=data.consumer_key, consumer_secret=data.consumer_secret)

    try:
        verification = await client.verify_connection()
        if not verification.get('connected'):
            raise HTTPException(status_code=400, detail=f"Failed to connect to WooCommerce: {verification.get('error', 'Unknown error')}")
    except Exception as e:
        logger.error(f"Failed to verify WooCommerce connection: {e}")
        raise HTTPException(status_code=400, detail=f"Failed to connect to WooCommerce store: {str(e)}")

    try:
        store = WooCommerceStore(
            merchant_id=data.merchant_id,
            store_url=store_url,
            store_name=data.store_name or verification.get('site_url'),
            api_version=settings.WC_API_VERSION,
            wp_version=verification.get('wp_version'),
            wc_version=verification.get('wc_version'),
            is_active=1,
            is_verified=1
        )
        store.consumer_key = data.consumer_key
        store.consumer_secret = data.consumer_secret
        db.add(store)
        db.commit()
        db.refresh(store)
        logger.info(f"Created WooCommerce store connection for merchant {data.merchant_id}: {store_url}")
    except Exception as e:
        db.rollback()
        logger.error(f"Failed to create store record: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to save store to database: {str(e)}")

    from app.services.product_sync import sync_all_products_background
    from app.services.webhook_manager import register_webhooks

    # Register webhooks for real-time sync
    try:
        await register_webhooks(store, db)
        logger.info(f"Registered webhooks for merchant {data.merchant_id}")
    except Exception as e:
        logger.warning(f"Failed to register webhooks: {e}")

    # Start initial product sync in background
    background_tasks.add_task(sync_all_products_background, store.id)
    return store


@router.post("/verify")
async def verify_connection(data: ConnectionVerify, _: str = Depends(verify_api_key)):
    client = WooCommerceClient(store_url=data.store_url.rstrip('/'), consumer_key=data.consumer_key, consumer_secret=data.consumer_secret)

    try:
        verification = await client.verify_connection()
        if verification.get('connected'):
            product_count = await client.get_products_count()
            return {
                "valid": True, "store_url": data.store_url,
                "wp_version": verification.get('wp_version'), "wc_version": verification.get('wc_version'),
                "product_count": product_count, "message": "Credentials are valid"
            }
        else:
            return {"valid": False, "error": verification.get('error', 'Connection failed'), "message": "Failed to connect to WooCommerce"}
    except Exception as e:
        return {"valid": False, "error": str(e), "message": "Failed to verify credentials"}


@router.get("/status", response_model=ConnectionStatus)
async def get_connection_status(merchant_id: str, db: Session = Depends(get_db), _: str = Depends(verify_api_key)):
    store = db.query(WooCommerceStore).filter(WooCommerceStore.merchant_id == merchant_id).first()

    if not store:
        return ConnectionStatus(connected=False, is_verified=False, product_count=0)

    product_count = db.query(Product).filter(Product.merchant_id == merchant_id, Product.is_deleted == 0).count()

    return ConnectionStatus(
        connected=True, store_url=store.store_url, store_name=store.store_name,
        is_verified=bool(store.is_verified), wp_version=store.wp_version,
        wc_version=store.wc_version, last_synced_at=store.last_synced_at, product_count=product_count
    )


@router.delete("/disconnect")
async def disconnect_store(merchant_id: str, db: Session = Depends(get_db), _: str = Depends(verify_api_key)):
    store = db.query(WooCommerceStore).filter(WooCommerceStore.merchant_id == merchant_id).first()

    if not store:
        raise HTTPException(status_code=404, detail=f"No store found for merchant: {merchant_id}")

    try:
        from app.services.webhook_manager import delete_all_webhooks
        await delete_all_webhooks(store, db)
    except Exception as e:
        logger.warning(f"Failed to delete webhooks during disconnect: {e}")

    store.is_active = 0
    store.updated_at = datetime.now(timezone.utc)
    db.commit()
    logger.info(f"Disconnected store for merchant {merchant_id}")

    return {"status": "disconnected", "merchant_id": merchant_id, "store_url": store.store_url, "message": "Store has been disconnected. Product data has been preserved."}


@router.post("/reconnect")
async def reconnect_store(data: ConnectionSetup, background_tasks: BackgroundTasks, db: Session = Depends(get_db), _: str = Depends(verify_api_key)):
    store = db.query(WooCommerceStore).filter(WooCommerceStore.merchant_id == data.merchant_id).first()

    if not store:
        raise HTTPException(status_code=404, detail=f"No store found for merchant: {data.merchant_id}. Use /setup for new connections.")

    client = WooCommerceClient(store_url=data.store_url.rstrip('/'), consumer_key=data.consumer_key, consumer_secret=data.consumer_secret)

    try:
        verification = await client.verify_connection()
        if not verification.get('connected'):
            raise HTTPException(status_code=400, detail=f"Failed to connect: {verification.get('error')}")
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to verify connection: {str(e)}")

    store.store_url = data.store_url.rstrip('/')
    store.consumer_key = data.consumer_key
    store.consumer_secret = data.consumer_secret
    store.store_name = data.store_name or store.store_name
    store.wp_version = verification.get('wp_version')
    store.wc_version = verification.get('wc_version')
    store.is_active = 1
    store.is_verified = 1
    store.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(store)

    from app.services.product_sync import sync_all_products_background
    from app.services.webhook_manager import register_webhooks

    # Re-register webhooks
    try:
        await register_webhooks(store, db)
        logger.info(f"Re-registered webhooks for merchant {data.merchant_id}")
    except Exception as e:
        logger.warning(f"Failed to re-register webhooks: {e}")

    background_tasks.add_task(sync_all_products_background, store.id)
    logger.info(f"Reconnected store for merchant {data.merchant_id}")

    return {"status": "reconnected", "merchant_id": data.merchant_id, "store_url": store.store_url, "message": "Store reconnected successfully. Webhooks registered and product sync started in background."}
