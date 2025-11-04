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
  python3 detect_model.py [--only MUNICIPALITY ...] [--dry-run] [--refresh]
  python3 detect_model.py --model31

"""
from __future__ import annotations

import argparse
import json
import os
import re
from urllib.parse import urlparse, unquote
import shutil
import subprocess

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
        # Gemeentelijk stembureau aanduiding; voor TK2025 centrale stemopneming is dit Na 31-2
        "GSB": re.compile(r"(gemeentelijk\s+stembureau|\bgsb\b)", re.I),
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
    # Heuristiek: 'Gemeentelijk stembureau' of 'GSB' duidt vrijwel zeker op model Na 31-2 bij TK2025
    if RX.get("GSB") and RX["GSB"].search(s):
        return "Na 31-2"
    return None


def read_first_page_text(local_url: str) -> str | None:
    # Alleen file:// ondersteunen
    if not (isinstance(local_url, str) and local_url.lower().startswith("file://")):
        return None
    u = urlparse(local_url)
    path = unquote(u.path)
    # macOS paths uit file:// hebben een leading slash al; unquote is al gedaan in norm_text
    # Snelste pad: gebruik 'pdftotext' als beschikbaar om alleen pagina 1 te extraheren
    try:
        exe = shutil.which("pdftotext")
        if exe and os.path.exists(path):
            # Eerst: layout, daarna raw; neem de langste
            out_layout = subprocess.run([exe, "-q", "-f", "1", "-l", "1", "-layout", path, "-"],
                                        check=False, capture_output=True)
            txt_layout = out_layout.stdout.decode("utf-8", errors="ignore").strip()
            if txt_layout:
                return txt_layout
            out_raw = subprocess.run([exe, "-q", "-f", "1", "-l", "1", "-raw", path, "-"],
                                     check=False, capture_output=True)
            txt_raw = out_raw.stdout.decode("utf-8", errors="ignore").strip()
            if txt_raw:
                return txt_raw
    except Exception:
        pass
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
            if txt:
                return txt
        except Exception:
            pass
    return None


def ocr_header_text(local_url: str) -> str | None:
    """OCR-fallback: render de kop (bovenste ~28%) van pagina 1 en lees met Tesseract (nld+eng).
    Gebruikt pdfplumber + pytesseract vergelijkbaar met ocr_methode1.
    """
    try:
        u = urlparse(local_url)
        path = unquote(u.path)
        import pdfplumber  # type: ignore
        from PIL import ImageOps, ImageFilter  # type: ignore
        from pytesseract import image_to_string  # type: ignore
        with pdfplumber.open(str(path)) as pdf:
            if not pdf.pages:
                return None
            page = pdf.pages[0]
            im = page.to_image(resolution=350).original
            h = im.height
            crop = im.crop((0, 0, im.width, int(h * 0.28)))
            g = ImageOps.grayscale(crop)
            g = ImageOps.autocontrast(g)
            g = g.filter(ImageFilter.SHARPEN)
            for langs in ("nld+eng", "eng"):
                try:
                    txt = image_to_string(g, config=f"--psm 6 -l {langs}")
                    if txt and txt.strip():
                        return txt
                except Exception:
                    continue
    except Exception:
        return None
    return None


def ocr_region_text(local_url: str, top_rel: float = 0.2, bottom_rel: float = 0.7, resolution: int = 350) -> str | None:
    """OCR een verticale strook van pagina 1 (top_rel..bottom_rel)."""
    try:
        u = urlparse(local_url)
        path = unquote(u.path)
        import pdfplumber  # type: ignore
        from PIL import ImageOps, ImageFilter  # type: ignore
        from pytesseract import image_to_string  # type: ignore
        with pdfplumber.open(str(path)) as pdf:
            if not pdf.pages:
                return None
            page = pdf.pages[0]
            im = page.to_image(resolution=resolution).original
            h = im.height
            y0 = max(0, int(h * max(0.0, min(1.0, top_rel))))
            y1 = max(y0 + 1, int(h * max(0.0, min(1.0, bottom_rel))))
            crop = im.crop((0, y0, im.width, y1))
            g = ImageOps.grayscale(crop)
            g = ImageOps.autocontrast(g)
            g = g.filter(ImageFilter.SHARPEN)
            for langs in ("nld+eng", "eng"):
                try:
                    txt = image_to_string(g, config=f"--psm 6 -l {langs}")
                    if txt and txt.strip():
                        return txt
                except Exception:
                    continue
    except Exception:
        return None
    return None


def is_bijlage_doc(local_url: str, text_hint: str | None = None, ocr_hint: str | None = None) -> bool:
    """Herken 'Bijlage 2' / 'uitkomsten per stembureau' documenten om ze te kunnen uitsluiten."""
    rx_bijlage = re.compile(r"\bbijlage\b", re.I)
    rx_bijlage2 = re.compile(r"\bbijlage\s*2\b", re.I)
    rx_uitkomsten = re.compile(r"uitkomsten\s+per\s+stembureau", re.I)
    rx_nummer = re.compile(r"nummer\s+stembureau", re.I)
    rx_locatie = re.compile(r"locatie\s+stembureau", re.I)

    for s in (text_hint or "", ocr_hint or ""):
        if not s:
            continue
        if rx_bijlage2.search(s) or (rx_bijlage.search(s) and rx_uitkomsten.search(s)) or rx_nummer.search(s) or rx_locatie.search(s):
            return True

    # Probeer uitgebreidere OCR-regio (middenstrook) om 'Bijlage 2' te vinden
    mid = ocr_region_text(local_url, 0.2, 0.7)
    if mid:
        if rx_bijlage2.search(mid) or (rx_bijlage.search(mid) and rx_uitkomsten.search(mid)) or rx_nummer.search(mid) or rx_locatie.search(mid):
            return True
    return False


def detect_model_for_item(p: dict) -> str:
    # 1) Snelle heuristiek op strings
    s = norm_text(p.get("pdf_name"), p.get("text"), p.get("remote_url"), p.get("local_url"), p.get("from"))
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
    # 3) OCR fallback op kop als bovenstaande faalt
    if loc:
        t2 = ocr_header_text(loc)
        if t2:
            hit3 = detect_from_strings(t2)
            if hit3:
                return hit3
    return "overig"


def detect_doc_kind(p: dict) -> str | None:
    """Specifieke documentsoort naast het model, bijv. 'bijlage-2' (uitkomsten per stembureau).
    Laat 'model' ongemoeid; dit is extra metadata voor downstream filters.
    """
    loc = p.get("local_url")
    # Snelle bestandsnaam/broncheck om OCR te vermijden
    fname = (p.get("pdf_name") or "").lower()
    hint = (p.get("text") or "") + " " + (p.get("from") or "")
    if any(k in fname for k in ("bijlage",)) or ("uitkomst" in fname and "stembureau" in fname):
        return "bijlage-2"
    # Inhoudelijk checken met tekst/OCR
    t = read_first_page_text(loc) if loc else None
    o = None
    if not t:
        o = ocr_header_text(loc) if loc else None
    if is_bijlage_doc(loc or "", text_hint=t, ocr_hint=o):
        return "bijlage-2"
    return None


def run(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Detecteer model van lokale verkiezings-PDFs en update index")
    ap.add_argument("--only", nargs='*', help="Beperk tot deze gemeenten (namen)")
    ap.add_argument("--dry-run", action="store_true", help="Geen wijzigingen schrijven, alleen tonen")
    ap.add_argument("--refresh", action="store_true", help="Herclassificeer alles (niet alleen ontbrekende modellen)")
    ap.add_argument("--model31", action="store_true", help="Genereer gemeente_model_31.json met alle gemeenten en hun Na 31-(-1/-2) PDFs")
    ap.add_argument("--filename-only", action="store_true", help="In --model31 modus: alleen bestandsnaam-heuristiek toepassen (geen PDF-tekst of OCR)")
    ap.add_argument("--include-bijlage", action="store_true", help="Neem ook bijlages (bijlage 2: uitkomsten per stembureau) mee in --model31")
    ap.add_argument("--prune-bijlage", action="store_true", help="Verwijder bestaande bijlage-2/uitkomsten-per-stembureau items uit de JSON (alleen in --model31)")
    ap.add_argument("--limit", type=int, default=None, help="Beperk in --model31 modus het aantal te scannen gemeenten (voor snelle test)")
    args = ap.parse_args(argv)

    data = load_index(INDEX_PATH)
    results = data.get("results", [])

    # Speciale modus: export van alle gemeenten (afgeleid uit ./pdfs) met hun Model 31 (-1 of -2)
    if args.model31:
        base_pdfs = os.path.join(os.path.dirname(__file__), "pdfs")
        if not os.path.isdir(base_pdfs):
            print(f"[model31] Map niet gevonden: {base_pdfs}")
            return 2

        # Verzamel gemeentenamen uit submappen van ./pdfs en sorteer A→Z
        municipalities_all = [d for d in os.listdir(base_pdfs) if os.path.isdir(os.path.join(base_pdfs, d))]
        municipalities_all.sort(key=lambda s: s.lower())

        # Laad bestaande output (niet leegmaken!) en zorg dat alle gemeenten als key bestaan
        output_path = os.path.join(os.path.dirname(__file__), "gemeente_model_31.json")
        out = {}
        try:
            if os.path.exists(output_path):
                with open(output_path, "r", encoding="utf-8") as f:
                    maybe = json.load(f)
                if isinstance(maybe, dict):
                    out = maybe
        except Exception:
            out = {}
        for name in municipalities_all:
            if name not in out or not isinstance(out.get(name), list):
                out[name] = []

        # Optioneel beperken tot expliciet gevraagde gemeenten of een limiet (alleen voor verwerking)
        if args.only:
            only = set(args.only)
            to_process = [m for m in municipalities_all if m in only]
        else:
            to_process = list(municipalities_all)
        if args.limit is not None:
            to_process = to_process[: max(0, int(args.limit))]

        # 1) Snelle pass: alleen bestandsnaam matchen (case-insensitive)
        #    Herken: 'na31' en 'n31' (met -, _ of spatie) en specifiek '31-1' / '31-2'
        #    Herken ook veelvoorkomende gemeentelijke naamgeving: 'uitkomst[_-]tk25' varianten
        # 'na31' moet als los 'na' voorkomen (geen deel van bv. 'Altena')
        rx_na31 = re.compile(r"(?<![A-Za-z])na[\s_\-–—]*31(?!\d)", re.I)
        rx_n31  = re.compile(r"(?<![A-Za-z])n[\s_\-–—]*31(?!\d)", re.I)
        # Vereis ten minste één scheidingsteken tussen '31' en '-1'/'-2' om '312' (stembureau-nummer) te vermijden
        rx_31_1 = re.compile(r"(?<!\d)31[\s_\-–—]+1(?!\d)", re.I)
        rx_31_2 = re.compile(r"(?<!\d)31[\s_\-–—]+2(?!\d)", re.I)
        rx_uitkomst_tk25 = re.compile(r"uitkomst[\s_\-–—]*tk[\s_\-–—]*25", re.I)

        def is_bijlage_filename(fname: str) -> bool:
            s = (fname or "").lower()
            if "bijlage" in s:
                return True
            # Heel specifiek patroon: uitkomsten per stembureau (ook met underscores/strepen)
            has_uitkomst = ("uitkomsten" in s) or ("uitkomst" in s) or ("uitslag" in s)
            if has_uitkomst and "stembureau" in s:
                return True
            # Sommige varianten gebruiken 'nummer-<n>' i.c.m. stembureau
            if "nummer" in s and "stembureau" in s:
                return True
            return False

        def merge_items(old_list, new_list):
            seen = set()
            merged = []
            for item in (list(old_list or []) + list(new_list or [])):
                if not isinstance(item, dict):
                    continue
                key = (item.get("local_url"), item.get("pdf_name"))
                if key in seen:
                    continue
                seen.add(key)
                merged.append({
                    "pdf_name": item.get("pdf_name"),
                    "local_url": item.get("local_url"),
                })
            return merged

        # Optioneel bestaande bijlages wegfilteren (met inhoudelijke check)
        if args.prune_bijlage:
            for name in (to_process or []):
                items = out.get(name, [])
                if not isinstance(items, list):
                    continue
                new_items = []
                for it in items:
                    if not isinstance(it, dict):
                        continue
                    fn = (it or {}).get("pdf_name") or ""
                    loc = (it or {}).get("local_url") or ""
                    # Snelle bestandsnaam check
                    s = fn.lower()
                    drop = False
                    if (
                        "bijlage" in s
                        or (("uitkomsten" in s or "uitkomst" in s or "uitslag" in s) and "stembureau" in s)
                        or ("nummer" in s and "stembureau" in s)
                    ):
                        drop = True
                    # Inhoudelijke check met tekst/OCR indien nog niet beslist
                    if not drop and loc:
                        t = read_first_page_text(loc) or ""
                        o = ocr_header_text(loc) or ""
                        if is_bijlage_doc(loc, text_hint=t, ocr_hint=o):
                            drop = True
                    if not drop:
                        new_items.append(it)
                out[name] = new_items

        # Altijd: snelle bijlage-prune op bestandsnaam (lichtgewicht), zodat oude bijlage-entries niet blijven hangen
        for name in (to_process or []):
            items = out.get(name, [])
            if not isinstance(items, list):
                continue
            quick = []
            for it in items:
                if not isinstance(it, dict):
                    continue
                s = ((it or {}).get("pdf_name") or "").lower()
                is_bij = (
                    ("bijlage" in s)
                    or (("uitkomsten" in s or "uitkomst" in s or "uitslag" in s) and "stembureau" in s)
                    or ("nummer" in s and "stembureau" in s)
                )
                if not is_bij:
                    quick.append(it)
            out[name] = quick

        # Extra: verwijder bestaande items die géén Na 31-1/Na 31-2 zijn (bv. N10-2 stembureau-PV's die eerder per ongeluk zijn toegevoegd)
        # Dit maakt 'empties' vrij voor een verse inhoudelijke scan.
        for name in (to_process or []):
            items = out.get(name, [])
            if not isinstance(items, list) or not items:
                continue
            kept = []
            for it in items:
                if not isinstance(it, dict):
                    continue
                loc = (it or {}).get("local_url") or ""
                t = read_first_page_text(loc) or ""
                label = detect_from_strings(t) if t else None
                if not label and not t:
                    txt = ocr_header_text(loc) or ""
                    if txt:
                        label = detect_from_strings(txt)
                if label in ("Na 31-1", "Na 31-2"):
                    kept.append(it)
            out[name] = kept

        for name in to_process:
            gdir = os.path.join(base_pdfs, name)
            coll: list[dict] = []
            try:
                files = [f for f in os.listdir(gdir) if f.lower().endswith(".pdf")]
            except Exception:
                files = []
            for fn in files:
                s = fn
                if (rx_na31.search(s) or rx_n31.search(s) or rx_31_1.search(s) or rx_31_2.search(s) or rx_uitkomst_tk25.search(s)) and not is_bijlage_filename(s):
                    abspath = os.path.join(gdir, fn)
                    coll.append({
                        "pdf_name": fn,
                        "local_url": f"file://{abspath}",
                    })
            if coll:
                out[name] = merge_items(out.get(name, []), coll)

        # 2) Voor gemeenten zonder resultaten: snelle tekstextractie van pagina 1, daarna pas OCR op kop
        empties = [n for n in to_process if not out.get(n)]
        if empties and not args.filename_only:
            rx_bijlage = re.compile(r"\bbijlage\b", re.I)
            rx_bijlage2 = re.compile(r"\bbijlage\s*2\b", re.I)
            rx_uitkomsten = re.compile(r"uitkomsten\s+per\s+stembureau", re.I)
            for name in empties:
                gdir = os.path.join(base_pdfs, name)
                try:
                    files = [f for f in os.listdir(gdir) if f.lower().endswith(".pdf")]
                except Exception:
                    files = []
                coll: list[dict] = []
                for fn in files:
                    abspath = os.path.join(gdir, fn)
                    loc = f"file://{abspath}"
                    # 2a. tekst van pagina 1 (snel)
                    t = read_first_page_text(loc) or ""
                    if t:
                        hit = detect_from_strings(t)
                        # standaard: bijlages overslaan, tenzij expliciet toegestaan
                        if (hit in ("Na 31-1", "Na 31-2") or RX["Na31"].search(t)):
                            if args.include_bijlage or not is_bijlage_doc(loc, text_hint=t):
                                coll.append({
                                    "pdf_name": fn,
                                    "local_url": loc,
                                })
                                continue
                    else:
                        # 2b. OCR van kop (alleen als tekst niets oplevert)
                        txt = ocr_header_text(loc) or ""
                        if txt:
                            hit = detect_from_strings(txt)
                            if (hit in ("Na 31-1", "Na 31-2") or RX["Na31"].search(txt)):
                                if args.include_bijlage or not is_bijlage_doc(loc, ocr_hint=txt):
                                    coll.append({
                                        "pdf_name": fn,
                                        "local_url": loc,
                                    })
                if coll:
                    out[name] = merge_items(out.get(name, []), coll)

        # 3) Verfijn gemeenten met meerdere treffers: kies beste per variant (-1/-2) op basis van inhoud
        def refine_multi_for_muni(name: str, items: list[dict]) -> list[dict]:
            if not items or len(items) <= 1:
                return items or []
            # Filter op bestandsnaam (bijlage/per-stembureau) vooraf
            prelim = [it for it in items if not (is_bijlage_filename((it or {}).get("pdf_name") or ""))]
            if not prelim:
                prelim = list(items)

            rx_gsb = re.compile(r"gemeentelijk\s+stembureau", re.I)
            rx_pv = re.compile(r"proces[-\s]?verbaal", re.I)
            rx_cso = re.compile(r"centrale\s+stemopneming", re.I)
            rx_nummer = re.compile(r"nummer\s+stembureau", re.I)
            rx_locatie = re.compile(r"locatie\s+stembureau", re.I)

            scored: list[tuple[int, str, dict]] = []
            for it in prelim:
                fn = (it or {}).get("pdf_name") or ""
                loc = (it or {}).get("local_url") or ""
                text = read_first_page_text(loc) or ""
                ocr = None
                score = 0
                label = detect_from_strings(text) if text else None
                if not label and not text:
                    ocr = ocr_header_text(loc) or ""
                    if ocr:
                        label = detect_from_strings(ocr)
                s_all = (text or "") + "\n" + (ocr or "")
                # hoofd-PV kenmerken
                if rx_pv.search(s_all) and rx_gsb.search(s_all):
                    score += 5
                if rx_cso.search(s_all):
                    score += 1
                # bijlage/per-stembureau signalen
                if is_bijlage_doc(loc, text_hint=text, ocr_hint=ocr or None):
                    score -= 10
                if rx_nummer.search(s_all) or rx_locatie.search(s_all):
                    score -= 3
                if label in ("Na 31-1", "Na 31-2"):
                    score += 2
                scored.append((score, label or "", it))

            by_var: dict[str, list[tuple[int, str, dict]]] = {}
            for tpl in scored:
                by_var.setdefault(tpl[1], []).append(tpl)
            selected: list[dict] = []
            for var in ("Na 31-2", "Na 31-1"):
                if var in by_var:
                    best = sorted(by_var[var], key=lambda x: x[0], reverse=True)[0]
                    selected.append(best[2])
            if not selected and scored:
                best_overall = sorted(scored, key=lambda x: x[0], reverse=True)[0]
                selected.append(best_overall[2])
            return selected

        if not args.filename_only:
            multis = [n for n in to_process if len(out.get(n, [])) > 1]
            for name in multis:
                refined = refine_multi_for_muni(name, out.get(name, []))
                out[name] = merge_items([], refined)

        tmp_path = output_path + ".tmp"
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(out, f, ensure_ascii=False, indent=2, sort_keys=True)
        os.replace(tmp_path, output_path)
        print(f"[model31] Geschreven: {output_path} (gemeenten={len(out)}, verwerkt={len(to_process)})")
        return 0

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
            # Default: alleen ontbrekende modellen aanvullen, behalve als --refresh is gezet
            if not args.refresh and p.get("model"):
                continue
            total += 1
            new_model = detect_model_for_item(p)
            old_model = p.get("model")
            if old_model != new_model:
                p["model"] = new_model
                updated += 1
            # Extra annotatie: documentsoort (bijlage-2) indien herkend
            try:
                kind = detect_doc_kind(p)
                if kind:
                    p["doc_kind"] = kind
            except Exception:
                pass
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
