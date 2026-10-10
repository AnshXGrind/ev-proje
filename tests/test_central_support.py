from __future__ import annotations

import json

from app import main
from app import route_api


CENTRAL_STATES = {"Bihar", "Uttar Pradesh", "Madhya Pradesh"}


def _feature(state: str, lat: float, lon: float) -> dict:
    return {
        "type": "Feature",
        "geometry": {"type": "Point", "coordinates": [lon, lat]},
        "properties": {
            "state": state,
            "district": "Test district",
            "city_village": "Test town",
            "location": "Test charging location",
            "cpo_name": "Test operator",
            "ownership_type": "Public",
            "charger_type": "Test connector",
            "charger_rating_kw": 60,
            "connector_rating_kw": 60,
            "number_of_connectors": 2,
            "source_pages": "1",
        },
    }


def test_central_states_have_screening_envelopes():
    assert CENTRAL_STATES.issubset(set(main.STATE_ORDER))
    assert CENTRAL_STATES.issubset(set(main.STATE_ENVELOPES))


def test_optional_central_inventory_loads_alongside_base(tmp_path, monkeypatch):
    base_path = tmp_path / "north_india_ev_chargers_map.geojson"
    ne_path = tmp_path / "northeast_ev_chargers_map.geojson"
    central_path = tmp_path / "central_states_ev_chargers_map.geojson"

    base_path.write_text(
        json.dumps({
            "type": "FeatureCollection",
            "features": [_feature("Delhi", 28.6, 77.1)],
        }),
        encoding="utf-8",
    )
    central_path.write_text(
        json.dumps({
            "type": "FeatureCollection",
            "features": [
                _feature("Bihar", 25.5941, 85.1376),
                _feature("Uttar Pradesh", 26.8467, 80.9462),
                _feature("Madhya Pradesh", 23.2599, 77.4126),
            ],
        }),
        encoding="utf-8",
    )

    monkeypatch.setattr(main, "DATA_PATH", base_path)
    monkeypatch.setattr(main, "NE_DATA_PATH", ne_path)
    monkeypatch.setattr(main, "CENTRAL_DATA_PATH", central_path)
    monkeypatch.setattr(main, "INDIA_DATA_PATH", tmp_path / "india_ev_chargers_map.geojson")
    monkeypatch.setattr(main, "INDIA_BOUNDARY_PATH", tmp_path / "india_state_boundaries.geojson")
    main.load_records.cache_clear()
    try:
        records = main.load_records()
        assert len(records) == 4
        assert {row["state"] for row in records} == {"Delhi", *CENTRAL_STATES}
        assert main._unique_coordinate_groups(records)
    finally:
        main.load_records.cache_clear()



def test_route_inventory_loader_includes_central_states(tmp_path, monkeypatch):
    base_path = tmp_path / "north_india_ev_chargers_map.geojson"
    ne_path = tmp_path / "northeast_ev_chargers_map.geojson"
    central_path = tmp_path / "central_states_ev_chargers_map.geojson"

    base_path.write_text(
        json.dumps({
            "type": "FeatureCollection",
            "features": [_feature("Delhi", 28.6, 77.1)],
        }),
        encoding="utf-8",
    )
    central_path.write_text(
        json.dumps({
            "type": "FeatureCollection",
            "features": [
                _feature("Bihar", 25.5941, 85.1376),
                _feature("Uttar Pradesh", 26.8467, 80.9462),
                _feature("Madhya Pradesh", 23.2599, 77.4126),
            ],
        }),
        encoding="utf-8",
    )

    monkeypatch.setattr(route_api, "DATA_PATH", base_path)
    monkeypatch.setattr(route_api, "NE_DATA_PATH", ne_path)
    monkeypatch.setattr(route_api, "CENTRAL_DATA_PATH", central_path)
    monkeypatch.setattr(route_api, "INDIA_DATA_PATH", tmp_path / "india_ev_chargers_map.geojson")
    monkeypatch.setattr(route_api, "INDIA_BOUNDARY_PATH", tmp_path / "india_state_boundaries.geojson")
    route_api._inventory_groups.cache_clear()
    try:
        groups = route_api._inventory_groups()
        assert len(groups) == 4
        assert {"Delhi", *CENTRAL_STATES}.issubset({group["state"] for group in groups})
    finally:
        route_api._inventory_groups.cache_clear()
