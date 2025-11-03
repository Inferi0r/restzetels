#!/usr/bin/env python3
import json
import os
from urllib.parse import urlparse


def sanitize_filename(name: str) -> str:
    import re
    name = (name or "").strip().replace("/", "-")
    name = re.sub(r"\s+", " ", name)
    name = re.sub(r"[^0-9A-Za-zÀ-ÖØ-öø-ÿ _\-\.()]", "", name)
    return name[:150] if len(name) > 150 else name


def load_json(path: str):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def list_local_pdfs_map(root: str):
    """Return dict: municipality_name -> set(pdf basenames) based on subdir names in root."""
    res = {}
    if not os.path.isdir(root):
        return res
    for entry in os.scandir(root):
        if not entry.is_dir():
            continue
        muni = entry.name
        pdfs = set()
        for r, _, files in os.walk(entry.path):
            for fn in files:
                if fn.lower().endswith('.pdf'):
                    pdfs.add(fn)
        res[muni] = pdfs
    return res


def pdfname_from_index_item(item: dict) -> str:
    pn = item.get("pdf_name")
    if isinstance(pn, str) and pn.strip():
        return pn
    try:
        path = urlparse(item.get("url") or "").path
        bn = os.path.basename(path)
        return bn or "unknown"
    except Exception:
        return "unknown"


def main() -> int:
    base = os.getcwd()
    idx_path = os.path.join(base, "pdf_scraper_input", "municipality_pdfs_index.json")
    pdfs_dir = os.path.join(base, "pdfs")
    if not os.path.exists(idx_path):
        print(f"Index not found: {idx_path}")
        return 1
    idx = load_json(idx_path)
    results = idx.get("results", []) if isinstance(idx, dict) else []

    # Map: display_muni_name -> index set of pdf_names
    index_map = {}
    for res in results:
        name = res.get("name") or "unknown"
        pdfs = res.get("pdfs") or []
        s = set()
        for it in pdfs:
            if not isinstance(it, dict):
                continue
            s.add(pdfname_from_index_item(it))
        index_map[name] = s

    # Map from disk
    disk_map = list_local_pdfs_map(pdfs_dir)

    # Build union of municipalities based on both
    all_munis = set(index_map.keys()) | set(disk_map.keys())

    missing_in_index = {}  # muni -> count
    missing_on_disk = {}   # muni -> count

    for name in sorted(all_munis):
        sani = sanitize_filename(name)
        disk_set = disk_map.get(sani, set()) if name not in disk_map else disk_map.get(name, set())
        # Some directories may be sanitized; try both exact and sanitized
        if not disk_set:
            disk_set = disk_map.get(sani, set())
        idx_set = index_map.get(name, set())

        # On disk but not in index
        diff_disk = disk_set - idx_set
        if diff_disk:
            missing_in_index[name] = len(diff_disk)

        # In index but not on disk
        diff_index = idx_set - disk_set
        if diff_index:
            missing_on_disk[name] = len(diff_index)

    print("Report — PDFs on disk but missing from index:")
    for k in sorted((k for k,v in missing_in_index.items() if v)):
        print(f"- {k}: {missing_in_index[k]}")
    if not any(missing_in_index.values() if missing_in_index else []):
        print("(none)")

    print("\nReport — PDFs in index but missing on disk (no changes made):")
    for k in sorted((k for k,v in missing_on_disk.items() if v)):
        print(f"- {k}: {missing_on_disk[k]}")
    if not any(missing_on_disk.values() if missing_on_disk else []):
        print("(none)")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

