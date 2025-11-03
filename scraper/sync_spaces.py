#!/usr/bin/env python3
"""
Sync the local `pdfs/` folder to a DigitalOcean Spaces bucket (S3-compatible).

Defaults (based on your message):
- Credentials are read from a local `.env` (preferred) or the configured AWS profile.
- profile: do-tor1 (fallback when no .env credentials are present)
- region: ams3
- endpoint: https://ams3.digitaloceanspaces.com
- bucket: verkiezingsdata
- remote prefix: pdfs/ (keeps keys like pdfs/<Gemeente>/<file>.pdf)

Examples
- Mirror (default): python3 sync_spaces.py
- Mirror explicit: python3 sync_spaces.py --sync
- Copy only (no delete): python3 sync_spaces.py --copy

Notes
- Put keys in `.env` (do not commit):
    DO_ACCESS_KEY_ID=...
    DO_SECRET_ACCESS_KEY=...
- Uploads are ACL public-read by default.
- Fast mode: skips hashing; treats same key (path) as unchanged.
- Requires `boto3`: pip install boto3
"""
from __future__ import annotations

import argparse
import base64
import concurrent.futures as cf
import mimetypes
import os
import sys
from dataclasses import dataclass
from typing import Dict, Iterable, Tuple

import boto3
from botocore.client import Config
from boto3.s3.transfer import TransferConfig


# Default local directory is scraper/pdfs (next to this script)
DEFAULT_LOCAL_DIR = os.path.join(os.path.dirname(__file__), "pdfs")
DEFAULT_BUCKET = "verkiezingsdata"
DEFAULT_PREFIX = "pdfs/"
DEFAULT_PROFILE = "do-tor1"
DEFAULT_REGION = "ams3"
DEFAULT_ENDPOINT = "https://ams3.digitaloceanspaces.com"


def load_dotenv(path: str = ".env") -> bool:
    """Tiny .env loader to avoid extra dependencies.
    Loads KEY=VALUE pairs into os.environ if not already set.
    Returns True if a file was found and parsed.
    """
    try:
        if not os.path.isfile(path):
            return False
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if "=" not in line:
                    continue
                k, v = line.split("=", 1)
                k = k.strip()
                v = v.strip().strip('"').strip("'")
                if k and v and k not in os.environ:
                    os.environ[k] = v
        return True
    except Exception:
        # Don't crash sync if .env has issues; simply proceed without it.
        return False


# No MD5 hashing: we assume identical keys (paths) are unchanged for speed.


def iter_local_pdfs(root: str) -> Iterable[Tuple[str, str]]:
    """Yield (abs_path, relative_key_under_root) for files ending in .pdf (case-insensitive)."""
    root = os.path.abspath(root)
    for dirpath, _, filenames in os.walk(root):
        for fn in filenames:
            if not fn.lower().endswith(".pdf"):
                continue
            p = os.path.join(dirpath, fn)
            rel = os.path.relpath(p, root).replace(os.sep, "/")
            yield p, rel


@dataclass
class RemoteObj:
    key: str
    etag: str | None
    size: int | None


def list_remote_objects(s3, bucket: str, prefix: str) -> Dict[str, RemoteObj]:
    out: Dict[str, RemoteObj] = {}
    paginator = s3.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
        for it in page.get("Contents", []) or []:
            key = it.get("Key")
            etag = (it.get("ETag") or "").strip('"') if it.get("ETag") else None
            size = it.get("Size")
            if key:
                out[key] = RemoteObj(key=key, etag=etag, size=size)
    return out


def ensure_mime(path: str) -> str:
    mt, _ = mimetypes.guess_type(path)
    return mt or "application/pdf"


def upload_one(s3, bucket: str, local_path: str, key: str, public: bool = False) -> None:
    extra = {"ContentType": ensure_mime(local_path)}
    if public:
        extra["ACL"] = "public-read"
    # Force single-part uploads so ETag == MD5, keeping our skip-logic correct
    tcfg = TransferConfig(multipart_threshold=5 * 1024 ** 3, multipart_chunksize=5 * 1024 ** 3)
    s3.upload_file(local_path, bucket, key, ExtraArgs=extra, Config=tcfg)


def delete_one(s3, bucket: str, key: str) -> None:
    s3.delete_object(Bucket=bucket, Key=key)


