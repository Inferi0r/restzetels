#!/usr/bin/env python3
import argparse
import json
import re
from pathlib import Path


def read_lines(path: Path) -> list[str]:
    return path.read_text(encoding="utf-8", errors="ignore").splitlines()


def split_pages(lines: list[str]) -> dict[int, list[str]]:
    pages: dict[int, list[str]] = {}
    buf: list[str] = []
    prev_p: int | None = None
    for line in lines:
        buf.append(line)
        m = re.search(r"(\d+)\s*/\s*(\d+)\s*$", line)
        if m:
            p = int(m.group(1))
            if prev_p is None:
                pages[p] = buf
                prev_p = p
                buf = []
                continue
            # Ignore spurious backward page markers (OCR-ruis zoals '21/32' laat in document)
            if p < prev_p:
                continue
            if p > prev_p + 1:
                pages[prev_p + 1] = buf
            else:
                pages[p] = buf
            prev_p = p
            buf = []
    # Any trailing buffer without marker -> next page number
    if buf:
        p = (prev_p + 1) if prev_p is not None else 1
        pages[p] = buf
    # Drop pages that are effectively empty (only contain page marker)
    def nonempty(pl: list[str]) -> bool:
        content = [x.strip() for x in pl if x.strip()]
        if not content:
            return False
        if len(content) == 1 and re.search(r"(stembureau\s+\d+\s+)?\d+\s*/\s*\d+", content[0], flags=re.IGNORECASE):
            return False
        return True
    pages = {k: v for k, v in pages.items() if nonempty(v)}
    return pages


def parse_meta(lines: list[str], gemeente_hint: str | None) -> dict:
    gemeente = gemeente_hint
    num = None
    name = None
    for l in lines:
        m = re.search(r"Nummer\s+stembureau\s*:?\s*(\d+)\b", l, flags=re.IGNORECASE)
        if m:
            num = int(m.group(1))
        m = re.search(r"Locatie\s+stembureau(?:\s*\([^)]*\))?\s*(.+)$", l, flags=re.IGNORECASE)
        if m:
            name = m.group(1).strip()
        if gemeente is None:
            g = re.search(r"(?m)^\s*Gemeente\s+(.+?)\s+[—-]\s*Kieskring", l)
            if g:
                gemeente = g.group(1).strip()
    return {"gemeente": gemeente, "stembureau_nummer": num, "stembureau_naam": name}


def last_int_or_unreadable(s: str):
    # Neem de laatste cijferreeks aan het eind van de regel, spaties toegestaan (bijv. "1 5 0" -> 150)
    m = re.search(r"([0-9](?:[0-9 ]*[0-9])?)\s*$", s)
    if not m:
        return "onleesbaar"
    return int(m.group(1).replace(" ", ""))


def parse_counts_page(page_lines: list[str]) -> tuple[dict | None, dict | None]:
    # Return (toegelaten, uitgebrachte)
    def find_line(prefix: str) -> str | None:
        for ll in page_lines:
            sll = ll.strip().lower()
            if sll.startswith(prefix):
                # Skip hertelling-varianten (A2/B2/C2) bij A/B/C
                if prefix.startswith("aantal geldige stempassen") and "a2" in sll:
                    continue
                if prefix.startswith("aantal geldige volmachtbewijzen") and "b2" in sll:
                    continue
                if prefix.startswith("aantal geldige kiezerspassen") and "c2" in sll:
                    continue
                return ll.strip()
        return None

    t = None
    u = None

    # Toegelaten kiezers
    a = find_line("aantal geldige stempassen")
    b = find_line("aantal geldige volmachtbewijzen")
    c = find_line("aantal geldige kiezerspassen")
    d = find_line("totaal aantal toegelaten kiezers")
    if any([a, b, c, d]):
        t = {
            "A": {"omschrijving": "Aantal geldige stempassen", "waarde": (last_int_or_unreadable(a) if a else "leeg")},
            "B": {"omschrijving": "Aantal geldige volmachtbewijzen (schriftelijk of via ingevulde stem- of kiezerspas)", "waarde": (last_int_or_unreadable(b) if b else "leeg")},
            "C": {"omschrijving": "Aantal geldige kiezerspassen", "waarde": (last_int_or_unreadable(c) if c else "leeg")},
            "D": {"omschrijving": "Totaal aantal toegelaten kiezers (A+B+C)", "waarde": (last_int_or_unreadable(d) if d else "leeg")},
        }

    # Uitgebrachte stemmen
    e = find_line("aantal stembiljetten met een geldige stem")
    f = find_line("aantal blanco stembiljetten")
    g = find_line("aantal ongeldige stembiljetten")
    h = find_line("totaal aantal uitgebrachte stemmen")
    if any([e, f, g, h]):
        u = {
            "E": {"omschrijving": "Aantal stembiljetten met een geldige stem op een kandidaat", "waarde": (last_int_or_unreadable(e) if e else "leeg")},
            "F": {"omschrijving": "Aantal blanco stembiljetten", "waarde": (last_int_or_unreadable(f) if f else "leeg")},
            "G": {"omschrijving": "Aantal ongeldige stembiljetten", "waarde": (last_int_or_unreadable(g) if g else "leeg")},
            "H": {"omschrijving": "Totaal aantal uitgebrachte stemmen (E+F+G)", "waarde": (last_int_or_unreadable(h) if h else "leeg")},
        }

    return t, u


