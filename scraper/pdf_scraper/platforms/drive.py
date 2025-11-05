from __future__ import annotations

import re
from typing import Dict, List


FILE_RE = re.compile(r"https?://drive\.google\.com/file/d/([a-zA-Z0-9_-]{10,})")
FOLDER_RE = re.compile(r"https?://drive\.google\.com/drive/folders/([a-zA-Z0-9_-]{10,})")


def handle(hub_url: str, req, tracer, municipality: str) -> List[Dict]:
    items: List[Dict] = []
    m = FILE_RE.search(hub_url)
    if m:
        fid = m.group(1)
        uc = f"https://drive.google.com/uc?export=download&id={fid}"
        items.append({'remote_url': uc, 'local_url': None, 'pdf_name': f'{fid}.pdf', 'text': 'Google Drive file', 'from': hub_url, 'score': 5})
        return items
    mf = FOLDER_RE.search(hub_url)
    if mf:
        try:
            r = req.get(hub_url, purpose="platform:drive")
        except Exception:
            return items
        tracer.record_discovery("platform", r.url, "google-drive")
        # naive parse: enumerate file anchors
        for a in re.finditer(r"https://drive\.google\.com/file/d/[a-zA-Z0-9_-]{10,}", r.text):
            fid = a.group(0).split('/file/d/')[1].split('/')[0]
            uc = f"https://drive.google.com/uc?export=download&id={fid}"
            items.append({'remote_url': uc, 'local_url': None, 'pdf_name': f'{fid}.pdf', 'text': 'Google Drive file', 'from': r.url, 'score': 5})
    return items

