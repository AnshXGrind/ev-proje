from __future__ import annotations

import csv
import json
import math
import shutil
import sys
import urllib.request
import zipfile
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SOURCE_PATH = ROOT / "data" / "raw" / "india_ev_chargers_raw.geojson"
BOUNDARY_ZIP_PATH = ROOT / "data" / "raw" / "state_NWIC_GeoJSON.zip"
BOUNDARY_PATH = ROOT / "data" / "processed" / "india_state_boundaries.geojson"
OUTPUT_PATH = ROOT / "data" / "processed" / "india_ev_chargers_map.geojson"
AUDIT_PATH = ROOT / "data" / "reports" / "india_ev_chargers_boundary_audit.csv"
SUMMARY_PATH = ROOT / "data" / "reports" / "india_ev_chargers_boundary_summary.csv"
BOUNDARY_URL = (
    "https://nwdp.nwic.gov.in/dataset/dd960900-34cc-4486-a95c-83200d2f2c7b/"
    "resource/f039e721-132c-4a24-9e5e-07af03064b4d/download/state_nwic_geojson.zip"
)
SOURCE_DESCRIPTION = (
    "Survey of India State Boundary GeoJSON published through the National Water Data Portal "
    "(NWIC), resource metadata updated 2025-05-01."
)

sys.path.insert(0, str(ROOT))
from app.geo_boundaries import (  # noqa: E402
    STATE_NAMES, load_state_boundaries, matching_states, normalize_state_name, point_inside_india
)

