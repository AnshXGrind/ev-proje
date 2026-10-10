# EV Charging Infrastructure Planner

A Python and FastAPI application for exploring a dated public EV charging-station inventory and screening possible locations for additional chargers across the seven original North Indian regions, eight North-Eastern states, and Bihar, Uttar Pradesh and Madhya Pradesh.

## What it does

- Displays charger records from the available Bureau of Energy Efficiency (BEE) snapshot.
- Optionally loads a North-East GeoJSON covering Assam, Arunachal Pradesh, Manipur, Meghalaya, Mizoram, Nagaland, Sikkim and Tripura.
- Optionally loads a Central states GeoJSON covering Bihar, Uttar Pradesh and Madhya Pradesh.
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

The local file `data/processed/north_india_ev_chargers_map.geojson` is required. To enable the eight North-Eastern states, place `northeast_ev_chargers_map.geojson` in `data/processed/`. To enable Bihar, Uttar Pradesh and Madhya Pradesh, also place `central_states_ev_chargers_map.geojson` there. Both supplemental files are supplied separately because generated data files are not tracked. `/api/health` reports whether each was loaded.

## Methods

- **DBSCAN:** groups approximate station coordinate locations by proximity.
- **Baseline placement:** ranks midpoint candidates using straight-line distances between reported coordinate groups.
- **Route screening:** compares a selected route with nearby reported inventory and estimates spacing from terrain, range and scenario inputs.

## Data and limitations

The inventory source snapshot is dated 26 October 2025. The North-East file contains 645 mapped source records across eight states and the Central states file contains 4,088 mapped source records across Bihar, Uttar Pradesh and Madhya Pradesh; source status is not live verified and these are not confirmed unique operating physical sites. It does not provide live operating status, traffic counts or charging-session history. Coordinate records are not a verified count of operating physical sites. Candidate locations are for initial review, not confirmed land parcels or approved roadside installations. Electrical feasibility requires local feeder, transformer and load data; it is not verified by the current application.

Road routing and place/elevation lookups use external services and require internet access. Route geometry, seasonal road conditions and access restrictions must be checked before using results for deployment. OpenStreetMap data attribution and licensing must be respected.
