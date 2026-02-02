"""
Authentication middleware and dependencies for WooCommerce Sync API.

Provides:
- API Key authentication for service-to-service calls
- Merchant ID validation for multi-tenant operations
"""
from fastapi import Header, HTTPException, Depends
from sqlalchemy.orm import Session
from app.database import get_db
from app.models import WooCommerceStore
from app.config import settings
import secrets
import logging

logger = logging.getLogger(__name__)


async def verify_api_key(x_api_key: str = Header(..., alias="X-API-Key")) -> str:
    """
    Dependency to verify API key from X-API-Key header.

    Args:
        x_api_key: API key from header

    Returns:
        The validated API key

    Raises:
        HTTPException: If API key is missing or invalid
    """
    if not x_api_key:
        raise HTTPException(
            status_code=401,
            detail="Missing X-API-Key header"
        )

    # Use constant-time comparison to prevent timing attacks
    if not secrets.compare_digest(x_api_key, settings.API_KEY):
        raise HTTPException(
            status_code=403,
            detail="Invalid API Key"
        )

    return x_api_key


async def get_merchant_id(x_merchant_id: str = Header(..., alias="X-Merchant-Id")) -> str:
    """
    Dependency to extract merchant ID from header.

    Args:
        x_merchant_id: Merchant ID from header

    Returns:
        The merchant ID

    Raises:
        HTTPException: If merchant ID is missing
    """
    if not x_merchant_id:
        raise HTTPException(
            status_code=400,
            detail="Missing X-Merchant-Id header"
        )

    return x_merchant_id


async def get_merchant_from_header(
    merchant_id: str = Depends(get_merchant_id),
    db: Session = Depends(get_db)
) -> WooCommerceStore:
    """
    Dependency to get and validate merchant/store from header.

    Validates that:
    - Merchant exists in database
    - Merchant is active
    - Merchant has verified API credentials

    Args:
        merchant_id: Merchant ID from header
        db: Database session

    Returns:
        WooCommerceStore instance

    Raises:
        HTTPException: If merchant not found, inactive, or not verified
    """
    store = db.query(WooCommerceStore).filter(
        WooCommerceStore.merchant_id == merchant_id
    ).first()

    if not store:
        raise HTTPException(
            status_code=404,
            detail=f"Merchant not found: {merchant_id}"
        )

    if not store.is_active:
        raise HTTPException(
            status_code=403,
            detail=f"Merchant is inactive: {merchant_id}"
        )

    if not store.is_verified:
        raise HTTPException(
            status_code=403,
            detail=f"Merchant connection not verified. Please verify WooCommerce connection first."
        )

    return store


async def get_merchant_optional(
    x_merchant_id: str = Header(None, alias="X-Merchant-Id"),
    db: Session = Depends(get_db)
) -> WooCommerceStore | None:
    """
    Dependency to optionally get merchant from header.
    Returns None if header not provided.

    Useful for endpoints that can work with or without merchant context.
    """
    if not x_merchant_id:
        return None

    store = db.query(WooCommerceStore).filter(
        WooCommerceStore.merchant_id == x_merchant_id,
        WooCommerceStore.is_active == 1
    ).first()

    return store
