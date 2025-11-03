#!/usr/bin/env python3
import json
import re
import subprocess
import time
from pathlib import Path
from typing import Dict, List, Optional

import pdfplumber
from PIL import Image, ImageOps, ImageFilter


PDF_PATH = Path('pdfs/Aalsmeer/2-aal-vzod.pdf')
COORDS_PATH = Path('ocr_methode3/sjabloon_coords.na31-2.json')
SJABL_PATH = Path('ocr_methode3/sjabloon.json')
OUT_JSON = Path('ocr_methode3/2-aal-vzod.json')
CACHE_DIR = Path('ocr_methode3/cache')


def run(cmd: List[str]) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)


def render_pages_cached(pdf_path: Path, dpi: int) -> List[Path]:
    cdir = CACHE_DIR / pdf_path.stem
    cdir.mkdir(parents=True, exist_ok=True)
    pages = sorted(cdir.glob('page-*.png'), key=lambda p: int(re.search(r'(\d+)', p.stem).group(1)))
    if pages:
        return pages
    prefix = cdir / 'page'
    cp = run(['pdftoppm', '-png', '-r', str(dpi), str(pdf_path), str(prefix)])
    if cp.returncode != 0:
        raise RuntimeError(f'pdftoppm failed: {cp.stderr}')
    return sorted(cdir.glob('page-*.png'), key=lambda p: int(re.search(r'(\d+)', p.stem).group(1)))


def ocr_digits(im: Image.Image) -> Optional[str]:
    from pytesseract import image_to_string
    g = ImageOps.grayscale(im)
    g = ImageOps.autocontrast(g)
    g = g.filter(ImageFilter.SHARPEN)
    # Try multiple preprocessing thresholds
    for cfg in (
        '--psm 7 -l eng -c tessedit_char_whitelist=0123456789',
        '--psm 6 -l eng -c tessedit_char_whitelist=0123456789',
    ):
        txt = image_to_string(g, config=cfg).strip()
        m = re.search(r'(\d+)', txt)
        if m:
            return m.group(1)
        # try simple thresholding
        for thr in (160, 190, 210):
            b = g.point(lambda p: 255 if p > thr else 0)
            b = b.filter(ImageFilter.SHARPEN)
            txt = image_to_string(b, config=cfg).strip()
            m = re.search(r'(\d+)', txt)
            if m:
                return m.group(1)
    return None


def extract_page_labels_via_roi(pdf_path: Path, coords: Dict) -> Dict[str, str]:
    dpi = coords.get('dpi', 400)
    pages = render_pages_cached(pdf_path, dpi)
    results: Dict[str, str] = {}
    # Pages 1 and 2
    for page_no in ('1', '2'):
        fields = coords.get('pages', {}).get(page_no) or []
        if not fields:
            continue
        idx = int(page_no) - 1
        if idx >= len(pages):
            continue
        im = Image.open(pages[idx])
        # pixel scaling: pdf points at 72 dpi; rendered at dpi
        with pdfplumber.open(str(pdf_path)) as pdf:
            page = pdf.pages[idx]
            scale_x = im.width / page.width
            scale_y = im.height / page.height
        for f in fields:
            if f.get('type') == 'digits':
                x0,y0,x1,y1 = f['roi_pdf']
                box = (int(x0*scale_x), int(y0*scale_y), int(x1*scale_x), int(y1*scale_y))
                crop = im.crop(box)
                val = ocr_digits(crop)
                if val:
                    results[f['name']] = val
            elif f.get('type') == 'text':
                # header free-text
                x0,y0,x1,y1 = f['roi_pdf']
                box = (int(x0*scale_x), int(y0*scale_y), int(x1*scale_x), int(y1*scale_y))
                crop = im.crop(box)
                from pytesseract import image_to_string
                timg = ImageOps.grayscale(crop)
                timg = ImageOps.autocontrast(timg)
                ttxt = image_to_string(timg, config='--psm 7 -l nld+eng').strip()
                if not ttxt:
                    ttxt = image_to_string(timg, config='--psm 6 -l nld+eng').strip()
                if ttxt:
                    results[f['name']] = ttxt
    return results


