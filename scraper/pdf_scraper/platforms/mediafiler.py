from __future__ import annotations

from typing import Dict, List
from bs4 import BeautifulSoup
import re


def handle(hub_url: str, req, tracer, municipality: str) -> List[Dict]:
    items: List[Dict] = []
    try:
        r = req.get(hub_url, purpose="platform:mediafiler")
    except Exception:
        return items
    tracer.record_discovery("platform", r.url, "mediafiler")
    s = BeautifulSoup(r.text, 'html.parser')
    for a in s.select('a[href]'):
        href = (a.get('href') or '').strip()
        low = href.lower()
        # Direct PDF links
        if low.endswith('.pdf') or ('/file/' in low):
            name = href.rsplit('/', 1)[-1] or 'document.pdf'
            items.append({'remote_url': href, 'local_url': None, 'pdf_name': name, 'text': a.get_text(' ', strip=True) or 'mediafiler', 'from': r.url, 'score': 5})
            continue
        # javascript:downloadTab('<id>', '<filename.pdf>') pattern — extract provided filename
        if low.startswith('javascript:downloadtab') or 'downloadtab(' in low:
            m = re.search(r"downloadTab\('\s*(\d+)\s*'\s*,\s*\"([^\"]+?\.pdf)\"\s*\)", href)
            if not m:
                m = re.search(r"downloadTab\('\s*(\d+)\s*'\s*,\s*'([^']+?\.pdf)'\s*\)", href)
            if m:
                fuid = m.group(1)
                fname = m.group(2)
                # Encode fuid and filename in fragment so downloader can perform JS click
                from urllib.parse import quote
                ru = f"{r.url}#fuid={fuid}&fn={quote(fname)}"
                items.append({'remote_url': ru, 'local_url': None, 'pdf_name': fname, 'text': a.get_text(' ', strip=True) or 'mediafiler', 'from': r.url, 'score': 6})
    return items
