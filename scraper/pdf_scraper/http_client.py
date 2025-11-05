from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Optional, Tuple

import requests

from .config import LIMITS


@dataclass
class ResponseInfo:
    url: str
    status: int
    content_type: str
    elapsed_ms: int
    size: int


class Requester:
    def __init__(self, user_agent: str = None, tracer=None):
        self.sess = requests.Session()
        if not user_agent:
            user_agent = (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/118.0 Safari/537.36"
            )
        self.sess.headers.update({
            "User-Agent": user_agent,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "nl-NL,nl;q=0.9,en-US;q=0.8,en;q=0.7",
        })
        self.tracer = tracer
        self.request_count = 0

    def head(self, url: str, purpose: str = "discover", timeout: Tuple[int, int] = (8, 12)) -> Optional[ResponseInfo]:
        t0 = time.time()
        try:
            r = self.sess.head(url, timeout=timeout, allow_redirects=True)
            self.request_count += 1
            elapsed = int((time.time() - t0) * 1000)
            info = ResponseInfo(
                url=r.url,
                status=r.status_code,
                content_type=(r.headers.get("content-type", "") or "").lower(),
                elapsed_ms=elapsed,
                size=int(r.headers.get("content-length") or 0),
            )
            if self.tracer:
                self.tracer.record_request("HEAD", url, purpose, info.status, info.content_type, info.size, info.elapsed_ms)
            print(f"[HEAD][{purpose}] {url} -> {info.status} {info.content_type}")
            return info
        except Exception as e:
            if self.tracer:
                self.tracer.record_request("HEAD", url, purpose, -1, "", 0, int((time.time()-t0)*1000), err=str(e))
            print(f"[HEAD][{purpose}] {url} -> ERROR {e}")
            return None

    def get(self, url: str, purpose: str = "discover", timeout: Tuple[int, int] = (15, 30), stream: bool = False):
        t0 = time.time()
        r = self.sess.get(url, timeout=timeout, allow_redirects=True, stream=stream)
        self.request_count += 1
        elapsed = int((time.time() - t0) * 1000)
        ct = (r.headers.get("content-type", "") or "").lower()
        size = int(r.headers.get("content-length") or 0)
        if self.tracer:
            self.tracer.record_request("GET", url, purpose, r.status_code, ct, size, elapsed)
        print(f"[GET][{purpose}] {url} -> {r.status_code} {ct}")
        r.raise_for_status()
        return r

    def probe_pdf_exists(self, url: str) -> bool:
        # try head first
        r = self.head(url, purpose="probe")
        if r and 200 <= r.status < 400:
            if ("pdf" in r.content_type) or url.lower().endswith(".pdf"):
                return True
        # fallback lightweight GET with Range
        try:
            t0 = time.time()
            rg = self.sess.get(url, headers={"Range": "bytes=0-0"}, timeout=(8, 12), allow_redirects=True, stream=True)
            self.request_count += 1
            elapsed = int((time.time()-t0)*1000)
            ct = (rg.headers.get("content-type", "") or "").lower()
            size = int(rg.headers.get("content-length") or 0)
            if self.tracer:
                self.tracer.record_request("GET", url, "probe-range", rg.status_code, ct, size, elapsed)
            ok = (200 <= rg.status_code < 400) or rg.status_code == 206
            if ok:
                rg.close()
                return ("pdf" in ct) or url.lower().endswith(".pdf")
            rg.close()
        except Exception:
            pass
        return False