def parse_difference_page(page_lines: list[str]) -> dict | None:
    diff_present = any("Is er een verschil" in l for l in page_lines)
    ret = any(l.lower().startswith("aantal geldige stempassen a2") or " b2" in l.lower() or " c2" in l.lower() or "d.2" in l.lower() or " d2" in l.lower() for l in page_lines)
    other = any("Hoe vaak is er geen verklaring" in l for l in page_lines)
    if not (diff_present or ret or other):
        return None
    d: dict = {
        "keuze": "onleesbaar",
        "hertelling": {
            "A2": {"omschrijving": "Aantal geldige stempassen (hertelling)", "waarde": "leeg"},
            "B2": {"omschrijving": "Aantal geldige volmachtbewijzen (hertelling)", "waarde": "leeg"},
            "C2": {"omschrijving": "Aantal geldige kiezerspassen (hertelling)", "waarde": "leeg"},
            "D2": {"omschrijving": "Totaal aantal toegelaten kiezers (hertelling)", "waarde": "leeg"},
        },
    }
    for l in page_lines:
        sl = l.strip().lower()
        if sl.startswith("aantal geldige stempassen a2"):
            d["hertelling"]["A2"]["waarde"] = last_int_or_unreadable(l)
        elif sl.startswith("aantal geldige volmachtbewijzen") and "b2" in sl:
            d["hertelling"]["B2"]["waarde"] = last_int_or_unreadable(l)
        elif sl.startswith("aantal geldige kiezerspassen") and "c2" in sl:
            d["hertelling"]["C2"]["waarde"] = last_int_or_unreadable(l)
        elif ("totaal aantal toegelaten kiezers" in sl) and ("d.2" in sl or " d2" in sl):
            d["hertelling"]["D2"]["waarde"] = last_int_or_unreadable(l)
        elif "totaal aantal toegelaten kiezers volgens het gemeentelijk stembureau" in sl:
            d["hertelling"]["D2"]["waarde"] = last_int_or_unreadable(l)
        elif sl.startswith("hoe vaak is er geen verklaring"):
            d["aantal_geen_verklaring"] = last_int_or_unreadable(l)
    return d


def parse_combined_page(page_lines: list[str]) -> str | None:
    if any("Bij gecombineerde stemmingen" in l for l in page_lines):
        return "onleesbaar"
    return None


def parse_lists_page(page_lines: list[str]) -> list[dict] | None:
    lists: dict[tuple[int, str], dict] = {}
    current_key: tuple[int, str] | None = None

    def ensure_list(list_no: int, party: str):
        key = (list_no, party)
        if key not in lists:
            lists[key] = {
                "lijstnummer": list_no,
                "partijnaam": party,
                "kandidaten": [],
                "subtotaal_links": "leeg",
                "subtotaal_rechts": "leeg",
                "totaal_lijst": "leeg",
            }
        return key

    for idx, l in enumerate(page_lines):
        s = l.strip()
        if not s:
            continue
        m = re.match(r"Lijst\s+(\d+)\s*-\s*(.+)", s)
        if m:
            list_no = int(m.group(1))
            party = m.group(2).strip()
            current_key = ensure_list(list_no, party)
            continue
        m = re.match(r"Vervolg:\s*Lijst\s+(\d+)\s*-\s*(.+)", s)
        if m:
            list_no = int(m.group(1))
            party = m.group(2).strip()
            current_key = ensure_list(list_no, party)
            continue
        if s.lower().startswith("naam kandidaat"):
            continue
        if s.lower().startswith("zet in elk vakje"):
            continue
        if s.lower().startswith("subtotaal") and current_key is not None:
            val = last_int_or_unreadable(s)
            lst = lists[current_key]
            if lst["subtotaal_links"] == "leeg":
                lst["subtotaal_links"] = val
            elif lst["subtotaal_rechts"] == "leeg":
                lst["subtotaal_rechts"] = val
            continue
        if s.lower().startswith("totaal") and current_key is not None:
            lists[current_key]["totaal_lijst"] = last_int_or_unreadable(s)
            continue
        if current_key is not None:
            # Candidate line
            if re.match(r"^[A-Za-zÀ-ÿ].+", s):
                # Default: nummer onbekend (invullen in aggregatie), stemmen leeg tenzij er een eindgetal staat
                mnum = re.search(r"(\d+)\s*$", s)
                stemmen = int(mnum.group(1)) if mnum else "leeg"
                naam = s if not mnum else s[: s.rfind(mnum.group(1))].strip().rstrip(',;')
                lists[current_key]['kandidaten'].append({
                    "kandidaatnummer": "leeg",
                    "kandidaatnaam": naam,
                    "stemmen": stemmen,
                })

    if not lists:
        return None
    return list(lists.values())


