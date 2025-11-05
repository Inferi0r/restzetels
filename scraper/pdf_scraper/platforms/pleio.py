from __future__ import annotations

from typing import Dict, List

from bs4 import BeautifulSoup


def handle(hub_url: str, req, tracer, municipality: str) -> List[Dict]:
    items: List[Dict] = []
    try:
        r = req.get(hub_url, purpose="platform:pleio")
    except Exception:
        return items
    tracer.record_discovery("platform", r.url, "pleio")
    s = BeautifulSoup(r.text, 'html.parser')
    for a in s.select('a[href]'):
        href = (a.get('href') or '').strip()
        low = href.lower()
        if low.endswith('.pdf') or ('/download/' in low) or ('?download=' in low):
            name = href.rsplit('/', 1)[-1] or 'document.pdf'
            items.append({'remote_url': href, 'local_url': None, 'pdf_name': name, 'text': a.get_text(' ', strip=True) or 'pleio', 'from': r.url, 'score': 5})
    return items

