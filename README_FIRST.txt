GRIDPULSE INDIA-WIDE EXPANSION BUNDLE

1. Stop the running Uvicorn server with Ctrl+C.
2. Extract this ZIP into your existing project root: C:\EV\ev proje
3. Open PowerShell and run:

   Set-Location "C:\EV\ev proje"
   powershell.exe -NoProfile -ExecutionPolicy Bypass -File "C:\EV\ev proje\update_gridpulse_india_expansion.ps1" -ProjectRoot "C:\EV\ev proje"

The updater downloads the matching code patch from the feature branch, backs up overwritten code, runs the boundary validation, writes the full exclusion audit and state/UT summary, and executes focused tests. Git CLI is not required.

The source rows were parsed from the BEE PDF dated 26 October 2025. The bundle is not yet a boundary-validated output dataset. Validation is performed on your machine against the Survey of India / NWIC administrative-boundary GeoJSON. The app fails closed instead of using the older partial regional inventory if national validation has not succeeded.

If the official boundary ZIP cannot download automatically, the updater prints the official URL and the required save location. Download the boundary ZIP there and rerun the command.