def is_candidate_line(text: str) -> bool:
    t = (text or '').strip()
    low = t.lower()
    if not t:
        return False
    if low.startswith('naam kandidaat'):
        return False
    if low.startswith('vervolg:'):
        return False
    if low.startswith('zet in elk vakje'):
        return False
    if low.startswith('subtotaal') or low.startswith('totaal'):
        return False
    if re.match(r'^lijst\s+\d+\s*-', t):
        return False
    return (',' in t) and ('(' in t) and (')' in t)


def tsv_lines(image_path: Path) -> List[Dict]:
    cp = run(['tesseract', str(image_path), 'stdout', '-l', 'nld+eng', 'tsv', '--psm', '6'])
    if cp.returncode != 0:
        return []
    header = None
    lines: Dict[tuple, Dict] = {}
    for i, row in enumerate(cp.stdout.splitlines()):
        if i == 0:
            header = row.split('\t')
            continue
        cols = row.split('\t')
        if not header or len(cols) != len(header):
            continue
        rec = dict(zip(header, cols))
        try:
            level = int(rec.get('level','0'))
        except Exception:
            continue
        if level not in (4,5):
            continue
        page = int(rec.get('page_num','1'))
        block = int(rec.get('block_num','0'))
        par = int(rec.get('par_num','0'))
        ln = int(rec.get('line_num','0'))
        left = int(rec.get('left','0'))
        top = int(rec.get('top','0'))
        width = int(rec.get('width','0'))
        height = int(rec.get('height','0'))
        text = (rec.get('text') or '').strip()
        key = (page, block, par, ln)
        if level == 4:
            lines[key] = {'top': top, 'bottom': top+height, 'left': left, 'right': left+width, 'text': text}
        elif level == 5:
            if key not in lines:
                lines[key] = {'top': top, 'bottom': top+height, 'left': left, 'right': left+width, 'text': ''}
            if text:
                if lines[key]['text']:
                    lines[key]['text'] += ' ' + text
                else:
                    lines[key]['text'] = text
    return [v for v in lines.values() if v.get('text')]


def extract_page_labels_hybrid(pdf_path: Path, sjabl: Dict) -> Dict[str, str]:
    """Find labels via TSV on the scan using sjabloon.json label texts, then OCR ROI to the right."""
    dpi = 400
    pages = render_pages_cached(pdf_path, dpi)
    results: Dict[str, str] = {}
    # Page 1
    if len(pages) >= 1:
        img = Image.open(pages[0])
        L = tsv_lines(pages[0])
        W, H = img.size
        # Header
        kop = sjabl.get('kop', {})
        header_labels = {
            'stembureau_nummer': kop.get('stembureau_nummer', {}).get('label', ''),
            'stembureau_naam': kop.get('stembureau_naam', {}).get('label', ''),
        }
        for name, lab in header_labels.items():
            if not lab:
                continue
            lab_low = lab.lower()
            for ln in L:
                if lab_low in ln['text'].lower():
                    # ROI to the right of this line
                    y0, y1 = ln['top'], ln['bottom']
                    x0 = ln['right'] + 8
                    box = (max(0, x0), max(0, y0 - 3), W - 8, y1 + 3)
                    crop = img.crop(box)
                    # text OCR
                    from pytesseract import image_to_string
                    timg = ImageOps.grayscale(crop)
                    timg = ImageOps.autocontrast(timg)
                    ttxt = image_to_string(timg, config='--psm 7 -l nld+eng').strip()
                    if not ttxt:
                        ttxt = image_to_string(timg, config='--psm 6 -l nld+eng').strip()
                    if ttxt:
                        results[name] = ttxt
                    break
        # A..H
        p1 = sjabl.get('pagina_1', {})
        lab_map = {}
        for k in ('A','B','C','D'):
            v = (p1.get('toegelaten_kiezers', {}).get(k, {}) or {}).get('label')
            if v:
                lab_map[k] = v
        for k in ('E','F','G','H'):
            v = (p1.get('uitgebrachte_stemmen', {}).get(k, {}) or {}).get('label')
            if v:
                lab_map[k] = v
        for key, lab in lab_map.items():
            lab_low = lab.lower()
            for ln in L:
                if lab_low in ln['text'].lower():
                    y0, y1 = ln['top'], ln['bottom']
                    x0 = ln['right'] + 8
                    box = (max(0, x0), max(0, y0 - 3), W - 8, y1 + 3)
                    crop = img.crop(box)
                    val = ocr_digits(crop)
                    if val:
                        results[key] = val
                    break
    # Page 2 (A2..D2)
    if len(pages) >= 2:
        img = Image.open(pages[1])
        L = tsv_lines(pages[1])
        W, H = img.size
        p2 = sjabl.get('pagina_2', {}).get('verschil_toegelaten_vs_uitgebrachte', {}).get('hertelling', {})
        lab_map = {}
        for k in ('A2','B2','C2','D2'):
            v = (p2.get(k) or {}).get('label')
            if v:
                lab_map[k] = v
        for key, lab in lab_map.items():
            lab_low = lab.lower()
            for ln in L:
                if lab_low in ln['text'].lower():
                    y0, y1 = ln['top'], ln['bottom']
                    x0 = ln['right'] + 8
                    box = (max(0, x0), max(0, y0 - 3), W - 8, y1 + 3)
                    crop = img.crop(box)
                    val = ocr_digits(crop)
                    if val:
                        results[key] = val
                    break
    return results
