from __future__ import annotations

import csv
import json
import math
import os
from collections import Counter
from functools import lru_cache
from pathlib import Path
from typing import Any

import numpy as np
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from sklearn.cluster import DBSCAN
from sklearn.neighbors import BallTree
from app.geo_boundaries import (
    normalize_state_name as normalize_boundary_state,
    point_inside_india,
    point_inside_state,
)

ROOT = Path(__file__).resolve().parents[1]
DATA_PATH = ROOT / "data" / "processed" / "north_india_ev_chargers_map.geojson"
INDIA_DATA_PATH = ROOT / "data" / "processed" / "india_ev_chargers_map.geojson"
INDIA_RAW_PATH = ROOT / "data" / "raw" / "india_ev_chargers_raw.geojson"
INDIA_BOUNDARY_PATH = ROOT / "data" / "processed" / "india_state_boundaries.geojson"
NE_DATA_PATH = ROOT / "data" / "processed" / "northeast_ev_chargers_map.geojson"
CENTRAL_DATA_PATH = ROOT / "data" / "processed" / "central_states_ev_chargers_map.geojson"
NORTHEAST_STATES = ["Assam", "Arunachal Pradesh", "Manipur", "Meghalaya", "Mizoram", "Nagaland", "Sikkim", "Tripura"]
CENTRAL_STATES = ["Bihar", "Uttar Pradesh", "Madhya Pradesh"]
CSV_PATH = ROOT / "data" / "processed" / "north_india_ev_chargers_exact_dedup_review.csv"
INDEX_PATH = ROOT / "app" / "static" / "index.html"
EARTH_RADIUS_KM = 6371.0088
STATE_ORDER = [
    "Andaman and Nicobar Islands", "Andhra Pradesh", "Arunachal Pradesh", "Assam",
    "Bihar", "Chandigarh", "Chhattisgarh", "Dadra and Nagar Haveli and Daman and Diu",
    "Delhi", "Goa", "Gujarat", "Haryana", "Himachal Pradesh", "Jammu and Kashmir",
    "Jharkhand", "Karnataka", "Kerala", "Ladakh", "Lakshadweep", "Madhya Pradesh",
    "Maharashtra", "Manipur", "Meghalaya", "Mizoram", "Nagaland", "Odisha",
    "Puducherry", "Punjab", "Rajasthan", "Sikkim", "Tamil Nadu", "Telangana",
    "Tripura", "Uttar Pradesh", "Uttarakhand", "West Bengal",
]

# Approximate screening envelopes, deliberately broader than administrative boundaries.
# Used only to reject obvious state-label/coordinate mismatches; not a legal boundary layer.
STATE_ENVELOPES = {
    "Delhi": (28.35, 28.90, 76.80, 77.40),
    "Haryana": (27.45, 31.05, 74.25, 77.70),
    "Punjab": (29.40, 32.70, 73.75, 77.05),
    "Himachal Pradesh": (30.20, 33.45, 75.25, 79.15),
    "Uttarakhand": (28.50, 31.60, 77.40, 81.20),
    "Jammu and Kashmir": (32.00, 35.95, 73.35, 79.35),
    "Ladakh": (32.00, 36.25, 75.00, 80.60),
    # Broad coordinate envelopes for screening only; not administrative boundaries.
    "Assam": (24.00, 28.30, 89.50, 96.20),
    "Arunachal Pradesh": (26.50, 29.80, 91.40, 97.50),
    "Manipur": (23.80, 25.80, 93.00, 94.90),
    "Meghalaya": (25.00, 26.30, 89.50, 92.80),
    "Mizoram": (21.80, 24.60, 91.80, 93.50),
    "Nagaland": (25.10, 27.20, 93.30, 95.40),
    "Sikkim": (26.90, 28.20, 88.00, 88.95),
    "Tripura": (22.90, 24.60, 91.10, 92.50),
    # Broad coordinate envelopes for initial screening, not official boundaries.
    "Bihar": (24.00, 27.60, 83.20, 88.30),
    "Uttar Pradesh": (23.70, 30.50, 77.00, 84.70),
    "Madhya Pradesh": (21.00, 26.95, 74.00, 82.85),
}

