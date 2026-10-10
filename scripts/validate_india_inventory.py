from __future__ import annotations

"""Validate the dated BEE EV charger inventory against Indian state/UT polygons.

Primary boundary source: NIC WebGIS administrative boundary layer. The validator
fails closed if the boundary source cannot be loaded; a bounding box is not a
substitute for point-in-polygon validation.
"""

import argparse
import csv
import json
import math
import re
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests
from shapely.geometry import Point, shape
from shapely.ops import unary_union
from shapely.validation import make_valid

ROOT = Path(__file__).resolve().parents[1]
INPUT_CSV = ROOT / "data" / "reports" / "india_ev_chargers_boundary_review.csv"
BOUNDARY_PATH = ROOT / "data" / "boundaries" / "india_states_boundary.geojson"
OUTPUT_GEOJSON = ROOT / "data" / "processed" / "india_ev_chargers_map.geojson"
AUDIT_CSV = ROOT / "data" / "reports" / "india_ev_chargers_boundary_audit.csv"
SUMMARY_JSON = ROOT / "data" / "reports" / "india_ev_chargers_boundary_summary.json"

BOUNDARY_URL = "https://webgis1.nic.in/nicstreet/rest/services/terraintile/MapServer/0/query"
BOUNDARY_SOURCE = (
    "NIC WebGIS International_boundary layer; service description cites digital "
    "administrative boundary data of Survey of India topomaps"
)
BOUNDARY_SOURCE_URL = "https://webgis1.nic.in/nicstreet/rest/services/terraintile/MapServer/0"
EXPECTED_STATE_UT_COUNT = 36

STATE_NAME_ALIASES = {
    "andaman & nicobar": "Andaman and Nicobar Islands",
    "andaman and nicobar": "Andaman and Nicobar Islands",
    "andaman & nicobar islands": "Andaman and Nicobar Islands",
    "andaman and nicobar islands": "Andaman and Nicobar Islands",
    "arunachal": "Arunachal Pradesh",
    "dadra & nagar haveli and daman & diu": "Dadra and Nagar Haveli and Daman and Diu",
    "dadra and nagar haveli and daman and diu": "Dadra and Nagar Haveli and Daman and Diu",
    "dadra and nagar haveli": "Dadra and Nagar Haveli and Daman and Diu",
    "daman and diu": "Dadra and Nagar Haveli and Daman and Diu",
    "jammu & kashmir": "Jammu and Kashmir",
    "jammu and kashmir": "Jammu and Kashmir",
    "jammu kashmir": "Jammu and Kashmir",
    "j&k": "Jammu and Kashmir",
    "orissa": "Odisha",
    "pondicherry": "Puducherry",
    "uttrakhand": "Uttarakhand",
    "uttaranchal": "Uttarakhand",
    "arunachal pradesh papum pare": "Arunachal Pradesh",
    "ut of d&nh and d&d": "Dadra and Nagar Haveli and Daman and Diu",
    "ut of d&nh and d&d daman": "Dadra and Nagar Haveli and Daman and Diu",
    "ut of d&nh and d&d diu": "Dadra and Nagar Haveli and Daman and Diu",
    "ut of d&nh and d&d silvassa(not in use)": "Dadra and Nagar Haveli and Daman and Diu",
}

CANONICAL_STATES = {
    "andhra pradesh": "Andhra Pradesh", "arunachal pradesh": "Arunachal Pradesh",
    "assam": "Assam", "bihar": "Bihar", "chandigarh": "Chandigarh",
    "chhattisgarh": "Chhattisgarh", "goa": "Goa", "gujarat": "Gujarat",
    "haryana": "Haryana", "himachal pradesh": "Himachal Pradesh",
    "jharkhand": "Jharkhand", "karnataka": "Karnataka", "kerala": "Kerala",
    "madhya pradesh": "Madhya Pradesh", "maharashtra": "Maharashtra",
    "manipur": "Manipur", "meghalaya": "Meghalaya", "mizoram": "Mizoram",
    "nagaland": "Nagaland", "odisha": "Odisha", "punjab": "Punjab",
    "rajasthan": "Rajasthan", "sikkim": "Sikkim", "tamil nadu": "Tamil Nadu",
    "telangana": "Telangana", "tripura": "Tripura", "uttar pradesh": "Uttar Pradesh",
    "west bengal": "West Bengal", "delhi": "Delhi", "ladakh": "Ladakh",
    "lakshadweep": "Lakshadweep", "puducherry": "Puducherry",
    "jammu and kashmir": "Jammu and Kashmir",
    "andaman and nicobar islands": "Andaman and Nicobar Islands",
    "dadra and nagar haveli and daman and diu": "Dadra and Nagar Haveli and Daman and Diu",
}


def normalize_state_name(value: Any) -> str:
    raw = re.sub(r"\\s+", " ", str(value or "").strip())
    key = raw.casefold()
    if key in STATE_NAME_ALIASES:
        return STATE_NAME_ALIASES[key]
    return CANONICAL_STATES.get(key, raw)


