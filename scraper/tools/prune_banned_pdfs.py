#!/usr/bin/env python3
import argparse
import os
import re
from typing import List


def sanitize_filename(name: str) -> str:
    name = (name or "").strip().replace("/", "-")
    name = re.sub(r"\s+", " ", name)
    name = re.sub(r"[^0-9A-Za-zÀ-ÖØ-öø-ÿ _\-\.()]", "", name)
    return name[:150] if len(name) > 150 else name


def is_allowed_2025(name: str) -> bool:
    import sys
    sys.path.insert(0, os.getcwd())
    from pdf_scraper import _is_current_year_pdf  # reuse scraper logic
    return _is_current_year_pdf(name)


def list_pdfs(path: str) -> List[str]:
    out: List[str] = []
    for root, _, files in os.walk(path):
        for fn in files:
            if fn.lower().endswith('.pdf'):
                out.append(os.path.join(root, fn))
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="Remove banned PDFs (non-2025 / other elections) in given municipalities")
    ap.add_argument("--only", nargs='*', default=["Beesel"], help="Municipalities to prune (default: Beesel)")
    ap.add_argument("--root", default="pdfs", help="Root PDFs directory")
    args = ap.parse_args()

    total_removed = 0
    for muni in args.only:
        d = os.path.join(args.root, sanitize_filename(muni))
        if not os.path.isdir(d):
            print(f"[skip] no dir: {d}")
            continue
        removed = 0
        for fp in list_pdfs(d):
            bn = os.path.basename(fp)
            if not is_allowed_2025(bn):
                try:
                    os.remove(fp)
                    removed += 1
                except Exception:
                    pass
        print(f"[prune] {muni}: removed {removed}")
        total_removed += removed
    print(f"Total removed: {total_removed}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