STATE_ALIASES = {
    "Jammu & Kashmir": "Jammu and Kashmir",
    "Jammu and kashmir": "Jammu and Kashmir",
    "Jammu Kashmir": "Jammu and Kashmir",
    "J&K": "Jammu and Kashmir",
    "Uttrakhand": "Uttarakhand",
    "Uttaranchal": "Uttarakhand",
    "Arunachal": "Arunachal Pradesh",
    "Andaman & Nicobar": "Andaman and Nicobar Islands",
    "Andaman and Nicobar": "Andaman and Nicobar Islands",
    "UT OF D&NH AND D&D": "Dadra and Nagar Haveli and Daman and Diu",
    "UT of D&NH and D&D": "Dadra and Nagar Haveli and Daman and Diu",
    "Pondicherry": "Puducherry",
    "Orissa": "Odisha",
}

app = FastAPI(
    title="EV-Yojna India-wide EV Charging Planner",
    version="0.2.0",
    description=(
        "EV charging inventory, spatial clustering and "
        "boundary-validated inventory and preliminary coverage-gap screening across India."
    ),
)
app.mount("/static", StaticFiles(directory=str(ROOT / "app" / "static")), name="static")


def normalize_state(value: Any) -> str:
    text = str(value or "").strip()
    return STATE_ALIASES.get(text, normalize_boundary_state(text) or text)


def _num(value: Any) -> float | None:
    try:
        if value is None or str(value).strip().lower() in {"", "nan", "none", "null", "not recorded"}:
            return None
        v = float(value)
        return v if math.isfinite(v) else None
    except (TypeError, ValueError):
        return None


def _load_geojson() -> dict:
    # Prefer the national inventory only after polygon validation has passed.
    if INDIA_DATA_PATH.exists():
        with INDIA_DATA_PATH.open("r", encoding="utf-8-sig") as f:
            india = json.load(f)
        validation = india.get("boundary_validation") or {}
        if validation.get("status") != "passed" or int(validation.get("boundary_state_count") or 0) != 36:
            raise RuntimeError(
                "National charger inventory is not marked as boundary-validated. "
                "Run scripts/prepare_india_inventory.py and review the boundary audit before starting EV-Yojna."
            )
        if not INDIA_BOUNDARY_PATH.exists():
            raise RuntimeError("Validated national inventory exists but india_state_boundaries.geojson is missing.")
        india["india_inventory_loaded"] = True
        india["india_source_candidate_records"] = int(validation.get("source_candidate_records") or 0)
        india["india_excluded_records"] = int(validation.get("excluded_records") or 0)
        india["northeast_inventory_loaded"] = True
        india["northeast_feature_count"] = 0
        india["central_inventory_loaded"] = True
        india["central_feature_count"] = 0
        return india

    if INDIA_RAW_PATH.exists() and not INDIA_DATA_PATH.exists():
        raise RuntimeError(
            "The national raw inventory is present, but the boundary-validated India inventory is missing. "
            "Run scripts/prepare_india_inventory.py and review data/reports/india_ev_chargers_boundary_audit.csv. "
            "EV-Yojna will not silently show a partial regional inventory as nationwide coverage."
        )
    if not DATA_PATH.exists():
        raise RuntimeError(
            f"Base inventory not found at {DATA_PATH}. Put north_india_ev_chargers_map.geojson "
            "inside data/processed/."
        )
    with DATA_PATH.open("r", encoding="utf-8-sig") as f:
        data = json.load(f)
    if data.get("type") != "FeatureCollection":
        raise RuntimeError("Base inventory must be a GeoJSON FeatureCollection.")

    # Keep the original inventory separate and load the NE BEE snapshot as a supplement.
    # Older local setups continue to work when the optional file has not been copied yet.
    features = list(data.get("features", []))
    if NE_DATA_PATH.exists():
        with NE_DATA_PATH.open("r", encoding="utf-8-sig") as f:
            northeast = json.load(f)
        if northeast.get("type") != "FeatureCollection":
            raise RuntimeError("Northeast inventory must be a GeoJSON FeatureCollection.")
        features.extend(northeast.get("features", []))
        data["northeast_inventory_loaded"] = True
        data["northeast_feature_count"] = len(northeast.get("features", []))
    else:
        data["northeast_inventory_loaded"] = False
        data["northeast_feature_count"] = 0

    data["central_inventory_loaded"] = False
    data["central_feature_count"] = 0
    if CENTRAL_DATA_PATH.exists():
        with CENTRAL_DATA_PATH.open("r", encoding="utf-8-sig") as f:
            central = json.load(f)
        if central.get("type") != "FeatureCollection":
            raise RuntimeError("Central states inventory must be a GeoJSON FeatureCollection.")
        features.extend(central.get("features", []))
        data["central_inventory_loaded"] = True
        data["central_feature_count"] = len(central.get("features", []))

    data["features"] = features
    data["india_inventory_loaded"] = False
    data["india_source_candidate_records"] = 0
    data["india_excluded_records"] = 0
    return data


