#!/usr/bin/env python3
import argparse
import json
import os
import re
import shlex
import subprocess
import sys
from pathlib import Path


def run(cmd, cwd=None, timeout=600):
    """Run a shell command and return (code, stdout, stderr)."""
    proc = subprocess.run(
        cmd,
        cwd=cwd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=timeout,
    )
    return proc.returncode, proc.stdout, proc.stderr


def ocr_sidecar(pdf_path: Path, sidecar_path: Path, lang: str = "nld+eng") -> Path:
    """Generate OCR sidecar text for a PDF using ocrmypdf. Caches by sidecar_path."""
    sidecar_path.parent.mkdir(parents=True, exist_ok=True)
    if sidecar_path.exists() and sidecar_path.stat().st_size > 0:
        return sidecar_path

    # We use --skip-text so we only OCR areas without an existing text layer.
    # Note: For volledig gescande PDF's wordt de hele pagina ge-OCR'd (incl. gedrukte tekst).
    output_pdf = sidecar_path.with_suffix(".pdf")
    cmd = [
        "ocrmypdf",
        "-l",
        lang,
        "--skip-text",
        "--sidecar",
        str(sidecar_path),
        str(pdf_path),
        str(output_pdf),
    ]
    code, out, err = run(cmd, timeout=1200)
    if code != 0:
        # Cleanup incomplete artifacts
        try:
            if output_pdf.exists():
                output_pdf.unlink()
        except Exception:
            pass
        raise RuntimeError(f"ocrmypdf failed for {pdf_path}: {err}\n{out}")

    # We don't keep the OCR'd PDF for now; the sidecar is what we need.
    try:
        if output_pdf.exists():
            output_pdf.unlink()
    except Exception:
        pass

    return sidecar_path


def extract_municipality(text: str) -> str | None:
    # Example: line starting with: "Gemeente Aa en Hunze — Kieskring 3 (Assen)"
    m = re.search(r"(?m)^\s*Gemeente\s+(.+?)\s+[—-]\s*Kieskring", text, flags=re.IGNORECASE)
    if m:
        return m.group(1).strip()
    # Fallback: line-only 'Gemeente <naam>'
    m = re.search(r"(?m)^\s*Gemeente\s+([A-Za-zÀ-ÿ .\-'()]+)\s*$", text, flags=re.IGNORECASE)
    if m:
        return m.group(1).strip()
    return None


def _clean_station_name(name: str) -> str:
    # Remove trailing page fraction artifacts like "1 / 29", "12129", "1 ! 29", "7/29" etc.
    name = re.sub(r"\s+\d+\s*[/!|Il¹]?\s*\d+\s*$", "", name)
    return name.strip()


def extract_station_line(text: str) -> tuple[int | None, str | None]:
    # Look for lines like: "Stembureau: 17. Dorpshuis Annen 2 1/10"
    # Be robust to OCR noise around separators
    for line in text.splitlines():
        if "Stembureau" in line:
            # normalize whitespace
            s = " ".join(line.split())
            # Accept with or without colon, page fraction may have spaces around '/'
            m = re.search(r"Stembureau\s*:?\s*(\d+)\.?\s+(.+?)\s+\d+\s*\/\s*\d+", s, flags=re.IGNORECASE)
            if m:
                try:
                    num = int(m.group(1))
                except Exception:
                    num = None
                name = _clean_station_name(m.group(2).strip())
                return num, name
            # if page fraction not present
            m = re.search(r"Stembureau\s*:?\s*(\d+)\.?\s+(.+)$", s, flags=re.IGNORECASE)
            if m:
                try:
                    num = int(m.group(1))
                except Exception:
                    num = None
                name = _clean_station_name(m.group(2).strip())
                return num, name
    return None, None


