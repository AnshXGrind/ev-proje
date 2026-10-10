# EV Infrastructure Planner

A landscape-aware, evidence-led EV charging infrastructure planning project.

## Initial pipeline

1. Fetch mapped roads and charger features.
2. Normalize station records and preserve source provenance.
3. Validate coordinates and missing fields.
4. Generate candidate locations from mapped points of interest.
5. Render an interactive HTML map.

## Important limitations

OpenStreetMap coverage can be incomplete.
Mapped candidate sites are not confirmed available land.
Road geometry is not measured traffic data.
Actual local electrical-grid capacity requires verified network information.

## Initial usage

Use the Python executable in `.venv` and run the scripts in `scripts/`.
See `configs/regions.yaml` for supported region IDs.

OpenStreetMap data attribution and licensing must be respected.