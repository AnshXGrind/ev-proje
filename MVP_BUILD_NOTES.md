# Implementation Notes

## Current components

- FastAPI serves the dashboard and JSON endpoints.
- The dashboard provides inventory summaries, region filters, station search, CSV export and a map of reported charger locations.
- DBSCAN groups approximate charger coordinates by geographic proximity.
- Inventory filters and route corridor matching support the seven original North Indian regions, eight North-Eastern states and Bihar, Uttar Pradesh and Madhya Pradesh when the supplemental GeoJSON files are present.
- The baseline planner ranks midpoint candidates using straight-line distances and user-provided budget assumptions.
- The Route Planner compares a selected driving route with nearby inventory and sampled elevation data.

## Data requirements

The local file `data/processed/north_india_ev_chargers_map.geojson` is required. The optional `data/processed/northeast_ev_chargers_map.geojson` file enables Assam, Arunachal Pradesh, Manipur, Meghalaya, Mizoram, Nagaland, Sikkim and Tripura. The supplemental file contains 645 mapped source records from the BEE snapshot labelled through 26 October 2025; it is not a live status feed or a verified count of physical operating sites. The optional `data/processed/central_states_ev_chargers_map.geojson` file contains 4,080 mapped records from Bihar, Uttar Pradesh and Madhya Pradesh in the same dated BEE snapshot. These records are not live verified or guaranteed unique physical sites. The inventory does not provide charging-session history.

## Limits

Candidate points need checks for land availability, road access, permissions and safety. A measured demand forecast requires traffic or charging-session observations. Electrical feasibility requires verified feeder, transformer and load information from the relevant utility.