def extract_candidates_via_column(pdf_path: Path, coords: Dict) -> List[Dict]:
    dpi = coords.get('dpi', 400)
    pages = render_pages_cached(pdf_path, dpi)
    out_pages: List[Dict] = []
    for idx in range(2, len(pages)):
        page_no = str(idx+1)
        items = coords.get('pages', {}).get(page_no) or []
        band = next((it for it in items if it.get('type')=='digits_column'), None)
        if not band:
            continue
        im = Image.open(pages[idx])
        with pdfplumber.open(str(pdf_path)) as pdf:
            page = pdf.pages[idx]
            scale_x = im.width / page.width
            scale_y = im.height / page.height
        x0 = int(band['x0_pdf']*scale_x)
        x1 = int(band['x1_pdf']*scale_x)
        lines = tsv_lines(pages[idx])
        lijsten: List[Dict] = []
        current = None
        for ln in lines:
            text = ln['text']
            low = text.lower().strip()
            if low.startswith('lijst '):
                if current:
                    out = current.copy()
                    lijsten.append(out)
                # try to grab list number and party name
                m = re.match(r"lijst\s+(\d+)\s*-\s*(.+)", text, re.I)
                lst_no = int(m.group(1)) if m else None
                party = m.group(2).strip() if m else text
                current = {
                    'lijstnummer': {'label':'Lijstnummer','waarde_bron':'sjabloon','waarde': lst_no},
                    'partijnaam': {'label':'Partijnaam','waarde_bron':'sjabloon','waarde': party},
                    'subtotaal_links': {'label':'Subtotaal links','waarde_bron':'handgeschreven','waarde':'leeg'},
                    'subtotaal_rechts': {'label':'Subtotaal rechts','waarde_bron':'handgeschreven','waarde':'leeg'},
                    'totaal_lijst': {'label':'Totaal lijst','waarde_bron':'handgeschreven','waarde':'leeg'},
                    'kandidaten': []
                }
                continue
            if low.startswith('subtotaal'):
                y0 = int(ln['top']*scale_y)
                y1 = int(ln['bottom']*scale_y)
                crop = im.crop((x0, y0-3, x1, y1+3))
                v = ocr_digits(crop)
                if v is None:
                    v = 'onleesbaar'
                # assign as links if first, anders rechts
                if current['subtotaal_links']['waarde'] in ('leeg','onleesbaar'):
                    current['subtotaal_links']['waarde']= v
                else:
                    current['subtotaal_rechts']['waarde']= v
                continue
            if low.startswith('totaal'):
                y0 = int(ln['top']*scale_y)
                y1 = int(ln['bottom']*scale_y)
                crop = im.crop((x0, y0-3, x1, y1+3))
                v = ocr_digits(crop)
                current['totaal_lijst']['waarde'] = v if v is not None else 'onleesbaar'
                continue
            if is_candidate_line(text):
                # OCR digits to the right band aligned with this line
                y0 = int(ln['top']*scale_y)
                y1 = int(ln['bottom']*scale_y)
                crop = im.crop((x0, y0-3, x1, y1+3))
                v = ocr_digits(crop)
                current['kandidaten'].append({
                    'kandidaatnummer': {'label':'Kandidaatnummer','waarde_bron':'sjabloon','waarde':'leeg'},
                    'kandidaatnaam': {'label':'Kandidaatnaam','waarde_bron':'sjabloon','waarde': text},
                    'stemmen': {'label':'Stemmen','waarde_bron':'handgeschreven','waarde': (v if v is not None else 'leeg')}
                })
        if current:
            lijsten.append(current)
        if lijsten:
            out_pages.append({'pagina': int(page_no), 'lijsten': lijsten})
    return out_pages


