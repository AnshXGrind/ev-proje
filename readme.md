# EV Charging Infrastructure Planner

A Python and FastAPI application for exploring a dated public EV charging-station inventory and screening possible locations for additional chargers across seven North Indian regions.

## What it does

- Displays charger records from the available Bureau of Energy Efficiency (BEE) snapshot.
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

The local file `data/processed/north_india_ev_chargers_map.geojson` must be present for inventory analysis. Generated data is not included in the repository.

## Methods

- **DBSCAN:** groups approximate station coordinate locations by proximity.
- **Baseline placement:** ranks midpoint candidates using straight-line distances between reported coordinate groups.
- **Route screening:** compares a selected route with nearby reported inventory and estimates spacing from terrain, range and scenario inputs.

## Data and limitations

The inventory source snapshot is dated 26 October 2025. It does not provide live operating status, traffic counts or charging-session history. Coordinate records are not a verified count of operating physical sites. Candidate locations are for initial review, not confirmed land parcels or approved roadside installations. Electrical feasibility requires local feeder, transformer and load data; it is not verified by the current application.

Road routing and place/elevation lookups use external services and require internet access. Route geometry, seasonal road conditions and access restrictions must be checked before using results for deployment. OpenStreetMap data attribution and licensing must be respected.
