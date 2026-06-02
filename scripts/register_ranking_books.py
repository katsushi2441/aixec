#!/usr/bin/env python3
"""楽天ブックスランキングからAIxECに書籍を一括登録する"""
import json
import ftplib
import html
import argparse
import os
import sqlite3
import sys
import time
from pathlib import Path
from urllib.parse import urlencode, urlparse
from urllib.request import urlopen, Request
from urllib.error import HTTPError, URLError

ROOT = Path(__file__).resolve().parents[1]
DB_PATH = Path(os.environ.get('AIXEC_DB', ROOT / 'storage' / 'aixec.sqlite'))
API_BASE = 'http://localhost:8081'
IMAGE_DIR = ROOT / 'webapps' / 'images' / 'products' / 'books'
BOOK_GENRES_JSON = ROOT / 'webapps' / 'data' / 'book_genres.json'

TABS = [
    {'label': '起業・開業',         'genre_id': '001006018003', 'keyword': '', 'group': 'startup'},
    {'label': '経営・マネジメント', 'genre_id': '001006018',    'keyword': '', 'group': 'management'},
    {'label': '健康・医療',         'genre_id': '001010010', 'keyword': '', 'group': 'health_medical'},
    {'label': '医学',               'genre_id': '', 'keyword': '医学', 'group': 'health_medical'},
    {'label': '漢方・東洋医学',     'genre_id': '', 'keyword': '漢方 東洋医学', 'group': 'health_medical'},
    {'label': '看護',               'genre_id': '', 'keyword': '看護 訪問看護', 'group': 'health_medical'},
    {'label': '介護・認知症',       'genre_id': '', 'keyword': '介護 認知症', 'group': 'health_medical'},
    {'label': 'リハビリ',           'genre_id': '', 'keyword': 'リハビリテーション', 'group': 'health_medical'},
    {'label': 'AI・テクノロジー',   'genre_id': '001005',    'keyword': 'AI', 'group': 'ai'},
    {'label': 'Web3・暗号資産',     'genre_id': '',          'keyword': 'ブロックチェーン', 'group': 'crypto_web3'},
    {'label': 'プログラミング・IT', 'genre_id': '001005005', 'keyword': '', 'group': 'it_programming'},
    {'label': '機械工学',           'genre_id': '001012010003', 'keyword': '', 'group': 'mechanical_engineering'},
    {'label': '電気工事・工具',     'genre_id': '001012010001', 'keyword': '電気工事士', 'group': 'electrical_tools'},
    {'label': 'DIY・リフォーム',    'genre_id': '001010004003', 'keyword': 'DIY', 'group': 'diy_renovation'},
    {'label': '木工・工具',         'genre_id': '001010004001', 'keyword': '木工', 'group': 'woodworking_tools'},
    {'label': '建設・施工',         'genre_id': '001012010002', 'keyword': '施工', 'group': 'construction'},
    {'label': '副業',               'genre_id': '', 'keyword': '副業', 'group': 'side_business'},
    {'label': '個人事業・確定申告', 'genre_id': '', 'keyword': '確定申告', 'group': 'sole_proprietor_tax'},
    {'label': '投資・新NISA',       'genre_id': '', 'keyword': '新NISA', 'group': 'investment_nisa'},
    {'label': '株式投資',           'genre_id': '', 'keyword': '株式投資', 'group': 'stock_investment'},
]

RAKUTEN_BOOKS_ENDPOINT = 'https://openapi.rakuten.co.jp/services/api/BooksBook/Search/20170404'
RAKUTEN_BOOKS_TAB_DELAY = float(os.environ.get('RAKUTEN_BOOKS_TAB_DELAY', '10.0'))


def load_env():
    env = {}
    for env_path in (ROOT.parent / '.env', ROOT / '.env'):
        if not env_path.exists():
            continue
        for line in env_path.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith('#') and '=' in line:
                k, v = line.split('=', 1)
                env.setdefault(k.strip(), v.strip().strip('"').strip("'"))
    return env


