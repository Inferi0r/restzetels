#!/usr/bin/env python3
import argparse
import json
from pathlib import Path


LABELS = {
    "gemeente": "Gemeente",
    "stembureau_nummer": "Nummer stembureau",
    "stembureau_naam": "Locatie stembureau",
    "A": "Aantal geldige stempassen",
    "B": "Aantal geldige volmachtbewijzen (schriftelijk of via ingevulde stem- of kiezerspas)",
    "C": "Aantal geldige kiezerspassen",
    "D": "Totaal aantal toegelaten kiezers (A+B+C)",
    "E": "Aantal stembiljetten met een geldige stem op een kandidaat",
    "F": "Aantal blanco stembiljetten",
    "G": "Aantal ongeldige stembiljetten",
    "H": "Totaal aantal uitgebrachte stemmen (E+F+G)",
    "A2": "Aantal geldige stempassen (hertelling)",
    "B2": "Aantal geldige volmachtbewijzen (hertelling)",
    "C2": "Aantal geldige kiezerspassen (hertelling)",
    "D2": "Totaal aantal toegelaten kiezers (hertelling)",
    "keuze": "Is er een verschil (Nee/Ja ...)",
    "Lijstnummer": "Lijstnummer",
    "Partijnaam": "Partijnaam",
    "Kandidaatnummer": "Kandidaatnummer",
    "Kandidaatnaam": "Kandidaatnaam",
    "Stemmen": "Stemmen",
    "Subtotaal links": "Subtotaal links",
    "Subtotaal rechts": "Subtotaal rechts",
    "Totaal lijst": "Totaal lijst",
}


def wrap(label, waarde, bron):
    return {"label": label, "waarde": waarde, "waarde_bron": bron}


def build_combined(src: dict) -> dict:
    out = {
        "bron_pdf": src.get("bestand"),
        "kop": {
            "gemeente": wrap(LABELS["gemeente"], src.get("gemeente"), "handgeschreven"),
            "stembureau_nummer": wrap(LABELS["stembureau_nummer"], src.get("stembureau_nummer"), "handgeschreven"),
            "stembureau_naam": wrap(LABELS["stembureau_naam"], src.get("stembureau_naam"), "handgeschreven"),
        },
    }
    # pagina_1: A-D en E-H
    p1 = next((p for p in src.get("paginas", []) if p.get("pagina") == 1), None)
    if p1:
        blok = {}
        if p1.get("aantal_toegelaten_kiezers"):
            ak = {}
            for k in ("A","B","C","D"):
                if k in p1["aantal_toegelaten_kiezers"]:
                    ak[k] = wrap(LABELS[k], p1["aantal_toegelaten_kiezers"][k]["waarde"], "handgeschreven")
            blok["toegelaten_kiezers"] = ak
        if p1.get("aantal_uitgebrachte_stemmen"):
            au = {}
            for k in ("E","F","G","H"):
                if k in p1["aantal_uitgebrachte_stemmen"]:
                    au[k] = wrap(LABELS[k], p1["aantal_uitgebrachte_stemmen"][k]["waarde"], "handgeschreven")
            blok["uitgebrachte_stemmen"] = au
        if blok:
            out["pagina_1"] = blok
    # pagina_2: verschil
    p2 = next((p for p in src.get("paginas", []) if p.get("pagina") == 2), None)
    if p2:
        vb = {}
        if "verschil_toegelaten_vs_uitgebrachte" in p2:
            v = p2["verschil_toegelaten_vs_uitgebrachte"]
            sect = {}
            if "keuze" in v:
                sect["keuze"] = wrap(LABELS["keuze"], v["keuze"], "handgeschreven")
            h = v.get("hertelling", {})
            if h:
                hs = {}
                for k in ("A2","B2","C2","D2"):
                    if k in h:
                        hs[k] = wrap(LABELS[k], h[k]["waarde"], "handgeschreven")
                sect["hertelling"] = hs
            if sect:
                vb["verschil_toegelaten_vs_uitgebrachte"] = sect
        if vb:
            out["pagina_2"] = vb

    # paginagewijs lijsten/kandidaten
    pages = []
    for page in src.get("paginas", []):
        entry = {"pagina": page.get("pagina")}
        if page.get("lijsten"):
            lijsten = []
            for lst in page.get("lijsten", []):
                lj = {
                    "lijstnummer": wrap(LABELS["Lijstnummer"], lst.get("lijstnummer"), "sjabloon"),
                    "partijnaam": wrap(LABELS["Partijnaam"], lst.get("partijnaam"), "sjabloon"),
                    "subtotaal_links": wrap(LABELS["Subtotaal links"], lst.get("subtotaal_links"), "handgeschreven") if lst.get("subtotaal_links") is not None else wrap(LABELS["Subtotaal links"], None, "handgeschreven"),
                    "subtotaal_rechts": wrap(LABELS["Subtotaal rechts"], lst.get("subtotaal_rechts"), "handgeschreven") if lst.get("subtotaal_rechts") is not None else wrap(LABELS["Subtotaal rechts"], None, "handgeschreven"),
                    "totaal_lijst": wrap(LABELS["Totaal lijst"], lst.get("totaal_lijst"), "handgeschreven") if lst.get("totaal_lijst") is not None else wrap(LABELS["Totaal lijst"], None, "handgeschreven"),
                    "kandidaten": [],
                }
                for cand in lst.get("kandidaten", []):
                    lj["kandidaten"].append({
                        "kandidaatnummer": wrap(LABELS["Kandidaatnummer"], cand.get("kandidaatnummer"), "sjabloon"),
                        "kandidaatnaam": wrap(LABELS["Kandidaatnaam"], cand.get("kandidaatnaam"), "sjabloon"),
                        "stemmen": wrap(LABELS["Stemmen"], cand.get("stemmen"), "handgeschreven"),
                    })
                lijsten.append(lj)
            entry["lijsten"] = lijsten
        pages.append(entry)
    out["paginas"] = pages
    return out


def main():
    ap = argparse.ArgumentParser(description="Maak combined.nl JSON in stijl van methode1")
    ap.add_argument("final_json", help="Pad naar .final.json")
    ap.add_argument("--out", required=True, help="Uitvoer pad voor combined.nl JSON")
    args = ap.parse_args()
    src = json.loads(Path(args.final_json).read_text(encoding="utf-8"))
    dst = build_combined(src)
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(dst, ensure_ascii=False, indent=2), encoding="utf-8")
    print(args.out)


if __name__ == "__main__":
    main()

