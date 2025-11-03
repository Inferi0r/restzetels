#!/usr/bin/env python3
import argparse
import json
import os
import re
from urllib.parse import urlparse
from typing import Dict, List


def sanitize_filename(name: str) -> str:
    name = (name or "").strip().replace("/", "-")
    name = re.sub(r"\s+", " ", name)
    name = re.sub(r"[^0-9A-Za-zÀ-ÖØ-öø-ÿ _\-\.()]", "", name)
    return name[:150] if len(name) > 150 else name


SUFFIX_RE = re.compile(r"^(?P<base>.*?)(?:_(?P<num>\d+))?(?P<ext>\.pdf)$", re.IGNORECASE)


def list_disk_pdfs(dirpath: str) -> Dict[str, str]:
    """Return mapping basename -> file:// absolute path for PDFs under dirpath."""
    out: Dict[str, str] = {}
    if not os.path.isdir(dirpath):
        return out
    for root, _, files in os.walk(dirpath):
        for fn in files:
            if not fn.lower().endswith('.pdf'):
                continue
            p = os.path.join(root, fn)
            out[fn] = "file://" + os.path.abspath(p)
    return out


def normalize_entry(item: dict) -> dict:
    q = dict(item or {})
    # legacy url
    legacy_url = q.get("url")
    if legacy_url:
        if legacy_url.lower().startswith(("http://", "https://")):
            q["remote_url"] = legacy_url
        elif legacy_url.lower().startswith("file://"):
            q["local_url"] = legacy_url
        q.pop("url", None)
    # pdf_name fallback
    if not q.get("pdf_name"):
        base_url = q.get("remote_url") or q.get("local_url") or ""
        try:
            q["pdf_name"] = os.path.basename(urlparse(base_url).path) or "unknown.pdf"
        except Exception:
            q["pdf_name"] = "unknown.pdf"
    # drop preview_text if present
    q.pop("preview_text", None)
    return q


def reconcile_muni(entry: dict, pdfs_root: str) -> bool:
    """Update a municipality entry in-place:
      - fix local_url to match on-disk file
      - if pdf_name had a _N suffix removed on disk, update to kept base
      - drop entries that have neither a remote_url nor a local file on disk
      Returns True if any change was made.
    """
    changed = False
    name = entry.get("name") or ""
    if not name:
        return False
    muni_dir = os.path.join(pdfs_root, sanitize_filename(name))
    disk_map = list_disk_pdfs(muni_dir)
    # Also map base without _N to disk file if present
    base_to_disk = {}
    for bn in disk_map.keys():
        m = SUFFIX_RE.match(bn)
        if m:
            base_to_disk.setdefault(m.group("base") + m.group("ext"), set()).add(bn)

    new_list: List[dict] = []
    for p in (entry.get("pdfs") or []):
        q = normalize_entry(p)
        pn = q.get("pdf_name") or ""
        lu = q.get("local_url")
        ru = q.get("remote_url")
        # If local_url exists but file is gone, clear it (will try to rebind)
        if lu and lu.startswith("file://"):
            abs_path = lu.replace("file://", "")
            if not os.path.exists(abs_path):
                q["local_url"] = None
                changed = True
        # Bind local_url by pdf_name
        if not q.get("local_url"):
            if pn in disk_map:
                q["local_url"] = disk_map[pn]
                changed = True
            else:
                # try remove _N suffix to match kept base
                m = SUFFIX_RE.match(pn)
                if m and m.group("num"):
                    base = m.group("base") + m.group("ext")
                    cands = base_to_disk.get(base, set())
                    if base in disk_map:
                        q["local_url"] = disk_map[base]
                        q["pdf_name"] = base
                        changed = True
                    elif cands:
                        choose = sorted(cands)[0]
                        q["local_url"] = disk_map.get(choose)
                        q["pdf_name"] = choose
                        changed = True
                # fallback: try remote basename
                if not q.get("local_url") and ru:
                    try:
                        rbn = os.path.basename(urlparse(ru).path)
                        if rbn in disk_map:
                            q["local_url"] = disk_map[rbn]
                            if not pn:
                                q["pdf_name"] = rbn
                            changed = True
                    except Exception:
                        pass
        # Decide whether to keep an entry
        if q.get("local_url") or q.get("remote_url"):
            new_list.append(q)
        else:
            # entry without any resolvable location is dropped
            changed = True
    if changed:
        entry["pdfs"] = new_list
    return changed


def main() -> int:
    ap = argparse.ArgumentParser(description="Reconcile index with disk after dedupe: fix local_url/pdf_name and drop stale entries")
    ap.add_argument("--slice", type=str, help="1-based inclusive slice, e.g. 11-20")
    ap.add_argument("--only", nargs='*', help="Municipality names to process")
    ap.add_argument("--index", default="pdf_scraper_input/municipality_pdfs_index.json")
    ap.add_argument("--munis", default="pdf_scraper_input/municipalities.json")
    ap.add_argument("--pdfs", default="pdfs")
    args = ap.parse_args()

    with open(args.munis, "r", encoding="utf-8") as f:
        allm = json.load(f).get("items", [])
    ordered = [it.get("name") for it in allm if it.get("name")]
    targets: List[str]
    if args.only:
        only = set(args.only)
        targets = [n for n in ordered if n in only]
    elif args.slice:
        try:
            a, b = args.slice.split("-", 1)
            s = max(1, int(a.strip())) - 1
            e = int(b.strip())
            targets = ordered[s:e]
        except Exception:
            print("Invalid --slice")
            return 1
    else:
        print("Provide --slice or --only")
        return 1

    with open(args.index, "r", encoding="utf-8") as f:
        idx = json.load(f)
    res = idx.get("results", []) if isinstance(idx, dict) else []
    name_to_entry: Dict[str, dict] = {e.get("name"): e for e in res if e.get("name")}

    changed_any = False
    for name in targets:
        e = name_to_entry.get(name)
        if not e:
            continue
        if reconcile_muni(e, args.pdfs):
            changed_any = True

    if changed_any:
        with open(args.index, "w", encoding="utf-8") as f:
            json.dump(idx, f, ensure_ascii=False, indent=2)
        print("Index reconciled and updated")
    else:
        print("Index already in sync for selected municipalities")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

