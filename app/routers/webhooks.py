from fastapi import APIRouter, Depends, HTTPException, Request, Header
from sqlalchemy.orm import Session
from app.database import get_db
from app.models import WooCommerceStore, Webhook
from app.schemas import WebhookResponse, WebhookListResponse, WebhookRegistrationResult
from app.middleware.auth import verify_api_key, get_merchant_from_header
from app.utils.webhook_verification import verify_woocommerce_webhook
from app.services.product_sync import upsert_product, soft_delete_product
from app.services import webhook_manager
from typing import Optional, List
import json
import logging

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/webhooks", tags=["Webhooks"])


async def verify_wc_webhook(
    request: Request,
    x_wc_webhook_signature: Optional[str] = Header(None, alias="X-WC-Webhook-Signature"),
    x_wc_webhook_source: Optional[str] = Header(None, alias="X-WC-Webhook-Source"),
    x_wc_webhook_topic: Optional[str] = Header(None, alias="X-WC-Webhook-Topic"),
    x_wc_webhook_resource: Optional[str] = Header(None, alias="X-WC-Webhook-Resource"),
    x_wc_webhook_event: Optional[str] = Header(None, alias="X-WC-Webhook-Event"),
    db: Session = Depends(get_db)
) -> dict:
    if not x_wc_webhook_source or not x_wc_webhook_signature:
        raise HTTPException(status_code=401, detail="Missing required webhook headers")

    store_url = x_wc_webhook_source.rstrip('/')
    store = db.query(WooCommerceStore).filter(WooCommerceStore.store_url == store_url, WooCommerceStore.is_active == 1).first()

    if not store:
        raise HTTPException(status_code=404, detail=f"Store not found: {store_url}")

    topic = x_wc_webhook_topic or f"{x_wc_webhook_resource}.{x_wc_webhook_event}"
    webhook = db.query(Webhook).filter(Webhook.store_id == store.id, Webhook.topic == topic, Webhook.is_active == 1).first()

    if not webhook or not webhook.secret:
        raise HTTPException(status_code=401, detail="Webhook not registered or missing secret")

    body = await request.body()

    if not verify_woocommerce_webhook(body, x_wc_webhook_signature, webhook.secret):
        raise HTTPException(status_code=401, detail="Invalid webhook signature")

    try:
        payload = json.loads(body.decode('utf-8'))
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON payload")

    return {"store": store, "topic": topic, "resource": x_wc_webhook_resource, "event": x_wc_webhook_event, "payload": payload, "db": db}


@router.post("/product/created")
async def product_created_webhook(webhook_data: dict = Depends(verify_wc_webhook)):
    store, payload, db = webhook_data["store"], webhook_data["payload"], webhook_data["db"]
    try:
        upsert_product(db, store, payload, generate_embedding=True)
        logger.info(f"Product created via webhook: {payload.get('id')} for {store.merchant_id}")
        return {"status": "success", "action": "created", "product_id": payload.get('id'), "merchant_id": store.merchant_id}
    except Exception as e:
        logger.error(f"Failed to process product.created webhook: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/product/updated")
async def product_updated_webhook(webhook_data: dict = Depends(verify_wc_webhook)):
    store, payload, db = webhook_data["store"], webhook_data["payload"], webhook_data["db"]
    try:
        upsert_product(db, store, payload, generate_embedding=True)
        logger.info(f"Product updated via webhook: {payload.get('id')} for {store.merchant_id}")
        return {"status": "success", "action": "updated", "product_id": payload.get('id'), "merchant_id": store.merchant_id}
    except Exception as e:
        logger.error(f"Failed to process product.updated webhook: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/product/deleted")
async def product_deleted_webhook(webhook_data: dict = Depends(verify_wc_webhook)):
    store, payload, db = webhook_data["store"], webhook_data["payload"], webhook_data["db"]
    try:
        product_id = payload.get('id')
        success = soft_delete_product(db, product_id, store.merchant_id)
        if success:
            logger.info(f"Product deleted via webhook: {product_id} for {store.merchant_id}")
            return {"status": "success", "action": "deleted", "product_id": product_id, "merchant_id": store.merchant_id}
        else:
            return {"status": "success", "action": "not_found", "product_id": product_id, "message": "Product not found in database"}
    except Exception as e:
        logger.error(f"Failed to process product.deleted webhook: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/product/restored")
async def product_restored_webhook(webhook_data: dict = Depends(verify_wc_webhook)):
    store, payload, db = webhook_data["store"], webhook_data["payload"], webhook_data["db"]
    try:
        upsert_product(db, store, payload, generate_embedding=True)
        logger.info(f"Product restored via webhook: {payload.get('id')} for {store.merchant_id}")
        return {"status": "success", "action": "restored", "product_id": payload.get('id'), "merchant_id": store.merchant_id}
    except Exception as e:
        logger.error(f"Failed to process product.restored webhook: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/register", response_model=List[WebhookRegistrationResult])
async def register_webhooks(store: WooCommerceStore = Depends(get_merchant_from_header), db: Session = Depends(get_db), _: str = Depends(verify_api_key)):
    results = await webhook_manager.register_webhooks(store, db)
    return [WebhookRegistrationResult(**r) for r in results]


@router.get("/list", response_model=WebhookListResponse)
async def list_webhooks(store: WooCommerceStore = Depends(get_merchant_from_header), db: Session = Depends(get_db), _: str = Depends(verify_api_key)):
    webhooks = await webhook_manager.list_webhooks(store, db)
    return WebhookListResponse(
        webhooks=[WebhookResponse(
            id=w['id'], wc_webhook_id=w['wc_webhook_id'], topic=w['topic'], delivery_url=w['delivery_url'],
            status=w['status'], is_active=1 if w.get('in_woocommerce', True) else 0, created_at=w.get('created_at')
        ) for w in webhooks],
        total=len(webhooks)
    )


@router.delete("/delete/{webhook_id}")
async def delete_webhook(webhook_id: int, store: WooCommerceStore = Depends(get_merchant_from_header), db: Session = Depends(get_db), _: str = Depends(verify_api_key)):
    success = await webhook_manager.delete_webhook(store, webhook_id, db)
    if not success:
        raise HTTPException(status_code=404, detail=f"Webhook {webhook_id} not found")
    return {"status": "deleted", "webhook_id": webhook_id}


@router.post("/sync")
async def sync_webhooks(store: WooCommerceStore = Depends(get_merchant_from_header), db: Session = Depends(get_db), _: str = Depends(verify_api_key)):
    return await webhook_manager.sync_webhooks(store, db)
