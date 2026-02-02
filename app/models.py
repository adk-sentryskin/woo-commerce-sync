from sqlalchemy import Column, Integer, String, DateTime, Text, BigInteger, ForeignKey
from sqlalchemy.sql import func
from sqlalchemy.ext.hybrid import hybrid_property
from sqlalchemy.orm import relationship
from sqlalchemy.dialects.postgresql import JSONB
from pgvector.sqlalchemy import Vector
from app.database import Base
from app.utils.encryption import get_encryption


class WooCommerceStore(Base):
    __tablename__ = "woocommerce_stores"
    __table_args__ = {'schema': 'woocommerce_sync'}

    id = Column(Integer, primary_key=True, index=True)
    merchant_id = Column(String(255), unique=True, index=True, nullable=False)
    store_url = Column(String(500), unique=True, nullable=False)
    store_name = Column(String(255), nullable=True)
    _consumer_key = Column("consumer_key", Text, nullable=False)
    _consumer_secret = Column("consumer_secret", Text, nullable=False)
    api_version = Column(String(20), default='wc/v3')
    wp_version = Column(String(20), nullable=True)
    wc_version = Column(String(20), nullable=True)
    is_active = Column(Integer, default=1)
    is_verified = Column(Integer, default=0)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    last_synced_at = Column(DateTime(timezone=True), nullable=True)

    @hybrid_property
    def consumer_key(self) -> str:
        if not self._consumer_key:
            return None
        try:
            return get_encryption().decrypt(self._consumer_key)
        except Exception:
            return None

    @consumer_key.setter
    def consumer_key(self, value: str):
        if not value:
            self._consumer_key = None
        else:
            self._consumer_key = get_encryption().encrypt(value)

    @hybrid_property
    def consumer_secret(self) -> str:
        if not self._consumer_secret:
            return None
        try:
            return get_encryption().decrypt(self._consumer_secret)
        except Exception:
            return None

    @consumer_secret.setter
    def consumer_secret(self, value: str):
        if not value:
            self._consumer_secret = None
        else:
            self._consumer_secret = get_encryption().encrypt(value)


class Product(Base):
    __tablename__ = "products"
    __table_args__ = {'schema': 'woocommerce_sync'}

    id = Column(Integer, primary_key=True, autoincrement=True)
    wc_product_id = Column(BigInteger, unique=True, index=True, nullable=False)
    store_id = Column(Integer, ForeignKey('woocommerce_sync.woocommerce_stores.id'), nullable=False)
    merchant_id = Column(String(255), nullable=False, index=True)
    name = Column(String(500))
    slug = Column(String(255))
    sku = Column(String(255))
    type = Column(String(50))
    status = Column(String(50))
    price = Column(String(50))
    regular_price = Column(String(50))
    sale_price = Column(String(50))
    categories = Column(JSONB)
    tags = Column(JSONB)
    wc_created_at = Column(DateTime(timezone=True))
    wc_modified_at = Column(DateTime(timezone=True))
    raw_data = Column(JSONB)
    embedding = Column(Vector(768), nullable=True)
    is_deleted = Column(Integer, default=0)
    deleted_at = Column(DateTime(timezone=True), nullable=True)
    synced_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    store = relationship("WooCommerceStore", backref="products", foreign_keys=[store_id])


class Webhook(Base):
    __tablename__ = "webhooks"
    __table_args__ = {'schema': 'woocommerce_sync'}

    id = Column(Integer, primary_key=True, autoincrement=True)
    store_id = Column(Integer, ForeignKey('woocommerce_sync.woocommerce_stores.id'), nullable=False)
    merchant_id = Column(String(255), nullable=False, index=True)
    wc_webhook_id = Column(BigInteger, unique=True, index=True, nullable=False)
    topic = Column(String(100), nullable=False, index=True)
    delivery_url = Column(String(500), nullable=False)
    secret = Column(String(255), nullable=True)
    status = Column(String(50), default="active")
    is_active = Column(Integer, default=1)
    last_verified_at = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    store = relationship("WooCommerceStore", backref="webhooks", foreign_keys=[store_id])
