#!/usr/bin/env python3
"""Read-only Amazon Creators API client for AIxEC experiments."""
from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from pathlib import Path
from urllib.parse import urlencode

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CREDENTIALS_CSV = ROOT / "docs" / "AIxEC-credentials.csv"


def load_dotenv() -> None:
    for env_path in (ROOT.parent / ".env", ROOT / ".env"):
        if not env_path.exists():
            continue
        for line in env_path.read_text(encoding="utf-8", errors="ignore").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def load_csv_credentials(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    with path.open(newline="", encoding="utf-8-sig") as fh:
        rows = list(csv.DictReader(fh))
    if not rows:
        return {}
    row = rows[0]
    return {
        "credential_id": row.get("Credential Id", "").strip(),
        "credential_secret": row.get("Secret", "").strip(),
        "version": row.get("Version", "").strip(),
        "application_id": row.get("Application Id", "").strip(),
    }


def settings(args) -> dict[str, str]:
    load_dotenv()
    csv_creds = load_csv_credentials(Path(args.credentials_csv))
    credential_id = (
        os.environ.get("AMAZON_API_CREDENTIAL_ID")
        or os.environ.get("AMAZON_API_CLIENT_ID")
        or csv_creds.get("credential_id")
    )
    credential_secret = (
        os.environ.get("AMAZON_API_CREDENTIAL_SECRET")
        or os.environ.get("AMAZON_API_CLIENT_SECRET")
        or csv_creds.get("credential_secret")
    )
    version = os.environ.get("AMAZON_API_VERSION") or csv_creds.get("version") or "3.3"
    partner_tag = os.environ.get("AMAZON_ASSOCIATE_TAG") or os.environ.get("AMAZON_PARTNER_TAG") or "bittensorman-22"
    marketplace = os.environ.get("AMAZON_MARKETPLACE") or "www.amazon.co.jp"
    missing = []
    if not credential_id:
        missing.append("AMAZON_API_CREDENTIAL_ID")
    if not credential_secret:
        missing.append("AMAZON_API_CREDENTIAL_SECRET")
    if missing:
        raise SystemExit("missing credentials: " + ", ".join(missing))
    return {
        "credential_id": credential_id,
        "credential_secret": credential_secret,
        "version": version,
        "partner_tag": partner_tag,
        "marketplace": marketplace,
    }


def build_api(config: dict[str, str]):
    try:
        from creators import Client

        return (
            "creators",
            Client(
                credential_id=config["credential_id"],
                credential_secret=config["credential_secret"],
                version=config["version"],
                marketplace=config["marketplace"],
                partner_tag=config["partner_tag"],
            ),
        )
    except ModuleNotFoundError:
        if str(config["version"]).startswith("3."):
            raise SystemExit(
                "Amazon Creators API credential version %s needs the newer creators package. "
                "Run with: uv run --python 3.12 --with creators python scripts/amazon_creators_client.py ..."
                % config["version"]
            )

    try:
        from creatorsapi_python_sdk import ApiClient, DefaultApi
    except ModuleNotFoundError as exc:
        raise SystemExit(
            "amazon-creatorsapi-python-sdk is not installed. "
            "Install with: python3 -m pip install --user amazon-creatorsapi-python-sdk"
        ) from exc
    api_client = ApiClient(
        credential_id=config["credential_id"],
        credential_secret=config["credential_secret"],
        version=config["version"],
    )
    return ("sdk", DefaultApi(api_client))


def high_value_resources():
    try:
        from creators import SearchItemsResource
    except ModuleNotFoundError:
        from creatorsapi_python_sdk import SearchItemsResource

    return [
        SearchItemsResource.ITEM_INFO_DOT_TITLE,
        SearchItemsResource.ITEM_INFO_DOT_BY_LINE_INFO,
        SearchItemsResource.ITEM_INFO_DOT_FEATURES,
        SearchItemsResource.ITEM_INFO_DOT_PRODUCT_INFO,
        SearchItemsResource.ITEM_INFO_DOT_TECHNICAL_INFO,
        SearchItemsResource.ITEM_INFO_DOT_EXTERNAL_IDS,
        SearchItemsResource.IMAGES_DOT_PRIMARY_DOT_LARGE,
        SearchItemsResource.OFFERS_V2_DOT_LISTINGS_DOT_PRICE,
        SearchItemsResource.OFFERS_V2_DOT_LISTINGS_DOT_AVAILABILITY,
        SearchItemsResource.OFFERS_V2_DOT_LISTINGS_DOT_IS_BUY_BOX_WINNER,
        SearchItemsResource.BROWSE_NODE_INFO_DOT_BROWSE_NODES,
        SearchItemsResource.BROWSE_NODE_INFO_DOT_BROWSE_NODES_DOT_SALES_RANK,
        SearchItemsResource.BROWSE_NODE_INFO_DOT_WEBSITE_SALES_RANK,
        SearchItemsResource.CUSTOMER_REVIEWS_DOT_COUNT,
        SearchItemsResource.CUSTOMER_REVIEWS_DOT_STAR_RATING,
    ]


def as_plain(value):
    if value is None:
        return None
    if isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, list):
        return [as_plain(v) for v in value]
    if isinstance(value, dict):
        return {k: as_plain(v) for k, v in value.items()}
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json", by_alias=True, exclude_none=True)
    if hasattr(value, "to_dict"):
        return value.to_dict()
    return str(value)


def dig(data, *path):
    cur = data
    for key in path:
        if cur is None:
            return None
        if isinstance(cur, dict):
            cur = cur.get(key)
        elif isinstance(cur, list):
            if not isinstance(key, int) or key >= len(cur):
                return None
            cur = cur[key]
        else:
            return None
    return cur


