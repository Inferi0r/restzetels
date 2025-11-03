Doel
Dit document legt de aanpak, keuzes en lessen vast om Model Na31‑2/N10‑2 proces‑verbalen te lezen en te converteren naar Nederlandse JSON. Het beschrijft de pipeline, gebruikte tools en heuristieken, zodat we later dezelfde stappen kunnen reproduceren en verbeteren.

Overzicht pipeline (v0 → v1)
- OCR sidecar (tekstlaag): met ocrmypdf wordt voor elke PDF een sidecar‑tekst gemaakt (alleen voor zones zonder tekstlaag via --skip-text). Deze tekst gebruiken we voor kopvelden, rubrieken en structuurherkenning.
- Pagina‑splitsing: de sidecar bevat voetteksten zoals "Stembureau 11 5/32". We splitsen op patronen "p/total". Ontbreekt een volgende markering, dan hangen we de buffer aan de eerstvolgende pagina. Lege pagina’s (alleen een paginamerker) worden weggelaten.
- Kopvelden Na31‑2: Aantal toegelaten kiezers (A,B,C,D) en Aantal uitgebrachte stemmen (E,F,G,H) worden per pagina via regex op de regelkoppen herkend. Het laatste cijferblok aan het einde van de regel wordt als waarde genomen. Als een regel bestaat maar geen eindcijfer herkend wordt, noteren we "onleesbaar"; als de regel op die pagina ontbreekt, noteren we "leeg".
- Verschil (rubriek 3): we verzamelen de vier opties (nee/nee onverklaard bij stembureau/ja met verklaring/ja onverklaard) als tekst en markeren 'keuze' voorlopig als "onleesbaar"; hertelling A2/B2/C2/D2 wordt per regel herkend met dezelfde eindcijfer‑heuristiek. "Hoe vaak is er geen verklaring" registreren we als getal indien aanwezig.
- Gecombineerde stemmingen (rubriek 4): alleen de aanwezigheid van de rubriek wordt vastgelegd; zonder read‑out van de aangevinkte keuze is de waarde "onleesbaar".
- Lijsten & kandidaten (sidecar): per pagina herkennen we "Lijst <nr> - <partij>" en erna elke naamregel als kandidaat. Zonder beeld‑OCR is er geen betrouwbare uitlezing van vakjes met cijfers; daarom noteren we bij kandidaten stemmen "leeg". Kandidatennummers worden doorlopend per lijst (over pagina’s heen) toegekend (1,2,3,…) zodat we consistent kunnen refereren.

Verbeteringen (v1.1–v1.2): beeld‑OCR voor cijfers
- Rendering: met pdftoppm renderen we de PDF‑pagina’s naar PNG (400 DPI), rekening houdend met rotatie. We houden de renders per PDF in data/ocr_png/<pdf.stem>/ bij.
- Tesseract TSV: we voeren tesseract (nld+eng, psm 6) op elke pagina uit en verzamelen per regel de tekst + bounding boxes. Hiermee kunnen we:
  - Lijstkoppen herkennen ("Lijst <nr> - <partij>")
  - Kandidatenregels detecteren en (indien aanwezig) het meest rechts herkende cijfer op die regel als stemmen nemen.
  - Subtotaal/Totaal per lijstpagina als getallen uitlezen.
- Digit‑pass: daarnaast draaien we een tweede OCR‑pass met alleen cijfers (whitelist 0‑9) om vakjescijfers betrouwbaarder te vinden en aan regels te koppelen via verticale overlap (> 50%).
- Kolom‑crops: als de cijferpass niets vindt, croppen we een rechter kolomband (ca. 62%–100% van paginabreedte, y = regelhoogte) en OCR’en die uitgeknipte strook in digits‑mode (psm 7). Dit vult extra stemmen/subtotalen/totaal.
- Column‑fusing: tesseract kan soms twee namen op één regel plakken. We splitsen dan heuristisch op “) <Hoofdletter>” en vullen afzonderlijke kandidaten (stemmen blijven in die gevallen vaak "leeg").
- Nummering: als een kandidaatsnummer aan het begin van de regel OCR‑baar is, nemen we die; anders vullen we sequentieel doorlopend per lijst.

