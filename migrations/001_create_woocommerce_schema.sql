-- =============================================================================
-- WooCommerce Sync Schema Migration
-- Version: 001
-- Description: Create initial schema and tables
-- =============================================================================

-- Create schema
CREATE SCHEMA IF NOT EXISTS woocommerce_sync;

-- Enable pgvector extension for embeddings
CREATE EXTENSION IF NOT EXISTS vector;

-- =============================================================================
-- WooCommerce Stores Table
-- =============================================================================
CREATE TABLE IF NOT EXISTS woocommerce_sync.woocommerce_stores (
    id SERIAL PRIMARY KEY,
    merchant_id VARCHAR(255) UNIQUE NOT NULL,
    store_url VARCHAR(500) UNIQUE NOT NULL,
    store_name VARCHAR(255),

    -- WooCommerce API Credentials (encrypted)
    consumer_key TEXT NOT NULL,
    consumer_secret TEXT NOT NULL,

    -- API Configuration
    api_version VARCHAR(20) DEFAULT 'wc/v3',
    wp_version VARCHAR(20),
    wc_version VARCHAR(20),

    -- Status
    is_active INTEGER DEFAULT 1,
    is_verified INTEGER DEFAULT 0,

    -- Timestamps
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE,
    last_synced_at TIMESTAMP WITH TIME ZONE
);

-- Indexes for stores
CREATE INDEX IF NOT EXISTS idx_wc_stores_merchant_id
    ON woocommerce_sync.woocommerce_stores(merchant_id);
CREATE INDEX IF NOT EXISTS idx_wc_stores_store_url
    ON woocommerce_sync.woocommerce_stores(store_url);
CREATE INDEX IF NOT EXISTS idx_wc_stores_active
    ON woocommerce_sync.woocommerce_stores(is_active);

-- =============================================================================
-- Products Table
-- =============================================================================
CREATE TABLE IF NOT EXISTS woocommerce_sync.products (
    id SERIAL PRIMARY KEY,
    wc_product_id BIGINT UNIQUE NOT NULL,

    -- Foreign Keys
    store_id INTEGER NOT NULL REFERENCES woocommerce_sync.woocommerce_stores(id),
    merchant_id VARCHAR(255) NOT NULL,

    -- Searchable Fields
    name VARCHAR(500),
    slug VARCHAR(255),
    sku VARCHAR(255),
    type VARCHAR(50),
    status VARCHAR(50),

    -- Pricing
    price VARCHAR(50),
    regular_price VARCHAR(50),
    sale_price VARCHAR(50),

    -- Categorization (JSONB arrays)
    categories JSONB,
    tags JSONB,

    -- Timestamps from WooCommerce
    wc_created_at TIMESTAMP WITH TIME ZONE,
    wc_modified_at TIMESTAMP WITH TIME ZONE,

    -- Full WooCommerce data
    raw_data JSONB,

    -- Vector Embedding for Semantic Search (768-dim for Vertex AI text-embedding-004)
    embedding vector(768),

    -- Soft Delete
    is_deleted INTEGER DEFAULT 0,
    deleted_at TIMESTAMP WITH TIME ZONE,

    -- Local timestamps
    synced_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE
);

-- Indexes for products
CREATE INDEX IF NOT EXISTS idx_wc_products_merchant_id
    ON woocommerce_sync.products(merchant_id);
CREATE INDEX IF NOT EXISTS idx_wc_products_wc_id
    ON woocommerce_sync.products(wc_product_id);
CREATE INDEX IF NOT EXISTS idx_wc_products_store_id
    ON woocommerce_sync.products(store_id);
CREATE INDEX IF NOT EXISTS idx_wc_products_status
    ON woocommerce_sync.products(status) WHERE is_deleted = 0;
CREATE INDEX IF NOT EXISTS idx_wc_products_sku
    ON woocommerce_sync.products(sku) WHERE is_deleted = 0;
CREATE INDEX IF NOT EXISTS idx_wc_products_name
    ON woocommerce_sync.products USING gin(to_tsvector('english', name));

-- Vector similarity index (IVFFlat for approximate nearest neighbor search)
-- Note: Create this after you have some data, with lists = sqrt(num_rows)
-- CREATE INDEX IF NOT EXISTS idx_wc_products_embedding
--     ON woocommerce_sync.products USING ivfflat (embedding vector_l2_ops) WITH (lists = 100);

-- =============================================================================
-- Webhooks Table
-- =============================================================================
CREATE TABLE IF NOT EXISTS woocommerce_sync.webhooks (
    id SERIAL PRIMARY KEY,
    store_id INTEGER NOT NULL REFERENCES woocommerce_sync.woocommerce_stores(id),
    merchant_id VARCHAR(255) NOT NULL,

    wc_webhook_id BIGINT UNIQUE NOT NULL,

    -- Webhook Details
    topic VARCHAR(100) NOT NULL,
    delivery_url VARCHAR(500) NOT NULL,
    secret VARCHAR(255),
    status VARCHAR(50) DEFAULT 'active',

    -- Status Tracking
    is_active INTEGER DEFAULT 1,
    last_verified_at TIMESTAMP WITH TIME ZONE,

    -- Timestamps
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE
);

-- Indexes for webhooks
CREATE INDEX IF NOT EXISTS idx_wc_webhooks_store_id
    ON woocommerce_sync.webhooks(store_id);
CREATE INDEX IF NOT EXISTS idx_wc_webhooks_merchant_id
    ON woocommerce_sync.webhooks(merchant_id);
CREATE INDEX IF NOT EXISTS idx_wc_webhooks_topic
    ON woocommerce_sync.webhooks(topic);
CREATE INDEX IF NOT EXISTS idx_wc_webhooks_active
    ON woocommerce_sync.webhooks(is_active);

-- =============================================================================
-- Comments
-- =============================================================================
COMMENT ON TABLE woocommerce_sync.woocommerce_stores IS 'Connected WooCommerce stores with encrypted API credentials';
COMMENT ON TABLE woocommerce_sync.products IS 'Products synced from WooCommerce stores';
COMMENT ON TABLE woocommerce_sync.webhooks IS 'Webhook subscriptions registered with WooCommerce';

COMMENT ON COLUMN woocommerce_sync.woocommerce_stores.consumer_key IS 'Encrypted WooCommerce API Consumer Key';
COMMENT ON COLUMN woocommerce_sync.woocommerce_stores.consumer_secret IS 'Encrypted WooCommerce API Consumer Secret';
COMMENT ON COLUMN woocommerce_sync.products.embedding IS '768-dimensional vector embedding for semantic search';
COMMENT ON COLUMN woocommerce_sync.products.raw_data IS 'Complete WooCommerce product JSON for flexibility';
