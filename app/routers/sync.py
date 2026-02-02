"""
Sync Router - Product Sync & Reconciliation Endpoints

Provides endpoints for:
- Manual sync triggers
- Reconciliation
- Sync status
"""
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from sqlalchemy.orm import Session
from app.database import get_db
from app.models import WooCommerceStore, Product, Webhook
from app.schemas import SyncStatusResponse, ProductSyncStatus, ReconciliationResult
from app.middleware.auth import verify_api_key, get_merchant_from_header
from app.services.product_sync import fetch_all_products_from_woocommerce, sync_all_products_background
from app.config import settings
import logging

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/sync", tags=["Sync"])


@router.get("/status", response_model=SyncStatusResponse)
async def get_sync_status(
    store: WooCommerceStore = Depends(get_merchant_from_header),
    db: Session = Depends(get_db),
    _: str = Depends(verify_api_key)
):
    """
    Get sync status for a merchant.
    """
    # Product counts
    total_products = db.query(Product).filter(
        Product.merchant_id == store.merchant_id
    ).count()

    active_products = db.query(Product).filter(
        Product.merchant_id == store.merchant_id,
        Product.is_deleted == 0
    ).count()

    deleted_products = total_products - active_products

    # Webhook count
    webhooks_registered = db.query(Webhook).filter(
        Webhook.store_id == store.id,
        Webhook.is_active == 1
    ).count()

    return SyncStatusResponse(
        merchant_id=store.merchant_id,
        store_url=store.store_url,
        total_products=total_products,
        active_products=active_products,
        deleted_products=deleted_products,
        last_synced_at=store.last_synced_at,
        webhooks_registered=webhooks_registered,
        scheduler_enabled=settings.ENABLE_SCHEDULER
    )


@router.post("/trigger", response_model=ProductSyncStatus)
async def trigger_sync(
    background: bool = False,
    store: WooCommerceStore = Depends(get_merchant_from_header),
    background_tasks: BackgroundTasks = None,
    db: Session = Depends(get_db),
    _: str = Depends(verify_api_key)
):
    """
    Trigger a full product sync.

    Args:
        background: If true, run sync in background and return immediately
    """
    if background and background_tasks:
        background_tasks.add_task(sync_all_products_background, store.id)
        return ProductSyncStatus(
            status="started",
            total_products=0,
            synced_count=0,
            created_count=0,
            updated_count=0,
            message="Sync started in background"
        )

    # Run sync synchronously
    result = await fetch_all_products_from_woocommerce(store, db)

    return ProductSyncStatus(
        status=result.get('status', 'completed'),
        total_products=result.get('total_products', 0),
        synced_count=result.get('synced_count', 0),
        created_count=result.get('created_count', 0),
        updated_count=result.get('updated_count', 0),
        failed_count=result.get('failed_count', 0),
        pages_fetched=result.get('pages_fetched', 0),
        message=result.get('error')
    )


@router.post("/force-resync", response_model=ProductSyncStatus)
async def force_resync(
    background_tasks: BackgroundTasks,
    store: WooCommerceStore = Depends(get_merchant_from_header),
    db: Session = Depends(get_db),
    _: str = Depends(verify_api_key)
):
    """
    Force a complete resync of all products.

    This will:
    1. Mark all existing products as potentially stale
    2. Fetch all products from WooCommerce
    3. Update/create products
    4. Products not in WooCommerce will remain but can be identified
    """
    # Start sync in background
    background_tasks.add_task(sync_all_products_background, store.id)

    # Get current count
    current_count = db.query(Product).filter(
        Product.merchant_id == store.merchant_id,
        Product.is_deleted == 0
    ).count()

    return ProductSyncStatus(
        status="started",
        total_products=current_count,
        synced_count=0,
        created_count=0,
        updated_count=0,
        message="Force resync started in background"
    )


@router.post("/reconcile", response_model=ReconciliationResult)
async def reconcile_products(
    store: WooCommerceStore = Depends(get_merchant_from_header),
    db: Session = Depends(get_db),
    _: str = Depends(verify_api_key)
):
    """
    Reconcile products between local database and WooCommerce.

    This will:
    1. Fetch current products from WooCommerce
    2. Compare with local database
    3. Add missing products
    4. Update changed products
    5. Mark deleted products
    """
    from app.services.woocommerce_client import WooCommerceClient
    from app.services.product_sync import upsert_product, soft_delete_product

    client = WooCommerceClient(
        store_url=store.store_url,
        consumer_key=store.consumer_key,
        consumer_secret=store.consumer_secret
    )

    result = ReconciliationResult(
        status="completed",
        products_checked=0,
        products_added=0,
        products_updated=0,
        products_deleted=0,
        errors=[]
    )

    try:
        # Get all product IDs from WooCommerce
        wc_product_ids = set()
        page = 1

        while True:
            products, total, total_pages = await client.get_products(page=page, per_page=100)

            if not products:
                break

            for product in products:
                wc_product_ids.add(product['id'])
                result.products_checked += 1

                # Check if exists locally
                existing = db.query(Product).filter(
                    Product.wc_product_id == product['id'],
                    Product.merchant_id == store.merchant_id
                ).first()

                if not existing:
                    upsert_product(db, store, product)
                    result.products_added += 1
                elif existing.is_deleted:
                    # Restore if was deleted
                    upsert_product(db, store, product)
                    result.products_updated += 1

            if page >= total_pages:
                break
            page += 1

        # Find products in DB that are not in WooCommerce
        local_products = db.query(Product).filter(
            Product.merchant_id == store.merchant_id,
            Product.is_deleted == 0
        ).all()

        for product in local_products:
            if product.wc_product_id not in wc_product_ids:
                soft_delete_product(db, product.wc_product_id, store.merchant_id)
                result.products_deleted += 1

    except Exception as e:
        logger.error(f"Reconciliation error: {e}")
        result.status = "partial"
        result.errors.append(str(e))

    return result


@router.get("/scheduler/status")
async def scheduler_status(
    _: str = Depends(verify_api_key)
):
    """
    Get scheduler status.
    """
    from app.services.scheduler import get_scheduler_info

    return get_scheduler_info()


@router.post("/scheduler/trigger")
async def trigger_scheduler(
    _: str = Depends(verify_api_key)
):
    """
    Manually trigger the scheduled reconciliation job.
    """
    from app.services.scheduler import run_reconciliation_now

    try:
        await run_reconciliation_now()
        return {
            "status": "triggered",
            "message": "Reconciliation job triggered"
        }
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to trigger reconciliation: {str(e)}"
        )