Betekenis waarden (veld ‘waarde’ of ‘stemmen’)
- Getal: interpretatie van een eindcijferblok op de regel (bijv. "1 5 0" → 150). Ook 0 is toegestaan (zeldzaam, maar mogelijk).
- "leeg": de betreffende regel of het vakje staat wel in het sjabloon, maar we lezen op die pagina geen cijfer (vakje leeg of niet ingevuld/afwezig op die pagina).
- "onleesbaar": er staat zichtbaar iets, maar OCR levert geen betrouwbaar eindcijfer (ruis/artefacten/afsnijding).

Bestanden en scripts
- tools/extract_handwritten.py: initieel OCR + headerextractie (gemeente, stembureau, basisstructuur).
- tools/sidecar_to_json_nl.py: zet sidecar‑tekst om naar Nederlandse JSON per pagina (A‑H, A2‑D2, lijsten/kandidaten, subtotalen links/rechts, totaal). Bepaalt ook verschillen_lijsttotalen (ja/nee) heuristisch.
- tools/ocr_votes_pdf.py: beeld‑OCR per pagina (TSV), reconstructie per lijst (kandidaten, stemmen, subtotalen, totaal). Schrijft Aparte JSON (…ocr.json) en kan later gemerged worden in de hoofd‑JSON.
- data/extracted_nl/Aalsmeer/Clubgebouw VZOD.json: samengestelde JSON op paginaniveau uit sidecar (huidig resultaat).
- data/extracted_nl/Aalsmeer/Clubgebouw VZOD.ocr.json: paginagewijs resultaat uit beeld‑OCR (voor het verfijnen van ‘leeg’ vs getal en subtotalen/totaal).

Heuristieken (details)
- Paginadetectie: regex "(\d+)\s*/\s*(\d+)" in voettekst. Bij missende marker wordt de buffer aan de eerstvolgende pagina toegekend. Lege pagina’s (alleen marker) worden gedropt.
- Eindcijferextractie: we zoeken de laatste cijferreeks aan het einde van de regel (met spaties toegestaan). Hierdoor lezen we getallen zoals "1 5 0".
- Kandidatenregels: herkennen via naam‑patroon (achternaam, initialen, voornaam tussen haakjes, (m)/(v)), met uitzonderingen voor kopregels (“Naam kandidaat …”, “Zet in elk vakje …”, “Vervolg: …”).
- Subtotaal links/rechts: we nemen maximaal twee ‘Subtotaal’ regels per lijstpagina; de eerste is ‘links’, de tweede ‘rechts’. Zonder getal → "onleesbaar"; ontbrekend → "leeg".
- Verschillen lijsttotalen (pagina 31): heuristiek op basis van de aanwezigheid van een invultabel na de ja/nee‑regels.

Bekende beperkingen en vervolgstappen
1) Stemmen per kandidaat: met sidecar alleen vrijwel altijd "leeg". Beeld‑OCR vult dit deels, maar bij twee kolommen en vakjes kan de uitlijning nog missen. Volgende stappen:
   - Tesseract numeric‑mode voor rechter kolom (whitelist 0‑9) en y‑uitlijning met kandidatenregellijnen (TSV‑box‑overlap > 50%).
   - Crops van rechter kolom per pagina (vaste x‑band) en dan numeric OCR daarop.
2) Ja/nee aankruisen: detectie van ingevulde checkbox is ruisgevoelig (symbolen ‘mj’, ‘q’, bullets). Beter: binaire drempeling + connected components rond de checkbox en dan dichtsbijzijnde label kiezen.
3) Rotatie/kwaliteit: PDF’s met rotatie (bijv. 270°) en lage DPI vragen soms om 400–450 DPI voor stabielere cijfers; nu ingesteld op 400 DPI in de render‑stap.
4) Mergen: data uit sidecar (A‑H, A2‑D2, kopvelden) en beeld‑OCR (kandidatenstemmen, subtotalen/totaal) kunnen automatisch worden samengevoegd per pagina → 1 definitieve JSON.

Hoe te reproduceren (stappen)
1) Sidecar genereren (al aanwezig in data/sidecar):
   - ocrmypdf -l nld+eng --skip-text --sidecar data/sidecar/<GEMEENTE>/<BESTAND>.txt <PDF> <tmp.pdf>