def _boundary_name(properties: dict[str, Any]) -> str:
    for key in ("STNAME", "stname", "STATE", "state", "STATE_NAME", "state_name", "name", "shapeName", "NAME_1", "NAME"):
        value = properties.get(key)
        if value:
            return normalize_state_name(value)
    return ""


def _usable_geometry(raw_geometry: dict[str, Any]) -> Any:
    geometry = shape(raw_geometry)
    if geometry.is_empty:
        raise ValueError("Boundary feature has empty geometry")
    if not geometry.is_valid:
        geometry = make_valid(geometry)
    if geometry.is_empty:
        raise ValueError("Boundary feature geometry could not be repaired")
    return geometry


def parse_boundary_geojson(payload: dict[str, Any]) -> dict[str, Any]:
    if payload.get("type") != "FeatureCollection":
        raise ValueError("Boundary response is not a GeoJSON FeatureCollection")
    features = payload.get("features") or []
    if len(features) < 30:
        raise ValueError(
            f"Boundary response has only {len(features)} features; expected roughly 36 state/UT polygons."
        )
    states: dict[str, Any] = {}
    for feature in features:
        if not feature.get("geometry"):
            continue
        state = _boundary_name(feature.get("properties") or {})
        if not state:
            continue
        geometry = _usable_geometry(feature["geometry"])
        states[state] = unary_union([states[state], geometry]) if state in states else geometry
    if len(states) < 30:
        raise ValueError(f"Could normalize only {len(states)} state/UT names from the boundary data")
    return {"states": states, "feature_count": len(features)}


def download_boundary(timeout: int = 45) -> dict[str, Any]:
    response = requests.get(
        BOUNDARY_URL,
        params={
            "where": "1=1", "outFields": "*", "outSR": "4326",
            "returnGeometry": "true", "f": "geojson",
        },
        headers={
            "User-Agent": "GRIDPULSE-EVPlanner/1.0 (India boundary validation)",
            "Accept": "application/geo+json,application/json",
        },
        timeout=timeout,
    )
    response.raise_for_status()
    payload = response.json()
    parsed = parse_boundary_geojson(payload)
    payload.setdefault("metadata", {})
    payload["metadata"].update({
        "source": BOUNDARY_SOURCE,
        "source_url": BOUNDARY_SOURCE_URL,
        "retrieved_at_utc": datetime.now(timezone.utc).isoformat(),
        "coordinate_order": "[longitude, latitude]",
        "state_ut_polygon_count_normalized": len(parsed["states"]),
    })
    BOUNDARY_PATH.parent.mkdir(parents=True, exist_ok=True)
    BOUNDARY_PATH.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    parsed["payload"] = payload
    return parsed