def extract_station_from_bijlage2(text: str) -> tuple[int | None, str | None]:
    """Extract from Model Na31-2 Bijlage 2 format.
    Looks for 'Nummer stembureau <n>' and 'Locatie stembureau ... <name>'.
    """
    num = None
    name = None
    # Nummer stembureau 8
    m = re.search(r"(?mi)^\s*Nummer\s+stembureau\s*:?\s*(\d+)\b", text)
    if m:
        try:
            num = int(m.group(1))
        except Exception:
            num = None
    # Locatie stembureau (..).. <name>
    # Accept the line and take the last chunk after the closing parenthesis or after the label
    for line in text.splitlines():
        if re.search(r"Locatie\s+stembureau", line, flags=re.IGNORECASE):
            m2 = re.search(r"Locatie\s+stembureau(?:\s*\([^)]*\))?\s*(.+)", line, flags=re.IGNORECASE)
            if m2:
                s = m2.group(1).strip()
                if s:
                    name = s
                    break
    return num, name


def extract_staff_block(text: str) -> dict:
    """Extract handwritten names from section 2 (Aanwezigheid stembureauleden).

    Heuristic: capture lines between the header '2. Aanwezigheid stembureauleden'
    and the next section '3' or '3.'. Then from those lines, try to parse name-like tokens.
    Returns a dict with array of raw lines and a list of probable lastnames.
    """
    start = None
    end = None
    lines = text.splitlines()
    for i, line in enumerate(lines):
        if re.search(r"\b2\.?\s*Aanwezigheid stembureauleden", line, flags=re.IGNORECASE):
            start = i + 1
            continue
        if start is not None and re.search(r"\b3\b|\b3\.", line):
            end = i
            break
    if start is None:
        return {"raw": [], "names": []}
    block = lines[start:end] if end is not None else lines[start:]

    # Clean and filter extremely short or header-like lines
    raw = [" ".join(l.split()) for l in block if l.strip()]

    # Extract probable names: sequences of letters (possibly with accents), capitalized.
    # Exclude common Dutch words seen in headers.
    candidates = []
    word_re = re.compile(r"[A-Za-zÀ-ÿ][A-Za-zÀ-ÿ'\-]{1,}")
    stop = set(
        w.lower()
        for w in [
            "Voorletters",
            "Achternaam",
            "Dag",
            "Maand",
            "Jaar",
            "Tijd",
            "van",
            "tot",
            "Aanwezig",
            "stembureau",
        ]
    )

    for l in raw:
        words = word_re.findall(l)
        # Heuristic: pick words that are capitalized and not stopwords
        for w in words:
            if w.lower() in stop:
                continue
            # likely a name if Titlecase and length > 1
            if w[0].isupper():
                candidates.append(w)

    # Deduplicate while preserving order
    seen = set()
    names = []
    for w in candidates:
        lw = w.lower()
        if lw not in seen:
            seen.add(lw)
            names.append(w)

    return {"raw": raw, "names": names}


def build_json(pdf_path: Path, sidecar_text: str, municipality_hint: str | None) -> dict:
    municipality = extract_municipality(sidecar_text) or municipality_hint
    num, name = extract_station_line(sidecar_text)
    # If name looks like a page fraction artifact (e.g., '1/32'), drop it
    if name is not None and re.fullmatch(r"\d+\s*[/!|Il¹]\s*\d+", name):
        name = None
    if num is None or name is None:
        n2, nm2 = extract_station_from_bijlage2(sidecar_text)
        if n2 is not None:
            num = n2
        if nm2 is not None:
            name = nm2

    staff = extract_staff_block(sidecar_text)

    # Detect template and parse additional sections if possible
    template = detect_template(sidecar_text)
    counts = parse_counts_na31(sidecar_text) if template == "Na31-2" else None
    difference = parse_difference_na31(sidecar_text) if template == "Na31-2" else None
    lists = parse_lists_na31(sidecar_text) if template == "Na31-2" else None

    data = {
        "file_path": str(pdf_path),
        "municipality": municipality,
        "polling_station_number": num,
        "polling_station_name": name,
        "template": template,
        "counts": counts,
        "difference_check": difference,
        "lists": lists,
        # Handwritten fields: start with stembureauleden block; add more parsers later
        "handwritten": {
            "Aanwezigheid stembureauleden": {
                "raw_lines": staff["raw"],
                "names": staff["names"],
            }
        },
    }
    return data