2) JSON (sidecar → NL) maken:
   - python3 tools/sidecar_to_json_nl.py data/sidecar/Aalsmeer/bc899e8… Clubgebouw VZOD.txt --gemeente Aalsmeer --pdf-pad Aalsmeer/2-aal-vzod.pdf --out data/extracted_nl/Aalsmeer/Clubgebouw\ VZOD.json
3) Beeld‑OCR voor lijsten/kandidaten/subtotalen/totaal:
   - python3 tools/ocr_votes_pdf.py Aalsmeer/2-aal-vzod.pdf --out data/extracted_nl/Aalsmeer/Clubgebouw\ VZOD.ocr.json
4) Merge: combineer per pagina de ‘lijsten’ uit .ocr.json met de overige velden uit de sidecar‑JSON, waarbij ‘stemmen’ voor kandidaten en (sub)totalen uit beeld‑OCR leidend zijn; ontbrekende getallen blijven “leeg”.

Samenvatting huidige status
- Deze aanpak levert een volledige paginagebaseerde JSON met duidelijke scheiding tussen getal/0/leeg/onleesbaar.
- Voor Clubgebouw VZOD is pagina 31 toegevoegd met ja/nee‑indicatie op ‘verschillen lijsttotalen’; lege pagina 32 is weggelaten.
- Kandidaten en subtotalen zijn volledig opgenomen; stemmen per kandidaat staan nu als "leeg" i.p.v. "onleesbaar" waar geen cijfers OCR‑baar zijn.

Sjabloon‑gedreven snelle modus (v2)
- Doel: sneller en consistenter door het sjabloon (geprinte structuur) éénmalig vast te leggen en per PDF alleen invulvelden (handgeschreven) te OCR’en.
- Bestanden:
  - `sjabloon.json`: enkel sjabloonwaarden (lijstnummer, partijnaam, kandidaten met nummers/namen per pagina). Wordt éénmalig opgebouwd en hergebruikt.
  - `fill_from_sjabloon.py`: leest `sjabloon.json`, rendert pagina’s en haalt alleen cijfers op bij relevante ROI’s (kandidaten, subtotaal links/rechts, totaallijst). Vulde pagina 1/2 (A–H, A2–D2) vanuit tekst‑OCR (`headers_from_text.py`).
  - `runner.py`: gebruikt, als `sjabloon.json` bestaat, standaard de snelle modus i.p.v. de volledige `sidecar_to_json_nl` → `ocr_votes_pdf.py` → `merge` pipeline. Valt automatisch terug op de volledige pipeline wanneer `sjabloon.json` nog niet bestaat, en maakt deze dan aan.
- Werking in het kort:
  1) Normaliseer/generate sidecar `.txt` voor naamconsistentie (niet vereist, wel handig).
  2) OCR headers (A–H, A2–D2, stembureau info) via `headers_from_text.py`.
  3) Indien `sjabloon.json` bestaat: `fill_from_sjabloon.py` vult direct `.final.json` op basis van sjabloon + ROI‑OCR.
  4) Converteer naar combined.nl‑stijl met `make_combined_nl.py` (`<pdf>.json`).
  5) Ontbreekt `sjabloon.json`? Runner draait legacy‑flow en maakt daarna `sjabloon.json` aan.
- OCR‑details snelle modus:
  - Per pagina: Tesseract TSV (nld+eng) voor tekstregels en een digits‑pass (whitelist 0‑9). Alleen lijnen binnen lijstblokken worden gescand.
  - Stemmen: eerst digits‑woorden met verticale overlap, dan regelnummers, dan crop van rechter kolomband (digits‑only, psm 7/6).
  - Subtotaal/Totaal: idem met een vaste band voor de rechterkolom per linkse/rechtse sectie.
  - Mapping: kandidaten uit OCR worden primair op kandidaatnummer gematcht aan het sjabloon; bij ontbreken, gebruikt de tool volgorde.

Benchmark/verwachting
- Doel is < 2 min voor 32 pagina’s op 400 DPI voor deze sjabloon (afhankelijk van systeem en Tesseract‑versie).
- De snelle modus slaat brede tekstherkenning en mergen over, en focust enkel op cijfer‑ROIs.
