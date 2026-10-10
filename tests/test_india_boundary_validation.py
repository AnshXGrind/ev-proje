from __future__ import annotations

import json

from shapely.geometry import mapping, box

from app.geo_boundaries import (
    STATE_NAMES,
    load_state_boundaries,
    matching_states,
    normalize_state_name,
    point_inside_india,
    point_inside_state,
)


def _write_test_boundaries(path):
    features = []
    # Isolated, non-overlapping test polygons; these test the validator mechanics,
    # not the real-world shape/position of India.
    for index, state in enumerate(STATE_NAMES):
        x = index * 10.0
        polygon = box(x, 0, x + 4, 4)
        features.append({
            "type": "Feature",
            "geometry": mapping(polygon),
            "properties": {"NAME_1": state},
        })
    path.write_text(json.dumps({
        "type": "FeatureCollection",
        "features": features,
    }), encoding="utf-8")


def test_boundary_loader_requires_all_36_state_ut_polygons(tmp_path):
    path = tmp_path / "bounds.geojson"
    _write_test_boundaries(path)
    polygons, country, missing = load_state_boundaries(path)
    assert set(polygons) == set(STATE_NAMES)
    assert not missing
    assert country.is_valid


def test_point_in_india_and_state_polygon(tmp_path):
    path = tmp_path / "bounds.geojson"
    _write_test_boundaries(path)
    ap_lon = STATE_NAMES.index("Andhra Pradesh") * 10.0 + 2.0
    assert point_inside_india(2, 2, path)
    assert point_inside_state("Andhra Pradesh", 2, ap_lon, path)
    assert not point_inside_india(20, 20, path)
    assert not point_inside_state("Andhra Pradesh", 2, 2, path)
    assert matching_states(2, 2, path) == ["Andaman and Nicobar Islands"]


def test_state_name_aliases_cover_common_inventory_variants():
    assert normalize_state_name("Andaman & Nicobar") == "Andaman and Nicobar Islands"
    assert normalize_state_name("Pondicherry") == "Puducherry"
    assert normalize_state_name("UT OF D&NH AND D&D") == "Dadra and Nagar Haveli and Daman and Diu"
    assert normalize_state_name("Jammu & Kashmir") == "Jammu and Kashmir"


def test_official_boundary_spelling_variants_normalize_to_canonical_names():
    assert normalize_state_name("Andaman & Nicobar Island") == "Andaman and Nicobar Islands"
    assert normalize_state_name("Arunāchal Pradesh") == "Arunachal Pradesh"
    assert normalize_state_name("Dādra and Nagar Haveli and Damān and Diu") == (
        "Dadra and Nagar Haveli and Daman and Diu"
    )
    assert normalize_state_name("Dadra and Nagar Haveli, Daman and Diu") == (
        "Dadra and Nagar Haveli and Daman and Diu"
    )