@lru_cache(maxsize=1)
def load_records() -> list[dict]:
    data = _load_geojson()
    rows: list[dict] = []
    for idx, feature in enumerate(data.get("features", [])):
        props = dict(feature.get("properties") or {})
        geometry = feature.get("geometry") or {}
        coords = geometry.get("coordinates") or []
        if geometry.get("type") != "Point" or len(coords) < 2:
            continue
        lon, lat = _num(coords[0]), _num(coords[1])
        if lon is None or lat is None or not (-180 <= lon <= 180 and -90 <= lat <= 90):
            continue
        state = normalize_state(props.get("state"))
        if state not in STATE_ORDER:
            continue
        if data.get("india_inventory_loaded"):
            # The national pipeline has already tested every source point against all
            # 36 WGS84 state/UT polygons and writes only accepted features to this file.
            # Repeating point-in-polygon operations for ~40,000 rows at API startup
            # made /api/health and every dashboard endpoint time out. Trust the
            # generated validation manifest plus each feature's accepted status here.
            if props.get("boundary_status") != "inside_india":
                continue
            if props.get("boundary_state_status") not in {
                "matched_source_state",
                "corrected_to_polygon_state",
            }:
                continue
        power = _num(props.get("charger_rating_kw"))
        connector_kw = _num(props.get("connector_rating_kw"))
        connectors = _num(props.get("number_of_connectors"))
        record = {
            "id": f"pcs-{idx+1}",
            "source_record_id": str(props.get("record_id") or f"pcs-{idx+1}"),
            "state": state,
            "source_state_raw": str(props.get("source_state_raw") or state),
            "boundary_status": str(props.get("boundary_status") or "not_authoritatively_checked"),
            "boundary_state_status": str(props.get("boundary_state_status") or "legacy_envelope_only"),
            "district": str(props.get("district") or "Not recorded"),
            "city_village": str(props.get("city_village") or "Not recorded"),
            "location": str(props.get("location") or "Location not recorded"),
            "cpo_name": str(props.get("cpo_name") or "Not recorded"),
            "ownership_type": str(props.get("ownership_type") or "Not recorded"),
            "charger_type": str(props.get("charger_type") or "Not recorded"),
            "charger_rating_kw": power,
            "connector_rating_kw": connector_kw,
            "number_of_connectors": connectors,
            "duplicate_occurrences": int(_num(props.get("duplicate_occurrences")) or 1),
            "source_pages": str(props.get("source_pages") or props.get("source_page") or "Not recorded"),
            "lat": lat,
            "lon": lon,
            "source_snapshot": "2025-10-26",
            "evidence_status": "reported_inventory_not_live_verified",
            "location_key": f"{lat:.4f},{lon:.4f}",
        }
        rows.append(record)
    if not rows:
        raise RuntimeError("No valid India point records were found in the GeoJSON.")
    return rows


def filtered_records(state: str | None = None, search: str | None = None,
                     charger_type: str | None = None) -> list[dict]:
    rows = load_records()
    selected_state = normalize_state(state) if state and state not in {"All North India", "All India", "All covered regions"} else None
    q = (search or "").strip().casefold()
    ct = (charger_type or "").strip().casefold()
    result = []
    for row in rows:
        if selected_state and row["state"] != selected_state:
            continue
        if ct and ct not in row["charger_type"].casefold():
            continue
        if q:
            haystack = " ".join(str(row.get(k, "")) for k in (
                "state", "district", "city_village", "location", "cpo_name", "charger_type"
            )).casefold()
            if q not in haystack:
                continue
        result.append(row)
    return result


