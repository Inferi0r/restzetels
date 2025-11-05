from __future__ import annotations

import json
import os
from urllib.parse import urlparse

from .config import DATA_DIR, INDEX_PATH


def light_merge_index(name: str, pdfs: list[dict]) -> None:
    try:
        with open(INDEX_PATH, 'r', encoding='utf-8') as f:
            data = json.load(f)
        results = data.get('results', []) if isinstance(data, dict) else []
    except Exception:
        results = []
    name_to = {e.get('name'): e for e in results}
    cur = name_to.get(name) or {'name': name, 'start_url': None, 'pdfs': []}
    seen = set()
    for q in cur.get('pdfs', []):
        k = q.get('remote_url') or ('N:' + (q.get('pdf_name') or ''))
        if k:
            seen.add(k)
    for p in pdfs:
        k = p.get('remote_url') or ('N:' + (p.get('pdf_name') or ''))
        if not k or k in seen:
            continue
        seen.add(k)
        cur.setdefault('pdfs', []).append({
            'remote_url': p.get('remote_url'),
            'local_url': p.get('local_url'),
            'pdf_name': p.get('pdf_name') or os.path.basename(urlparse((p.get('remote_url') or '')).path) or 'unknown.pdf',
            'text': p.get('text') or p.get('pdf_name') or '',
            'from': p.get('from') or (p.get('remote_url') or 'unknown'),
            'score': int(p.get('score') or 0),
        })
    name_to[name] = cur
    out = [name_to[k] for k in sorted(name_to.keys())]
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(INDEX_PATH, 'w', encoding='utf-8') as f:
        json.dump({'results': out, 'count': len(out)}, f, ensure_ascii=False, indent=2)
    print(f"[INDEX] Merged {len(pdfs)} items for {name} -> {INDEX_PATH}")

