"""
Webhook Manager Service

Handles:
- Registering webhooks with WooCommerce
- Listing and managing webhooks
- Syncing webhook state
"""
from sqlalchemy.orm import Session
from app.models import WooCommerceStore, Webhook
from app.services.woocommerce_client import WooCommerceClient
from app.utils.webhook_verification import generate_webhook_secret
from app.config import settings
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional
import logging

logger = logging.getLogger(__name__)


# Webhook topics to register for product sync
WEBHOOK_TOPICS = [
    {
        "topic": "product.created",
        "description": "Triggered when a new product is created"
    },
    {
        "topic": "product.updated",
        "description": "Triggered when a product is updated"
    },
    {
        "topic": "product.deleted",
        "description": "Triggered when a product is deleted"
    },
    {
        "topic": "product.restored",
        "description": "Triggered when a product is restored from trash"
    }
]


def get_webhook_delivery_url(topic: str) -> str:
    """
    Generate the delivery URL for a webhook topic.

    Example: product.created -> /api/webhooks/product/created
    """
    # Convert topic format: product.created -> product/created
    path = topic.replace('.', '/')
    return f"{settings.APP_URL}/api/webhooks/{path}"


async def register_webhooks(
    store: WooCommerceStore,
    db: Session
) -> List[Dict[str, Any]]:
    """
    Register all required webhooks with WooCommerce.

    Returns:
        List of registration results
    """
    results = []

    client = WooCommerceClient(
        store_url=store.store_url,
        consumer_key=store.consumer_key,
        consumer_secret=store.consumer_secret
    )

    # Generate a shared secret for this store's webhooks
    webhook_secret = generate_webhook_secret(settings.WEBHOOK_SECRET_LENGTH)

    for config in WEBHOOK_TOPICS:
        topic = config['topic']
        delivery_url = get_webhook_delivery_url(topic)

        try:
            # Check if webhook already exists in our database
            existing_db = db.query(Webhook).filter(
                Webhook.store_id == store.id,
                Webhook.topic == topic,
                Webhook.is_active == 1
            ).first()

            if existing_db:
                # Verify it still exists in WooCommerce
                try:
                    wc_webhook = await client.get_webhook(existing_db.wc_webhook_id)
                    results.append({
                        "topic": topic,
                        "action": "already_exists",
                        "webhook_id": existing_db.wc_webhook_id
                    })
                    continue
                except Exception:
                    # Webhook doesn't exist in WooCommerce anymore, remove from DB
                    existing_db.is_active = 0
                    db.commit()

            # Create new webhook in WooCommerce
            wc_webhook = await client.create_webhook(
                topic=topic,
                delivery_url=delivery_url,
                secret=webhook_secret,
                name=f"CheckoutAI - {topic}"
            )

            # Save to database
            webhook = Webhook(
                store_id=store.id,
                merchant_id=store.merchant_id,
                wc_webhook_id=wc_webhook['id'],
                topic=topic,
                delivery_url=delivery_url,
                secret=webhook_secret,
                status=wc_webhook.get('status', 'active'),
                is_active=1,
                last_verified_at=datetime.now(timezone.utc)
            )
            db.add(webhook)
            db.commit()

            results.append({
                "topic": topic,
                "action": "created",
                "webhook_id": wc_webhook['id']
            })

            logger.info(f"Registered webhook {topic} for merchant {store.merchant_id}")

        except Exception as e:
            logger.error(f"Failed to register webhook {topic}: {e}")
            results.append({
                "topic": topic,
                "action": "failed",
                "error": str(e)
            })

    return results


