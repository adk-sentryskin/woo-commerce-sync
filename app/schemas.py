from pydantic import BaseModel, Field
from typing import Optional, List, Any, Dict
from datetime import datetime


class WooCommerceStoreBase(BaseModel):
    merchant_id: str
    store_url: str


class WooCommerceStoreCreate(WooCommerceStoreBase):
    consumer_key: str
    consumer_secret: str
    store_name: Optional[str] = None


class WooCommerceStoreResponse(WooCommerceStoreBase):
    id: int
    store_name: Optional[str] = None
    api_version: str
    wp_version: Optional[str] = None
    wc_version: Optional[str] = None
    is_active: int
    is_verified: int
    created_at: Optional[datetime] = None
    last_synced_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class ConnectionSetup(BaseModel):
    store_url: str
    consumer_key: str
    consumer_secret: str
    merchant_id: str
    store_name: Optional[str] = None


class ConnectionVerify(BaseModel):
    store_url: str
    consumer_key: str
    consumer_secret: str


class ConnectionStatus(BaseModel):
    connected: bool
    store_url: Optional[str] = None
    store_name: Optional[str] = None
    is_verified: bool
    wp_version: Optional[str] = None
    wc_version: Optional[str] = None
    last_synced_at: Optional[datetime] = None
    product_count: int = 0


class ProductBase(BaseModel):
    wc_product_id: int
    name: Optional[str] = None
    slug: Optional[str] = None
    sku: Optional[str] = None
    type: Optional[str] = None
    status: Optional[str] = None


class ProductResponse(ProductBase):
    id: int
    merchant_id: str
    price: Optional[str] = None
    regular_price: Optional[str] = None
    sale_price: Optional[str] = None
    categories: Optional[List[Dict[str, Any]]] = None
    tags: Optional[List[Dict[str, Any]]] = None
    wc_created_at: Optional[datetime] = None
    wc_modified_at: Optional[datetime] = None
    synced_at: Optional[datetime] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class ProductListResponse(BaseModel):
    products: List[ProductResponse]
    total: int
    page: int
    per_page: int
    total_pages: int


class ProductSyncStatus(BaseModel):
    status: str
    total_products: int
    synced_count: int
    created_count: int
    updated_count: int
    failed_count: int = 0
    pages_fetched: int = 0
    message: Optional[str] = None


class WebhookCreate(BaseModel):
    topic: str
    delivery_url: str


class WebhookResponse(BaseModel):
    id: int
    wc_webhook_id: int
    topic: str
    delivery_url: str
    status: str
    is_active: int
    created_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class WebhookRegistrationResult(BaseModel):
    topic: str
    action: str
    webhook_id: Optional[int] = None
    error: Optional[str] = None


class WebhookListResponse(BaseModel):
    webhooks: List[WebhookResponse]
    total: int


class SyncStatusResponse(BaseModel):
    merchant_id: str
    store_url: str
    total_products: int
    active_products: int
    deleted_products: int
    last_synced_at: Optional[datetime] = None
    webhooks_registered: int
    scheduler_enabled: bool


class ReconciliationResult(BaseModel):
    status: str
    products_checked: int
    products_added: int
    products_updated: int
    products_deleted: int
    errors: List[str] = []


class ErrorResponse(BaseModel):
    detail: str
    error_code: Optional[str] = None
