#!/usr/bin/env python3
import argparse
import hashlib
import json
import os
import re
from typing import Dict, List, Tuple


def sanitize_filename(name: str) -> str:
    import re
    name = (name or "").strip().replace("/", "-")
    name = re.sub(r"\s+", " ", name)
    name = re.sub(r"[^0-9A-Za-zÀ-ÖØ-öø-ÿ _\-\.()]", "", name)
    return name[:150] if len(name) > 150 else name


def load_municipalities(path: str) -> List[str]:
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return [it.get("name") for it in data.get("items", []) if it.get("name")]


def list_pdfs(dirpath: str) -> List[str]:
    files: List[str] = []
    for root, _, fs in os.walk(dirpath):
        for fn in fs:
            if fn.lower().endswith(".pdf"):
                files.append(os.path.join(root, fn))
    return files


SUFFIX_RE = re.compile(r"^(?P<base>.*?)(?:_(?P<num>\d+))?(?P<ext>\.pdf)$", re.IGNORECASE)


def rank_filename(path: str) -> Tuple[int, int, int, str]:
    """Return a rank tuple for a filename: lower is better.
    Criteria:
      1) prefer without numeric suffix _N
      2) if with suffix, prefer smaller N
      3) prefer shorter filename length
      4) tiebreak lexicographically
    """
    bn = os.path.basename(path)
    m = SUFFIX_RE.match(bn)
    has_suffix = 1
    num = 0
    if m and m.group("num"):
        has_suffix = 1
        num = int(m.group("num"))
    else:
        has_suffix = 0
    return (has_suffix, num, len(bn), bn.lower())


def sha256_of(path: str, chunk_size: int = 1024 * 1024) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            b = f.read(chunk_size)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def dedupe_dir(dirpath: str) -> Tuple[int, List[str]]:
    """Deduplicate identical PDFs in dirpath by content hash.
    Keep the best-ranked filename, remove others. Returns (#removed, removed_paths).
    """
    files = list_pdfs(dirpath)
    if not files:
        return 0, []
    by_hash: Dict[str, List[str]] = {}
    removed: List[str] = []
    for fp in files:
        try:
            h = sha256_of(fp)
        except Exception:
            # if unreadable, skip it from dedupe
            continue
        by_hash.setdefault(h, []).append(fp)
    total_removed = 0
    for h, fpaths in by_hash.items():
        if len(fpaths) <= 1:
            continue
        # choose best to keep
        best = sorted(fpaths, key=rank_filename)[0]
        for fp in fpaths:
            if fp == best:
                continue
            try:
                os.remove(fp)
                removed.append(fp)
                total_removed += 1
            except Exception:
                pass
    return total_removed, removed


def main() -> int:
    ap = argparse.ArgumentParser(description="Remove duplicate PDFs (same content) and keep best-named file.")
    ap.add_argument("--slice", type=str, default=None, help="1-based inclusive slice e.g. 11-20")
    ap.add_argument("--only", nargs='*', help="Specific municipality names")
    ap.add_argument("--root", type=str, default="pdfs", help="Root PDFs directory")
    ap.add_argument("--muni-index", type=str, default="pdf_scraper_input/municipalities.json", help="Municipalities JSON")
    args = ap.parse_args()

    munis = load_municipalities(args.muni_index)
    targets: List[str]
    if args.only:
        only = set(args.only)
        targets = [m for m in munis if m in only]
    elif args.slice:
        try:
            a, b = args.slice.split("-", 1)
            s = max(1, int(a.strip())) - 1
            e = int(b.strip())
            targets = [m for m in munis[s:e] if m]
        except Exception:
            print("Invalid --slice; exiting")
            return 1
    else:
        print("Provide --slice or --only")
        return 1

    report = []
    total = 0
    for name in targets:
        d = os.path.join(args.root, sanitize_filename(name))
        if not os.path.isdir(d):
            continue
        cnt, removed = dedupe_dir(d)
        total += cnt
        report.append((name, cnt))

    print("Deduplication report:")
    for name, cnt in report:
        print(f"- {name}: removed {cnt}")
    print(f"Total removed: {total}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