def load_boundary(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    parsed = parse_boundary_geojson(payload)
    parsed["payload"] = payload
    return parsed


def _is_finite_number(value: Any) -> bool:
    try:
        return math.isfinite(float(value))
    except (TypeError, ValueError):
        return False


def validate_rows(
    rows: list[dict[str, Any]], state_geometries: dict[str, Any]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Return accepted GeoJSON features plus a per-row audit."""
    if not state_geometries:
        raise ValueError("No state/UT polygons supplied; refusing to certify any coordinates")
    india_geometry = unary_union(list(state_geometries.values()))
    accepted: list[dict[str, Any]] = []
    audit: list[dict[str, Any]] = []
    for row in rows:
        state = normalize_state_name(row.get("state"))
        lat_raw, lon_raw = row.get("latitude"), row.get("longitude")
        status = ""
        matched_states: list[str] = []
        inside_india = False
        inside_reported_state = False
        lat = lon = None
        if not _is_finite_number(lat_raw) or not _is_finite_number(lon_raw):
            status = "invalid_coordinate"
        else:
            lat, lon = float(lat_raw), float(lon_raw)
            if not (-90 <= lat <= 90 and -180 <= lon <= 180):
                status = "coordinate_out_of_range"
            elif abs(lat - lon) < 1e-9:
                status = "suspicious_latitude_equals_longitude"
            else:
                point = Point(lon, lat)
                inside_india = bool(india_geometry.covers(point))
                if not inside_india:
                    status = "outside_india_boundary"
                elif state not in state_geometries:
                    status = "reported_state_missing_from_boundary_data"
                else:
                    inside_reported_state = bool(state_geometries[state].covers(point))
                    if inside_reported_state:
                        status = "accepted_inside_india_and_reported_state"
                    else:
                        for matched_name, polygon in state_geometries.items():
                            if polygon.covers(point):
                                matched_states.append(matched_name)
                        status = "reported_state_boundary_mismatch"
        audit_row = dict(row)
        audit_row.update({
            "normalized_state": state,
            "inside_india_boundary": inside_india,
            "inside_reported_state_boundary": inside_reported_state,
            "boundary_matched_state_names": ";".join(matched_states),
            "boundary_validation_status": status,
        })
        audit.append(audit_row)
        if status == "accepted_inside_india_and_reported_state":
            props: dict[str, Any] = {}
            for key, value in row.items():
                if key in {"latitude", "longitude"}:
                    continue
                if value is None:
                    props[key] = None
                elif isinstance(value, float) and not math.isfinite(value):
                    props[key] = None
                else:
                    props[key] = value
            props.update({
                "state": state,
                "inside_india_boundary": True,
                "inside_reported_state_boundary": True,
                "coordinate_validation_status": status,
                "boundary_source": BOUNDARY_SOURCE,
            })
            accepted.append({
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [lon, lat]},
                "properties": props,
            })
    return accepted, audit


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8-sig")
        return
    columns: list[str] = []
    for row in rows:
        for key in row:
            if key not in columns:
                columns.append(key)
    with path.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def validate_inventory(
    input_csv: Path = INPUT_CSV,
    boundary_path: Path = BOUNDARY_PATH,
    output_geojson: Path = OUTPUT_GEOJSON,
    audit_csv: Path = AUDIT_CSV,
    summary_json: Path = SUMMARY_JSON,
    download_if_missing: bool = True,
) -> dict[str, Any]:
    if not input_csv.exists():
        raise FileNotFoundError(f"Inventory review CSV not found: {input_csv}")
    used_cached_boundary = boundary_path.exists()
    if used_cached_boundary:
        boundary = load_boundary(boundary_path)
    elif download_if_missing:
        boundary = download_boundary()
    else:
        raise FileNotFoundError(f"State/UT boundary file not found: {boundary_path}")
    with input_csv.open("r", newline="", encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))
    accepted, audit = validate_rows(rows, boundary["states"])
    output_geojson.parent.mkdir(parents=True, exist_ok=True)
    meta = {
        "source": "BEE EV Public Charging Stations PDF snapshot",
        "source_snapshot_date": "2025-10-26",
        "boundary_validation_status": "point_in_polygon_passed_for_all_output_features",
        "boundary_source": BOUNDARY_SOURCE,
        "boundary_source_url": BOUNDARY_SOURCE_URL,
        "boundary_polygon_count": boundary["feature_count"],
        "normalized_state_ut_polygon_count": len(boundary["states"]),
        "validation_time_utc": datetime.now(timezone.utc).isoformat(),
        "exact_source_field_groups_audited": len(rows),
        "accepted_features": len(accepted),
        "excluded_for_review": len(audit) - len(accepted),
        "important_note": "Inventory snapshot only. Current charger operational status and physical-site uniqueness are not verified.",
    }
    output_geojson.write_text(json.dumps({
        "type": "FeatureCollection",
        "name": "GRIDPULSE India-wide EV charger inventory",
        "metadata": meta, "features": accepted,
    }, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    _write_csv(audit_csv, audit)
    accepted_by_state = Counter(f["properties"]["state"] for f in accepted)
    status_counts = Counter(r["boundary_validation_status"] for r in audit)
    summary = {
        **meta,
        "accepted_by_state": dict(sorted(accepted_by_state.items())),
        "audit_status_counts": dict(sorted(status_counts.items())),
        "boundary_file": str(boundary_path),
        "output_geojson": str(output_geojson),
        "audit_csv": str(audit_csv),
        "boundary_validation_source_is_live_query": not used_cached_boundary,
    }
    summary_json.parent.mkdir(parents=True, exist_ok=True)
    summary_json.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-csv", type=Path, default=INPUT_CSV)
    parser.add_argument("--boundary", type=Path, default=BOUNDARY_PATH)
    parser.add_argument("--output", type=Path, default=OUTPUT_GEOJSON)
    parser.add_argument("--audit", type=Path, default=AUDIT_CSV)
    parser.add_argument("--summary", type=Path, default=SUMMARY_JSON)
    parser.add_argument("--no-download", action="store_true", help="Do not download boundary data if the local file is absent")
    args = parser.parse_args(argv)
    try:
        summary = validate_inventory(
            args.input_csv, args.boundary, args.output, args.audit, args.summary,
            not args.no_download,
        )
    except Exception as exc:
        print(f"BOUNDARY VALIDATION FAILED: {exc}", file=sys.stderr)
        print(
            "No validated India map was produced. Keep the candidate inventory separate "
            "until the official boundary source is available.",
            file=sys.stderr,
        )
        return 2
    print("India boundary validation completed.")
    print(f"Grouped records audited: {summary['exact_source_field_groups_audited']}")
    print(f"Accepted point records: {summary['accepted_features']}")
    print(f"Excluded for review: {summary['excluded_for_review']}")
    print(f"Boundary polygons: {summary['boundary_polygon_count']} source features / {summary['normalized_state_ut_polygon_count']} normalized state/UT polygons")
    print(f"Validated map: {summary['output_geojson']}")
    print(f"Audit CSV: {summary['audit_csv']}")
    print(f"Summary JSON: {args.summary}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
