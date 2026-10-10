# GRIDPULSE MVP

The original North India MVP has been extended to support the India-wide inventory, with 36 state/UT selectors and boundary-aware filtering.

To use the nationwide map, extract the India-wide data bundle and run:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-mvp.txt
.\.venv\Scripts\python.exe scripts\validate_india_inventory.py
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

The validator uses the NIC WebGIS administrative state/UT polygons and only exports points that fall inside both India and the state/UT reported in the source. Excluded records remain in the audit CSV. If the boundary service is unavailable or incomplete, validation exits with an error and does not certify the candidate inventory.

The source is a BEE public charging-station snapshot dated 2025-10-26. It is not a live operational-status feed. Location records and spatial clusters are not verified unique physical chargers, utilization, grid capacity or demand predictions.

See `readme.md` and `README_ROUTE_PLANNER.md` for current limitations and details.
