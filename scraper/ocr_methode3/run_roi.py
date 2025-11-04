#!/usr/bin/env python3
import json
import re
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple

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


def _cache_for(pdf_path: Path) -> Path:
    d = CACHE_DIR / pdf_path.stem
    d.mkdir(parents=True, exist_ok=True)
    return d


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


def _tsv_cache_path(image_path: Path, kind: str) -> Path:
    return image_path.with_name(f"{kind}-" + image_path.name.replace('page-','') + '.tsv')


def tsv_lines(image_path: Path) -> List[Dict]:
    cache = _tsv_cache_path(image_path, 'lines')
    if cache.exists() and cache.stat().st_size > 0:
        content = cache.read_text(encoding='utf-8', errors='ignore')
    else:
        cp = run(['tesseract', str(image_path), 'stdout', '-l', 'nld+eng', 'tsv', '--psm', '6'])
        if cp.returncode != 0:
            return []
        content = cp.stdout
        cache.write_text(content, encoding='utf-8')
    header = None
    lines: Dict[tuple, Dict] = {}
    for i, row in enumerate(content.splitlines()):
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


def tsv_digits(image_path: Path) -> List[Dict]:
    cache = _tsv_cache_path(image_path, 'digits')
    if cache.exists() and cache.stat().st_size > 0:
        content = cache.read_text(encoding='utf-8', errors='ignore')
    else:
        cp = run(['tesseract', str(image_path), 'stdout', 'tsv', '--psm', '6', '-l', 'eng', '-c', 'tessedit_char_whitelist=0123456789'])
        if cp.returncode != 0:
            return []
        content = cp.stdout
        cache.write_text(content, encoding='utf-8')
    header = None
    words: List[Dict] = []
    for i, row in enumerate(content.splitlines()):
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
        if level != 5:
            continue
        text = (rec.get('text') or '').strip()
        if not text or not re.fullmatch(r'\d+', text):
            continue
        try:
            left = int(rec.get('left','0')); top = int(rec.get('top','0'))
            width = int(rec.get('width','0')); height = int(rec.get('height','0'))
        except Exception:
            continue
        words.append({'text': text, 'left': left, 'top': top, 'right': left+width, 'bottom': top+height})
    return words


def _digits_right_of_line(ln: Dict, digits_words: List[Dict], min_right: int, y_tol: int = 4) -> Optional[str]:
    y0 = ln['top'] - y_tol
    y1 = ln['bottom'] + y_tol
    parts: List[Tuple[int,str]] = []
    for w in digits_words:
        if w['left'] >= min_right and not (w['bottom'] < y0 or w['top'] > y1):
            parts.append((w['left'], w['text']))
    if not parts:
        return None
    parts.sort(key=lambda x: x[0])
    return ''.join(p for _,p in parts)


# --- Sidecar OCR fallback (fast and robust for p1/p2 header blocks) ---
def _run(cmd: List[str], timeout: int = 600) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=timeout)


def _ocr_sidecar_cached(pdf_path: Path) -> Tuple[str, str]:
    """Returns (sidecar_text, layout_text) using cache when available."""
    cdir = _cache_for(pdf_path)
    side_p = cdir / 'sidecar.txt'
    layout_p = cdir / 'layout.txt'
    if side_p.exists() and layout_p.exists():
        return (
            side_p.read_text(encoding='utf-8', errors='ignore'),
            layout_p.read_text(encoding='utf-8', errors='ignore')
        )
    with tempfile.TemporaryDirectory(prefix='sidecar_') as td:
        outpdf = Path(td) / 'out.pdf'
        side = Path(td) / 'sidecar.txt'
        cp = _run([
            'python', '-m', 'ocrmypdf', '--language', 'nld+eng+snum',
            '--force-ocr', '--optimize', '0', str(pdf_path), str(outpdf), '--sidecar', str(side)
        ], timeout=1800)
        if cp.returncode != 0:
            raise RuntimeError(f'ocrmypdf failed: {cp.stderr}')
        side_text = side.read_text(encoding='utf-8', errors='ignore')
        cp2 = _run(['pdftotext', '-layout', '-q', str(outpdf), '-'])
        layout_text = cp2.stdout if cp2.returncode == 0 else ''
    side_p.write_text(side_text, encoding='utf-8')
    layout_p.write_text(layout_text, encoding='utf-8')
    return side_text, layout_text