def fetch_books(env, genre_id, keyword, hits=20):
    app_id = env.get('RAKUTEN_APPLICATION_ID', '')
    access_key = env.get('RAKUTEN_ACCESS_KEY', '')
    affiliate_id = env.get('RAKUTEN_AFFILIATE_ID', '')
    params = {
        'applicationId': app_id,
        'format': 'json',
        'hits': str(hits),
        'sort': 'sales',
    }
    if genre_id:
        params['booksGenreId'] = genre_id
    if keyword:
        params['title'] = keyword
    if affiliate_id:
        params['affiliateId'] = affiliate_id
    url = RAKUTEN_BOOKS_ENDPOINT + '?' + urlencode(params)
    req = Request(url, headers={
        'User-Agent': 'AIxEC/0.1',
        'Referer': 'https://aixec.exbridge.jp/',
        'Origin': 'https://aixec.exbridge.jp',
        'accessKey': access_key,
    })
    with urlopen(req, timeout=20) as res:
        payload = json.loads(res.read().decode('utf-8'))
    books = []
    for item in payload.get('Items', []):
        if 'Item' in item:
            item = item['Item']
        books.append({
            'title':          item.get('title', ''),
            'author':         item.get('author', ''),
            'publisher_name': item.get('publisherName', ''),
            'isbn':           item.get('isbn', ''),
            'item_caption':   item.get('itemCaption', ''),
            'item_price':     item.get('itemPrice'),
            'item_url':       item.get('itemUrl', ''),
            'affiliate_url':  item.get('affiliateUrl') or item.get('itemUrl', ''),
            'image_url':      item.get('largeImageUrl') or item.get('mediumImageUrl') or '',
        })
    return books


def already_registered(isbn):
    """ISBNまたはinternal_skuで登録済みか確認"""
    if not isbn:
        return False
    with sqlite3.connect(str(DB_PATH)) as conn:
        row = conn.execute(
            "SELECT id FROM products WHERE jan=? OR internal_sku=?",
            (isbn, 'rakuten_books:' + isbn)
        ).fetchone()
    return row is not None


def register_book(book):
    isbn = book['isbn'].replace('-', '') if book['isbn'] else ''
    local_image = book.get('local_image') or ''
    desc = description(book, local_image)
    payload = {
        'name':               book['title'],
        'maker':              book.get('publisher_name') or '楽天ブックス',
        'model_number':       isbn or None,
        'jan':                isbn or None,
        'internal_sku':       'rakuten_books:' + isbn if isbn else None,
        'description':        desc,
        'sale_price':         book['item_price'],
        'source_url':         book['item_url'],
        'rakuten_url':        book['affiliate_url'],
        'affiliate_priority': 'rakuten',
        'status':             'active',
    }
    data = json.dumps(payload, ensure_ascii=False).encode('utf-8')
    req = Request(API_BASE + '/products', data=data,
                  headers={'Content-Type': 'application/json'}, method='POST')
    with urlopen(req, timeout=15) as res:
        result = json.loads(res.read().decode('utf-8'))
    return result.get('item', {})


def rakuten_go_url(book):
    params = {
        'to': 'rakuten',
        'kw': book.get('title') or '本',
    }
    isbn = book['isbn'].replace('-', '') if book.get('isbn') else ''
    if isbn:
        params['jan'] = isbn
        params['model'] = isbn
    return '/go.php?' + urlencode(params)


def description(book, local_image):
    title = html.escape(book.get('title') or '')
    author = html.escape(book.get('author') or '')
    publisher = html.escape(book.get('publisher_name') or '')
    isbn = html.escape(book['isbn'].replace('-', '') if book.get('isbn') else '')
    caption = html.escape(book.get('item_caption') or '')
    rakuten = html.escape(rakuten_go_url(book), quote=True)
    parts = [
        '<p style="margin-bottom:16px; padding:12px; background:#fff7f7; border:1px solid #bf0000; border-radius:4px;">'
        '<a href="%s" target="_blank" rel="nofollow sponsored noopener" style="color:#bf0000; font-weight:bold;">楽天でこの本を見る →</a><br>'
        '<span style="font-size:0.9em; color:#555;">楽天ブックスの商品ページで価格・在庫・電子書籍版をご確認ください。</span>'
        '</p>' % rakuten
    ]
    if local_image:
        parts.append('<p><img src="%s" alt="%s" style="max-width:100%%;"></p>' % (html.escape(local_image), title))
    parts.append('<p><strong>%s</strong></p>' % title)
    meta = []
    if author:
        meta.append('著者: %s' % author)
    if publisher:
        meta.append('出版社: %s' % publisher)
    if isbn:
        meta.append('ISBN/JAN: %s' % isbn)
    meta.append('形式: 書籍')
    parts.append('<p>%s</p>' % '<br>'.join(meta))
    if caption:
        parts.append('<p>%s</p>' % caption)
    return ''.join(parts)


def image_ext(url):
    path = urlparse(url).path.lower()
    if path.endswith('.png'):
        return '.png'
    if path.endswith('.webp'):
        return '.webp'
    return '.jpg'


