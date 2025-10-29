# Restzetels dashboard

A small static site + serverless fetchers to visualize Dutch House of Representatives election results (ANP, NOS, and optional Kiesraad) with rest seat calculations.

## Party Labels (per year)
- 2025 example (open page source in the browser):
  - view-source:https://widgets.verkiezingsdienst.anp.nl/tk25/web/2qxn3l/index.html
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
  - http://192.168.1.6:5000/web

## Run locally (PHP built-in server)
- cd into the project root
  - `cd /Users/arcovink/Documents/restzetels`
  - `php -S 127.0.0.1:5000`
  - Open `http://127.0.0.1:5000/index.html`

## Repository notes
- 2023 logic is the correctness baseline for seats/rest seats and data joins.
- Year-specific assets (e.g., party labels and optional Kiesraad totals) can be added alongside the generic code to enable full feature parity for new years.