def _unique_coordinate_groups(rows: list[dict]) -> list[dict]:
    """Approximate point groups; not a verified physical-station count."""
    groups: dict[str, dict] = {}
    for row in rows:
        key = row["location_key"]
        if key not in groups:
            groups[key] = {"lat": row["lat"], "lon": row["lon"], "records": [], "state": row["state"]}
        groups[key]["records"].append(row)
    output = []
    for group in groups.values():
        group["record_count"] = len(group["records"])
        group["max_power_kw"] = max((r["charger_rating_kw"] or 0 for r in group["records"]), default=0)
        group["connector_total_reported"] = sum((r["number_of_connectors"] or 0 for r in group["records"]), 0)
        output.append(group)
    return output


def _state_metrics(rows: list[dict]) -> list[dict]:
    output = []
    for state in STATE_ORDER:
        sr = [r for r in rows if r["state"] == state]
        sites = _unique_coordinate_groups(sr)
        powers = [r["charger_rating_kw"] for r in sr if r["charger_rating_kw"] is not None]
        output.append({
            "state": state,
            "records": len(sr),
            "approx_coordinate_groups": len(sites),
            "reported_connectors": round(sum((r["number_of_connectors"] or 0) for r in sr), 2),
            "fast_power_records_50kw_plus": sum(1 for v in powers if v >= 50),
            "median_reported_kw": round(float(np.median(powers)), 2) if powers else None,
            "districts_represented": len({r["district"] for r in sr if r["district"] != "Not recorded"}),
        })
    return output


def _distribution(rows: list[dict], field: str, limit: int = 10) -> list[dict]:
    counter = Counter(str(r.get(field) or "Not recorded") for r in rows)
    return [{"label": label, "count": count} for label, count in counter.most_common(limit)]


class PlanRequest(BaseModel):
    state: str = Field(default="Himachal Pradesh", min_length=1)
    budget_lakh: float = Field(default=150, ge=10, le=100000)
    target_gap_km: float = Field(default=20, ge=5, le=100)
    charger_power_kw: float = Field(default=60, ge=3, le=350)
    cost_per_site_lakh: float = Field(default=25, ge=1, le=10000)
    max_sites: int = Field(default=6, ge=1, le=30)


