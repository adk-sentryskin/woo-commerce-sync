"""
Product Sync Service for WooCommerce

Handles:
- Bulk initial sync of all products
- Single product upsert (for webhooks)
- Product parsing and normalization
"""
from sqlalchemy.orm import Session
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy import func
from app.database import SessionLocal
from app.models import WooCommerceStore, Product
from app.services.woocommerce_client import WooCommerceClient
from app.config import settings
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional
import asyncio
import logging

logger = logging.getLogger(__name__)


def parse_datetime(date_string: Optional[str]) -> Optional[datetime]:
    """Parse WooCommerce datetime string to Python datetime"""
    if not date_string:
        return None
    try:
        # WooCommerce uses ISO 8601 format: 2024-01-15T10:30:00
        return datetime.fromisoformat(date_string.replace('Z', '+00:00'))
    except (ValueError, AttributeError):
        return None


def parse_woocommerce_product(product_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Parse WooCommerce product data to database-ready format.

    WooCommerce product structure:
    - id: Product ID
    - name: Product title (not 'title' like Shopify)
    - slug: URL slug
    - sku: Product SKU
    - type: simple, variable, grouped, external
    - status: publish, draft, pending, private
    - price, regular_price, sale_price
    - categories: Array of {id, name, slug}
    - tags: Array of {id, name, slug}
    - date_created: ISO datetime
    - date_modified: ISO datetime (not 'updated_at' like Shopify)
    """
    return {
        'wc_product_id': product_data.get('id'),
        'name': product_data.get('name'),
        'slug': product_data.get('slug'),
        'sku': product_data.get('sku'),
        'type': product_data.get('type'),
        'status': product_data.get('status'),
        'price': product_data.get('price'),
        'regular_price': product_data.get('regular_price'),
        'sale_price': product_data.get('sale_price'),
        'categories': product_data.get('categories', []),
        'tags': product_data.get('tags', []),
        'wc_created_at': parse_datetime(product_data.get('date_created')),
        'wc_modified_at': parse_datetime(product_data.get('date_modified')),
        'raw_data': product_data
    }


def upsert_product(
    db: Session,
    store: WooCommerceStore,
    product_data: Dict[str, Any],
    generate_embedding: bool = False
) -> Product:
    """
    Insert or update a single product.

    Uses PostgreSQL's ON CONFLICT DO UPDATE for atomic upsert.
    """
    parsed_data = parse_woocommerce_product(product_data)
    parsed_data['store_id'] = store.id
    parsed_data['merchant_id'] = store.merchant_id

    # Generate embedding if enabled
    if generate_embedding and settings.ENABLE_EMBEDDINGS:
        try:
            from app.services.embedding_service import get_embedding_service
            emb_service = get_embedding_service()
            product_text = emb_service.prepare_product_text(product_data)
            embedding = emb_service.generate_embedding(product_text)
            parsed_data['embedding'] = embedding
        except Exception as e:
            logger.warning(f"Failed to generate embedding for product {product_data.get('id')}: {e}")

    # PostgreSQL UPSERT
    stmt = insert(Product).values(**parsed_data)
    update_set = {
        'name': parsed_data['name'],
        'slug': parsed_data['slug'],
        'sku': parsed_data['sku'],
        'type': parsed_data['type'],
        'status': parsed_data['status'],
        'price': parsed_data['price'],
        'regular_price': parsed_data['regular_price'],
        'sale_price': parsed_data['sale_price'],
        'categories': parsed_data['categories'],
        'tags': parsed_data['tags'],
        'wc_modified_at': parsed_data['wc_modified_at'],
        'raw_data': parsed_data['raw_data'],
        'is_deleted': 0,  # Restore if was soft-deleted
        'deleted_at': None,
        'synced_at': func.now(),
        'updated_at': func.now()
    }
    # Update embedding if generated
    if parsed_data.get('embedding'):
        update_set['embedding'] = parsed_data['embedding']

    stmt = stmt.on_conflict_do_update(
        index_elements=['wc_product_id'],
        set_=update_set
    )

    db.execute(stmt)
    db.commit()

    # Fetch and return the upserted product
    product = db.query(Product).filter(
        Product.wc_product_id == parsed_data['wc_product_id']
    ).first()

    return product


def sync_products_batch(
    db: Session,
    store: WooCommerceStore,
    products: List[Dict[str, Any]]
) -> Dict[str, int]:
    """
    Sync a batch of products.

    Returns:
        Dict with counts: synced, created, updated, failed
    """
    stats = {
        'synced_count': 0,
        'created_count': 0,
        'updated_count': 0,
        'failed_count': 0
    }

    for product_data in products:
        try:
            # Check if product exists
            existing = db.query(Product).filter(
                Product.wc_product_id == product_data.get('id')
            ).first()

            upsert_product(db, store, product_data, generate_embedding=settings.ENABLE_EMBEDDINGS)

            stats['synced_count'] += 1
            if existing:
                stats['updated_count'] += 1
            else:
                stats['created_count'] += 1

        except Exception as e:
            logger.error(f"Failed to sync product {product_data.get('id')}: {e}")
            stats['failed_count'] += 1
            db.rollback()

    return stats


async def fetch_all_products_from_woocommerce(
    store: WooCommerceStore,
    db: Session
) -> Dict[str, Any]:
    """
    Fetch ALL products from WooCommerce with pagination.

    WooCommerce uses offset-based pagination (page, per_page)
    unlike Shopify's cursor-based pagination (since_id).
    """
    total_stats = {
        'status': 'completed',
        'total_products': 0,
        'synced_count': 0,
        'created_count': 0,
        'updated_count': 0,
        'failed_count': 0,
        'pages_fetched': 0
    }

    # Create WooCommerce client
    client = WooCommerceClient(
        store_url=store.store_url,
        consumer_key=store.consumer_key,
        consumer_secret=store.consumer_secret
    )

    page = 1
    per_page = settings.WC_PRODUCTS_PER_PAGE

    try:
        while True:
            logger.info(f"Fetching page {page} for merchant {store.merchant_id}")

            products, total, total_pages = await client.get_products(
                page=page,
                per_page=per_page,
                status='any'  # Get all statuses
            )

            if not products:
                break

            # Update total on first page
            if page == 1:
                total_stats['total_products'] = total

            # Sync batch
            batch_stats = sync_products_batch(db, store, products)

            # Accumulate stats
            total_stats['synced_count'] += batch_stats['synced_count']
            total_stats['created_count'] += batch_stats['created_count']
            total_stats['updated_count'] += batch_stats['updated_count']
            total_stats['failed_count'] += batch_stats['failed_count']
            total_stats['pages_fetched'] += 1

            logger.info(f"Synced page {page}/{total_pages}: {batch_stats['synced_count']} products")

            # Check if we've reached the last page
            if page >= total_pages or len(products) < per_page:
                break

            page += 1

            # Rate limiting - small delay between pages
            await asyncio.sleep(0.5)

        # Update store's last_synced_at
        store.last_synced_at = datetime.now(timezone.utc)
        db.commit()

    except Exception as e:
        logger.error(f"Error during bulk sync for merchant {store.merchant_id}: {e}")
        total_stats['status'] = 'failed'
        total_stats['error'] = str(e)

    return total_stats


def sync_all_products_background(store_id: int):
    """
    Background task to sync all products.

    Creates its own database session since it runs in a separate thread.
    """
    db = SessionLocal()
    try:
        store = db.query(WooCommerceStore).filter(
            WooCommerceStore.id == store_id
        ).first()

        if not store:
            logger.error(f"Store {store_id} not found for background sync")
            return

        logger.info(f"Starting background sync for merchant {store.merchant_id}")

        # Run async function in new event loop
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            result = loop.run_until_complete(
                fetch_all_products_from_woocommerce(store, db)
            )
            logger.info(f"Background sync completed for {store.merchant_id}: {result}")
        finally:
            loop.close()

    except Exception as e:
        logger.error(f"Background sync failed for store {store_id}: {e}")
    finally:
        db.close()


def soft_delete_product(db: Session, wc_product_id: int, merchant_id: str) -> bool:
    """
    Soft delete a product (mark as deleted instead of removing).
    """
    product = db.query(Product).filter(
        Product.wc_product_id == wc_product_id,
        Product.merchant_id == merchant_id
    ).first()

    if not product:
        return False

    product.is_deleted = 1
    product.deleted_at = datetime.now(timezone.utc)
    product.status = 'deleted'
    db.commit()

    logger.info(f"Soft deleted product {wc_product_id} for merchant {merchant_id}")
    return True


def restore_product(db: Session, wc_product_id: int, merchant_id: str) -> bool:
    """
    Restore a soft-deleted product.
    """
    product = db.query(Product).filter(
        Product.wc_product_id == wc_product_id,
        Product.merchant_id == merchant_id
    ).first()

    if not product:
        return False

    product.is_deleted = 0
    product.deleted_at = None
    db.commit()

    logger.info(f"Restored product {wc_product_id} for merchant {merchant_id}")
    return True
