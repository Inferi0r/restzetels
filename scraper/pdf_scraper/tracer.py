from __future__ import annotations

import json
import os
import time
from typing import Any, Dict, Optional

from .config import TRACES_DIR
from .utils import sanitize_filename, ensure_pdf_extension, strip_size_tokens
from urllib.parse import urlparse


class Tracer:
    def __init__(self, municipality: str):
        os.makedirs(TRACES_DIR, exist_ok=True)
        ts = time.strftime("%Y%m%d-%H%M%S")
        safe = municipality.replace("/", "-")
        self.path = os.path.join(TRACES_DIR, f"trace_{safe}_{ts}.jsonl")
        self.muni = municipality
        self.meta: Dict[str, Any] = {"municipality": municipality, "started_at": ts}
        self._write({"type": "start", "municipality": municipality, "ts": ts})

    def record_meta(self, **kv):
        self.meta.update(kv)
        self._write({"type": "meta", **kv})

    def record_request(self, method: str, url: str, purpose: str, status: int, content_type: str, size: int, elapsed_ms: int, err: Optional[str] = None):
        self._write({
            "type": "request", "method": method, "url": url, "purpose": purpose,
            "status": status, "content_type": content_type, "size": size,
            "elapsed_ms": elapsed_ms, "err": err, "t": time.time(),
        })

    def record_discovery(self, stage: str, url: str, note: str = ""):
        self._write({"type": "discover", "stage": stage, "url": url, "note": note, "t": time.time()})

    def record_found_pdf(self, remote_url: str, source_url: str, name: str, score: int):
        # Compute the preferred download filename we would use locally
        try:
            base = (name or '').strip() or (urlparse(remote_url).path.rsplit('/', 1)[-1] or 'document.pdf')
        except Exception:
            base = name or 'document.pdf'
        # Apply hard naming rules globally:
        # - Never include size tokens (e.g., "(pdf, 2.24 MB)", "124.65 kB")
        # - Replace .htm/.html with .pdf (avoid ".htm.pdf")
        # - Ensure it ends with .pdf
        try:
            base = strip_size_tokens(base)
            base = ensure_pdf_extension(base)
            if not base.lower().endswith('.pdf'):
                base = base + '.pdf'
        except Exception:
            pass
        preferred = sanitize_filename(base)
        self._write({
            "type": "found_pdf",
            "remote_url": remote_url,
            "from": source_url,
            "name": name,
            "download_name": preferred,
            "score": score,
            "t": time.time(),
        })

    def record_stop(self, reason: str, stats: Optional[Dict[str, Any]] = None):
        self._write({"type": "stop", "reason": reason, "stats": stats or {}, "t": time.time()})

    def _write(self, obj: Dict[str, Any]):
        with open(self.path, "a", encoding="utf-8") as f:
            f.write(json.dumps(obj, ensure_ascii=False) + "\n")
