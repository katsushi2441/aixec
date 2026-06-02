#!/usr/bin/env python3
import argparse
import csv
import sqlite3
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB = ROOT / "storage" / "aixec.sqlite"
DEFAULT_INPUT = ROOT.parent / "data" / "asahikoki_missing_products_proposal.csv"


def connect(db_path):
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def load_rows(path):
    with path.open(newline="", encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))
    if not rows:
        raise SystemExit("No rows to import")
    return rows


def product_values(row):
    return {
        "internal_sku": "asahikoki-price:" + row["jan"],
        "jan": row["jan"],
        "gtin": row["jan"],
        "asin": None,
        "maker": "旭工機",
        "model_number": row["model_number"],
        "name": row["name"],
        "source_url": row["source_url"],
        "description": row["description"],
        "cost_price": int(row["cost_price"]),
        "sale_price": int(row["sale_price"]),
        "amazon_url": None,
        "rakuten_url": None,
        "own_store_url": None,
        "affiliate_priority": "auto",
        "status": "active",
    }


def upsert_attr(conn, product_id, name, value, source="asahikoki_price"):
    if value is None or str(value).strip() == "":
        return
    conn.execute(
        """INSERT INTO product_attributes
           (product_id, attr_name, attr_value, source, created_at, updated_at)
           VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
           ON CONFLICT(product_id, attr_name, source) DO UPDATE SET
             attr_value=excluded.attr_value,
             updated_at=CURRENT_TIMESTAMP""",
        (product_id, name, str(value), source),
    )


def upsert_identifier(conn, product_id, id_type, id_value):
    if not id_value:
        return
    conn.execute(
        """INSERT OR IGNORE INTO product_identifiers
           (product_id, id_type, id_value, source)
           VALUES (?, ?, ?, 'asahikoki_price')""",
        (product_id, id_type, str(id_value)),
    )


def upsert_product(conn, row):
    values = product_values(row)
    existing = conn.execute(
        """SELECT id FROM products
           WHERE internal_sku = ? OR jan = ? OR (maker = ? AND model_number = ?)
           LIMIT 1""",
        (
            values["internal_sku"],
            values["jan"],
            values["maker"],
            values["model_number"],
        ),
    ).fetchone()
    if existing:
        product_id = existing["id"]
        conn.execute(
            """UPDATE products SET
                 internal_sku=:internal_sku, jan=:jan, gtin=:gtin, asin=:asin,
                 maker=:maker, model_number=:model_number, name=:name,
                 source_url=:source_url, description=:description,
                 cost_price=:cost_price, sale_price=:sale_price,
                 amazon_url=:amazon_url, rakuten_url=:rakuten_url,
                 own_store_url=:own_store_url,
                 affiliate_priority=:affiliate_priority, status=:status,
                 updated_at=CURRENT_TIMESTAMP
               WHERE id=:id""",
            dict(values, id=product_id),
        )
    else:
        cur = conn.execute(
            """INSERT INTO products
               (internal_sku, jan, gtin, asin, maker, model_number, name,
                source_url, description, cost_price, sale_price, amazon_url,
                rakuten_url, own_store_url, affiliate_priority, status,
                created_at, updated_at)
               VALUES
               (:internal_sku, :jan, :gtin, :asin, :maker, :model_number, :name,
                :source_url, :description, :cost_price, :sale_price, :amazon_url,
                :rakuten_url, :own_store_url, :affiliate_priority, :status,
                CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)""",
            values,
        )
        product_id = cur.lastrowid

    upsert_identifier(conn, product_id, "jan", values["jan"])
    upsert_identifier(conn, product_id, "gtin", values["gtin"])
    upsert_identifier(conn, product_id, "model_number", values["model_number"])
    upsert_identifier(conn, product_id, "internal_sku", values["internal_sku"])
    upsert_attr(conn, product_id, "asahikoki_list_price", row["list_price"])
    upsert_attr(conn, product_id, "asahikoki_name1", row["name1"])
    upsert_attr(conn, product_id, "asahikoki_name2", row["name2"])
    upsert_attr(conn, product_id, "asahikoki_raw_model", row["raw_model"])
    upsert_attr(conn, product_id, "asahikoki_source_url", row["source_url"])
    upsert_attr(conn, product_id, "product_image", row["image_url"], "asahikoki_official")
    return product_id


def main():
    parser = argparse.ArgumentParser(description="Import Asahi Koki price-list-only products into AIxEC")
    parser.add_argument("--db", default=str(DEFAULT_DB))
    parser.add_argument("--input", default=str(DEFAULT_INPUT))
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    rows = load_rows(Path(args.input))
    conn = connect(Path(args.db))
    try:
        existing = 0
        for row in rows:
            found = conn.execute(
                """SELECT id FROM products
                   WHERE internal_sku = ? OR jan = ? OR (maker = '旭工機' AND model_number = ?)
                   LIMIT 1""",
                ("asahikoki-price:" + row["jan"], row["jan"], row["model_number"]),
            ).fetchone()
            if found:
                existing += 1
        print(f"input_rows={len(rows)} existing_matches={existing} new_or_update={len(rows)}")
        if not args.apply:
            print("dry-run only; pass --apply to write DB")
            return
        with conn:
            ids = [upsert_product(conn, row) for row in rows]
        print("upserted=%d first_id=%s last_id=%s" % (len(ids), ids[0], ids[-1]))
    finally:
        conn.close()


if __name__ == "__main__":
    main()
