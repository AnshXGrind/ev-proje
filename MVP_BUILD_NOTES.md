# Implementation Notes

## Current components

- FastAPI serves the dashboard and JSON endpoints.
- The dashboard provides inventory summaries, region filters, station search, CSV export and a map of reported charger locations.
- DBSCAN groups approximate charger coordinates by geographic proximity.
- The baseline planner ranks midpoint candidates using straight-line distances and user-provided budget assumptions.
- The Route Planner compares a selected driving route with nearby inventory and sampled elevation data.

## Data requirements

The local file `data/processed/north_india_ev_chargers_map.geojson` is required for inventory analysis and is not stored in this repository. The inventory is a dated public snapshot; it does not provide live operating status or charging-session history.

## Limits

Candidate points need checks for land availability, road access, permissions and safety. A measured demand forecast requires traffic or charging-session observations. Electrical feasibility requires verified feeder, transformer and load information from the relevant utility.
