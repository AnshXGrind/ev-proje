# EV-Yojna — India-wide inventory and boundary validation

This expansion adds a nationwide BEE source inventory and a required point-in-polygon validation step. It is a research/planning dataset, not a live charger-status service.

## Source data

- Charger records: Bureau of Energy Efficiency (BEE), *EV Public Charging Stations Data till 26 October 2025*. The PDF is a dated snapshot and does not verify that every listed point is currently operational.
- Administrative boundaries: Survey of India State Boundary GeoJSON distributed by the National Water Data Portal / National Water Informatics Centre (NWIC). The preparation script downloads the official resource to the project data/raw folder if it is not already present.
- The source PDF was parsed into **39,628 candidate coordinate rows**. This is a count of rows extracted from the source PDF, not a count of verified unique physical sites. Some source rows can duplicate the same coordinate, and wrapped PDF text can require manual review.

Official sources:
- BEE data page: https://www.beeindia.gov.in/show_content.php?lang=1&level=2&lid=67&ls_id=345
- Survey of India / NWIC state boundary dataset: https://nwdp.nwic.gov.in/dataset/state-boundary
- Boundary ZIP: https://nwdp.nwic.gov.in/dataset/dd960900-34cc-4486-a95c-83200d2f2c7b/resource/f039e721-132c-4a24-9e5e-07af03064b4d/download/state_NWIC_GeoJSON.zip

## Install on Windows without Git

1. Stop the running app with Ctrl+C in its Uvicorn terminal.
2. Extract the India-wide bundle into the existing project root, C:\EV\ev proje. Allow the new data/raw/india_ev_chargers_raw.geojson and updater file to be added.
3. Run from PowerShell:

       Set-Location "C:\EV\ev proje"
       powershell.exe -NoProfile -ExecutionPolicy Bypass -File "C:\EV\ev proje\update_gridpulse_india_expansion.ps1" -ProjectRoot "C:\EV\ev proje"

   This downloads the code patch to a staging directory, backs up existing code, compiles the Python modules, downloads the official boundary data, builds the validated nationwide dataset and audit reports, and runs focused tests. It does not require the Git command-line tool.

4. Only after the installer reports SUCCESS, start the app:

       Set-Location "C:\EV\ev proje"
       .\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000

5. Open http://127.0.0.1:8000 and check http://127.0.0.1:8000/api/health. Verify india_inventory_loaded is true and boundary_validation_passed is true.

## What the validator does

- Requires a complete boundary layer representing all 36 current states and Union Territories. It stops instead of using a partial or unrecognized layer.
- Checks coordinate ranges and tests each source point against the union of all official state/UT polygons using Shapely point-in-polygon geometry.
- Keeps source state labels when the corresponding state polygon covers the coordinate; corrects labels only when exactly one different polygon uniquely covers the point.
- Excludes out-of-country points, missing/non-point/invalid coordinates, ambiguous state-border points that do not match the source state, and points with no state-polygon match from the planner dataset.
- Retains every input row in data/reports/india_ev_chargers_boundary_audit.csv with a status and the inclusion decision, so exclusions can be reviewed.
- Writes data/reports/india_ev_chargers_boundary_summary.csv with counts for all 36 states/UTs.
- Verifies every included output coordinate again before writing the validated map.
- Checks manual coordinates, route samples and proposed route candidate points against the same India geometry when the national inventory has passed validation.
- Fails closed when the raw India-wide source exists but has not yet passed boundary validation; it will not silently show the old regional subset as nationwide coverage.

## Output files

- data/processed/india_state_boundaries.geojson — official state/UT polygons used for validation.
- data/processed/india_ev_chargers_map.geojson — accepted features plus validation metadata; consumed by the dashboard and route planner.
- data/reports/india_ev_chargers_boundary_audit.csv — full source-row audit, including exclusions and state-label corrections.
- data/reports/india_ev_chargers_boundary_summary.csv — per-state/UT accepted/corrected/excluded row counts.

If boundary download fails, download the ZIP directly from the official resource:
https://nwdp.nwic.gov.in/dataset/dd960900-34cc-4486-a95c-83200d2f2c7b/resource/f039e721-132c-4a24-9e5e-07af03064b4d/download/state_NWIC_GeoJSON.zip

Save it as data/raw/state_NWIC_GeoJSON.zip under the project root and rerun the installer.

## Limitations

- The input source snapshot is dated 26 October 2025; operating status is not live-verified.
- Candidate rows are not guaranteed unique physical stations. Do not report the input row count as a verified station total.
- Coordinates on or very near administrative boundary lines can be ambiguous because of source precision or polygon precision. Such cases are flagged for review rather than moved arbitrarily.
- Polygon inclusion proves that the coordinate is inside the supplied administrative polygon; it does not independently prove the source location text, accessibility, land availability, road access, electricity connection or grid hosting capacity.
- Candidate locations generated by the route planner are conceptual screening points, not approved construction sites.
