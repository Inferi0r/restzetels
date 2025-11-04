#!/usr/bin/env python3
"""
Generic Pleio scraper: discovers Pleio hubs for a municipality, enumerates
all '/files/view/<GUID>/' links with Playwright (briefly opens the hub),
then downloads the PDFs directly via HTTP using '/file/download/<GUID>'.

Usage examples:
  - By municipality name:  python3 pdf_scraper_pleio.py --only Zandvoort --outdir ./tmp_pleio_Zandvoort
  - Direct hub URL:        python3 pdf_scraper_pleio.py --hub https://haarlem.pleio.nl/groups/view/.../files/... --outdir ./tmp
  - Headful mode (more stable): add --headful
"""
import os
import sys
import argparse
from urllib.parse import urljoin, urlparse

import pdf_scraper as ps


def discover_hubs_for(name: str) -> list[str]:
    hubs: list[str] = []
    start = ps.get_start_url(name)
    if start:
        # If start URL itself is a Pleio hub, include it directly
        try:
            from urllib.parse import urlparse
            pu = urlparse(start)
            if pu.netloc and 'pleio.nl' in pu.netloc:
                hubs.append(start)
        except Exception:
            pass
        try:
            html, base = ps.fetch_html(start, allow_render=False)
            if html:
                hubs += ps.find_pleio_hubs_from_html(html, base)
        except Exception:
            pass
    # include extra seeds if present
    extra = ps.load_extra_seeds()
    for s in (extra.get(name, []) if extra else [])[:5]:
        try:
            h2, b2 = ps.fetch_html(s, allow_render=False)
            if h2:
                hubs += ps.find_pleio_hubs_from_html(h2, b2)
        except Exception:
            pass
    # dedup
    out = []
    seen = set()
    for u in hubs:
        if u in seen:
            continue
        seen.add(u)
        out.append(u)
    return out


def direct_download_from_views(view_links: list[str], out_dir: str) -> int:
    os.makedirs(out_dir, exist_ok=True)
    saved = 0
    for v in view_links:
        dest = ps.download_pdf(v, out_dir)
        if dest:
            saved += 1
    return saved


def run(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Generic Pleio scraper (enumerate then HTTP-download)")
    ap.add_argument('--only', type=str, default=None, help='Municipality name (uses start_url to find Pleio hubs)')
    ap.add_argument('--hub', type=str, default=None, help='Explicit Pleio hub URL to enumerate')
    ap.add_argument('--outdir', type=str, default=None, help='Output directory (defaults to ./pdfs/<muni>_pleio_tmp or ./tmp_pleio)')
    ap.add_argument('--headful', action='store_true', help='Open Pleio headful for enumerating (more stable)')
    args = ap.parse_args(argv)

    hubs: list[str] = []
    mun = args.only
    if args.hub:
        hubs = [args.hub]
        if not mun:
            mun = 'pleio'
    else:
        if not mun:
            print('[pleio] Provide --only <Municipality> or --hub <URL>')
            return 2
        hubs = discover_hubs_for(mun)
        if not hubs:
            print(f"[pleio] No Pleio hubs discovered for {mun}")
            return 1

    out_dir = args.outdir or (os.path.join(os.getcwd(), 'pdfs', ps.sanitize_filename(mun + '_pleio_tmp')))
    os.makedirs(out_dir, exist_ok=True)
    print(f"[pleio] Target: {mun} -> hubs={len(hubs)} out={out_dir}")

    total_saved = 0
    for hub in hubs:
        print(f"[pleio] Enumerating hub: {hub}")
        try:
            views = ps.pleio_enumerate_view_links(hub, headful=args.headful)
        except Exception as e:
            print(f"[pleio] enumerate failed: {e}")
            views = []
        print(f"[pleio] Views discovered: {len(views)}")
        if not views:
            continue
        saved = direct_download_from_views(views, out_dir)
        print(f"[pleio] Saved {saved} PDFs from {hub}")
        total_saved += saved
    print(f"[pleio] Done. Total saved: {total_saved}")
    return 0 if total_saved > 0 else 1


if __name__ == '__main__':
    sys.exit(run())
