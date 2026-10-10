from __future__ import annotations

import json

from app import main


NORTHEAST_STATES = {
    "Assam", "Arunachal Pradesh", "Manipur", "Meghalaya",
    "Mizoram", "Nagaland", "Sikkim", "Tripura",
}


def test_all_northeast_states_have_screening_envelopes():
    assert NORTHEAST_STATES.issubset(set(main.STATE_ORDER))
    assert NORTHEAST_STATES.issubset(set(main.STATE_ENVELOPES))


def test_arunachal_short_alias_is_normalized():
    assert main.normalize_state("Arunachal") == "Arunachal Pradesh"


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


def test_optional_northeast_inventory_is_loaded_alongside_base(tmp_path, monkeypatch):
    base_path = tmp_path / "north_india_ev_chargers_map.geojson"
    ne_path = tmp_path / "northeast_ev_chargers_map.geojson"

    base_path.write_text(
        json.dumps({
            "type": "FeatureCollection",
            "features": [_feature("Delhi", 28.6, 77.1)],
        }),
        encoding="utf-8",
    )
    ne_path.write_text(
        json.dumps({
            "type": "FeatureCollection",
            "features": [_feature("Assam", 26.1, 91.8)],
        }),
        encoding="utf-8",
    )

    monkeypatch.setattr(main, "DATA_PATH", base_path)
    monkeypatch.setattr(main, "NE_DATA_PATH", ne_path)
    main.load_records.cache_clear()
    try:
        records = main.load_records()
        assert len(records) == 2
        assert {row["state"] for row in records} == {"Delhi", "Assam"}
        assert main._unique_coordinate_groups(records)
    finally:
        main.load_records.cache_clear()