def ensure_remote_dir(ftp, remote_dir):
    try:
        ftp.cwd(remote_dir)
    except ftplib.error_perm:
        ftp.mkd(remote_dir)
        ftp.cwd(remote_dir)


def upload_book_image(rel_path, env):
    host = env.get('FTP_HOST') or os.environ.get('FTP_HOST')
    user = env.get('FTP_USER') or os.environ.get('FTP_USER')
    password = env.get('FTP_PASS') or os.environ.get('FTP_PASS')
    remote_root = env.get('FTP_REMOTE') or os.environ.get('FTP_REMOTE') or '/web/aixec_exbridge_jp'
    if not (host and user and password):
        return False
    local_path = ROOT / 'webapps' / rel_path.lstrip('/')
    if not local_path.exists():
        return False
    parts = rel_path.strip('/').split('/')
    ftp = ftplib.FTP(host, timeout=30)
    try:
        ftp.login(user, password)
        ensure_remote_dir(ftp, remote_root)
        for part in parts[:-1]:
            ensure_remote_dir(ftp, part)
        with local_path.open('rb') as fh:
            ftp.storbinary('STOR ' + parts[-1], fh)
        return True
    finally:
        try:
            ftp.quit()
        except Exception:
            pass


def download_book_image(book, env=None):
    url = (book.get('image_url') or '').strip()
    if not url:
        return ''
    isbn = book['isbn'].replace('-', '') if book.get('isbn') else ''
    key = isbn or book.get('title', '').strip()
    if not key:
        return ''
    safe = ''.join(c if c.isalnum() or c in ('-', '_') else '-' for c in key).strip('-')[:80]
    if not safe:
        return ''
    IMAGE_DIR.mkdir(parents=True, exist_ok=True)
    rel = '/images/products/books/' + safe + image_ext(url)
    dest = ROOT / 'webapps' / rel.lstrip('/')
    if dest.exists() and dest.stat().st_size > 0:
        if env:
            try:
                upload_book_image(rel, env)
            except Exception as e:
                print(f"  image_upload_error ({book.get('title','')[:30]}): {e}", flush=True)
        return rel
    req = Request(url, headers={'User-Agent': 'AIxEC/0.1'})
    try:
        with urlopen(req, timeout=20) as res:
            data = res.read()
        if data:
            dest.write_bytes(data)
            if env:
                try:
                    upload_book_image(rel, env)
                except Exception as e:
                    print(f"  image_upload_error ({book.get('title','')[:30]}): {e}", flush=True)
            return rel
    except Exception as e:
        print(f"  image_error ({book.get('title','')[:30]}): {e}", flush=True)
    return ''


def upsert_book_attrs(product_id, image_url, book):
    if not product_id:
        return
    with sqlite3.connect(str(DB_PATH)) as conn:
        if image_url:
            conn.execute(
                """INSERT INTO product_attributes (product_id, attr_name, attr_value, source)
                   VALUES (?,?,?,?)
                   ON CONFLICT(product_id, attr_name, source)
                   DO UPDATE SET attr_value=excluded.attr_value""",
                (product_id, 'book_image', image_url, 'rakuten_books')
            )
        attr_values = {
            'book_author': book.get('author') or '',
            'book_publisher': book.get('publisher_name') or '',
            'book_source': 'book',
        }
        if book.get('item_caption'):
            attr_values['book_description_rakuten'] = book['item_caption']
        for attr_name, attr_value in attr_values.items():
            if attr_value:
                conn.execute(
                    """INSERT INTO product_attributes (product_id, attr_name, attr_value, source)
                       VALUES (?,?,?,?)
                       ON CONFLICT(product_id, attr_name, source)
                       DO UPDATE SET attr_value=excluded.attr_value""",
                    (product_id, attr_name, attr_value, 'rakuten_books')
                )
        description_source = 'rakuten' if (book.get('item_caption') or '') else 'basic'
        conn.execute(
            """INSERT INTO product_attributes (product_id, attr_name, attr_value, source)
               VALUES (?,?,?,?)
               ON CONFLICT(product_id, attr_name, source)
               DO UPDATE SET attr_value=excluded.attr_value""",
            (product_id, 'book_description_source', description_source, 'rakuten_books')
        )
        conn.commit()


