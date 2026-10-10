# North-East charger inventory supplement

This data bundle adds the eight North-Eastern states to the EV planner. Extract the archive into the repository root (for example `C:\EV\ev proje`) and allow the `data` folder to merge.

The application expects the main file at:

`data/processed/northeast_ev_chargers_map.geojson`

The map dataset contains 645 point records from the BEE public charging-station PDF inventory labelled as data through 26 October 2025. Exact repeats of source fields have been grouped; 645 does not mean 645 verified unique operational physical stations. Operating status has not been checked live.

The archive also includes the raw extracted rows and a review CSV. Use the review file to check coordinate anomalies and duplicates; do not treat coordinate matches as proof that two records are the same physical site.

After extracting, restart the FastAPI server and check:

`http://127.0.0.1:8000/api/health`

Expected fields include `northeast_inventory_loaded: true`, `northeast_records: 645`, and `inventory_records: 5160` for the supplied base inventory combined with this supplement.