def _norm_digits(s: str) -> str:
    table = str.maketrans({
        'O': '0', 'o': '0', 'Q': '0', 'D': '0',
        'I': '1', 'l': '1', '|': '1', '!': '1',
        'Z': '2', 'z': '2',
        'S': '5', 's': '5', '§': '5',
        'B': '8',
    })
    s = (s or '').translate(table)
    return re.sub(r'[^0-9]', '', s)


def _take_tail_digits(line: str) -> Optional[str]:
    if '|' in line:
        tail = line.split('|')[-1].strip()
        d = _norm_digits(tail)
        return d or None
    if '=' in line:
        tail = line.split('=')[-1].strip()
        d = _norm_digits(tail)
        return d or None
    tokens = (line or '').strip().split()
    for tok in reversed(tokens):
        if len(tok) > 7:
            continue
        cleaned = _norm_digits(tok)
        if cleaned:
            return cleaned
    return None


def _find_value(lines: List[str], label: str, window: int = 2) -> Optional[str]:
    for i, ln in enumerate(lines):
        if label in ln:
            v = _take_tail_digits(ln)
            if v:
                return v
            for j in range(1, window + 1):
                if i + j < len(lines):
                    v = _take_tail_digits(lines[i + j])
                    if v:
                        return v
    return None


def _extract_headers(merged_text: str) -> Dict[str, Optional[str]]:
    lines = merged_text.splitlines()
    out: Dict[str, Optional[str]] = {k: None for k in ('A','B','C','D','E','F','G','H')}
    out['A'] = _find_value(lines, 'Aantal geldige stempassen')
    out['B'] = _find_value(lines, 'Aantal geldige volmachtbewijzen')
    out['C'] = _find_value(lines, 'Aantal geldige kiezerspassen')
    out['D'] = _find_value(lines, 'Totaal aantal toegelaten kiezers')
    out['E'] = _find_value(lines, 'Aantal stembiljetten met een geldige stem')
    out['F'] = _find_value(lines, 'Aantal blanco stembiljetten')
    out['G'] = _find_value(lines, 'Aantal ongeldige stembiljetten')
    out['H'] = _find_value(lines, 'Totaal aantal uitgebrachte stemmen')
    return out


def _extract_retally(merged_text: str) -> Dict[str, Optional[str]]:
    lines = merged_text.splitlines()
    out: Dict[str, Optional[str]] = {k: None for k in ('A2','B2','C2','D2')}
    def find_after_token(token: str) -> Optional[str]:
        for idx, ln in enumerate(lines):
            if token in ln:
                v = _take_tail_digits(ln)
                if v:
                    return v
                for j in range(1,3):
                    if idx+j < len(lines):
                        nxt = lines[idx+j]
                        v = _take_tail_digits(nxt)
                        if v:
                            return v
        return None
    out['A2'] = find_after_token('A2')
    out['B2'] = find_after_token('B2')
    out['C2'] = find_after_token('C2')
    out['D2'] = find_after_token('D.2') or find_after_token('D2')
    return out


def _extract_header_info(merged_text: str) -> Dict[str, Optional[str]]:
    out: Dict[str, Optional[str]] = {'stembureau_nummer': None, 'stembureau_naam': None}
    m = re.search(r'Nummer\s+stembureau\s*:?\s*([0-9OIl|!]+)', merged_text)
    if m:
        s = m.group(1)
        s = s.replace('O','0').replace('I','1').replace('l','1').replace('|','1').replace('!','1')
        out['stembureau_nummer'] = s
    else:
        m2 = re.search(r'Nummer\s+stembureau\s*:?\s*(.+)', merged_text)
        if m2:
            out['stembureau_nummer'] = m2.group(1).strip()
    m3 = re.search(r'Locatie\s+stembureau(?:\s*\([^)]*\))?\s*(.+)', merged_text)
    if m3:
        out['stembureau_naam'] = m3.group(1).strip()
    return out


