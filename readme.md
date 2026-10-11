# EV Charging Infrastructure Planner

A Python and FastAPI application for exploring the dated BEE public EV charging-station inventory and screening possible locations for additional chargers across all 36 Indian states and Union Territories after administrative-boundary validation.

## What it does

- Displays charger records from the available Bureau of Energy Efficiency (BEE) snapshot.
- Loads a validated nationwide GeoJSON covering all 28 states and 8 Union Territories when the India-wide data preparation pipeline has passed.
- Includes a full source-row boundary audit, state/UT summary and traceable extraction page for source inventory rows.
- Validates manual coordinates, route geometry and generated route-candidate coordinates against the same India boundary.
- Filters and searches records by region and charger details.
- Uses DBSCAN with Haversine distance to group nearby coordinate locations.
- Generates preliminary coverage-gap candidates from reported coordinates.
- Reviews a selected driving route against nearby inventory and sampled elevation data.
- Calculates route-spacing scenarios from terrain, usable vehicle range, battery reserve and user-selected assumptions.
- Exports candidate locations and analysis results as CSV or JSON.

## Run locally

From PowerShell in the repository folder:

```powershell
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Open `http://127.0.0.1:8000`. The API documentation is at `http://127.0.0.1:8000/docs`; the route page is at `http://127.0.0.1:8000/route-planner`.

For nationwide mode, extract the India-wide expansion bundle and run update_gridpulse_india_expansion.ps1 (see INSTALL_GRIDPULSE_INDIA.md). It loads the BEE source candidates, downloads the Survey of India / NWIC state-boundary GeoJSON, validates points against all 36 state/UT polygons, writes the accepted map and a complete exclusion audit, and runs focused tests. If national source data exists but validation has not succeeded, the API fails closed instead of showing the old regional subset as nationwide coverage. /api/health reports india_inventory_loaded and boundary_validation_passed.

## Methods

- **DBSCAN:** groups approximate station coordinate locations by proximity.
- **Baseline placement:** ranks midpoint candidates using straight-line distances between reported coordinate groups.
- **Route screening:** compares a selected route with nearby reported inventory and estimates spacing from terrain, range and scenario inputs.

## Data and limitations

The BEE inventory source snapshot is dated 26 October 2025. The PDF parser extracted 39,628 candidate coordinate rows across 36 states/UTs; this is a source-row count, not a verified count of unique physical or currently operating sites. All-India mode only opens after the official boundary validation pipeline writes a validated inventory and audit. The source does not provide live operating status, traffic counts or charging-session history. Candidate locations are for initial review, not confirmed land parcels or approved roadside installations. Electrical feasibility requires local feeder, transformer and load data; it is not verified by the current application.

Road routing and place/elevation lookups use external services and require internet access. Route geometry, seasonal road conditions and access restrictions must be checked before using results for deployment. OpenStreetMap data attribution and licensing must be respected.
