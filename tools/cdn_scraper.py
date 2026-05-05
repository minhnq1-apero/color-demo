#!/usr/bin/env python3
"""
CDN scraper — Iceors Color-by-Number catalog → CMS JSON manifest.

Fetches the live catalog, downloads all assets (lineart preview, mid-preview,
game ZIP) and emits a catalog.json that matches the schema in cmssetupdata.md.

Usage:
    python tools/cdn_scraper.py [options]

Options:
    -o, --output DIR        Output directory (default: cdn_output)
    --workers N             Parallel download workers (default: 6)
    --json-only             Fetch catalog and emit catalog.json only; skip all downloads
    --upload                After downloading, upload assets to Cloudflare R2 and write
                            public URLs into catalog.json (requires boto3)
    --collections NAME...   Download only these collection names (case-insensitive)
    --limit N               Cap items per collection (for quick testing)
"""

from __future__ import annotations

import argparse
import json
import sys
import threading
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Literal

# ── CDN constants ──────────────────────────────────────────────────────────────

CATALOG_URL  = "https://coloring.galaxyaura.com/coloringbook"
CDN_ROOT     = "http://zhangxiaobog.cdn-doodlemobile.com/color_book"
USER_AGENT   = (
    "Mozilla/5.0 (Linux; Android 14; sdk_gphone64_arm64 Build/UPB5.230623.003)"
    " ColoringBook/3.7.8"
)
CATALOG_BODY = b'{"cv":0,"tz":0,"banner":0,"cl":0,"dy":0,"dy2":0,"fev":0}'

# ── Cloudflare R2 config ───────────────────────────────────────────────────────
# Override via env vars: R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY

import os as _os
R2_ENDPOINT    = "https://e21f4d523154ce4879fb3248016b60ce.r2.cloudflarestorage.com"
R2_BUCKET      = "data"
R2_PUBLIC_BASE = "https://pub-bb57f8079c734f2c9a3d9bb44fba8197.r2.dev"
R2_ACCESS_KEY  = _os.environ.get("R2_ACCESS_KEY_ID",     "bc60de286f794d231abe50a36f1db3a8")
R2_SECRET_KEY  = _os.environ.get("R2_SECRET_ACCESS_KEY", "3252e5ab217dae5ef1ee1bd80156c6ae624c275140d731bfa6756aa83b802dd2")

# ── CDN URL builders (mirror IceorsCdn.kt) ────────────────────────────────────

def _enc(s: str) -> str:
    return urllib.parse.quote(s, safe="")

def url_lineart(key: str) -> str:
    k = _enc(key)
    return f"{CDN_ROOT}/pictures/{k}/{k}"


def url_mid_preview(key: str) -> str:
    k = _enc(key)
    return f"{CDN_ROOT}/pictures/{k}/{k}_mid"

def url_game_zip(key: str) -> str:
    k = _enc(key)
    return f"{CDN_ROOT}/zips/{k}_b.zip"


# ── HTTP helpers ───────────────────────────────────────────────────────────────