def _detect_lijsttotalen_ja_nee(lines: list[str]) -> str | None:
    # Heuristiek: in de sectie "Verschillen met de door het stembureau vastgestelde lijsttotalen"
    # staan regels met 'Nee' en 'Ja'. Als er een invultabel volgt (data-achtig), kiezen we 'ja'.
    found = False
    for i, l in enumerate(lines):
        if 'Verschillen met de door het stembureau vastgestelde lijsttotalen' in l:
            found = True
        if found:
            if re.search(r"\bNee\b", l):
                # mark presence; final decision below
                pass
            if re.search(r"\bJa\b", l):
                # check if following lines contain any digits (as if a tabel is ingevuld)
                tail = '\n'.join(lines[i:i+15])
                if re.search(r"\b\d+\b", tail):
                    return 'ja'
                # if no digits found, prefer 'nee'
                return 'nee'
    return None


def build_json(sidecar_path: Path, gemeente_hint: str | None, pdf_path_hint: str | None) -> dict:
    lines = read_lines(sidecar_path)
    meta = parse_meta(lines, gemeente_hint)
    pages = split_pages(lines)
    pagina_array = []
    # Hou per lijst lopende kandidaatnummers bij over pagina's heen
    next_num: dict[tuple[int, str], int] = {}

    for pnum in sorted(pages.keys()):
        plines = pages[pnum]
        t, u = parse_counts_page(plines)
        d = parse_difference_page(plines)
        g = parse_combined_page(plines)
        lijsten = parse_lists_page(plines)
        # Verrijk lijsten met doorlopende kandidaatnummers
        if lijsten:
            for lst in lijsten:
                key = (lst["lijstnummer"], lst["partijnaam"])
                start = next_num.get(key, 1)
                for idx, k in enumerate(lst["kandidaten"], start=start):
                    k["kandidaatnummer"] = idx
                next_num[key] = start + len(lst["kandidaten"])

        # Extra ja/nee op pagina (lijsttotalen)
        lt = _detect_lijsttotalen_ja_nee(plines)
        entry: dict = {"pagina": pnum}
        if t:
            entry["aantal_toegelaten_kiezers"] = t
        if u:
            entry["aantal_uitgebrachte_stemmen"] = u
        if d:
            entry["verschil_toegelaten_vs_uitgebrachte"] = d
        if g is not None:
            entry["gecombineerde_stemmingen"] = g
        if lijsten:
            entry["lijsten"] = lijsten
        if lt is not None:
            entry["verschillen_lijsttotalen"] = lt
        pagina_array.append(entry)

    data = {
        "bestand": pdf_path_hint or sidecar_path.name.replace('.txt', '.pdf'),
        "gemeente": meta["gemeente"],
        "stembureau_nummer": meta["stembureau_nummer"],
        "stembureau_naam": meta["stembureau_naam"],
        "paginas": pagina_array,
    }
    return data


def main():
    ap = argparse.ArgumentParser(description="Converteer sidecar-tekst naar NL JSON per pagina")
    ap.add_argument("sidecar", help="Pad naar sidecar .txt")
    ap.add_argument("--gemeente", default=None)
    ap.add_argument("--pdf-pad", default=None)
    ap.add_argument("--out", default=None, help="Uitvoerbestand .json")
    args = ap.parse_args()

    sidecar = Path(args.sidecar)
    gemeente = args.gemeente
    pdf_hint = args.pdf_pad
    data = build_json(sidecar, gemeente, pdf_hint)
    out_path = Path(args.out) if args.out else (Path("data/extracted_nl") / (sidecar.parent.name) / (sidecar.stem + ".json"))
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(out_path)


if __name__ == "__main__":
    main()
