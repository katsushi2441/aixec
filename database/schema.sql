PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS products (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    internal_sku TEXT UNIQUE,
    jan TEXT,
    gtin TEXT,
    asin TEXT,
    maker TEXT,
    model_number TEXT,
    name TEXT NOT NULL,
    source_url TEXT,
    description TEXT,
    cost_price INTEGER,
    sale_price INTEGER,
    amazon_url TEXT,
    rakuten_url TEXT,
    own_store_url TEXT,
    xdirect_status TEXT,
    xdirect_http_status INTEGER,
    xdirect_checked_at TEXT,
    affiliate_priority TEXT DEFAULT 'auto',
    status TEXT DEFAULT 'draft',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS product_identifiers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    product_id INTEGER NOT NULL,
    id_type TEXT NOT NULL,
    id_value TEXT NOT NULL,
    source TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(product_id) REFERENCES products(id) ON DELETE CASCADE,
    UNIQUE(id_type, id_value)
);


CREATE TABLE IF NOT EXISTS product_attributes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    product_id INTEGER NOT NULL,
    attr_name TEXT NOT NULL,
    attr_value TEXT,
    source TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(product_id) REFERENCES products(id) ON DELETE CASCADE,
    UNIQUE(product_id, attr_name, source)
);

CREATE TABLE IF NOT EXISTS channel_payloads (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    product_id INTEGER NOT NULL,
    channel TEXT NOT NULL,
    external_id TEXT,
    payload_json TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(product_id) REFERENCES products(id) ON DELETE CASCADE,
    UNIQUE(channel, external_id)
);

CREATE TABLE IF NOT EXISTS price_rules (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    channel TEXT NOT NULL,
    markup_rate REAL NOT NULL DEFAULT 0,
    rounding_unit INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS import_jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_url TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'queued',
    raw_payload TEXT,
    result_payload TEXT,
    error_message TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_products_jan_unique ON products(jan) WHERE jan IS NOT NULL AND jan != '';
CREATE UNIQUE INDEX IF NOT EXISTS idx_products_gtin_unique ON products(gtin) WHERE gtin IS NOT NULL AND gtin != '';
CREATE UNIQUE INDEX IF NOT EXISTS idx_products_asin_unique ON products(asin) WHERE asin IS NOT NULL AND asin != '';
CREATE INDEX IF NOT EXISTS idx_products_maker_model ON products(maker, model_number);
CREATE INDEX IF NOT EXISTS idx_products_status ON products(status);
CREATE INDEX IF NOT EXISTS idx_identifiers_product ON product_identifiers(product_id);
CREATE INDEX IF NOT EXISTS idx_product_attributes_product ON product_attributes(product_id);
CREATE INDEX IF NOT EXISTS idx_channel_payloads_product ON channel_payloads(product_id);
CREATE INDEX IF NOT EXISTS idx_import_jobs_status ON import_jobs(status);
