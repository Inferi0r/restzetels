#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import sys

from .discovery import discover_pdfs, rank_overview_candidates_from_html
from .platforms import detect as detect_platform, REGISTRY as PLATFORM_HANDLERS
from .downloader import download_index_items
from .http_client import Requester
from .index import light_merge_index
from .model10 import log_model10_progress
from .tracer import Tracer
from .utils import get_all_names, get_municipalities_slice, get_start_url
from .utils import is_electionish, normalize_source_url, same_registrable_domain
from .fallback_playwright import playwright_collect_pdfs, playwright_discover_and_collect
from .verified_urls import add_source_url as verified_add_source
from .verified_urls import record_kiesraad_url as verified_record_kiesraad
from .fetch_gemeente_urls import kiesraad_url_for
from .config import EXTRA_SEEDS as MANUAL_SEEDS


def run_for_municipality(name: str, dry_run: bool = False) -> None:
    start_url = get_start_url(name)
    if not start_url:
        print(f"[SKIP] No start URL for {name}")
        return
    tracer = Tracer(name)
    req = Requester(tracer=tracer)
    print(f"[START] {name} -> {start_url}")
    # Ensure kiesraad_url is recorded for this municipality (cached fetch)
    try:
        kr = kiesraad_url_for(name)
        if kr:
            verified_record_kiesraad(name, kr)
    except Exception:
        pass
    items = []
    # If start is a mijnstembureau portal, try the platform handler first for better coverage
    try:
        sysname = detect_platform(start_url)
        if sysname == 'mijnstembureau':
            handler = PLATFORM_HANDLERS.get(sysname)
            if handler:
                its = handler(start_url, req, tracer, name) or []
                for it in its:
                    u = it.get('remote_url') or ''
                    if not u:
                        continue
                    tracer.record_found_pdf(u, it.get('from') or start_url, it.get('pdf_name') or '', int(it.get('score') or 0))
                items.extend(its)
    except Exception:
        pass
    # Then continue with general discovery (de-dup downstream)
    more = discover_pdfs(req, tracer, name, start_url)
    if more:
        items.extend(more)
    print(f"[FOUND] {name}: {len(items)} PDF candidates")
    # Classify known systems to help learning later
    try:
        systems = set()
        for it in items:
            u = (it.get('remote_url') or '').lower()
            if 'stembureau-' in u or 'mijnstembureau' in u:
                systems.add('mijnstembureau')
            if 'pleio.nl' in u:
                systems.add('pleio')
            if 'drive.google.com' in u:
                systems.add('google-drive')
            if 'stackstorage.com' in u:
                systems.add('stackstorage')
            if 'mediafiler' in u:
                systems.add('mediafiler')
        if systems:
            print(f"[SYSTEMS] {name}: {', '.join(sorted(systems))}")
            try:
                tracer.record_meta(systems=sorted(systems))
            except Exception:
                pass
    except Exception:
        pass
    log_model10_progress(name, items)
    if not items and not getattr(sys.modules.get(__name__), 'ARGS_NO_FALLBACK', False):
        print(f"[FALLBACK] Trying Playwright on start page…")
        cap = playwright_discover_and_collect(tracer, name, start_url, max_pages=3, max_items=250)
        if not cap:
            cap = playwright_collect_pdfs(tracer, name, start_url, max_items=200)
        if cap:
            items.extend(cap)
            print(f"[FOUND][fallback] {len(cap)} more via Playwright")
            try:
                for it in cap:
                    u = it.get('remote_url') or ''
                    if not u:
                        continue
                    tracer.record_found_pdf(u, it.get('from') or start_url, it.get('pdf_name') or '', int(it.get('score') or 0))
            except Exception:
                pass
    # Determine best source pages by majority of items' 'from' field; normalize & filter; save top 3
    try:
        src_count = {}
        for it in items:
            src = (it.get('from') or '').strip()
            if not src:
                continue
            norm = normalize_source_url(src)
            if not is_electionish(norm):
                continue
            # Only keep sources from the same registrable domain as the start URL
            if not same_registrable_domain(start_url, norm):
                continue
            src_count[norm] = src_count.get(norm, 0) + 1
        if src_count:
            for src, _ in sorted(src_count.items(), key=lambda kv: (-kv[1], kv[0]))[:3]:
                verified_add_source(name, src)
            # Also persist any manual seed pages for this municipality (even if not visited due to early pivot)
            for s in (MANUAL_SEEDS.get(name) or []):
                cand = normalize_source_url(s)
                if is_electionish(cand):
                    verified_add_source(name, cand)
        elif not items:
            # As a fallback, rank start page links and save the top candidate
            try:
                r = req.get(start_url, purpose="rank")
                ranked = rank_overview_candidates_from_html(r.text, r.url)
                if ranked:
                    # Prefer the first ranked candidate on the same registrable domain
                    cand_raw = next((u for u in ranked if same_registrable_domain(start_url, u)), ranked[0])
                    cand = normalize_source_url(cand_raw)
                    if is_electionish(cand) and same_registrable_domain(start_url, cand):
                        verified_add_source(name, cand)
            except Exception:
                pass
    except Exception:
        pass
    if dry_run:
        try:
            tracer.record_stop("dry-run", {"found": len(items), "downloaded": 0, "requests": req.request_count})
            print(f"[TRACE] {tracer.path}")
        except Exception:
            pass
        return
    downloaded = download_index_items(req, name, items)
    print(f"[DOWNLOADED] {name}: {len(downloaded)}/{len(items)} PDFs")
    light_merge_index(name, downloaded)
    print(f"[REQUESTS] {name}: {req.request_count}")
    tracer.record_stop("done", {"found": len(items), "downloaded": len(downloaded), "requests": req.request_count})


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="Modular PV PDF scraper")
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--only", nargs="*", help="Only process these municipality names")
    g.add_argument("--slice", help="Slice indexes e.g. 101-120")
    g.add_argument("--first", type=int, help="Process first N municipalities")
    ap.add_argument("--dry-run", action="store_true", help="Discover but do not download")
    ap.add_argument("--no-fallback", action="store_true", help="Do not use Playwright fallback; save best source and stop")
    return ap.parse_args()


def main():
    args = parse_args()
    # propagate no-fallback flag into module for run function
    global ARGS_NO_FALLBACK
    ARGS_NO_FALLBACK = bool(getattr(args, 'no_fallback', False))
    if args.only:
        names = args.only
    elif args.slice:
        try:
            a, b = args.slice.split("-", 1)
            names = get_municipalities_slice(int(a), int(b))
        except Exception:
            names = []
    elif args.first:
        names = get_all_names()[: args.first]
    else:
        names = get_all_names()
    for name in names:
        try:
            run_for_municipality(name, dry_run=args.dry_run)
        except KeyboardInterrupt:
            raise
        except Exception as e:
            print(f"[ERROR] {name}: {e}")


if __name__ == "__main__":
    main()
