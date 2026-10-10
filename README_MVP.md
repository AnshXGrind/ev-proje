# North, Central & Northeast India EV Planner (MVP)

This adds a local FastAPI backend and an interactive dashboard to the existing `ev-proje` project. It uses the filtered BEE public charging-station inventory already extracted from the PDF. No Open Charge Map API key is needed.

## Run on Windows

1. Extract this ZIP into the existing `C:\EV\ev proje` repository root and allow the files to merge/overwrite.
2. In PowerShell:

   ```powershell
   Set-Location "C:\EV\ev proje"
   .\start_ev_planner.ps1
   ```

3. The app opens at `http://127.0.0.1:8000`. Keep the terminal window open. Swagger API docs are at `http://127.0.0.1:8000/docs`.

The startup script installs four runtime dependencies into the project `.venv`: FastAPI, Uvicorn, NumPy and scikit-learn.

## What works

- FastAPI health, inventory, regional analytics, station search and filtered inventory endpoints.
- Interactive frontend: region selector, clustered station map, charger mix, power-band summaries, searchable table, and CSV export.
- Unsupervised spatial DBSCAN clustering (Haversine distance) on approximate coordinate groups.
- Budget-based midpoint screening for possible coverage gaps, with CSV export.
- Local map/API use, no external charger-data API key required. Map tiles and Leaflet assets still require internet access.

## Data limits

- Inventory source snapshot: 26 October 2025; operating status is not live verified.
- Approximate coordinate groups are not a verified count of physical stations.
- DBSCAN is an unsupervised spatial clustering model, not a trained demand forecasting model.
- Candidate points are straight-line midpoint screening coordinates, not confirmed road-side sites or available land.
- Per-site cost is an editable scenario assumption, not a sourced price quote.
- Local feeder/transformer capacity, traffic counts, and hourly session history are not present; no real grid hosting-capacity or validated demand forecast is claimed.

## North-East inventory

To include the eight North-Eastern states, copy `northeast_ev_chargers_map.geojson` into `data/processed/` alongside the existing North India file. The supplemental file contains 645 mapped records extracted from the BEE snapshot dated 26 October 2025. It is a dated source inventory, not live status or a verified count of unique operating sites. The `/api/health` endpoint reports `northeast_inventory_loaded` and `northeast_records` so you can confirm the file was found.

## Bihar, Uttar Pradesh and Madhya Pradesh inventory

Copy `central_states_ev_chargers_map.geojson` into `data/processed/` alongside the existing North India and North-East files. It contains 4,080 mapped source records extracted from the BEE snapshot labelled through 26 October 2025. The records are not a live status feed or a verified count of unique operating physical sites. The `/api/health` endpoint reports `central_inventory_loaded` and `central_records` so you can confirm the file was found.

## Local data layout

`data/processed/north_india_ev_chargers_map.geojson` is required. The CSV included is available for manual review/analysis. Do not commit personal API keys or virtual environment files.
