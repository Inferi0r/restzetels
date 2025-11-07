from __future__ import annotations

import os
from typing import Dict, Optional
from urllib.parse import urlparse, parse_qs

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
    # Special handling: MediaFiler albums with javascript download require a JS click
    try:
        if ('mediafiler' in (remote_url or '').lower()) and ('#' in remote_url):
            base, frag = remote_url.split('#', 1)
            qs = parse_qs(frag)
            fuid = (qs.get('fuid') or [''])[0]
            fn = (qs.get('fn') or [''])[0] or name
            # Ensure filename reflects provided 'fn'
            if fn:
                try:
                    from .utils import strip_size_tokens as _strip_sz, ensure_pdf_extension as _ensure_pdf
                    fn2 = _ensure_pdf(_strip_sz(fn))
                except Exception:
                    fn2 = fn
                if fn2 and fn2.lower().endswith('.pdf'):
                    dest = os.path.join(out_dir, sanitize_filename(fn2))
            if os.path.exists(dest) and os.path.getsize(dest) > 0:
                print(f"[SKIP] exists {dest}")
                return dest
            print(f"[DOWNLOAD][mediafiler] fuid={fuid} fn={fn} from {base} -> {dest}")
            try:
                from playwright.sync_api import sync_playwright  # type: ignore
            except Exception as e:
                print(f"[ERROR] Playwright unavailable for mediafiler: {e}")
                return None
            try:
                with sync_playwright() as p:
                    b = p.chromium.launch(headless=True)
                    ctx = b.new_context(accept_downloads=True)
                    page = ctx.new_page()
                    page.goto(base, wait_until="domcontentloaded", timeout=60000)
                    try:
                        page.wait_for_load_state("networkidle", timeout=15000)
                    except Exception:
                        pass
                    # Trigger download via the page's downloadTab function
                    triggered = False
                    try:
                        page.evaluate("(fuid, fn) => window.downloadTab && window.downloadTab(fuid, fn)", fuid, fn)
                        triggered = True
                    except Exception:
                        pass
                    if not triggered:
                        # Fallback: click the first anchor whose href contains downloadTab('<fuid>')
                        try:
                            page.evaluate(
                                "(fuid) => { const els = Array.from(document.querySelectorAll('a[href]')); const el = els.find(e => (e.getAttribute('href')||'').includes(`downloadTab('${fuid}'`)); if (el) el.click(); }",
                                fuid
                            )
                            triggered = True
                        except Exception:
                            pass
                    # Wait for the download event and save
                    d = page.wait_for_event('download', timeout=60000)
                    try:
                        d.save_as(dest)
                    except Exception:
                        # If saving fails, try to stream from the response URL
                        try:
                            url = d.url or ''
                            if url:
                                with req.get(url, purpose="download", stream=True) as r:
                                    r.raise_for_status()
                                    with open(dest, 'wb') as f:
                                        for chunk in r.iter_content(chunk_size=32768):
                                            if chunk:
                                                f.write(chunk)
                        except Exception:
                            pass
                    ctx.close(); b.close()
                    if os.path.exists(dest) and os.path.getsize(dest) > 0:
                        return dest
                    print("[ERROR] MediaFiler download did not produce a file")
                    return None
            except Exception as e:
                print(f"[ERROR] mediafiler download failed: {e}")
                try:
                    if os.path.exists(dest):
                        os.remove(dest)
                except Exception:
                    pass
                return None
    except Exception:
        # Fall through to generic HTTP streaming
        pass

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