def build_s3_client(profile: str, region: str, endpoint: str):
    # Prefer explicit credentials from environment/.env
    access_key = os.getenv("DO_ACCESS_KEY_ID") or os.getenv("AWS_ACCESS_KEY_ID")
    secret_key = os.getenv("DO_SECRET_ACCESS_KEY") or os.getenv("AWS_SECRET_ACCESS_KEY")

    if access_key and secret_key:
        session = boto3.Session()
        return session.client(
            "s3",
            region_name=region,
            endpoint_url=endpoint,
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            config=Config(s3={"addressing_style": "virtual"}),
        )

    # Fallback: use profile-based auth (e.g., do-tor1 configured via AWS CLI)
    session = boto3.Session(profile_name=profile) if profile else boto3.Session()
    return session.client(
        "s3",
        region_name=region,
        endpoint_url=endpoint,
        config=Config(s3={"addressing_style": "virtual"}),
    )


def sync(
    local_dir: str,
    bucket: str,
    prefix: str,
    profile: str,
    region: str,
    endpoint: str,
    delete: bool,
    workers: int = 8,
) -> None:
    if not os.path.isdir(local_dir):
        raise SystemExit(f"Local directory not found: {local_dir}")
    s3 = build_s3_client(profile, region, endpoint)

    # Gather locals
    locals_list = list(iter_local_pdfs(local_dir))
    print(f"[sync] Local PDFs: {len(locals_list)}")
    # Build remote map
    remote_map = list_remote_objects(s3, bucket, prefix)
    print(f"[sync] Remote keys under '{prefix}': {len(remote_map)}")

    # Decide uploads
    plan_uploads: list[Tuple[str, str]] = []  # (local_path, key)
    local_keys_set = set()
    for abs_path, rel_key in locals_list:
        key = prefix.rstrip("/") + "/" + rel_key if prefix else rel_key
        local_keys_set.add(key)
        # Fast-path: if key exists remotely, assume unchanged (skip hashing/etag)
        if key in remote_map:
            continue
        plan_uploads.append((abs_path, key))

    # Decide deletions
    plan_deletes: list[str] = []
    if delete:
        for key in remote_map.keys():
            if key not in local_keys_set:
                plan_deletes.append(key)

    # Execute
    print(f"[sync] To upload: {len(plan_uploads)}; To delete: {len(plan_deletes)}")

    # Parallel uploads
    with cf.ThreadPoolExecutor(max_workers=workers) as ex:
        futs = [ex.submit(upload_one, s3, bucket, lp, key, True) for lp, key in plan_uploads]
        for i, fut in enumerate(cf.as_completed(futs), 1):
            try:
                fut.result()
            except Exception as e:
                print(f"[sync] Upload error: {e}")
            if i % 25 == 0:
                print(f"[sync] Uploaded {i}/{len(plan_uploads)}")

    # Parallel deletes
    if plan_deletes:
        with cf.ThreadPoolExecutor(max_workers=min(8, len(plan_deletes))) as ex:
            futs = [ex.submit(delete_one, s3, bucket, key) for key in plan_deletes]
            for fut in cf.as_completed(futs):
                try:
                    fut.result()
                except Exception as e:
                    print(f"[sync] Delete error: {e}")

    # Summary
    origin = f"https://{bucket}.ams3.digitaloceanspaces.com" if endpoint.endswith("digitaloceanspaces.com") else f"{endpoint}/{bucket}"
    print(f"[sync] Done. Origin: {origin}; CDN: https://{bucket}.ams3.cdn.digitaloceanspaces.com")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Sync local pdfs/ to DigitalOcean Spaces (S3-compatible)")
    # Action mode: only two commands
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--sync", action="store_true", help="Mirror: delete remote objects not present locally (default)")
    mode.add_argument("--copy", action="store_true", help="Copy-only: do not delete remote objects")
    args = ap.parse_args(argv)

    # Determine delete behavior: default to sync (mirror) when no flag given
    delete_mode = True if args.sync or not args.copy else False

    # Load credentials from local .env if present
    load_dotenv()

    try:
        sync(
            local_dir=DEFAULT_LOCAL_DIR,
            bucket=DEFAULT_BUCKET,
            prefix=DEFAULT_PREFIX,
            profile=DEFAULT_PROFILE,
            region=DEFAULT_REGION,
            endpoint=DEFAULT_ENDPOINT,
            delete=delete_mode,
            workers=8,
        )
        return 0
    except KeyboardInterrupt:
        print("[sync] Interrupted")
        return 130
    except Exception as e:
        print(f"[sync] ERROR: {e}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