def extract_from_sidecar(pdf_path: Path) -> Dict[str, Optional[str]]:
    side, layout = _ocr_sidecar_cached(pdf_path)
    merged = side + '\n' + layout
    hdr = _extract_headers(merged)
    rtl = _extract_retally(merged)
    inf = _extract_header_info(merged)
    out = {}
    out.update(hdr)
    out.update(rtl)
    out.update(inf)
    return out


def extract_page_labels_hybrid(pdf_path: Path, sjabl: Dict) -> Dict[str, str]:
    """Find labels via TSV on the scan using sjabloon.json label texts, then OCR ROI to the right."""
    dpi = 400
    pages = render_pages_cached(pdf_path, dpi)
    results: Dict[str, str] = {}
    # Page 1
    if len(pages) >= 1:
        img = Image.open(pages[0])
        L = tsv_lines(pages[0])
        D = tsv_digits(pages[0])
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
                    # Try digits/text via TSV first (for nummer), then ROI OCR as fallback
                    if name == 'stembureau_nummer':
                        dig = _digits_right_of_line(ln, D, ln['right']+8)
                        if dig:
                            results[name] = dig
                            break
                    # ROI to the right of this line (text OCR)
                    y0, y1 = ln['top'], ln['bottom']
                    x0 = ln['right'] + 8
                    box = (max(0, x0), max(0, y0 - 3), W - 8, y1 + 3)
                    crop = img.crop(box)
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
                    # Prefer TSV digits right of label; fallback to ROI OCR
                    val = _digits_right_of_line(ln, D, ln['right']+8)
                    if not val:
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
        D = tsv_digits(pages[1])
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
                    val = _digits_right_of_line(ln, D, ln['right']+8)
                    if not val:
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
    # Sidecar fallback for any missing header/p1/p2 values
    try:
        side_vals = extract_from_sidecar(PDF_PATH)
    except Exception as e:
        side_vals = {}
    pages = extract_candidates_via_column(PDF_PATH, coords)
    out = {
        'bron_pdf': str(PDF_PATH),
        'kop': {
            'gemeente': {'label': sjabl.get('kop',{}).get('gemeente',{}).get('label','Gemeente'), 'waarde':'TBD','waarde_bron':'handgeschreven'},
            'stembureau_nummer': {'label': sjabl.get('kop',{}).get('stembureau_nummer',{}).get('label','Nummer stembureau'), 'waarde': (side_vals.get('stembureau_nummer') or values.get('stembureau_nummer') or 'TBD'), 'waarde_bron':'handgeschreven'},
            'stembureau_naam': {'label': sjabl.get('kop',{}).get('stembureau_naam',{}).get('label','Locatie stembureau'), 'waarde': (side_vals.get('stembureau_naam') or values.get('stembureau_naam') or 'TBD'), 'waarde_bron':'handgeschreven'},
        },
        'pagina_1': {
            'toegelaten_kiezers': {k:{'label': sjabl.get('pagina_1',{}).get('toegelaten_kiezers',{}).get(k,{}).get('label',k), 'waarde':(values.get(k) or side_vals.get(k) or 'TBD'),'waarde_bron':'handgeschreven'} for k in ('A','B','C','D')},
            'uitgebrachte_stemmen': {k:{'label': sjabl.get('pagina_1',{}).get('uitgebrachte_stemmen',{}).get(k,{}).get('label',k), 'waarde':(values.get(k) or side_vals.get(k) or 'TBD'),'waarde_bron':'handgeschreven'} for k in ('E','F','G','H')},
        },
        'pagina_2': {
            'verschil_toegelaten_vs_uitgebrachte': {
                'keuze': {'label':'Is er een verschil (Nee/Ja ...)','waarde':'TBD','waarde_bron':'handgeschreven'},
                'hertelling': {k:{'label': sjabl.get('pagina_2',{}).get('verschil_toegelaten_vs_uitgebrachte',{}).get('hertelling',{}).get(k,{}).get('label',k), 'waarde':(values.get(k) or side_vals.get(k) or 'TBD'),'waarde_bron':'handgeschreven'} for k in ('A2','B2','C2','D2')}
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
