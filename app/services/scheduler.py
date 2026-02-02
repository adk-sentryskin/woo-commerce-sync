"""
Scheduler Service - Daily Reconciliation

Uses APScheduler to run periodic reconciliation jobs.
"""
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy.orm import Session
from app.database import SessionLocal
from app.models import WooCommerceStore
from app.config import settings
from datetime import datetime, timezone
from typing import Dict, Any, Optional
import asyncio
import logging

logger = logging.getLogger(__name__)

# Global scheduler instance
_scheduler: Optional[AsyncIOScheduler] = None


def get_scheduler() -> Optional[AsyncIOScheduler]:
    """Get the scheduler instance"""
    return _scheduler


def start_scheduler():
    """
    Start the scheduler with configured jobs.
    """
    global _scheduler

    if not settings.ENABLE_SCHEDULER:
        logger.info("Scheduler disabled by configuration")
        return

    _scheduler = AsyncIOScheduler()

    # Add daily reconciliation job
    _scheduler.add_job(
        reconciliation_job,
        CronTrigger(
            hour=settings.RECONCILIATION_HOUR,
            minute=settings.RECONCILIATION_MINUTE
        ),
        id='daily_reconciliation',
        name='Daily Product Reconciliation',
        replace_existing=True
    )

    _scheduler.start()
    logger.info(
        f"Scheduler started. Reconciliation scheduled for "
        f"{settings.RECONCILIATION_HOUR:02d}:{settings.RECONCILIATION_MINUTE:02d} daily"
    )


def stop_scheduler():
    """Stop the scheduler"""
    global _scheduler

    if _scheduler:
        _scheduler.shutdown(wait=False)
        _scheduler = None
        logger.info("Scheduler stopped")


async def reconciliation_job():
    """
    Scheduled job to reconcile all active stores.
    """
    logger.info("Starting scheduled reconciliation job")

    db = SessionLocal()
    try:
        # Get all active stores
        stores = db.query(WooCommerceStore).filter(
            WooCommerceStore.is_active == 1,
            WooCommerceStore.is_verified == 1
        ).all()

        logger.info(f"Found {len(stores)} active stores to reconcile")

        for store in stores:
            try:
                await reconcile_store(store, db)
            except Exception as e:
                logger.error(f"Reconciliation failed for {store.merchant_id}: {e}")

        logger.info("Scheduled reconciliation job completed")

    except Exception as e:
        logger.error(f"Reconciliation job error: {e}")
    finally:
        db.close()


async def reconcile_store(store: WooCommerceStore, db: Session):
    """
    Reconcile a single store.
    """
    from app.services.woocommerce_client import WooCommerceClient
    from app.services.product_sync import fetch_all_products_from_woocommerce

    logger.info(f"Reconciling store: {store.merchant_id}")

    try:
        result = await fetch_all_products_from_woocommerce(store, db)
        logger.info(
            f"Reconciliation for {store.merchant_id}: "
            f"synced={result.get('synced_count', 0)}, "
            f"created={result.get('created_count', 0)}, "
            f"updated={result.get('updated_count', 0)}"
        )
    except Exception as e:
        logger.error(f"Failed to reconcile {store.merchant_id}: {e}")
        raise


async def run_reconciliation_now():
    """
    Manually trigger reconciliation job.
    """
    await reconciliation_job()


def get_scheduler_info() -> Dict[str, Any]:
    """
    Get scheduler status information.
    """
    global _scheduler

    if not _scheduler:
        return {
            "enabled": settings.ENABLE_SCHEDULER,
            "running": False,
            "jobs": []
        }

    jobs = []
    for job in _scheduler.get_jobs():
        next_run = job.next_run_time
        jobs.append({
            "id": job.id,
            "name": job.name,
            "next_run": next_run.isoformat() if next_run else None
        })

    return {
        "enabled": settings.ENABLE_SCHEDULER,
        "running": _scheduler.running,
        "reconciliation_time": f"{settings.RECONCILIATION_HOUR:02d}:{settings.RECONCILIATION_MINUTE:02d}",
        "jobs": jobs
    }