def haversine_km(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """Pairwise distance from one [lat,lon] point to many points."""
    lat1 = np.radians(float(a[0])); lon1 = np.radians(float(a[1]))
    lat2 = np.radians(b[:, 0]); lon2 = np.radians(b[:, 1])
    dlat = lat2 - lat1; dlon = lon2 - lon1
    h = np.sin(dlat / 2) ** 2 + np.cos(lat1) * np.cos(lat2) * np.sin(dlon / 2) ** 2
    return 2 * EARTH_RADIUS_KM * np.arcsin(np.sqrt(np.clip(h, 0, 1)))


def _midpoint(lat1: float, lon1: float, lat2: float, lon2: float) -> tuple[float, float]:
    # Spherical midpoint, safer than averaging coordinates across longitude.
    p1, l1, p2, l2 = map(math.radians, [lat1, lon1, lat2, lon2])
    bx = math.cos(p2) * math.cos(l2 - l1)
    by = math.cos(p2) * math.sin(l2 - l1)
    lat3 = math.atan2(math.sin(p1) + math.sin(p2), math.sqrt((math.cos(p1) + bx) ** 2 + by ** 2))
    lon3 = l1 + math.atan2(by, math.cos(p1) + bx)
    return math.degrees(lat3), ((math.degrees(lon3) + 540) % 360) - 180


def _coverage_plan(req: PlanRequest) -> dict:
    state = normalize_state(req.state)
    if state in {"All North India", "All India", "All covered regions"}:
        state_rows = load_records()
    elif state not in STATE_ORDER:
        raise HTTPException(status_code=400, detail=f"Unknown region: {req.state}")
    else:
        state_rows = [r for r in load_records() if r["state"] == state]
    if state in {"All North India", "All India", "All covered regions"}:
        raise HTTPException(status_code=400, detail="Choose one state/UT for the placement scenario so the budget and candidate ranking remain region-specific.")

    all_sites = _unique_coordinate_groups(state_rows)
    bounds = STATE_ENVELOPES.get(state)
    if INDIA_DATA_PATH.exists():
        sites = [s for s in all_sites if point_inside_state(state, s["lat"], s["lon"], INDIA_BOUNDARY_PATH)]
    else:
        sites = [s for s in all_sites if bounds and bounds[0] <= s["lat"] <= bounds[1] and bounds[2] <= s["lon"] <= bounds[3]]
    excluded_coordinate_groups = len(all_sites) - len(sites)
    if len(sites) < 3:
        raise HTTPException(status_code=422, detail="Not enough in-envelope coordinate groups for a gap-screening analysis.")

    points = np.array([[p["lat"], p["lon"]] for p in sites], dtype=float)
    n = len(points)
    tree = BallTree(np.radians(points), metric="haversine")
    # Query nearest 8 existing locations. Pair midpoints become candidate zones only when the straight-line gap is materially wide.
    neighbor_n = min(8, n)
    dist_rad, neighbors = tree.query(np.radians(points), k=neighbor_n)
    min_pair_km = max(req.target_gap_km * 1.75, 12.0)
    max_pair_km = min(max(req.target_gap_km * 5.0, 80.0), 300.0)
    candidate_dict: dict[tuple[int, int], dict] = {}
    for i in range(n):
        for rank in range(1, neighbor_n):
            j = int(neighbors[i, rank])
            if j <= i:
                continue
            pair_km = float(dist_rad[i, rank] * EARTH_RADIUS_KM)
            if pair_km < min_pair_km or pair_km > max_pair_km:
                continue
            lat, lon = _midpoint(points[i, 0], points[i, 1], points[j, 0], points[j, 1])
            if INDIA_DATA_PATH.exists():
                if not point_inside_india(lat, lon, INDIA_BOUNDARY_PATH) or not point_inside_state(state, lat, lon, INDIA_BOUNDARY_PATH):
                    continue
            elif not bounds or not (bounds[0] <= lat <= bounds[1] and bounds[2] <= lon <= bounds[3]):
                continue
            cand = np.array([lat, lon], dtype=float)
            all_dist = haversine_km(cand, points)
            nearest_idx = int(np.argmin(all_dist))
            nearest_km = float(all_dist[nearest_idx])
            if nearest_km < req.target_gap_km * 0.55:
                continue
            key = (round(lat * 5), round(lon * 5))  # roughly 22 km bucket, only used to reduce candidate count
            existing = candidate_dict.get(key)
            if existing is None or nearest_km > existing["nearest_existing_km"]:
                candidate_dict[key] = {
                    "lat": lat, "lon": lon,
                    "pair_distance_km": pair_km,
                    "nearest_existing_km": nearest_km,
                    "nearest_station": sites[nearest_idx],
                    "gap_score": min(100.0, round(100 * nearest_km / req.target_gap_km, 1)),
                }

    candidates = list(candidate_dict.values())
    candidates.sort(key=lambda c: c["nearest_existing_km"], reverse=True)
    # Greedy diversity: avoid recommending several points in nearly the same area.
    selected = []
    separation_km = max(8.0, req.target_gap_km * 0.6)
    for cand in candidates:
        if all(float(haversine_km(np.array([cand["lat"], cand["lon"]]), np.array([[s["lat"], s["lon"]]]))[0]) >= separation_km for s in selected):
            selected.append(cand)
        if len(selected) >= 100:
            break

    site_budget = int(req.budget_lakh // req.cost_per_site_lakh)
    recommended_count = min(site_budget, req.max_sites, len(selected))
    selected = selected[:recommended_count]
    items = []
    for idx, cand in enumerate(selected, start=1):
        items.append({
            "rank": idx,
            "candidate_id": f"{state.lower().replace(' ', '-')}-gap-{idx:02d}",
            "lat": round(cand["lat"], 6),
            "lon": round(cand["lon"], 6),
            "nearest_existing_km": round(cand["nearest_existing_km"], 2),
            "neighbor_pair_gap_km": round(cand["pair_distance_km"], 2),
            "gap_score": cand["gap_score"],
            "suggested_charger_power_kw": req.charger_power_kw,
            "assumed_site_cost_lakh": req.cost_per_site_lakh,
            "estimated_capex_lakh": req.cost_per_site_lakh,
            "reason": f"Straight-line gap screening: nearest reported coordinate group is about {cand['nearest_existing_km']:.1f} km away.",
            "evidence_status": "MODEL_SCREENING_NOT_SITE_VERIFIED",
        })

    return {
        "state": state,
        "method": "Greedy, spatially diversified midpoint screening between reported locations with large straight-line separation.",
        "model_type": "Deterministic coordinate-based coverage-gap screening",
        "candidate_pool_size": len(candidates),
        "requested_budget_lakh": req.budget_lakh,
        "assumed_cost_per_site_lakh": req.cost_per_site_lakh,
        "affordable_sites_at_assumption": site_budget,
        "recommended_sites": len(items),
        "estimated_total_capex_lakh": round(len(items) * req.cost_per_site_lakh, 2),
        "planned_total_power_kw": round(len(items) * req.charger_power_kw, 2),
        "target_gap_km": req.target_gap_km,
        "inventory_coordinate_groups": len(sites),
        "excluded_coordinate_groups_outside_approximate_region_envelope": excluded_coordinate_groups,
        "recommendations": items,
        "limitations": [
            "Candidate coordinates are spherical midpoints, not verified land parcels or road-side sites.",
            "Gap measurement is straight-line distance, not road travel distance.",
            "The inventory is a dated 26 Oct 2025 snapshot; station operating status is not live-verified.",
            "Cost per site is a user-editable scenario assumption, not a sourced quotation; grid augmentation is excluded.",
            "This is not an electrical hosting-capacity calculation; utility feeder and transformer data are not included.",
        ],
    }


@app.get("/", response_class=HTMLResponse)
def index() -> HTMLResponse:
    if not INDEX_PATH.exists():
        return HTMLResponse("<h1>Frontend missing</h1><p>app/static/index.html not found.</p>", status_code=500)
    return HTMLResponse(INDEX_PATH.read_text(encoding="utf-8"))


@app.get("/api/health")
def health() -> dict:
    try:
        rows = load_records()
        data = _load_geojson()
        national_loaded = bool(data.get("india_inventory_loaded"))
        northeast_rows = sum(1 for row in rows if row["state"] in NORTHEAST_STATES)
        central_rows = sum(1 for row in rows if row["state"] in CENTRAL_STATES)
        validation = data.get("boundary_validation") or {}
        return {"status": "ok", "service": "ev-yojna-india-ev-planner", "inventory_loaded": True,
                "inventory_records": len(rows), "states": len({r['state'] for r in rows}),
                "northeast_inventory_loaded": national_loaded or NE_DATA_PATH.exists(),
                "northeast_records": northeast_rows,
                "central_inventory_loaded": national_loaded or CENTRAL_DATA_PATH.exists(),
                "central_records": central_rows,
                "india_inventory_loaded": national_loaded,
                "india_source_candidate_records": int(data.get("india_source_candidate_records") or 0),
                "india_excluded_records": int(data.get("india_excluded_records") or 0),
                "boundary_validation_passed": validation.get("status") == "passed",
                "boundary_validated_records": int(validation.get("included_records") or len(rows)) if national_loaded else 0,
                "state_label_corrections": int(validation.get("corrected_state_labels") or 0) if national_loaded else 0,
                "states_and_uts_target": 36,
                "source_snapshot": "2025-10-26",
                "data_file": str((INDIA_DATA_PATH if national_loaded else DATA_PATH).relative_to(ROOT)),
                "boundary_file": str(INDIA_BOUNDARY_PATH.relative_to(ROOT)) if national_loaded else None,
                "northeast_data_file": str(NE_DATA_PATH.relative_to(ROOT)) if NE_DATA_PATH.exists() else None,
                "central_data_file": str(CENTRAL_DATA_PATH.relative_to(ROOT)) if CENTRAL_DATA_PATH.exists() else None}
    except Exception as exc:
        return {"status": "error", "inventory_loaded": False, "india_inventory_loaded": INDIA_DATA_PATH.exists(), "detail": str(exc)}


@app.get("/api/overview")
def overview(state: str | None = None) -> dict:
    rows = filtered_records(state)
    coordinate_groups = _unique_coordinate_groups(rows)
    valid_power = [r["charger_rating_kw"] for r in rows if r["charger_rating_kw"] is not None and r["charger_rating_kw"] >= 0]
    reported_connectors = sum((r["number_of_connectors"] or 0) for r in rows)
    fast_records = sum(1 for r in rows if (r["charger_rating_kw"] or 0) >= 50)
    return {
        "selected_region": normalize_state(state) if state and state not in {"All North India", "All India", "All covered regions"} else "All India",
        "inventory_records": len(rows),
        "approx_coordinate_groups": len(coordinate_groups),
        "reported_connector_total": round(reported_connectors, 2),
        "records_50kw_plus": fast_records,
        "median_reported_power_kw": round(float(np.median(valid_power)), 2) if valid_power else None,
        "regions_represented": len({r["state"] for r in rows}),
        "source_snapshot": "26 Oct 2025",
        "note": "Coordinate groups are an approximate inventory indicator, not verified physical station counts."
    }


@app.get("/api/states")
def states() -> dict:
    metrics = _state_metrics(load_records())
    return {"states": metrics, "order": STATE_ORDER}


@app.get("/api/stations")
def stations(state: str = "All India", search: str = "", charger_type: str = "",
             limit: int = Query(default=5000, ge=1, le=10000), offset: int = Query(default=0, ge=0)) -> dict:
    rows = filtered_records(state, search, charger_type)
    page = rows[offset:offset + limit]
    features = []
    for r in page:
        p = {k: v for k, v in r.items() if k not in {"lat", "lon", "location_key", "id"}}
        p["record_id"] = r["id"]
        features.append({"type": "Feature", "geometry": {"type": "Point", "coordinates": [r["lon"], r["lat"]]}, "properties": p})
    return {"type": "FeatureCollection", "features": features,
            "total_filtered": len(rows), "offset": offset, "limit": limit,
            "snapshot": "2025-10-26"}


@app.get("/api/analytics")
def analytics(state: str = "All North India") -> dict:
    rows = filtered_records(state)
    state_counts = [{"label": r["state"], "count": r["records"]} for r in _state_metrics(rows) if r["records"] > 0]
    power_bands = Counter()
    for row in rows:
        kw = row["charger_rating_kw"]
        if kw is None:
            band = "Unknown"
        elif kw <= 7.4:
            band = "â‰¤7.4 kW"
        elif kw <= 22:
            band = "7.5â€“22 kW"
        elif kw < 50:
            band = "22â€“49 kW"
        else:
            band = "â‰¥50 kW"
        power_bands[band] += 1
    return {
        "state": normalize_state(state) if state not in {"All North India", "All India", "All covered regions"} else state,
        "records_by_state": state_counts,
        "charger_types": _distribution(rows, "charger_type", 8),
        "operators": _distribution(rows, "cpo_name", 8),
        "ownership": _distribution(rows, "ownership_type", 6),
        "power_bands": [{"label": k, "count": v} for k, v in power_bands.most_common()],
        "top_districts": _distribution(rows, "district", 12),
    }


@app.get("/api/quality")
def quality(state: str = "All North India") -> dict:
    rows = filtered_records(state)
    groups = _unique_coordinate_groups(rows)
    out_of_envelope = 0
    for row in rows:
        bounds = STATE_ENVELOPES.get(row["state"])
        if bounds and not (bounds[0] <= row["lat"] <= bounds[1] and bounds[2] <= row["lon"] <= bounds[3]):
            out_of_envelope += 1
    missing_power = sum(1 for r in rows if r["charger_rating_kw"] is None)
    missing_operator = sum(1 for r in rows if r["cpo_name"] == "Not recorded")
    return {
        "state": normalize_state(state) if state != "All North India" else state,
        "inventory_records": len(rows),
        "approx_coordinate_groups": len(groups),
        "missing_power_rating_records": missing_power,
        "missing_operator_records": missing_operator,
        "records_outside_approximate_region_envelope": out_of_envelope if not INDIA_DATA_PATH.exists() else None,
        "records_outside_authoritative_state_boundary": sum(
            1 for row in rows
            if INDIA_DATA_PATH.exists()
            and not point_inside_state(row["state"], row["lat"], row["lon"], INDIA_BOUNDARY_PATH)
        ) if INDIA_DATA_PATH.exists() else None,
        "boundary_validation_applied": bool(INDIA_DATA_PATH.exists()),
        "source_snapshot": "2025-10-26",
        "note": "Broad bounding envelopes only identify potential state/coordinate mismatches; they do not replace an authoritative state-boundary dataset."
    }


@app.get("/api/model/info")
def model_info() -> dict:
    return {
        "spatial_model": "DBSCAN (Haversine distance)",
        "purpose": "Group nearby mapped inventory coordinate locations.",
        "not_a_demand_model": True,
        "inputs": ["latitude", "longitude"],
        "limitations": [
            "Dense points may represent multiple connector records at one physical site.",
            "Clusters are spatial concentration, not demand, traffic, utilization, or grid capacity.",
        ],
        "planner": "Midpoint coverage-gap screening based on straight-line distances",
        "forecasting": "A validated demand forecast is not calculated because traffic observations and charging-session time series are unavailable."
    }


@app.get("/api/clusters")
def clusters(state: str = "Delhi", eps_km: float = Query(default=3.0, ge=0.5, le=20),
             min_samples: int = Query(default=4, ge=2, le=30)) -> dict:
    if state in {"All North India", "All India", "All covered regions"}:
        rows = load_records()
    else:
        state = normalize_state(state)
        if state not in STATE_ORDER:
            raise HTTPException(status_code=400, detail=f"Unknown region: {state}")
        rows = filtered_records(state)
    sites = _unique_coordinate_groups(rows)
    if len(sites) < min_samples:
        return {"state": state, "clusters": [], "noise_locations": len(sites), "coordinate_groups": len(sites),
                "eps_km": eps_km, "min_samples": min_samples}
    coords = np.radians(np.array([[s["lat"], s["lon"]] for s in sites], dtype=float))
    model = DBSCAN(eps=eps_km / EARTH_RADIUS_KM, min_samples=min_samples, metric="haversine", algorithm="ball_tree")
    labels = model.fit_predict(coords)
    output = []
    for label in sorted(int(v) for v in set(labels) if v >= 0):
        idxs = np.where(labels == label)[0]
        points = np.array([[sites[i]["lat"], sites[i]["lon"]] for i in idxs])
        row_states = Counter(sites[i]["state"] for i in idxs)
        output.append({"cluster_id": label, "center_lat": round(float(points[:, 0].mean()), 6),
                       "center_lon": round(float(points[:, 1].mean()), 6), "coordinate_groups": int(len(idxs)),
                       "states": dict(row_states), "centroid_method": "arithmetic mean of lat/lon; display only"})
    output.sort(key=lambda x: x["coordinate_groups"], reverse=True)
    return {"state": state, "clusters": output, "cluster_count": len(output),
            "noise_locations": int((labels == -1).sum()), "coordinate_groups": len(sites),
            "eps_km": eps_km, "min_samples": min_samples,
            "note": "DBSCAN groups nearby coordinates; clusters describe geographic concentration, not EV demand."}


@app.post("/api/plan")
def plan(request: PlanRequest) -> dict:
    return _coverage_plan(request)


@app.post("/api/plan/export.csv")
def plan_export(request: PlanRequest) -> StreamingResponse:
    result = _coverage_plan(request)
    from io import StringIO
    buffer = StringIO()
    columns = ["rank", "candidate_id", "lat", "lon", "nearest_existing_km", "neighbor_pair_gap_km",
               "gap_score", "suggested_charger_power_kw", "assumed_site_cost_lakh", "reason", "evidence_status"]
    writer = csv.DictWriter(buffer, fieldnames=columns, extrasaction="ignore")
    writer.writeheader()
    writer.writerows(result["recommendations"])
    buffer.seek(0)
    return StreamingResponse(iter([buffer.getvalue()]), media_type="text/csv",
                             headers={"Content-Disposition": "attachment; filename=north_india_ev_site_screening_plan.csv"})


from app.route_api import router as route_planner_router
app.include_router(route_planner_router)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host="127.0.0.1", port=8000, reload=False)
