# GRIDPULSE — North India EV Planner (MVP)

This overlay adds a local FastAPI backend and a live dashboard to the existing `ev-proje` scaffold. It uses the filtered BEE public charging-station inventory already extracted from the PDF. No Open Charge Map API key is needed.

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
- Budget-parameterized, spatially diversified midpoint coverage-gap screening and CSV export.
- Local map/API use, no external charger-data API key required. Map tiles and Leaflet assets still require internet access.

## Important claims boundary

- Inventory source snapshot: 26 October 2025; operating status is not live verified.
- Approximate coordinate groups are not a verified count of physical stations.
- DBSCAN is an unsupervised spatial clustering model, not a trained demand forecasting model.
- Candidate points are straight-line midpoint screening coordinates, not confirmed road-side sites or available land.
- Per-site cost is an editable scenario assumption, not a sourced price quote.
- Local feeder/transformer capacity, traffic counts, and hourly session history are not present; no real grid hosting-capacity or validated demand forecast is claimed.

## Local data layout

`data/processed/north_india_ev_chargers_map.geojson` is required. The CSV included is available for manual review/analysis. Do not commit personal API keys or virtual environment files.