def update_book_genre_json(product_id, label, group):
    if not product_id or not label or not group:
        return
    try:
        BOOK_GENRES_JSON.parent.mkdir(parents=True, exist_ok=True)
        if BOOK_GENRES_JSON.exists():
            data = json.loads(BOOK_GENRES_JSON.read_text(encoding='utf-8'))
        else:
            data = {}
        key = str(int(product_id))
        current = data.get(key, {})
        keywords = list(current.get('keywords', []))
        groups = list(current.get('groups', []))
        if label not in keywords:
            keywords.append(label)
        if group not in groups:
            groups.append(group)
        current['keywords'] = keywords
        current['groups'] = groups
        data[key] = current
        BOOK_GENRES_JSON.write_text(json.dumps(data, ensure_ascii=False, separators=(',', ':')), encoding='utf-8')
    except Exception as e:
        print(f"  genre_json_error ({product_id}): {e}", flush=True)


def enrich_book_metadata(product_id):
    if not product_id:
        return
    try:
        from enrich_books_metadata import connect, enrich_one, load_books
        with connect() as conn:
            rows = load_books(conn, limit=1, min_id=int(product_id), max_id=int(product_id))
            if rows:
                stats = enrich_one(conn, rows[0])
                print(
                    "  enrich openbd=%s google=%s desc=%s" %
                    (stats.get('openbd_hit', 0), stats.get('google_hit', 0), stats.get('description', 0)),
                    flush=True
                )
    except Exception as e:
        print(f"  enrich_error ({product_id}): {e}", flush=True)


def selected_tabs(groups=None, labels=None):
    groups = set(groups or [])
    labels = set(labels or [])
    if not groups and not labels:
        return list(TABS)
    tabs = []
    for tab in TABS:
        if tab.get('group') in groups or tab.get('label') in labels:
            tabs.append(tab)
    return tabs


def run_all_tabs(env=None, groups=None, labels=None):
    """全タブを巡回して書籍を登録する。

    Returns:
        dict: {tab_label: [新規登録タイトル, ...], ...}  新規0件のタブは含まない
    """
    if env is None:
        env = load_env()
    new_by_tab = {}

    tabs = selected_tabs(groups=groups, labels=labels)
    for idx, tab in enumerate(tabs):
        if idx > 0 and RAKUTEN_BOOKS_TAB_DELAY > 0:
            print(f"  wait {RAKUTEN_BOOKS_TAB_DELAY:g}s before next Rakuten Books request", flush=True)
            time.sleep(RAKUTEN_BOOKS_TAB_DELAY)
        print(f"\n[{tab['label']}] 取得中...", flush=True)
        try:
            books = fetch_books(env, tab['genre_id'], tab['keyword'], hits=20)
        except Exception as e:
            print(f"  ERROR: {e}", flush=True)
            continue

        print(f"  {len(books)}件取得", flush=True)
        tab_new = []
        for book in books:
            if not book['title']:
                continue
            isbn = book['isbn'].replace('-', '') if book['isbn'] else ''
            if already_registered(isbn):
                print(f"  - (skip) {book['title'][:40]}", flush=True)
                continue
            try:
                local_image = download_book_image(book, env)
                book['local_image'] = local_image
                item = register_book(book)
                product_id = item.get('id')
                if product_id:
                    upsert_book_attrs(product_id, local_image or book['image_url'], book)
                    update_book_genre_json(product_id, tab['label'], tab.get('group', ''))
                    enrich_book_metadata(product_id)
                    tab_new.append(book['title'])
                    print(f"  + [{product_id}] {book['title'][:40]}", flush=True)
                else:
                    print(f"  ? {book['title'][:40]}", flush=True)
            except Exception as e:
                print(f"  ERROR ({book['title'][:30]}): {e}", flush=True)

        if tab_new:
            new_by_tab[tab['label']] = tab_new

    total_new = sum(len(v) for v in new_by_tab.values())
    print(f"\n完了: 新規登録 {total_new}件", flush=True)
    return new_by_tab


def main():
    parser = argparse.ArgumentParser(description='楽天ブックスランキングからAIxECに書籍を登録する')
    parser.add_argument('--groups', default='', help='カンマ区切りのgroupだけ実行する')
    parser.add_argument('--labels', default='', help='カンマ区切りのlabelだけ実行する')
    args = parser.parse_args()
    groups = [x.strip() for x in args.groups.split(',') if x.strip()]
    labels = [x.strip() for x in args.labels.split(',') if x.strip()]
    new_by_tab = run_all_tabs(groups=groups, labels=labels)
    total = sum(len(v) for v in new_by_tab.values())
    print(f"新規登録合計: {total}件", flush=True)


if __name__ == '__main__':
    main()