def municipality_from_path(pdf_path: Path) -> str | None:
    # Assume structure: <root>/<municipality>/<file>.pdf
    parts = pdf_path.parts
    if len(parts) >= 2:
        return parts[-2]
    return None


def detect_template(text: str) -> str | None:
    if "Bijlage 2: uitkomsten per stembureau" in text or "Model Na31-2" in text:
        return "Na31-2"
    if "Model N 10-2" in text:
        return "N10-2"
    return None


def _parse_trailing_ints(s: str) -> list[int]:
    vals: list[int] = []
    for m in re.finditer(r"([0-9][0-9 ]*[0-9]|\b[0-9]\b)", s):
        vals.append(int(m.group(0).replace(" ", "")))
    return vals


def _parse_last_int_or_none(s: str) -> int | None:
    vals = _parse_trailing_ints(s)
    return vals[-1] if vals else None


def parse_counts_na31(text: str) -> dict:
    counts = {
        "toegelaten_kiezers": {
            "A": {"label": "Aantal geldige stempassen", "value": None, "raw": None},
            "B": {"label": "Aantal geldige volmachtbewijzen (schriftelijk of via ingevulde stem- of kiezerspas)", "value": None, "raw": None},
            "C": {"label": "Aantal geldige kiezerspassen", "value": None, "raw": None},
            "D": {"label": "Totaal aantal toegelaten kiezers (A+B+C)", "value": None, "raw": None},
        },
        "uitgebrachte_stemmen": {
            "E": {"label": "Aantal stembiljetten met een geldige stem op een kandidaat", "value": None, "raw": None},
            "F": {"label": "Aantal blanco stembiljetten", "value": None, "raw": None},
            "G": {"label": "Aantal ongeldige stembiljetten", "value": None, "raw": None},
            "H": {"label": "Totaal aantal uitgebrachte stemmen (E+F+G)", "value": None, "raw": None},
        },
    }
    for line in text.splitlines():
        s = line.strip()
        sl = s.lower()
        if sl.startswith("aantal geldige stempassen") and "a" in sl:
            counts["toegelaten_kiezers"]["A"]["raw"] = s
            counts["toegelaten_kiezers"]["A"]["value"] = _parse_last_int_or_none(s)
        elif sl.startswith("aantal geldige volmachtbewijzen"):
            counts["toegelaten_kiezers"]["B"]["raw"] = s
            counts["toegelaten_kiezers"]["B"]["value"] = _parse_last_int_or_none(s)
        elif sl.startswith("aantal geldige kiezerspassen"):
            counts["toegelaten_kiezers"]["C"]["raw"] = s
            counts["toegelaten_kiezers"]["C"]["value"] = _parse_last_int_or_none(s)
        elif sl.startswith("totaal aantal toegelaten kiezers"):
            counts["toegelaten_kiezers"]["D"]["raw"] = s
            counts["toegelaten_kiezers"]["D"]["value"] = _parse_last_int_or_none(s)
        elif sl.startswith("aantal stembiljetten met een geldige stem"):
            counts["uitgebrachte_stemmen"]["E"]["raw"] = s
            counts["uitgebrachte_stemmen"]["E"]["value"] = _parse_last_int_or_none(s)
        elif sl.startswith("aantal blanco stembiljetten"):
            counts["uitgebrachte_stemmen"]["F"]["raw"] = s
            counts["uitgebrachte_stemmen"]["F"]["value"] = _parse_last_int_or_none(s)
        elif sl.startswith("aantal ongeldige stembiljetten"):
            counts["uitgebrachte_stemmen"]["G"]["raw"] = s
            counts["uitgebrachte_stemmen"]["G"]["value"] = _parse_last_int_or_none(s)
        elif sl.startswith("totaal aantal uitgebrachte stemmen"):
            counts["uitgebrachte_stemmen"]["H"]["raw"] = s
            counts["uitgebrachte_stemmen"]["H"]["value"] = _parse_last_int_or_none(s)
    return counts


