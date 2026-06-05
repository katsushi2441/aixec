# Amazon Creators API Integration Notes

## Purpose

AIxEC can use Amazon Creators API to enrich affiliate product pages and future
market registration flows with Amazon catalog data.

This is not the old PA-API 5.0 integration plan. Amazon now points developers to
Creators API as the current documentation path for programmatic product catalog
access.

## Local Credentials

Local credential CSV:

```text
docs/AIxEC-credentials.csv
```

This file contains secrets and is intentionally ignored by Git.

Expected columns:

```text
Application, Application Id, Credential Id, Secret, Version
```

Do not commit this file, copy its values into source code, or write secrets to
logs.

## Useful Operations

The product-catalog operations that matter first for AIxEC are:

- `SearchItems`: keyword, filter, or browse-node based product search.
- `GetItems`: detailed lookup for ASIN or other item identifiers.
- `GetVariations`: variation lookup for parent products.
- `GetBrowseNodes`: category and browse-node hierarchy lookup.

## AIxEC Fit

Use Creators API as a read-side product source only.

Initial integration should be a small Python module that:

1. Loads credentials from environment variables or the local CSV.
2. Searches Amazon products by keyword/JAN/ISBN/ASIN.
3. Normalizes results into AIxEC candidate item JSON.
4. Sends registration candidates to the existing AIxEC API flow.

Do not let RQDB4AI or other queue systems write directly to the production
SQLite database. Amazon-derived candidates should follow the same API-based
registration boundary as Rakuten-derived candidates.

## Recommended Environment Variables

```bash
AMAZON_API_CLIENT_ID=
AMAZON_API_CLIENT_SECRET=
AMAZON_API_CREDENTIAL_ID=
AMAZON_API_VERSION=v3.3
AMAZON_ASSOCIATE_TAG=bittensorman-22
AMAZON_MARKETPLACE=www.amazon.co.jp
```

## First Implementation Target

Create a small client module, for example:

```text
scripts/amazon_creators_client.py
```

The first test should be read-only:

```bash
python3 scripts/amazon_creators_client.py search --keywords "生成AI 書籍" --limit 5
python3 scripts/amazon_creators_client.py get --asin "XXXXXXXXXX"
```

After read-only search works, integrate it into product candidate generation.

## Notes

- Keep API credentials in `.env` or local CSV only.
- Store only normalized product metadata needed by AIxEC.
- Keep affiliate links generated through AIxEC `go.php` so click tracking stays
  consistent.
- Respect Amazon Associates and Creators API usage policies when displaying
  prices, images, and product details.
