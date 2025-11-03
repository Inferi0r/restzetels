#!/usr/bin/env python3
import json
import os
import sys
from urllib.parse import urlparse


def sanitize_entry(p: dict) -> dict:
    out = dict(p or {})
    # Prefer remote_url as canonical 'url' for legacy compatibility
    url = out.get("remote_url") or out.get("url") or "unknown"
    out["url"] = url

    # pdf_name
    pdf_name = out.get("pdf_name")
    if not isinstance(pdf_name, str) or not pdf_name.strip():
        try:
            base = os.path.basename(urlparse(url).path)
            pdf_name = base if base else "unknown"
        except Exception:
            pdf_name = "unknown"
        out["pdf_name"] = pdf_name

    # text (no preview_text anymore)
    if not isinstance(out.get("text"), str) or not out.get("text").strip():
        out["text"] = pdf_name or "unknown"

    # drop preview_text if present
    if "preview_text" in out:
        out.pop("preview_text", None)

    # from
    if not isinstance(out.get("from"), str) or not out.get("from").strip():
        if isinstance(url, str) and "mediafiler.net" in url and "#fuid=" in url:
            out["from"] = url.split("#", 1)[0]
        else:
            out["from"] = "unknown"

    # score
    if not isinstance(out.get("score"), (int, float)):
        out["score"] = 0

    return out


def main() -> int:
    # Default path
    idx_path = os.path.join("pdf_scraper_input", "municipality_pdfs_index.json")
    if len(sys.argv) > 1:
        idx_path = sys.argv[1]
    if not os.path.exists(idx_path):
        print(f"Index not found: {idx_path}")
        return 1
    with open(idx_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    # Expected structure: { results: [ { name, start_url, pdfs: [...] } ], count }
    if isinstance(data, dict) and isinstance(data.get("results"), list):
        changed = False
        for res in data["results"]:
            pdfs = res.get("pdfs")
            if isinstance(pdfs, list):
                new_list = []
                for p in pdfs:
                    np = sanitize_entry(p if isinstance(p, dict) else {})
                    # Only mark changed if fields were added/normalized
                    if np != p:
                        changed = True
                    new_list.append(np)
                res["pdfs"] = new_list
        if changed:
            with open(idx_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            print(f"Normalized index written -> {idx_path}")
        else:
            print("Index already normalized; no changes.")
        return 0
    else:
        print("Unexpected index format.")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