def main():
    t0=time.time()
    coords = json.loads(COORDS_PATH.read_text(encoding='utf-8'))
    sjabl = json.loads(SJABL_PATH.read_text(encoding='utf-8'))
    # Hybrid: find labels on scan via TSV with sjabloon labels, then ROI OCR to the right
    values = extract_page_labels_hybrid(PDF_PATH, sjabl)
    pages = extract_candidates_via_column(PDF_PATH, coords)
    out = {
        'bron_pdf': str(PDF_PATH),
        'kop': {
            'gemeente': {'label': sjabl.get('kop',{}).get('gemeente',{}).get('label','Gemeente'), 'waarde':'TBD','waarde_bron':'handgeschreven'},
            'stembureau_nummer': {'label': sjabl.get('kop',{}).get('stembureau_nummer',{}).get('label','Nummer stembureau'), 'waarde': values.get('stembureau_nummer','TBD'), 'waarde_bron':'handgeschreven'},
            'stembureau_naam': {'label': sjabl.get('kop',{}).get('stembureau_naam',{}).get('label','Locatie stembureau'), 'waarde': values.get('stembureau_naam','TBD'), 'waarde_bron':'handgeschreven'},
        },
        'pagina_1': {
            'toegelaten_kiezers': {k:{'label': sjabl.get('pagina_1',{}).get('toegelaten_kiezers',{}).get(k,{}).get('label',k), 'waarde':values.get(k,'TBD'),'waarde_bron':'handgeschreven'} for k in ('A','B','C','D')},
            'uitgebrachte_stemmen': {k:{'label': sjabl.get('pagina_1',{}).get('uitgebrachte_stemmen',{}).get(k,{}).get('label',k), 'waarde':values.get(k,'TBD'),'waarde_bron':'handgeschreven'} for k in ('E','F','G','H')},
        },
        'pagina_2': {
            'verschil_toegelaten_vs_uitgebrachte': {
                'keuze': {'label':'Is er een verschil (Nee/Ja ...)','waarde':'TBD','waarde_bron':'handgeschreven'},
                'hertelling': {k:{'label': sjabl.get('pagina_2',{}).get('verschil_toegelaten_vs_uitgebrachte',{}).get('hertelling',{}).get(k,{}).get('label',k), 'waarde':values.get(k,'TBD'),'waarde_bron':'handgeschreven'} for k in ('A2','B2','C2','D2')}
            }
        },
        'paginas': pages,
    }
    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding='utf-8')
    t1=time.time()
    print(OUT_JSON)
    print(f'Elapsed: {t1-t0:.2f}s')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
