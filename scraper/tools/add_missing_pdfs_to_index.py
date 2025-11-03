#!/usr/bin/env python3
import json
import os
import sys
from typing import List, Dict


def sanitize_filename(name: str) -> str:
    import re
    name = (name or "").strip().replace("/", "-")
    name = re.sub(r"\s+", " ", name)
    name = re.sub(r"[^0-9A-Za-zÀ-ÖØ-öø-ÿ _\-\.()]", "", name)
    return name[:150] if len(name) > 150 else name


def load_json(path: str):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_json(path: str, data) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def list_local_pdfs(root: str) -> List[str]:
    res: List[str] = []
    for r, _, files in os.walk(root):
        for fn in files:
            if fn.lower().endswith('.pdf'):
                res.append(os.path.join(r, fn))
    return res


def main() -> int:
    import argparse
    ap = argparse.ArgumentParser(description="Add missing local PDFs to index for selected municipalities")
    ap.add_argument("--only", nargs='*', help="Municipality names to process (default: slice 5..10)")
    args = ap.parse_args()
    base = os.getcwd()
    idx_path = os.path.join(base, "pdf_scraper_input", "municipality_pdfs_index.json")
    muni_path = os.path.join(base, "pdf_scraper_input", "municipalities.json")
    pdfs_dir = os.path.join(base, "pdfs")

    if not os.path.exists(idx_path):
        print(f"Index not found: {idx_path}")
        return 1
    if not os.path.exists(muni_path):
        print(f"Municipalities not found: {muni_path}")
        return 1
    if not os.path.isdir(pdfs_dir):
        print(f"PDFs dir not found: {pdfs_dir}")
        return 1

    idx = load_json(idx_path)
    muni = load_json(muni_path)
    items = muni.get("items", [])
    if args.only:
        only_set = set(args.only)
        target_names = [it.get("name") for it in items if it.get("name") in only_set]
    else:
        # 1-based positions 5..10 -> 0-based slice [4:10]
        target_names = [it.get("name") for it in items[4:10] if it.get("name")]
    if not target_names:
        print("No target municipalities (5..10) found in municipalities.json")
        return 1

    # Build map name -> result entry in index
    results = idx.get("results", []) if isinstance(idx, dict) else []
    name_to_entry: Dict[str, dict] = {e.get("name"): e for e in results if isinstance(e, dict) and e.get("name")}

    report_missing_in_files: Dict[str, List[str]] = {}
    added_total = 0

    for name in target_names:
        sani = sanitize_filename(name)
        local_dir = os.path.join(pdfs_dir, sani)
        if not os.path.isdir(local_dir):
            print(f"[skip] No local dir for {name}: {local_dir}")
            continue
        local_files = list_local_pdfs(local_dir)
        local_basenames = {os.path.basename(p) for p in local_files}

        entry = name_to_entry.get(name)
        if not entry:
            # Create new entry shell
            entry = {"name": name, "start_url": None, "pdfs": []}
            results.append(entry)
            name_to_entry[name] = entry
        pdfs_list = entry.get("pdfs") or []

        # Build known set by pdf_name (fallback to url basename)
        known_names = set()
        for p in pdfs_list:
            if not isinstance(p, dict):
                continue
            pn = p.get("pdf_name")
            if pn and isinstance(pn, str):
                known_names.add(pn)
            else:
                try:
                    from urllib.parse import urlparse
                    path = urlparse(p.get("url") or "").path
                    bn = os.path.basename(path)
                    if bn:
                        known_names.add(bn)
                except Exception:
                    pass

        # Add missing local files as local entries
        added = 0
        for bn in sorted(local_basenames):
            if bn not in known_names:
                abs_path = os.path.join(local_dir, bn)
                rel_url = "file://" + os.path.abspath(abs_path)
                base_no_ext = os.path.splitext(bn)[0]
                pdfs_list.append({
                    "url": rel_url,
                    "pdf_name": bn,
                    "text": base_no_ext,
                    "from": "local",
                    "score": 0,
                })
                added += 1
        if added:
            entry["pdfs"] = pdfs_list
            added_total += added
            print(f"[update] {name}: added {added} local pdfs to index")

        # Compute index entries missing on disk (report only)
        missing = []
        for p in pdfs_list:
            if not isinstance(p, dict):
                continue
            pn = p.get("pdf_name")
            if pn and pn not in local_basenames:
                missing.append(pn)
        if missing:
            report_missing_in_files[name] = missing

    # Save back
    idx["results"] = results
    idx["count"] = len(results)
    save_json(idx_path, idx)
    print(f"Index updated -> {idx_path} (added total {added_total} entries)")

    # Report
    if report_missing_in_files:
        print("Missing on disk compared to index (report only):")
        for name, lst in report_missing_in_files.items():
            print(f"- {name}: {len(lst)} items (e.g., {', '.join(lst[:5])}{'...' if len(lst)>5 else ''})")
    else:
        print("No index entries missing on disk for target municipalities.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
