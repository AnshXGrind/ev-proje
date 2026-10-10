from __future__ import annotations

from shapely.geometry import box

from app import main
from scripts.validate_india_inventory import validate_rows


def test_state_order_includes_all_36_states_and_union_territories():
    assert len(main.STATE_ORDER) == 36
    assert "Kerala" in main.STATE_ORDER
    assert "Tamil Nadu" in main.STATE_ORDER
    assert "Maharashtra" in main.STATE_ORDER
    assert "Andaman and Nicobar Islands" in main.STATE_ORDER
    assert "Lakshadweep" in main.STATE_ORDER


def test_state_aliases_cover_common_source_spellings():
    assert main.normalize_state("Orissa") == "Odisha"
    assert main.normalize_state("Pondicherry") == "Puducherry"
    assert main.normalize_state("Andaman & Nicobar Islands") == "Andaman and Nicobar Islands"


def test_all_india_filter_aliases_are_supported():
    assert main.is_all_regions("All India")
    assert main.is_all_regions("All North India")
    assert main.is_all_regions("All covered regions")
    assert not main.is_all_regions("Maharashtra")


def test_validator_keeps_only_points_inside_india_and_reported_state():
    # Synthetic polygons make the test deterministic and do not depend on a live boundary service.
    state_geometries = {
        "Kerala": box(75, 9, 77, 12),
        "Tamil Nadu": box(77, 9, 79, 12),
    }
    rows = [
        {"state": "Kerala", "latitude": 10.5, "longitude": 76.0, "location": "inside"},
        {"state": "Tamil Nadu", "latitude": 10.5, "longitude": 76.0, "location": "wrong state"},
        {"state": "Kerala", "latitude": 20.0, "longitude": 85.0, "location": "outside"},
        {"state": "Kerala", "latitude": 10.5, "longitude": 10.5, "location": "suspicious equal coordinates"},
    ]
    accepted, audit = validate_rows(rows, state_geometries)
    assert [f["properties"]["location"] for f in accepted] == ["inside"]
    assert all(f["properties"]["inside_india_boundary"] for f in accepted)
    assert all(f["properties"]["inside_reported_state_boundary"] for f in accepted)
    assert [row["boundary_validation_status"] for row in audit] == [
        "accepted_inside_india_and_reported_state",
        "reported_state_boundary_mismatch",
        "outside_india_boundary",
        "suspicious_latitude_equals_longitude",
    ]
