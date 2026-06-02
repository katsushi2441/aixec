# AIxEC

AIxEC is a VS Code centric PIM/API project for AI assisted EC operations and affiliate-oriented product publishing.

## Local start

```bash
cd /home/kojima/exdirect/aixec
sqlite3 storage/aixec.sqlite < database/schema.sql
php -S 127.0.0.1:8020 -t public
```

## Endpoints

- `GET /health`
- `GET /products`
- `GET /products/{jan}`
- `POST /products`
- `POST /import/url` currently stores an import job stub

## Heteml

The `aixec.exbridge.jp` document root is `/web/aixec_exbridge_jp` and PHP 8.2 is enabled by `.htaccess`:

```apache
AddHandler php8.2-script .php
```
