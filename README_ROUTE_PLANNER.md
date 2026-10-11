# Route Planner

This module adds a Route Planner page to GRIDPULSE. In India-wide mode, manual coordinates, routed geometry and proposed candidate points must pass the validated India boundary check.

## Install on Windows

1. Extract this patch ZIP into the existing repository root (for example `C:\EV\ev proje`) and allow files to merge.
2. Run from PowerShell in the repo root:

   ```powershell
   powershell.exe -NoProfile -ExecutionPolicy Bypass -File "C:\EV\ev proje\install_route_planner.ps1"
   ```

3. Stop the old Uvicorn process with Ctrl+C, then restart:

   ```powershell
   .\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
   ```

4. Open `http://127.0.0.1:8000/route-planner` or click Route Planner from the main dashboard.

## What it adds

- Origin and destination search (default example: Narnaul, Haryana → Jammu, J&K).
- OSRM driving route geometry, distance, duration and road labels.
- Elevation samples from Open-Meteo/Copernicus GLO-90, terrain segmentation and a remote/seasonal risk override.
- A spacing formula based on terrain class, usable vehicle range, reserve, conservative/base/accelerated adoption scenario, and optional traffic/EV-share inputs.
- Side-aware existing inventory proximity checks and candidate coordinates. The dated BEE inventory is loaded locally; the API does not scrape charging stations.
- A 20 km general public-charger reference and 100 km long-range/heavy-duty fast-charger reference from EVCI-2024 guidance are reported separately from the more conservative spacing rules. It does not certify regulatory compliance.
- Optional illustrative future public charging sessions/day and energy/day when users provide traffic, EV share, public-charge share, growth and session-energy assumptions.
- CSV export for candidates, full JSON export, and a downloadable grid-feasibility utility-data template.

## What this version can and cannot estimate

Route spacing is calculated from explicit rules and user-selected assumptions; it is not trained on measured charging sessions. The main dashboard uses DBSCAN to group nearby charger coordinates. Scenario results are estimates from the supplied inputs, not measured demand forecasts.

Route geometry comes from the public OSRM driving router over OpenStreetMap data, place lookup from Nominatim, and elevations from Open-Meteo. These services are best-effort demo services and may time out or change. Requests are cached in process; geocoding is rate-limited. They need internet for new places/routes/elevation.

The model does not establish EV legality on every road, road surface/width, snow/landslide/avalanche closures, right-of-way, land ownership, station uptime, traffic counts, feeder/transformer capacity, voltage drops, outage risk, or grid hosting capacity. Remote/high-altitude routes require manual confirmation with the relevant road authorities and utility. Grid readiness remains **UNVERIFIED** until utility feeder/transformer and load data are imported and assessed.

## Inputs and formula

- `usable_range = vehicle_real_world_range × (1 − reserve_fraction) × terrain_energy_factor`
- `suggested general spacing = min(20 km EVCI-2024 policy reference, policy reference × terrain_factor × scenario_factor × demand_factor × remote-risk factor, usable_range × 0.35)`
- `suggested fast-review spacing = min(100 km policy reference, 100 km × terrain_fast_factor × scenario_factor × demand_factor × remote-risk factor, usable_range × 0.75)`
- Terrain class is estimated from elevation and sampled grade proxies; manually override to high-Himalaya or remote/seasonal when known.
- Demand factor bands are heuristic and labelled in the API output. They must be recalibrated with measured traffic/session data before any real investment decisions.

## Tests

The installer compiles `app/route_api.py` and runs `tests/test_route_planner_model.py`. The full existing suite can be run separately with `.\.venv\Scripts\python.exe -m pytest tests -q` (it can take several minutes because the current tests load a large inventory).
