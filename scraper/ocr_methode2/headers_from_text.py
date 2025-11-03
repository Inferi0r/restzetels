#!/usr/bin/env python3
import argparse
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Optional, List, Dict


def run(cmd: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)


def ocr_texts(pdf: Path) -> tuple[str, str]:
    tmpdir = Path(tempfile.mkdtemp(prefix="hdrtxt_"))
    outpdf = tmpdir / "hdr_ocr.pdf"
    side = tmpdir / "hdr_sidecar.txt"
    cmd = [
        sys.executable, "-m", "ocrmypdf",
        "--language", "nld+eng+snum",
        "--force-ocr", "--optimize", "0",
        str(pdf), str(outpdf),
        "--sidecar", str(side),
    ]
    cp = run(cmd)
    if cp.returncode != 0:
        raise RuntimeError(f"ocrmypdf failed: {cp.stderr.strip()}")
    side_text = side.read_text(encoding="utf-8", errors="ignore")
    cp2 = run(["pdftotext", "-layout", "-q", str(outpdf), "-"])
    layout = cp2.stdout if cp2.returncode == 0 else ""
    return side_text, layout


def norm_digits(s: str) -> str:
    table = str.maketrans({
        "O": "0", "o": "0", "Q": "0", "D": "0",
        "I": "1", "l": "1", "|": "1", "!": "1",
        "Z": "2", "z": "2",
        "S": "5", "s": "5", "§": "5",
        "B": "8",
    })
    s = s.translate(table)
    return re.sub(r"[^0-9]", "", s)


def take_tail_digits(line: str) -> Optional[str]:
    if '|' in line:
        tail = line.split('|')[-1].strip()
        d = norm_digits(tail)
        return d or None
    if '=' in line:
        tail = line.split('=')[-1].strip()
        d = norm_digits(tail)
        return d or None
    tokens = line.strip().split()
    for tok in reversed(tokens):
        if len(tok) > 7:
            continue
        cleaned = norm_digits(tok)
        if cleaned:
            return cleaned
    return None


def find_value(lines: List[str], label: str, window: int = 2) -> Optional[str]:
    for i, ln in enumerate(lines):
        if label in ln:
            if ('|' in ln) or ('=' in ln):
                v = take_tail_digits(ln)
                if v:
                    return v
            for j in range(1, window + 1):
                if i + j < len(lines):
                    v = take_tail_digits(lines[i + j])
                    if v:
                        return v
    return None


def extract_headers(merged_text: str) -> Dict[str, Optional[str]]:
    lines = merged_text.splitlines()
    out: Dict[str, Optional[str]] = {k: None for k in ("A","B","C","D","E","F","G","H")}
    out["A"] = find_value(lines, "Aantal geldige stempassen")
    out["B"] = find_value(lines, "Aantal geldige volmachtbewijzen")
    out["C"] = find_value(lines, "Aantal geldige kiezerspassen")
    out["D"] = find_value(lines, "Totaal aantal toegelaten kiezers")
    out["E"] = find_value(lines, "Aantal stembiljetten met een geldige stem")
    out["F"] = find_value(lines, "Aantal blanco stembiljetten")
    out["G"] = find_value(lines, "Aantal ongeldige stembiljetten")
    out["H"] = find_value(lines, "Totaal aantal uitgebrachte stemmen")
    return out


def extract_retally(merged_text: str) -> Dict[str, Optional[str]]:
    lines = merged_text.splitlines()
    out: Dict[str, Optional[str]] = {k: None for k in ("A2","B2","C2","D2")}
    def find_after_token(token: str) -> Optional[str]:
        for idx, ln in enumerate(lines):
            if token in ln:
                v = take_tail_digits(ln)
                if v:
                    return v
                for j in range(1,3):
                    if idx+j < len(lines):
                        nxt = lines[idx+j]
                        v = take_tail_digits(nxt)
                        if v:
                            return v
        return None
    out["A2"] = find_after_token("A2")
    out["B2"] = find_after_token("B2")
    out["C2"] = find_after_token("C2")
    out["D2"] = find_after_token("D.2") or find_after_token("D2")
    return out


def extract_header_info(merged_text: str) -> Dict[str, Optional[str]]:
    lines = merged_text.splitlines()
    def find_line(prefix: str, window: int = 2) -> Optional[str]:
        for i, ln in enumerate(lines):
            if prefix in ln:
                # take rest of line after label
                tail = ln.split(prefix, 1)[1].strip()
                if tail:
                    return tail
                for j in range(1, window+1):
                    if i+j < len(lines) and lines[i+j].strip():
                        return lines[i+j].strip()
        return None
    out: Dict[str, Optional[str]] = {"stembureau_nummer": None, "stembureau_naam": None}
    # Nummer stembureau <n>
    import re
    m = re.search(r"Nummer\s+stembureau\s*:?\s*([0-9OIl|!]+)", merged_text)
    if m:
        s = m.group(1)
        s = s.replace('O','0').replace('I','1').replace('l','1').replace('|','1').replace('!','1')
        out["stembureau_nummer"] = s
    else:
        v = find_line("Nummer stembureau")
        if v:
            out["stembureau_nummer"] = v
    # Locatie stembureau ... ) <naam>
    m2 = re.search(r"Locatie\s+stembureau(?:\s*\([^)]*\))?\s*(.+)", merged_text)
    if m2:
        out["stembureau_naam"] = m2.group(1).strip()
    else:
        v2 = find_line("Locatie stembureau")
        if v2:
            out["stembureau_naam"] = v2
    return out


def main():
    ap = argparse.ArgumentParser(description="Headers uit OCR-tekst (A–H en hertelling A2–D2)")
    ap.add_argument("pdf")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    pdf = Path(args.pdf)
    side_text, layout = ocr_texts(pdf)
    merged = side_text + "\n" + layout
    hdr = extract_headers(merged)
    rtl = extract_retally(merged)
    inf = extract_header_info(merged)
    out = {"A": hdr.get("A"), "B": hdr.get("B"), "C": hdr.get("C"), "D": hdr.get("D"),
           "E": hdr.get("E"), "F": hdr.get("F"), "G": hdr.get("G"), "H": hdr.get("H"),
           "A2": rtl.get("A2"), "B2": rtl.get("B2"), "C2": rtl.get("C2"), "D2": rtl.get("D2"),
           "stembureau_nummer": inf.get("stembureau_nummer"), "stembureau_naam": inf.get("stembureau_naam")}
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(args.out)


if __name__ == "__main__":
    main()
