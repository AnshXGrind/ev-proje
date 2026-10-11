# EV-Yojna: Bihar, Uttar Pradesh and Madhya Pradesh add-on

## Install

1. Extract this ZIP into the existing repository root, for example `C:\EV\ev proje`. The archive contains the GeoJSON at `data/processed/central_states_ev_chargers_map.geojson`.
2. Open PowerShell in the repository root and run:

   ```powershell
   powershell.exe -NoProfile -ExecutionPolicy Bypass -File ".\update_gridpulse_central_expansion.ps1" -ProjectRoot "C:\EV\ev proje"
   ```

   The updater downloads the current code from the repository's `main` branch, backs up existing code first, and does not require Git. Internet access to `raw.githubusercontent.com` is required.
3. Stop the running server with Ctrl+C, then restart:

   ```powershell
   .\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
   ```
4. Check `http://127.0.0.1:8000/api/health`. The new fields should include `central_inventory_loaded: true` and `central_records: 4080`.
5. Run the new tests:

   ```powershell
   .\.venv\Scripts\python.exe -m pytest tests\test_central_support.py tests\test_northeast_support.py -q
   ```

## Included data

- `data/processed/central_states_ev_chargers_map.geojson`: 4,080 mapped, exact-source-field-grouped records across Bihar, Uttar Pradesh and Madhya Pradesh.
- `data/raw/central_states_ev_chargers_raw.csv`: 4,308 parsed source rows with PDF page references.
- `data/reports/central_states_ev_chargers_exact_dedup_review.csv`: 4,102 exact-field groups, including coordinate-quality review flags.

Source: BEE EV Public Charging Stations PDF labelled data through 26 October 2025. These are dated source records, not a live charger-status feed or a verified count of unique operating physical sites. Records excluded from the map by the broad coordinate screens remain in the review CSV. State envelopes are preliminary screening boxes, not official administrative boundaries.
