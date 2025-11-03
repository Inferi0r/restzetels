#!/usr/bin/env python3
import json
import re
from pathlib import Path
import pdfplumber


TEMPLATE_PDF = Path('modellen/Model+Na+31-2+correctie.pdf')
OUT_JSON = Path('ocr_methode3/sjabloon_coords.na31-2.json')


def norm(s: str) -> str:
    return re.sub(r"\s+", " ", (s or '').strip().lower())


LABELS_P1 = {
    'A': 'Aantal geldige stempassen',
    'B': 'Aantal geldige volmachtbewijzen',
    'C': 'Aantal geldige kiezerspassen',
    'D': 'Totaal aantal toegelaten kiezers',
    'E': 'Aantal stembiljetten met een geldige stem',
    'F': 'Aantal blanco stembiljetten',
    'G': 'Aantal ongeldige stembiljetten',
    'H': 'Totaal aantal uitgebrachte stemmen',
}

LABELS_P2 = {
    'A2': 'Aantal geldige stempassen',
    'B2': 'Aantal geldige volmachtbewijzen',
    'C2': 'Aantal geldige kiezerspassen',
    'D2': 'Totaal aantal toegelaten kiezers',
}


def find_label_right_roi(page, label_text: str):
    words = page.extract_words(use_text_flow=True)
    target = norm(label_text)
    # scan sliding window of 8 words to find phrase
    for i in range(len(words)):
        phrase = norm(' '.join(w['text'] for w in words[i:i+8]))
        if target in phrase:
            x1 = max(w['x1'] for w in words[i:i+8])
            top = min(w['top'] for w in words[i:i+8])
            bottom = max(w['bottom'] for w in words[i:i+8])
            # ROI to the right of label until near right margin
            return [x1 + 8, top - 4, page.width - 12, bottom + 6]
    return None


def build_coords(pdf_path: Path):
    out = {
        'dpi': 400,
        'pages': {}
    }
    with pdfplumber.open(str(pdf_path)) as pdf:
        # Page indices are 0-based
        # Page 1
        if len(pdf.pages) >= 1:
            p1 = pdf.pages[0]
            page_items = []
            # Header fields
            header_labels = {
                'stembureau_nummer': 'Nummer stembureau',
                'stembureau_naam': 'Locatie stembureau',
            }
            for name, lab in header_labels.items():
                roi = find_label_right_roi(p1, lab)
                if roi:
                    # Extend ROI width for longer values
                    roi = [roi[0], roi[1]-2, p1.width-8, roi[3]+2]
                    page_items.append({'name': name, 'type': 'text', 'roi_pdf': roi})
            for k, lab in LABELS_P1.items():
                roi = find_label_right_roi(p1, lab)
                if roi:
                    # Slightly enlarge ROI vertically and to right
                    roi = [roi[0], roi[1]-2, p1.width-8, roi[3]+2]
                    page_items.append({'name': k, 'type': 'digits', 'roi_pdf': roi})
            out['pages']['1'] = page_items
        # Page 2 (hertelling)
        if len(pdf.pages) >= 2:
            p2 = pdf.pages[1]
            page_items = []
            for k, lab in LABELS_P2.items():
                roi = find_label_right_roi(p2, lab)
                if roi:
                    roi = [roi[0], roi[1]-2, p2.width-8, roi[3]+2]
                    page_items.append({'name': k, 'type': 'digits', 'roi_pdf': roi})
            out['pages']['2'] = page_items
        # Candidate pages: define right column band (x band)
        for idx in range(2, len(pdf.pages)):
            page = pdf.pages[idx]
            # band: begin rond 62% van breedte (kolom met cijfers)
            x0 = page.width * 0.62
            x1 = page.width - 8
            out['pages'][str(idx+1)] = [{'name': 'right_column', 'type': 'digits_column', 'x0_pdf': x0, 'x1_pdf': x1}]
    return out


def main():
    if not TEMPLATE_PDF.exists():
        print(f"Template not found: {TEMPLATE_PDF}")
        return 1
    coords = build_coords(TEMPLATE_PDF)
    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(coords, ensure_ascii=False, indent=2), encoding='utf-8')
    print(OUT_JSON)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
