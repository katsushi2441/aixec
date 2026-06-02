#!/usr/bin/env python3
"""Upload public webapp files to the heteml server.

By default, product image directories are skipped because AIxEC should use
affiliate provider image URLs directly instead of storing book/product images.
"""
import argparse
import ftplib
import os
from pathlib import Path

HOST = os.environ["FTP_HOST"]
USER = os.environ["FTP_USER"]
PASS = os.environ["FTP_PASS"]
REMOTE = os.environ.get("FTP_REMOTE", "/web/aixec_exbridge_jp")
ROOT = Path(__file__).resolve().parents[1]
WEBAPPS = ROOT / "webapps"
SKIP_DIRS = {
    ("images", "products"),
}


def ensure_remote_dir(ftp, remote_dir):
    try:
        ftp.cwd(remote_dir)
    except ftplib.error_perm:
        ftp.mkd(remote_dir)
        ftp.cwd(remote_dir)


def should_skip_dir(path, include_product_images=False):
    if include_product_images:
        return False
    try:
        rel = path.relative_to(WEBAPPS).parts
    except ValueError:
        return False
    return any(rel[:len(prefix)] == prefix for prefix in SKIP_DIRS)


def upload_dir(ftp, local_dir, remote_dir, include_product_images=False):
    ensure_remote_dir(ftp, remote_dir)
    for path in sorted(local_dir.iterdir()):
        if path.is_file():
            with path.open("rb") as fh:
                ftp.storbinary("STOR " + path.name, fh)
            print("uploaded", path.relative_to(WEBAPPS))
        elif path.is_dir():
            if should_skip_dir(path, include_product_images=include_product_images):
                print("skipped", path.relative_to(WEBAPPS))
                continue
            upload_dir(ftp, path, remote_dir + "/" + path.name, include_product_images=include_product_images)
    ftp.cwd("..")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--include-product-images",
        action="store_true",
        help="Upload webapps/images/products. Do not use for Rakuten/Amazon affiliate products.",
    )
    args = parser.parse_args()
    ftp = ftplib.FTP(HOST, timeout=30)
    ftp.login(USER, PASS)
    upload_dir(ftp, WEBAPPS, REMOTE, include_product_images=args.include_product_images)
    ftp.quit()


if __name__ == "__main__":
    main()
