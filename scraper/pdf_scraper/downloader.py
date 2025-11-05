from __future__ import annotations

import os
from typing import Dict, Optional
from urllib.parse import urlparse

from .config import OUT_BASE
from .http_client import Requester
from .utils import sanitize_filename, is_current_year_pdf, ensure_pdf_extension, strip_size_tokens


def ensure_out_dir(municipality: str) -> str:
    d = os.path.join(OUT_BASE, sanitize_filename(municipality))
    os.makedirs(d, exist_ok=True)
    return d


def stream_download_pdf(req: Requester, municipality: str, remote_url: str, preferred_name: Optional[str] = None) -> Optional[str]:
    out_dir = ensure_out_dir(municipality)
    name = preferred_name or (os.path.basename(urlparse(remote_url).path) or 'document.pdf')
    # Apply global naming rules for downloads
    try:
        name = strip_size_tokens(name)
        name = ensure_pdf_extension(name)
        if not name.lower().endswith('.pdf'):
            name += '.pdf'
    except Exception:
        pass
    name = sanitize_filename(name)
    if not is_current_year_pdf(name + ' ' + remote_url):
        return None
    dest = os.path.join(out_dir, name)
    # Avoid redownloading
    if os.path.exists(dest) and os.path.getsize(dest) > 0:
        print(f"[SKIP] exists {dest}")
        return dest
    print(f"[DOWNLOAD] {remote_url} -> {dest}")
    try:
        with req.get(remote_url, purpose="download", stream=True) as r:
            r.raise_for_status()
            with open(dest, 'wb') as f:
                for chunk in r.iter_content(chunk_size=32768):
                    if chunk:
                        f.write(chunk)
        return dest
    except Exception as e:
        print(f"[ERROR] download failed {remote_url}: {e}")
        try:
            if os.path.exists(dest):
                os.remove(dest)
        except Exception:
            pass
        return None


def download_index_items(req: Requester, municipality: str, items: list[Dict]) -> list[Dict]:
    out: list[Dict] = []
    for it in items:
        u = it.get('remote_url') or ''
        if not u:
            continue
        print(f"[FOUND.PDF] {u}")
        dest = stream_download_pdf(req, municipality, u, it.get('pdf_name'))
        if dest:
            it2 = dict(it)
            it2['local_url'] = 'file://' + os.path.abspath(dest)
            out.append(it2)
    return out
