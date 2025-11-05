from __future__ import annotations

from typing import List, Dict

from urllib.parse import urlparse
import time


API_BASE = "https://api.data.amsterdam.nl/v1/verkiezingen/processenverbaal"
PV_BASE = "https://pv-verkiezingen.amsterdam.nl/verkiezingen/procesverbalen/2025/"


def handle(hub_url: str, req, tracer, municipality: str) -> List[Dict]:
    """Amsterdam-specific handler: enumerate PVs via the official API.

    Returns synthetic found items with remote_url and inferred names.
    """
    if (municipality or '').strip().lower() != 'amsterdam':
        return []
    items: List[Dict] = []
    seen: set[str] = set()
    next_url = API_BASE + "?verkiezingsjaar=2025&page_size=1000"
    tries = 0
    while next_url and tries < 20:
        tries += 1
        # Use explicit JSON Accept to avoid HTML content
        t0 = time.time()
        try:
            r = req.sess.get(next_url, headers={"Accept": "application/hal+json, application/json;q=0.9, */*;q=0.5"}, timeout=(15, 30), allow_redirects=True)
            elapsed = int((time.time() - t0) * 1000)
            ct = (r.headers.get("content-type") or "").lower()
            size = len(r.content or b"")
            try:
                tracer.record_request("GET", next_url, "platform:amsterdam-api", r.status_code, ct, size, elapsed)
            except Exception:
                pass
        except Exception:
            break
        try:
            data = r.json() or {}
        except Exception:
            # Not JSON; stop
            break
        arr = (data.get('_embedded') or {}).get('processenverbaal', []) or []
        for it in arr:
            dn = (it or {}).get('documentnaam') or ''
            uri = (it or {}).get('uri') or ''
            if not dn or not dn.lower().endswith('.pdf'):
                continue
            low = dn.lower()
            # Only proces-verbaal / model 10 (per stembureau)
            if ('proces' not in low) and ('model_10' not in low) and ('proces_verbaal' not in low):
                continue
            href = uri if uri.startswith('http') else (PV_BASE + dn)
            key = href.split('?', 1)[0]
            if key in seen:
                continue
            seen.add(key)
            name = dn
            items.append({'remote_url': key, 'local_url': None, 'pdf_name': name, 'text': 'Amsterdam API', 'from': r.url, 'score': 7})
        # next page
        try:
            nxt = (data.get('_links') or {}).get('next') or {}
            next_url = nxt.get('href') if isinstance(nxt, dict) else None
        except Exception:
            next_url = None
    return items