def _download_boundary() -> None:
    BOUNDARY_ZIP_PATH.parent.mkdir(parents=True, exist_ok=True)
    print("Downloading the official Survey of India/NWIC state-boundary GeoJSON...")
    request = urllib.request.Request(
        BOUNDARY_URL,
        headers={"User-Agent": "GRIDPULSE-IndiaBoundaryAudit/1.0"},
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response, BOUNDARY_ZIP_PATH.open("wb") as target:
            shutil.copyfileobj(response, target)
    except Exception as exc:
        try:
            BOUNDARY_ZIP_PATH.unlink(missing_ok=True)
        except Exception:
            pass
        raise RuntimeError(
            "Could not download the official boundary archive. Download it in a browser from:\n"
            f"{BOUNDARY_URL}\nSave it as:\n{BOUNDARY_ZIP_PATH}\nThen run this script again. "
            f"Provider error: {exc}"
        ) from exc

def _extract_boundaries() -> None:
    if BOUNDARY_PATH.exists():
        try:
            load_state_boundaries(BOUNDARY_PATH)
            return
        except Exception:
            print("Existing boundary file is incomplete or invalid; rebuilding from source archive.")
    if not BOUNDARY_ZIP_PATH.exists():
        _download_boundary()
    if not zipfile.is_zipfile(BOUNDARY_ZIP_PATH):
        raise RuntimeError(f"Boundary download is not a valid ZIP file: {BOUNDARY_ZIP_PATH}")
    candidates: list[tuple[int, str, dict[str, Any]]] = []
    with zipfile.ZipFile(BOUNDARY_ZIP_PATH) as archive:
        for name in archive.namelist():
            if name.endswith("/") or not name.lower().endswith((".geojson", ".json")):
                continue
            try:
                obj = json.loads(archive.read(name).decode("utf-8-sig"))
            except Exception:
                continue
            if obj.get("type") == "FeatureCollection" and isinstance(obj.get("features"), list):
                candidates.append((len(obj["features"]), name, obj))
    if not candidates:
        raise RuntimeError(
            "The official ZIP did not contain a readable GeoJSON FeatureCollection. "
            f"Inspect the archive at {BOUNDARY_ZIP_PATH} and provide the GeoJSON manually."
        )
    candidates.sort(reverse=True, key=lambda item: item[0])
    _, chosen_name, data = candidates[0]
    BOUNDARY_PATH.parent.mkdir(parents=True, exist_ok=True)
    data.setdefault("metadata", {})
    data["metadata"]["source"] = SOURCE_DESCRIPTION
    data["metadata"]["source_url"] = BOUNDARY_URL
    data["metadata"]["archive_member"] = chosen_name
    BOUNDARY_PATH.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    polygons, _, _ = load_state_boundaries(BOUNDARY_PATH)
    print(f"Loaded {len(polygons)} state/UT geometries from {chosen_name}.")

def _number(value: Any) -> float | None:
    try:
        if value is None or str(value).strip().lower() in {"", "none", "null", "nan"}:
            return None
        result = float(value)
        return result if math.isfinite(result) else None
    except (TypeError, ValueError):
        return None

def _write_csv(path: Path, rows: list[dict[str, Any]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)

def validate() -> dict[str, Any]:
    if not SOURCE_PATH.exists():
        raise FileNotFoundError(
            f"Raw all-India candidate inventory missing: {SOURCE_PATH}. "
            "Extract the complete GRIDPULSE India expansion bundle into the project root first."
        )
    _extract_boundaries()
    polygons, country_union, missing = load_state_boundaries(BOUNDARY_PATH)
    if missing or len(polygons) != 36:
        raise RuntimeError(f"Boundary validation is unsafe; missing state/UT polygons: {missing}")

    source = json.loads(SOURCE_PATH.read_text(encoding="utf-8-sig"))
    if source.get("type") != "FeatureCollection":
        raise RuntimeError("Raw source inventory is not a GeoJSON FeatureCollection.")
    output_features: list[dict[str, Any]] = []
    audit_rows: list[dict[str, Any]] = []
    state_counts: Counter[str] = Counter()
    raw_counts: Counter[str] = Counter()
    corrected_counts: Counter[str] = Counter()
    excluded_counts: Counter[str] = Counter()
    status_counts: Counter[str] = Counter()

    for index, feature in enumerate(source.get("features", []), start=1):
        props = dict(feature.get("properties") or {})
        record_id = str(props.get("record_id") or f"BEEPDF-R{index:06d}")
        raw_state = str(props.get("source_state_raw") or props.get("state") or "")
        source_state = normalize_state_name(raw_state)
        raw_counts[source_state or "Unrecognized state"] += 1
        geometry = feature.get("geometry") or {}
        coords = geometry.get("coordinates") or []
        lon = lat = None
        reason = ""
        matches: list[str] = []
        chosen_state = ""
        inside = False
        if geometry.get("type") != "Point" or len(coords) < 2:
            reason = "missing_or_non_point_geometry"
        else:
            lon, lat = _number(coords[0]), _number(coords[1])
            if lon is None or lat is None or not (-180 <= lon <= 180 and -90 <= lat <= 90):
                reason = "invalid_coordinate"
            else:
                try:
                    matches = matching_states(lat, lon, BOUNDARY_PATH)
                    inside = bool(country_union.covers(__import__("shapely.geometry", fromlist=["Point"]).Point(lon, lat)))
                except Exception as exc:
                    raise RuntimeError(f"Boundary geometry check failed at source record {record_id}: {exc}") from exc
                if not inside:
                    reason = "outside_india_boundary"
                elif not matches:
                    reason = "inside_union_but_no_state_polygon_match"
                elif source_state in matches:
                    chosen_state = source_state
                    reason = "inside_boundary_state_matched"
                elif len(matches) == 1:
                    chosen_state = matches[0]
                    reason = "inside_boundary_state_label_corrected"
                else:
                    reason = "inside_boundary_ambiguous_state_border"

        accepted = reason in {"inside_boundary_state_matched", "inside_boundary_state_label_corrected"}
        audit_rows.append({
            "record_id": record_id,
            "source_page": props.get("source_page"),
            "source_state_raw": raw_state,
            "normalized_source_state": source_state,
            "matched_state": chosen_state or "; ".join(matches),
            "latitude": lat,
            "longitude": lon,
            "inside_india_boundary": inside,
            "state_polygon_matches": len(matches),
            "validation_status": reason,
            "included_in_planner": accepted,
            "location": props.get("location", ""),
            "operator": props.get("cpo_name", ""),
        })
        status_counts[reason] += 1
        if not accepted:
            excluded_counts[source_state or raw_state or "Unrecognized state"] += 1
            continue

        new_props = dict(props)
        new_props["state_before_boundary_validation"] = raw_state
        new_props["state"] = chosen_state
        new_props["boundary_status"] = "inside_india"
        new_props["boundary_state_status"] = (
            "matched_source_state" if reason == "inside_boundary_state_matched" else "corrected_to_polygon_state"
        )
        new_props["boundary_polygon_matches"] = matches
        new_props["boundary_source"] = SOURCE_DESCRIPTION
        output_features.append({
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [float(lon), float(lat)]},
            "properties": new_props,
        })
        state_counts[chosen_state] += 1
        if reason == "inside_boundary_state_label_corrected":
            corrected_counts[chosen_state] += 1

    if not output_features:
        raise RuntimeError("No rows passed polygon validation; no map inventory was written.")
    # Safety check: re-check every feature that will enter the dashboard.
    for f in output_features:
        lon, lat = f["geometry"]["coordinates"]
        if not point_inside_india(lat, lon, BOUNDARY_PATH):
            raise RuntimeError(f"Post-validation safety check failed for {f['properties'].get('record_id')}.")

    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    metadata = {
        "status": "passed",
        "validation_method": "Point-in-polygon using covers() on the union of all 36 official state/UT polygons",
        "state_match_policy": "Keep the source state when its polygon covers the point; otherwise correct a uniquely covered point to the polygon's state; exclude ambiguous boundary matches for review.",
        "boundary_source": SOURCE_DESCRIPTION,
        "boundary_source_url": BOUNDARY_URL,
        "boundary_file": "data/processed/india_state_boundaries.geojson",
        "raw_source": "BEE EV Public Charging Stations Data till 26 October 2025",
        "source_snapshot": "2025-10-26",
        "validated_at_utc": now,
        "boundary_state_count": len(polygons),
        "source_candidate_records": len(source.get("features", [])),
        "included_records": len(output_features),
        "excluded_records": len(source.get("features", [])) - len(output_features),
        "corrected_state_labels": sum(corrected_counts.values()),
        "excluded_by_reason": dict(status_counts),
        "current_operating_status_verified": False,
        "physical_site_deduplication_verified": False,
    }
    result = {
        "type": "FeatureCollection",
        "name": "GRIDPULSE India EV Charging Inventory",
        "metadata": source.get("metadata", {}),
        "boundary_validation": metadata,
        "features": output_features,
    }
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(result, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    audit_fields = [
        "record_id", "source_page", "source_state_raw", "normalized_source_state", "matched_state",
        "latitude", "longitude", "inside_india_boundary", "state_polygon_matches",
        "validation_status", "included_in_planner", "location", "operator"
    ]
    _write_csv(AUDIT_PATH, audit_rows, audit_fields)
    summary_rows = []
    for state in STATE_NAMES:
        summary_rows.append({
            "state_or_ut": state, "included_source_records": state_counts[state],
            "state_label_corrected_records": corrected_counts[state],
            "excluded_source_records": excluded_counts[state],
            "boundary_validation": "passed",
        })
    summary_rows.append({
        "state_or_ut": "ALL INDIA",
        "included_source_records": len(output_features),
        "state_label_corrected_records": sum(corrected_counts.values()),
        "excluded_source_records": len(source.get("features", [])) - len(output_features),
        "boundary_validation": "passed",
    })
    _write_csv(SUMMARY_PATH, summary_rows, [
        "state_or_ut", "included_source_records", "state_label_corrected_records",
        "excluded_source_records", "boundary_validation"
    ])
    print(json.dumps(metadata, indent=2))
    print(f"Validated inventory: {OUTPUT_PATH}")
    print(f"Full source-row audit: {AUDIT_PATH}")
    print(f"State/UT summary: {SUMMARY_PATH}")
    return metadata

if __name__ == "__main__":
    try:
        validate()
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
