# Repository review and four-hour MVP scope

## Starting point inspected

The public `AnshXGrind/ev-proje` main branch contained:
- `configs/regions.yaml`
- `scripts/fetch_roads.py`, `fetch_chargers.py`, `clean_data.py`, `validate_data.py`, `build_candidates.py`, `render_map.py`, `render_north_india_map.py`
- `src/evplanner/config.py` and geospatial I/O helper
- `pyproject.toml`, `requirements.txt`, and a short README

There was no working FastAPI endpoint layer or application dashboard. The repository's `.gitignore` excludes generated data beneath `data/processed`, so the extracted inventory has to exist locally at runtime.

## This MVP adds

- A single local FastAPI server serving the frontend and JSON API.
- North India inventory health, metrics, state and charger-type analytics, station search, and CSV export.
- Interactive state-filtered Leaflet map with clustered charger markers and charger-detail popups.
- Scikit-learn DBSCAN clustering using Haversine distance over approximate coordinate groups.
- Budget configurable midpoint gap-screening planner and CSV export.
- Approximate broad region envelopes to prevent obvious state-label/coordinate anomalies from being used as planning endpoints.

## Deliberate scope limits

A four-hour MVP cannot honestly train a validated EV-demand forecaster without suitable session time-series targets. It also cannot verify real grid hosting capacity without feeder/transformer topology and measurements. The UI exposes these as data gaps instead of inventing results.