async def list_webhooks(
    store: WooCommerceStore,
    db: Session
) -> List[Dict[str, Any]]:
    """
    List all webhooks for a store from both database and WooCommerce.
    """
    # Get from database
    db_webhooks = db.query(Webhook).filter(
        Webhook.store_id == store.id,
        Webhook.is_active == 1
    ).all()

    # Get from WooCommerce
    client = WooCommerceClient(
        store_url=store.store_url,
        consumer_key=store.consumer_key,
        consumer_secret=store.consumer_secret
    )

    try:
        wc_webhooks = await client.get_webhooks()
    except Exception as e:
        logger.error(f"Failed to fetch webhooks from WooCommerce: {e}")
        wc_webhooks = []

    # Map WooCommerce webhooks by ID
    wc_map = {w['id']: w for w in wc_webhooks}

    result = []
    for db_wh in db_webhooks:
        wc_wh = wc_map.get(db_wh.wc_webhook_id, {})
        result.append({
            "id": db_wh.id,
            "wc_webhook_id": db_wh.wc_webhook_id,
            "topic": db_wh.topic,
            "delivery_url": db_wh.delivery_url,
            "status": wc_wh.get('status', db_wh.status),
            "in_woocommerce": db_wh.wc_webhook_id in wc_map,
            "created_at": db_wh.created_at
        })

    return result


async def delete_webhook(
    store: WooCommerceStore,
    webhook_id: int,
    db: Session
) -> bool:
    """
    Delete a webhook from both WooCommerce and database.
    """
    webhook = db.query(Webhook).filter(
        Webhook.id == webhook_id,
        Webhook.store_id == store.id
    ).first()

    if not webhook:
        return False

    # Delete from WooCommerce
    client = WooCommerceClient(
        store_url=store.store_url,
        consumer_key=store.consumer_key,
        consumer_secret=store.consumer_secret
    )

    try:
        await client.delete_webhook(webhook.wc_webhook_id)
    except Exception as e:
        logger.warning(f"Failed to delete webhook from WooCommerce: {e}")

    # Mark as inactive in database
    webhook.is_active = 0
    webhook.updated_at = datetime.now(timezone.utc)
    db.commit()

    return True


async def delete_all_webhooks(
    store: WooCommerceStore,
    db: Session
) -> int:
    """
    Delete all webhooks for a store.

    Returns:
        Number of webhooks deleted
    """
    webhooks = db.query(Webhook).filter(
        Webhook.store_id == store.id,
        Webhook.is_active == 1
    ).all()

    client = WooCommerceClient(
        store_url=store.store_url,
        consumer_key=store.consumer_key,
        consumer_secret=store.consumer_secret
    )

    deleted = 0
    for webhook in webhooks:
        try:
            await client.delete_webhook(webhook.wc_webhook_id)
        except Exception as e:
            logger.warning(f"Failed to delete webhook {webhook.wc_webhook_id}: {e}")

        webhook.is_active = 0
        deleted += 1

    db.commit()
    return deleted


async def sync_webhooks(
    store: WooCommerceStore,
    db: Session
) -> Dict[str, Any]:
    """
    Sync webhook state between WooCommerce and database.

    - Marks webhooks deleted in WooCommerce as inactive
    - Reports missing webhooks that need re-registration
    """
    result = {
        "synced": 0,
        "missing_in_wc": [],
        "orphaned_in_db": []
    }

    # Get from database
    db_webhooks = db.query(Webhook).filter(
        Webhook.store_id == store.id,
        Webhook.is_active == 1
    ).all()

    # Get from WooCommerce
    client = WooCommerceClient(
        store_url=store.store_url,
        consumer_key=store.consumer_key,
        consumer_secret=store.consumer_secret
    )

    try:
        wc_webhooks = await client.get_webhooks(status='all')
        wc_ids = {w['id'] for w in wc_webhooks}
    except Exception as e:
        logger.error(f"Failed to sync webhooks: {e}")
        return {"error": str(e)}

    for db_wh in db_webhooks:
        if db_wh.wc_webhook_id not in wc_ids:
            # Webhook exists in DB but not in WooCommerce
            result["missing_in_wc"].append(db_wh.topic)
            db_wh.is_active = 0
            result["orphaned_in_db"].append(db_wh.id)
        else:
            db_wh.last_verified_at = datetime.now(timezone.utc)
            result["synced"] += 1

    db.commit()
    return result


def get_webhook_secret(
    store: WooCommerceStore,
    topic: str,
    db: Session
) -> Optional[str]:
    """
    Get the webhook secret for a specific topic.
    """
    webhook = db.query(Webhook).filter(
        Webhook.store_id == store.id,
        Webhook.topic == topic,
        Webhook.is_active == 1
    ).first()

    return webhook.secret if webhook else None
