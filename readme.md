# India-wide EV Charging Infrastructure Planner

GRIDPULSE is a Python/FastAPI planning prototype for exploring a dated public EV charging-station inventory, screening coverage gaps, and reviewing route corridors across **all 28 Indian states and 8 union territories**.

## What it does

- Displays source-reported charger records from the Bureau of Energy Efficiency (BEE) public charging-station PDF snapshot dated **26 October 2025**.
- Validates charger coordinates against a state/UT polygon layer and only puts records inside both India and their reported state/UT into the operational nationwide map.
- Retains out-of-country, invalid-coordinate, suspicious-coordinate and state-mismatch records in a row-level audit CSV for review instead of silently plotting them.
- Filters and searches records by state/UT, district, charger details and source provenance.
- Uses DBSCAN with Haversine distance to group nearby coordinate locations; clusters are not demand estimates.
- Generates preliminary coverage-gap candidates and screens candidate points against their selected state/UT polygon.
- Reviews route corridors against nearby reported inventory, sampled elevation and conservative scenario assumptions.
- Exposes `/api/health` fields describing nationwide-data and boundary availability, and `/api/boundaries` for the locally installed polygons.

## Install / run on Windows

From PowerShell in the repository root:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-mvp.txt
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Open `http://127.0.0.1:8000`. API documentation is at `http://127.0.0.1:8000/docs`; route planner is at `http://127.0.0.1:8000/route-planner`.

## Nationwide inventory data

The source-derived CSVs and resulting national map are generated-data files and are not stored in Git. Install the India-wide data bundle, then run:

```powershell
.\.venv\Scripts\python.exe scripts\validate_india_inventory.py
```

The validator downloads the NIC WebGIS state/UT polygons (the layer description says it contains 36 polygons sourced from Survey of India topographic-map administrative boundaries), runs point-in-polygon checks, and writes:

- `data/processed/india_ev_chargers_map.geojson` — accepted points only.
- `data/reports/india_ev_chargers_boundary_audit.csv` — row-level accepted/excluded status and matched state.
- `data/reports/india_ev_chargers_boundary_summary.json` — counts, source and timestamp.
- `data/boundaries/india_states_boundary.geojson` — saved boundary input used by the app and planner.

The validation script **fails closed** if it cannot obtain a usable boundary layer. A rough bounding rectangle is not treated as proof that a point is inside India. Keep the candidate map separate until validation succeeds.

## Method and limitations

- **Inventory source:** dated snapshot, not live. Current operating status, charger availability, physical-site uniqueness, land access, grid capacity and permits are not verified.
- **Exact deduplication:** identical source-field groups are combined for review and retain duplicate occurrence counts; this does not claim unique physical stations.
- **DBSCAN:** spatial concentration only; not supervised ML and not a demand model.
- **Coverage planning:** candidate locations are screening suggestions only. State polygon containment does not verify road access, land suitability, flood risk or electrical interconnection.
- **Route planner:** routing, geocoding and elevation providers are best-effort public endpoints. Terrain/range/adoption results are explicit assumptions, not trained or validated forecasts.

## Project status

The application supports the nationwide schema and boundary checks. The final accepted record count depends on the downloaded boundary layer and is reported by `/api/health` and `data/reports/india_ev_chargers_boundary_summary.json`.