def parse_difference_na31(text: str) -> dict:
    diff = {
        "options_raw": [],
        "selected_option": None,
        "retally": {
            "A2": {"label": "Aantal geldige stempassen (hertelling)", "value": None, "raw": None},
            "B2": {"label": "Aantal geldige volmachtbewijzen (hertelling)", "value": None, "raw": None},
            "C2": {"label": "Aantal geldige kiezerspassen (hertelling)", "value": None, "raw": None},
            "D2": {"label": "Totaal aantal toegelaten kiezers (hertelling)", "value": None, "raw": None},
        },
        "geen_verklaring_count": None,
    }
    for line in text.splitlines():
        s = line.strip()
        if re.search(r"Is er een verschil.*onderdeel H\) \?", s):
            diff["options_raw"].append(s)
        elif re.search(r"^\s*[o0dDyY].*Nee\.", s) or re.search(r"^\s*[o0dDyY].*Ja\.", s):
            diff["options_raw"].append(s)
        if s.lower().startswith("aantal geldige stempassen a2"):
            diff["retally"]["A2"]["raw"] = s
            diff["retally"]["A2"]["value"] = _parse_last_int_or_none(s)
        elif s.lower().startswith("aantal geldige volmachtbewijzen") and ("b2" in s.lower()):
            diff["retally"]["B2"]["raw"] = s
            diff["retally"]["B2"]["value"] = _parse_last_int_or_none(s)
        elif s.lower().startswith("aantal geldige kiezerspassen") and ("c2" in s.lower()):
            diff["retally"]["C2"]["raw"] = s
            diff["retally"]["C2"]["value"] = _parse_last_int_or_none(s)
        elif re.search(r"totaal aantal toegelaten kiezers.*(d\.?2|d2)\)?", s, flags=re.IGNORECASE):
            diff["retally"]["D2"]["raw"] = s
            diff["retally"]["D2"]["value"] = _parse_last_int_or_none(s)
        elif s.lower().startswith("hoe vaak is er geen verklaring"):
            diff["geen_verklaring_count"] = _parse_last_int_or_none(s)
    return diff


def parse_lists_na31(text: str) -> list[dict] | None:
    lines = text.splitlines()
    pages = []
    for i, l in enumerate(lines):
        m = re.search(r"\b(\d+)\s*/\s*(\d+)\b", l)
        if m:
            pages.append({"line": i, "page": int(m.group(1)), "of": int(m.group(2)), "raw": l.strip()})
    blocks = []
    for i, l in enumerate(lines):
        m = re.match(r"\s*Lijst\s+(\d+)\s*-\s*(.+)", l)
        if m:
            blocks.append({"start": i, "list_number": int(m.group(1)), "party_name": m.group(2).strip()})
    if not blocks:
        return None
    for idx in range(len(blocks)):
        start = blocks[idx]["start"]
        end = blocks[idx + 1]["start"] if idx + 1 < len(blocks) else len(lines)
        segment = lines[start:end]
        candidates: list[dict] = []
        subtotals: list[dict] = []
        total_value = None
        for j, raw in enumerate(segment):
            s = raw.strip()
            if not s:
                continue
            if s.lower().startswith("naam kandidaat") or s.lower().startswith("vervolg:"):
                continue
            if s.lower().startswith("subtotaal"):
                val = _parse_last_int_or_none(s)
                page = None
                for p in reversed(pages):
                    if start <= p["line"] <= (start + j):
                        page = p["page"]
                        break
                subtotals.append({"page": page, "value": val, "raw": s})
                continue
            if s.lower().startswith("totaal"):
                total_value = _parse_last_int_or_none(s)
                continue
            if re.match(r"^[A-Za-zÀ-ÿ].+", s) and len(s) < 120:
                candidates.append({"candidate_number": None, "candidate_name": s, "votes": None})
        blocks[idx]["candidates"] = candidates
        blocks[idx]["subtotals"] = subtotals
        blocks[idx]["total"] = total_value
    return [
        {
            "list_number": b["list_number"],
            "party_name": b["party_name"],
            "candidates": b.get("candidates", []),
            "subtotals": b.get("subtotals", []),
            "total": b.get("total", None),
        }
        for b in blocks
    ]