def http_post(url: str, body: bytes, timeout: int = 30) -> bytes | None:
    req = urllib.request.Request(
        url, data=body, method="POST",
        headers={
            "User-Agent": USER_AGENT,
            "Content-Type": "text/plain; charset=utf-8",
            "Cache-Control": "no-cache, max-age=0",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read()
    except Exception as e:
        print(f"[ERROR] POST {url}: {e}", file=sys.stderr)
        return None


def http_get(url: str, timeout: int = 30) -> bytes | None:
    req = urllib.request.Request(
        url,
        headers={"User-Agent": USER_AGENT, "Cache-Control": "no-cache, max-age=0"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read()
    except urllib.error.HTTPError as e:
        if e.code in (403, 404):
            return None   # missing on CDN — treated as skip
        raise
    except Exception:
        return None

# ── Data models (matching cmssetupdata.md) ────────────────────────────────────

Badge    = Literal["NEW", "HOT"]
ItemType = Literal["WITH_IMAGE", "WITHOUT_IMAGE"]


@dataclass
class Item:
    id: str
    name: str
    badge: Badge
    type: ItemType
    preview_image: str    # local path or R2 public URL
    result_image: str     # local path or R2 public URL
    data_zip: str         # local path or R2 public URL


@dataclass
class Category:
    id: str
    name: str
    items: list[Item] = field(default_factory=list)

# ── Catalog parsing ────────────────────────────────────────────────────────────

def _item_type_from_catalog(pic_type: str, pic_game_type: int) -> ItemType:
    """
    Derive WITH_IMAGE / WITHOUT_IMAGE from catalog fields.

    IceorsCache.kt notes:
      picGameType 4/5 (SP/SPV/SSPV) → zip contains {key}c  → WITH_IMAGE
      picGameType 3   (V/oil/fairy)  → zip contains only {key}b → WITHOUT_IMAGE
    Fallback: check if "SPV" or "SP" appears in the type string.
    """
    if pic_game_type in (4, 5):
        return "WITH_IMAGE"
    if pic_game_type == 3:
        return "WITHOUT_IMAGE"
    # type string heuristic
    t = pic_type.upper()
    if "SPV" in t or t.startswith("SP"):
        return "WITH_IMAGE"
    return "WITHOUT_IMAGE"


def parse_catalog(raw: dict, limit: int | None = None) -> list[Category]:
    cb = raw.get("collectionBean") or {}
    collections = cb.get("collection") or []
    categories: list[Category] = []

    for coll in collections:
        cat_id   = coll.get("name", "").strip()
        cat_name = coll.get("displayName", cat_id).strip()
        if not cat_id:
            continue

        pics = coll.get("pics") or []
        if limit:
            pics = pics[:limit]

        items: list[Item] = []
        for pic in pics:
            key = pic.get("key", "").strip()
            if not key:
                continue
            items.append(Item(
                id=key,
                name=key,          # CDN has no human-readable name; update in CMS
                badge="NEW",       # unknown from CDN; update in CMS after review
                type=_item_type_from_catalog(
                    pic.get("type", ""),
                    pic.get("picGameType", 0),
                ),
                preview_image="",
                result_image="",
                data_zip="",
            ))

        categories.append(Category(id=cat_id, name=cat_name, items=items))

    return categories

# ── File download helpers ──────────────────────────────────────────────────────

def download_to(url: str, dest: Path) -> bool:
    """Download url → dest. Returns True on success. Skips if file already exists."""
    if dest.exists() and dest.stat().st_size > 0:
        return True
    dest.parent.mkdir(parents=True, exist_ok=True)
    data = http_get(url)
    if not data:
        return False
    tmp = dest.with_name(dest.name + ".part")
    tmp.write_bytes(data)
    tmp.rename(dest)
    return True


def refine_type_from_zip(zip_path: Path, key: str) -> ItemType:
    """Read zip and check for {key}c to confirm WITH_IMAGE / WITHOUT_IMAGE."""
    try:
        with zipfile.ZipFile(zip_path) as zf:
            if f"{key}c" in zf.namelist():
                return "WITH_IMAGE"
    except Exception:
        pass
    return "WITHOUT_IMAGE"

# ── R2 upload helpers ─────────────────────────────────────────────────────────

_MIME = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
         ".zip": "application/zip"}

# Thread-local boto3 client — boto3 sessions are not thread-safe to share.
_tls = threading.local()

def _r2_client():
    if not hasattr(_tls, "s3"):
        try:
            import boto3
        except ImportError:
            sys.exit("[FATAL] boto3 is required for --upload.  Install: pip install boto3")
        _tls.s3 = boto3.client(
            "s3",
            endpoint_url=R2_ENDPOINT,
            aws_access_key_id=R2_ACCESS_KEY,
            aws_secret_access_key=R2_SECRET_KEY,
            region_name="auto",
        )
    return _tls.s3


def r2_upload(local: Path, object_key: str) -> str:
    """Upload local file to R2. Returns public URL. Skips if object already exists."""
    import botocore.exceptions
    s3 = _r2_client()
    try:
        s3.head_object(Bucket=R2_BUCKET, Key=object_key)
        return f"{R2_PUBLIC_BASE}/{object_key}"   # already uploaded
    except botocore.exceptions.ClientError as e:
        code = e.response["Error"]["Code"]
        if code not in ("404", "NoSuchKey"):
            raise RuntimeError(f"R2 head_object failed ({code}): {e}") from e
    mime = _MIME.get(local.suffix.lower(), "application/octet-stream")
    try:
        s3.upload_file(str(local), R2_BUCKET, object_key,
                       ExtraArgs={"ContentType": mime})
    except Exception as e:
        raise RuntimeError(f"R2 upload failed for {object_key}: {e}") from e
    return f"{R2_PUBLIC_BASE}/{object_key}"


def r2_test_connection() -> None:
    """Quick auth check — raises RuntimeError with a clear message on failure."""
    import botocore.exceptions
    s3 = _r2_client()
    try:
        s3.list_objects_v2(Bucket=R2_BUCKET, MaxKeys=1)
    except botocore.exceptions.ClientError as e:
        code = e.response["Error"]["Code"]
        msg  = e.response["Error"].get("Message", str(e))
        raise RuntimeError(f"R2 auth/bucket check failed [{code}]: {msg}") from e

# ── Per-item download ──────────────────────────────────────────────────────────

def download_item(item: Item, items_dir: Path, upload: bool = False) -> Item:
    """Download lineart, mid-preview and game-zip for one item. Returns updated Item."""
    item_dir     = items_dir / item.id
    preview_dest = item_dir / f"{item.id}.png"
    result_dest  = item_dir / f"{item.id}_mid.png"
    zip_dest     = item_dir / f"{item.id}_b.zip"

    download_to(url_lineart(item.id),     preview_dest)
    download_to(url_mid_preview(item.id), result_dest)
    ok_zip = download_to(url_game_zip(item.id), zip_dest)

    # Refine type from actual zip content (overrides catalog heuristic)
    if ok_zip and zip_dest.exists():
        item.type = refine_type_from_zip(zip_dest, item.id)

    base    = items_dir.parent
    r2_base = f"items/{item.id}"

    if upload:
        item.preview_image = r2_upload(preview_dest, f"{r2_base}/{item.id}.png")    if preview_dest.exists() else ""
        item.result_image  = r2_upload(result_dest,  f"{r2_base}/{item.id}_mid.png") if result_dest.exists()  else ""
        item.data_zip      = r2_upload(zip_dest,     f"{r2_base}/{item.id}_b.zip")  if zip_dest.exists()     else ""
    else:
        item.preview_image = str(preview_dest.relative_to(base)) if preview_dest.exists() else ""
        item.result_image  = str(result_dest.relative_to(base))  if result_dest.exists()  else ""
        item.data_zip      = str(zip_dest.relative_to(base))     if zip_dest.exists()     else ""

    return item

# ── Progress counter (thread-safe) ────────────────────────────────────────────

class Counter:
    def __init__(self, total: int) -> None:
        self._n = 0
        self._total = total
        self._lock = threading.Lock()

    def inc(self, key: str) -> None:
        with self._lock:
            self._n += 1
            if self._n % 25 == 0 or self._n == self._total:
                print(f"  [{self._n}/{self._total}] …{key[:40]}")

# ── Main ───────────────────────────────────────────────────────────────────────

def main() -> None:
    ap = argparse.ArgumentParser(
        description="Scrape Iceors CDN catalog → CMS-ready JSON + assets"
    )
    ap.add_argument("-o", "--output",      default="cdn_output", metavar="DIR")
    ap.add_argument("--workers",           type=int, default=6,  metavar="N")
    ap.add_argument("--json-only",         action="store_true",
                    help="Fetch catalog and emit catalog.json only; skip all downloads")
    ap.add_argument("--upload",            action="store_true",
                    help="Upload assets to Cloudflare R2; catalog.json will contain public URLs")
    ap.add_argument("--collections",       nargs="*", metavar="NAME",
                    help="Filter to specific collection names (case-insensitive)")
    ap.add_argument("--limit",             type=int, metavar="N",
                    help="Max items per collection (for testing)")
    args = ap.parse_args()

    out_dir   = Path(args.output)
    items_dir = out_dir / "items"
    out_dir.mkdir(parents=True, exist_ok=True)

    # ── 1. Fetch catalog ──────────────────────────────────────────────────────
    print("Fetching catalog from API…")
    raw_bytes = http_post(CATALOG_URL, CATALOG_BODY)
    if raw_bytes is None:
        sys.exit("[FATAL] Could not reach catalog API")

    raw = json.loads(raw_bytes.decode("utf-8"))
    (out_dir / "catalog_raw.json").write_text(
        json.dumps(raw, indent=2, ensure_ascii=False)
    )
    print(f"  Raw catalog saved → {out_dir}/catalog_raw.json")

    categories = parse_catalog(raw, limit=args.limit)
    print(f"  → {len(categories)} categories parsed")

    # ── 2. Optional collection filter ─────────────────────────────────────────
    if args.collections:
        wanted = {c.lower() for c in args.collections}
        categories = [
            c for c in categories
            if c.id.lower() in wanted or c.name.lower() in wanted
        ]
        print(f"  → filtered to {len(categories)} categories")

    total_items = sum(len(c.items) for c in categories)
    print(f"  → {total_items} items in scope")

    # Save immediately after parsing — paths are empty but structure is complete.
    # Will be overwritten again after downloads/uploads with real paths/URLs.
    manifest_path = out_dir / "catalog.json"
    manifest_path.write_text(json.dumps([asdict(c) for c in categories], indent=2, ensure_ascii=False))
    print(f"  catalog.json saved (empty paths) → {manifest_path}")

    if getattr(args, "upload", False) and not args.json_only:
        print("Testing R2 connection…")
        try:
            r2_test_connection()
            print("  R2 OK")
        except RuntimeError as e:
            sys.exit(f"[FATAL] {e}")

    write_lock = threading.Lock()

    def save_manifest():
        with write_lock:
            manifest_path.write_text(
                json.dumps([asdict(c) for c in categories], indent=2, ensure_ascii=False)
            )

    if args.json_only:
        print("[json-only] Skipping all downloads.")
    else:
        # ── 3. Download + upload item assets (parallel) ───────────────────────
        print(f"Downloading {total_items} items with {args.workers} workers…")
        counter = Counter(total_items)

        flat: list[tuple[int, int, Item]] = [
            (ci, ii, item)
            for ci, cat in enumerate(categories)
            for ii, item in enumerate(cat.items)
        ]

        def _worker(args_tuple):
            ci, ii, item = args_tuple
            updated = download_item(item, items_dir, upload=args.upload)
            counter.inc(item.id)
            return ci, ii, updated

        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            futures = {pool.submit(_worker, t): t for t in flat}
            for fut in as_completed(futures):
                ci, ii, updated = fut.result()
                categories[ci].items[ii] = updated
                save_manifest()

    # ── 5. Final save ─────────────────────────────────────────────────────────
    save_manifest()

    print(f"\nDone.")
    print(f"  CMS manifest → {manifest_path}")
    if not args.json_only:
        print(f"  Assets       → {out_dir}/items/")
    if args.upload:
        print(f"  R2 public    → {R2_PUBLIC_BASE}/items/{{key}}/...")


if __name__ == "__main__":
    main()