def first_listing(item: dict):
    return dig(item, "offersV2", "listings", 0) or {}


def first_image(item: dict) -> str:
    return (
        dig(item, "images", "primary", "large", "url")
        or dig(item, "images", "primary", "medium", "url")
        or dig(item, "images", "primary", "small", "url")
        or ""
    )


def first_price(item: dict):
    listing = first_listing(item)
    price = dig(listing, "price")
    if isinstance(price, dict):
        return price.get("amount") or price.get("displayAmount")
    return price


def first_browse_node_rank(item: dict):
    nodes = dig(item, "browseNodeInfo", "browseNodes") or []
    best = None
    for node in nodes:
        rank = node.get("salesRank") if isinstance(node, dict) else None
        try:
            rank_int = int(rank)
        except (TypeError, ValueError):
            continue
        if best is None or rank_int < best:
            best = rank_int
    return best


def amazon_detail_url(asin: str, partner_tag: str) -> str:
    query = urlencode({"tag": partner_tag}) if partner_tag else ""
    return "https://www.amazon.co.jp/dp/%s%s" % (asin, ("?" + query) if query else "")


def normalize_item(item: dict, keyword: str, partner_tag: str) -> dict:
    asin = item.get("asin") or item.get("ASIN") or ""
    title = dig(item, "itemInfo", "title", "displayValue") or item.get("title") or ""
    byline = dig(item, "itemInfo", "byLineInfo", "brand", "displayValue") or ""
    features = dig(item, "itemInfo", "features", "displayValues") or []
    website_rank = dig(item, "browseNodeInfo", "websiteSalesRank", "salesRank")
    return {
        "source": "amazon_creators",
        "keyword": keyword,
        "name": str(title).strip(),
        "catchcopy": "",
        "caption": " / ".join(str(v) for v in features[:5]),
        "price": first_price(item),
        "item_url": amazon_detail_url(asin, partner_tag) if asin else "",
        "affiliate_url": amazon_detail_url(asin, partner_tag) if asin else "",
        "image_url": first_image(item),
        "shop_name": "Amazon",
        "shop_code": "amazon",
        "item_code": asin,
        "asin": asin,
        "brand": byline,
        "genre_id": str(dig(item, "browseNodeInfo", "browseNodes", 0, "id") or ""),
        "review_average": dig(item, "customerReviews", "starRating", "value") or "",
        "review_count": dig(item, "customerReviews", "count") or "",
        "sales_rank": first_browse_node_rank(item),
        "website_sales_rank": website_rank,
    }


def search(args) -> list[dict]:
    try:
        from creators import Availability, SearchItemsRequestContent, SortBy
    except ModuleNotFoundError:
        from creatorsapi_python_sdk import Availability, SearchItemsRequestContent, SortBy

    config = settings(args)
    api_kind, api = build_api(config)
    sort = getattr(SortBy, args.sort_enum)
    try:
        if api_kind == "creators":
            response = api.search_items(
                keywords=args.keywords,
                search_index=args.search_index,
                item_count=args.limit,
                item_page=args.page,
                min_price=args.min_price,
                availability=Availability.AVAILABLE,
                sort_by=sort,
                languages_of_preference=["ja_JP"],
                resources=high_value_resources(),
            )
        else:
            request = SearchItemsRequestContent(
                partnerTag=config["partner_tag"],
                keywords=args.keywords,
                searchIndex=args.search_index,
                itemCount=args.limit,
                itemPage=args.page,
                minPrice=args.min_price,
                availability=Availability.AVAILABLE,
                sortBy=sort,
                languagesOfPreference=["ja_JP"],
                resources=high_value_resources(),
            )
            response = api.search_items(config["marketplace"], request, _request_timeout=args.timeout)
    except Exception as exc:
        text = str(exc)
        if "AssociateNotEligible" in text or "eligibility requirements" in text:
            raise SystemExit(
                "Amazon Creators API request was authenticated, but Amazon rejected this account as not eligible yet "
                "(AssociateNotEligible). Check Creators API eligibility in Associates Central."
            ) from exc
        raise
    plain = as_plain(response)
    items = dig(plain, "searchResult", "items") or []
    normalized = [normalize_item(item, args.keywords, config["partner_tag"]) for item in items]
    return normalized


def print_items(items: list[dict], raw_json: bool) -> None:
    if raw_json:
        print(json.dumps(items, ensure_ascii=False, indent=2))
        return
    print("items=%d" % len(items))
    for idx, item in enumerate(items, 1):
        print(
            "#{idx} price={price} rank={rank} web_rank={web_rank} asin={asin} brand={brand} name={name}".format(
                idx=idx,
                price=item.get("price") or "",
                rank=item.get("sales_rank") or "",
                web_rank=item.get("website_sales_rank") or "",
                asin=item.get("asin") or "",
                brand=(item.get("brand") or "")[:30],
                name=(item.get("name") or "")[:120],
            )
        )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["search"])
    parser.add_argument("--credentials-csv", default=str(DEFAULT_CREDENTIALS_CSV))
    parser.add_argument("--keywords", default="RTX 5090 ゲーミングPC")
    parser.add_argument("--search-index", default="All")
    parser.add_argument("--limit", type=int, default=5)
    parser.add_argument("--page", type=int, default=1)
    parser.add_argument("--min-price", type=int, default=50000)
    parser.add_argument(
        "--sort-enum",
        default="FEATURED",
        choices=["FEATURED", "PRICE_COLON_HIGH_TO_LOW", "RELEVANCE", "AVGCUSTOMERREVIEWS", "NEWESTARRIVALS"],
    )
    parser.add_argument("--timeout", type=int, default=30)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    if args.command == "search":
        items = search(args)
        print_items(items, args.json)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