def pdftotext_extract(pdf_path: Path) -> str:
    """Extract text layer via pdftotext if available."""
    cmd = [
        "pdftotext",
        "-layout",
        "-enc",
        "UTF-8",
        "-nopgbrk",
        str(pdf_path),
        "-",
    ]
    code, out, err = run(cmd, timeout=120)
    if code == 0:
        return out
    return ""


def process_pdf(pdf_path: Path, out_root: Path, sidecar_root: Path) -> Path | None:
    try:
        rel = pdf_path.relative_to(Path.cwd())
    except Exception:
        rel = pdf_path
    sidecar_path = sidecar_root / rel.with_suffix(".txt")
    sidecar_path.parent.mkdir(parents=True, exist_ok=True)

    sidecar_text = ""
    try:
        ocr_sidecar(pdf_path, sidecar_path)
        sidecar_text = sidecar_path.read_text(encoding="utf-8", errors="ignore")
    except Exception as e:
        print(f"[WARN] OCR failed for {pdf_path}: {e}", file=sys.stderr)
        # continue with empty sidecar_text
        sidecar_text = ""

    # If sidecar is empty or contains only skip notice, fall back to pdftotext for printed fields
    printed_text = ""
    if not sidecar_text.strip() or sidecar_text.strip().startswith("[OCR skipped"):
        printed_text = pdftotext_extract(pdf_path)
    # Prefer sidecar for handwritten block parsing; for station/municipality, try both
    merged_for_headers = sidecar_text + "\n" + printed_text
    text_for_handwritten = sidecar_text

    muni_hint = municipality_from_path(pdf_path)
    data = build_json(pdf_path, merged_for_headers, muni_hint)
    # Replace handwritten block source with sidecar-only text to avoid printed noise in typed PDFs
    if text_for_handwritten:
        staff = extract_staff_block(text_for_handwritten)
        data["handwritten"]["Aanwezigheid stembureauleden"] = {
            "raw_lines": staff["raw"],
            "names": staff["names"],
        }

    out_path = out_root / rel.with_suffix(".json")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return out_path


def find_pdfs(paths: list[Path]) -> list[Path]:
    pdfs: list[Path] = []
    for base in paths:
        if base.is_file() and base.suffix.lower() == ".pdf":
            pdfs.append(base)
        elif base.is_dir():
            for root, _, files in os.walk(base):
                for fn in files:
                    if fn.lower().endswith(".pdf"):
                        pdfs.append(Path(root) / fn)
    return pdfs


def main(argv=None):
    p = argparse.ArgumentParser(description="Extract handwritten fields from PV PDFs into JSON")
    p.add_argument("inputs", nargs="*", default=["."], help="Directories or PDFs to process")
    p.add_argument("--out", dest="out", default="data/extracted", help="Output root for JSON")
    p.add_argument(
        "--sidecar-out", dest="sidecar", default="data/sidecar", help="Output root for OCR sidecars"
    )
    p.add_argument("--limit", type=int, default=0, help="Limit number of PDFs (0 = no limit)")
    args = p.parse_args(argv)

    paths = [Path(x) for x in args.inputs]
    pdfs = find_pdfs(paths)
    if args.limit:
        pdfs = pdfs[: args.limit]
    if not pdfs:
        print("No PDFs found in inputs", file=sys.stderr)
        return 2

    out_root = Path(args.out)
    sidecar_root = Path(args.sidecar)

    written = []
    for i, pdf in enumerate(pdfs, 1):
        print(f"[{i}/{len(pdfs)}] {pdf}")
        out_path = process_pdf(pdf, out_root, sidecar_root)
        if out_path:
            written.append(out_path)

    print(f"Done. Wrote {len(written)} JSON files under {out_root}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
