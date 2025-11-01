# Restzetels dashboard

A small static site + serverless fetchers to visualize Dutch House of Representatives election results (ANP, NOS, and optional Kiesraad) with rest seat calculations.

## Party Labels (per year)
- TK2017 ANP/NOS widget: https://localfocus2.appspot.com/58cab665b9671
- PS2019 widget: https://lfverkiezingen2019nllive.appspot.com/public/builds/rx611b/index.html
- TK2021 NOS/ANP: https://d2vz64kg7un9ye.cloudfront.net/widgets/t2wmrc/index.html
- TK2023 NOS: https://app.nos.nl/nieuws/tk2023/
- PS2023 NOS: https://d2ytsyjyg1iox1.cloudfront.net/web/jrf5ks/index.html
- PS2023 NOS: https://app.nos.nl/nieuws/ps2023/
- TK2023 ANP: https://d1nxan4hfcgbsv.cloudfront.net/web/iir9q1/index.html
- TK2025 ANP: (open page source in the browser): view-source:https://widgets.verkiezingsdienst.anp.nl/tk25/web/2qxn3l/index.html
- TK2025 NOS: https://app.nos.nl/nieuws/tk2025/
- General pattern:
  - view-source:<ANP widgets base URL>/index.html

Use your browser’s “View Page Source” (or prepend `view-source:`) on the ANP widget page to locate the embedded party label data used for mapping (long/short names, NOS short names, colors, etc.).

- ANP widget links: often discoverable via AD.nl election pages (they embed the official ANP widgets). Open the page source and look for the ANP widget URL.

## Serverless PHP functions (fetch layer)
- Hosted as DigitalOcean Functions:
  - https://cloud.digitalocean.com/functions/fn-99532869-f9f1-44c3-ba3b-9af9d74b05e5?i=a80b61
- The frontend calls `fetch/getdata.php` (deployed to DO Functions) with sources:
  - `anp_votes` (alias: `votes`)
  - `anp_last_update` (alias: `last_update`)
  - `nos_index` (alias: `nos`)
  - `nos_gemeente` (alias: `gemeente`) — currently not used by the site.

## Website hosting
- The static website is hosted at:
  - https://cloud.digitalocean.com/apps/8634eb6f-45c7-40a9-bf00-426a386157f3?i=a80b61 (http://192.168.1.6:5000/web is and old version)

## Run locally (PHP built-in server)
- cd into the project root
  - `cd /Users/arcovink/Documents/restzetels`
  - `php -S 127.0.0.1:5000`
  - Open `http://127.0.0.1:5000/index.html`

## Repository notes
- 2023 logic is the correctness baseline for seats/rest seats and data joins.
- Year-specific assets (e.g., party labels and optional Kiesraad totals) can be added alongside the generic code to enable full feature parity for new years.

## Google Analytics
- Realtime overview: https://analytics.google.com/analytics/web/#/a2777124p417078801/realtime/overview

## Deployment notes

### Build ID and instant refresh

We use a single build identifier to force fresh assets and a service worker upgrade per deploy.

- Bump in one place: edit `js/config.js` and change `BUILD_ID` (e.g., `2025-11-01-02`).
- What it does:
  - Registers the service worker as `sw.js?v=BUILD_ID`, so the browser detects a new SW and upgrades.
  - The SW uses `BUILD_ID` to version caches (`static-<BUILD_ID>`, `data-<BUILD_ID>`, etc.).
  - The page auto‑reloads once when the new SW takes control, so visitors see the newest build immediately.
- HTML caching at the edge:
  - `_headers` sets `Cache-Control: no-store` for `/` and all `*.html`, so Cloudflare won’t serve stale HTML shells.
  - Static assets can be long‑lived; the SW and (optional) URL query strings ensure fresh content after deploy.

### Steps per deploy
1. Update `BUILD_ID` in `js/config.js`.
2. Deploy the site.
3. Verify:
   - `curl -I https://<host>/` should not show a long `s-maxage` on HTML (expect no-store/no-cache).
   - `curl -I https://<host>/sw.js?v=BUILD_ID` should be `no-store`.
4. Load the site: it should auto‑refresh once and then run the new build.
