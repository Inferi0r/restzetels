#!/usr/bin/env python3
"""
Ad-hoc scraper voor Olst-Wijhe om PV's (stembureaus) te vinden via een kleine BFS
binnen het eigen domein. Zodra bevestigd werkt, integreren we dit generiek.
"""
import os
import sys
import re
from collections import deque
from urllib.parse import urljoin, urlparse
from bs4 import BeautifulSoup

import pdf_scraper as ps


KEY_RE = re.compile(r"verkiez|uitslag|proces|verbaal|stembur|tweede.*kamer|pv\b|n10|na\s*31|na31|model", re.I)


def fetch(url: str) -> tuple[str, str] | tuple[None, None]:
    try:
        r = ps.http_get(url)
        if r.status_code == 200:
            return r.text, r.url
    except Exception:
        pass
    return None, None


def bfs_collect_internal(start_url: str, max_depth: int = 2, max_pages: int = 60) -> list[str]:
    pu = urlparse(start_url)
    origin = f"{pu.scheme}://{pu.netloc}"
    seen = set()
    out_pages: list[str] = []
    q = deque([(start_url, 0)])
    seen.add(start_url)
    while q and len(out_pages) < max_pages:
        u, d = q.popleft()
        html, base = fetch(u)
        if not html:
            continue
        out_pages.append(base)
        if d >= max_depth:
            continue
        soup = BeautifulSoup(html, 'html.parser')
        for a in soup.select('a[href]'):
            href = a.get('href'); full = urljoin(base, href or '')
            if not full:
                continue
            uu = urlparse(full)
            if uu.netloc != pu.netloc:
                continue
            # don't queue pdfs
            if uu.path.lower().endswith('.pdf'):
                continue
            low = (full + ' ' + (a.get_text(' ', strip=True) or '')).lower()
            if KEY_RE.search(low):
                if full not in seen:
                    seen.add(full)
                    q.append((full, d + 1))
    # dedup preserve order
    out = []
    seen2 = set()
    for u in out_pages:
        if u in seen2:
            continue
        seen2.add(u); out.append(u)
    return out


def run() -> int:
    name = 'Olst-Wijhe'
    start = ps.get_start_url(name) or 'https://www.olst-wijhe.nl/verkiezingen'
    pages = bfs_collect_internal(start, max_depth=2, max_pages=80)
    print(f"[olst-wijhe] discovered {len(pages)} pages to scan")
    out_dir = os.path.join(os.getcwd(), 'pdfs', ps.sanitize_filename(name))
    os.makedirs(out_dir, exist_ok=True)
    found = []
    for p in pages:
        try:
            r = ps.http_get(p, timeout=20)
        except Exception:
            continue
        found += ps.extract_pdf_links(r.text, r.url)
    # dedup by remote_url
    seen = set(); pdfs = []
    for e in found:
        u = e.get('remote_url')
        if not u or u in seen:
            continue
        seen.add(u); pdfs.append(e)
    print(f"[olst-wijhe] candidates: {len(pdfs)}")
    saved = 0
    for p in pdfs:
        u = p.get('remote_url');
        if not u:
            continue
        dest = ps.download_pdf(u, out_dir)
        if dest:
            saved += 1
    print(f"[olst-wijhe] saved {saved} PDFs -> {out_dir}")
    return 0


if __name__ == '__main__':
    sys.exit(run())

