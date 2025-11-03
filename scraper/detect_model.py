#!/usr/bin/env python3
"""
Detecteer het modeltype van lokale verkiezings-PDFs en schrijf 'model' weg
in pdf_scraper_input/municipality_pdfs_index.json.

Herkenbare modellen (exacte labels):
  - N10-1
  - N10-2
  - Na 31-1
  - Na 31-2
  - overig

Detectiestrategie (snel → robuust):
  1) Heuristiek op basis van bestandsnaam, tekstvelden en URL-basename
  2) Zo nodig: eerste pagina van de lokale PDF uitlezen (indien mogelijk)

Gebruik:
  python3 detect_model.py [--only MUNICIPALITY ...] [--dry-run]

"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from urllib.parse import urlparse, unquote

DATA_DIR = os.path.join(os.path.dirname(__file__), "pdf_scraper_input")
INDEX_PATH = os.path.join(DATA_DIR, "municipality_pdfs_index.json")


def load_index(path: str = INDEX_PATH):
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if isinstance(data, dict) and isinstance(data.get("results"), list):
        return data
    # legacy: list
    return {"results": data, "count": len(data)}


def save_index(data, path: str = INDEX_PATH):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def compile_regex():
    # Specifieke modellen eerst (om generieke hits te vermijden)
    # Let op: NA/Na/nA varianten toelaten, diverse scheidingstekens
    sep = r"[-_\s–—]*"  # bindtekens inclusief en-dash/em-dash
    rx = {
        "N10-1": re.compile(rf"\b(model{sep})?n{sep}10{sep}1\b", re.I),
        "N10-2": re.compile(rf"\b(model{sep})?n{sep}10{sep}2\b", re.I),
        "Na 31-2": re.compile(rf"\b(model{sep})?na{sep}31{sep}2\b", re.I),
        "Na 31-1": re.compile(rf"\b(model{sep})?na{sep}31{sep}1\b", re.I),
        # Generieke vangnetten (niet gebruikt voor label, alleen ter ondersteuning)
        "N10": re.compile(rf"\b(model{sep})?n{sep}10\b", re.I),
        "Na31": re.compile(rf"\b(model{sep})?na{sep}31\b", re.I),
    }
    return rx


RX = compile_regex()


def norm_text(*parts: str | None) -> str:
    s = " ".join([p for p in parts if isinstance(p, str) and p])
    # URL path basenames ook meenemen gedecodeerd
    out = [s]
    for p in parts:
        if not isinstance(p, str) or not p:
            continue
        try:
            if p.startswith("http") or p.startswith("file://"):
                u = urlparse(p)
                out.append(unquote(os.path.basename(u.path)))
        except Exception:
            pass
    z = " ".join(out)
    return z


def detect_from_strings(s: str) -> str | None:
    if not s:
        return None
    # Volgorde is belangrijk
    if RX["N10-1"].search(s):
        return "N10-1"
    if RX["N10-2"].search(s):
        return "N10-2"
    if RX["Na 31-2"].search(s):
        return "Na 31-2"
    if RX["Na 31-1"].search(s):
        return "Na 31-1"
    return None


def read_first_page_text(local_url: str) -> str | None:
    # Alleen file:// ondersteunen
    if not (isinstance(local_url, str) and local_url.lower().startswith("file://")):
        return None
    path = urlparse(local_url).path
    # macOS paths uit file:// hebben een leading slash al; unquote is al gedaan in norm_text
    try:
        # Probeer PyPDF2 – lichtgewicht en vaak aanwezig
        from PyPDF2 import PdfReader  # type: ignore
        with open(path, "rb") as f:
            reader = PdfReader(f)
            if len(reader.pages) == 0:
                return None
            page0 = reader.pages[0]
            try:
                txt = page0.extract_text() or ""
            except Exception:
                txt = ""
            return txt
    except Exception:
        # Val terug op pdfminer.six indien beschikbaar
        try:
            from pdfminer.high_level import extract_text  # type: ignore
            txt = extract_text(path, maxpages=1) or ""
            return txt
        except Exception:
            return None


def detect_model_for_item(p: dict) -> str:
    # 1) Snelle heuristiek op strings
    s = norm_text(p.get("pdf_name"), p.get("text"), p.get("preview_text"), p.get("remote_url"), p.get("local_url"), p.get("from"))
    hit = detect_from_strings(s)
    if hit:
        return hit
    # 2) Eerste pagina van lokale PDF
    loc = p.get("local_url")
    t = read_first_page_text(loc) if loc else None
    if t:
        hit2 = detect_from_strings(t)
        if hit2:
            return hit2
    return "overig"


def run(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Detecteer model van lokale verkiezings-PDFs en update index")
    ap.add_argument("--only", nargs='*', help="Beperk tot deze gemeenten (namen)")
    ap.add_argument("--dry-run", action="store_true", help="Geen wijzigingen schrijven, alleen tonen")
    args = ap.parse_args(argv)

    data = load_index(INDEX_PATH)
    results = data.get("results", [])

    # Subset bepalen
    if args.only:
        only = set(args.only)
        todo = [e for e in results if e.get("name") in only]
    else:
        todo = list(results)

    updated = 0
    total = 0
    for entry in todo:
        name = entry.get("name") or ""
        pdfs = entry.get("pdfs") or []
        for p in pdfs:
            # Alleen lokale bestanden classificeren
            if not p.get("local_url"):
                continue
            total += 1
            new_model = detect_model_for_item(p)
            old_model = p.get("model")
            if old_model != new_model:
                p["model"] = new_model
                updated += 1
        # einde entry

    if args.dry_run:
        print(f"[detect] Done (dry-run). to_classify={total}, updated={updated}")
        return 0

    # Schrijf terug
    data["count"] = len(results)
    save_index(data, INDEX_PATH)
    print(f"[detect] Done. classified={total}, updated={updated} -> {INDEX_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())

