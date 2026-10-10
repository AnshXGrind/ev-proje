"""Route-based EV charger screening.

This is an initial planning screen, not a traffic forecast or a
power-flow study. It combines OSRM road geometry, sampled elevation, a
transparent terrain/range/scenario model, and the dated BEE charger inventory.
Public geocoding/routing/elevation endpoints are best-effort and must not be
used as a production SLA.
"""
from __future__ import annotations

import csv
import io
import json
import math
import re
import threading
import time
from collections import Counter, defaultdict
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

import numpy as np
import requests
from fastapi import APIRouter, HTTPException
from fastapi.responses import HTMLResponse, StreamingResponse
from pydantic import BaseModel, Field, model_validator
from pyproj import CRS, Transformer
from shapely.geometry import LineString, Point
from shapely.ops import transform as shapely_transform

router = APIRouter(tags=["route-planner"])
ROOT = Path(__file__).resolve().parents[1]
DATA_PATH = ROOT / "data" / "processed" / "north_india_ev_chargers_map.geojson"
ROUTE_HTML = ROOT / "app" / "static" / "route_planner.html"
EARTH_RADIUS_KM = 6371.0088
APP_UA = "GRIDPULSE-EVPlanner/0.4 (research prototype; github.com/AnshXGrind/ev-proje)"
NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
OSRM_URL = "https://router.project-osrm.org/route/v1/driving"
ELEVATION_URL = "https://api.open-meteo.com/v1/elevation"

STATE_ORDER = [
    "Delhi", "Haryana", "Punjab", "Himachal Pradesh", "Uttarakhand",
    "Jammu and Kashmir", "Ladakh",
]
STATE_ALIASES = {
    "Jammu & Kashmir": "Jammu and Kashmir", "Jammu and kashmir": "Jammu and Kashmir",
    "Jammu Kashmir": "Jammu and Kashmir", "J&K": "Jammu and Kashmir",
    "Uttrakhand": "Uttarakhand", "Uttaranchal": "Uttarakhand",
}
# Broad envelopes flag obviously mismatched inventory coordinates. They are not authoritative boundaries.
STATE_ENVELOPES = {
    "Delhi": (28.35, 28.90, 76.80, 77.40),
    "Haryana": (27.45, 31.05, 74.25, 77.70),
    "Punjab": (29.40, 32.70, 73.75, 77.05),
    "Himachal Pradesh": (30.20, 33.45, 75.25, 79.15),
    "Uttarakhand": (28.50, 31.60, 77.40, 81.20),
    "Jammu and Kashmir": (32.00, 35.95, 73.35, 79.35),
    "Ladakh": (32.00, 36.25, 75.00, 80.60),
}

# Transparent screening parameters, deliberately configurable in one place.
# Values are planning assumptions; they are not fitted coefficients from observed sessions.
TERRAIN = {
    "plains": {
        "label": "Plains / highway", "spacing_factor": 1.00, "range_factor": 0.92,
        "fast_factor": 1.00, "description": "Lower relief; policy benchmark and range generally dominate spacing.",
    },
    "rolling": {
        "label": "Rolling terrain", "spacing_factor": 0.90, "range_factor": 0.82,
        "fast_factor": 0.86, "description": "Moderate relief; somewhat tighter spacing for energy and access uncertainty.",
    },
    "hills": {
        "label": "Hills / mountain road", "spacing_factor": 0.76, "range_factor": 0.68,
        "fast_factor": 0.70, "description": "Grade and route variability reduce practical range; add redundancy.",
    },
    "high_himalaya": {
        "label": "High Himalaya", "spacing_factor": 0.56, "range_factor": 0.52,
        "fast_factor": 0.50, "description": "High elevation can reduce range and increase seasonal access/recovery concerns.",
    },
    "remote_high_himalaya": {
        "label": "Remote / seasonal high-altitude road", "spacing_factor": 0.43, "range_factor": 0.42,
        "fast_factor": 0.38, "description": "Conservative mode for remote, exposed, or seasonally constrained corridors.",
    },
    "unknown": {
        "label": "Terrain unknown (conservative fallback)", "spacing_factor": 0.72, "range_factor": 0.70,
        "fast_factor": 0.68, "description": "Elevation service unavailable; use conservative interim screen and verify terrain manually.",
    },
}
SCENARIOS = {
    "conservative": {"label": "Conservative", "density_factor": 1.00, "growth_multiplier": 0.65},
    "base": {"label": "Base", "density_factor": 0.92, "growth_multiplier": 1.00},
    "accelerated": {"label": "Accelerated adoption", "density_factor": 0.82, "growth_multiplier": 1.35},
}
POLICY_GENERAL_SPACING_KM = 20.0
POLICY_FAST_SPACING_KM = 100.0
GEOCODE_MIN_INTERVAL_S = 1.1

_geocode_cache: dict[str, dict[str, Any]] = {}
_geocode_lock = threading.Lock()
_last_geocode_at = 0.0
_route_cache: dict[tuple[float, float, float, float], dict[str, Any]] = {}
_route_cache_lock = threading.Lock()
_route_request_lock = threading.Lock()
_last_route_request_at = 0.0
_elevation_cache: dict[tuple[float, float], float | None] = {}
_elevation_lock = threading.Lock()


class RouteAnalyzeRequest(BaseModel):
    origin: str = Field(default="Narnaul, Haryana, India", min_length=2, max_length=160)
    destination: str = Field(default="Jammu, Jammu and Kashmir, India", min_length=2, max_length=160)
    terrain_mode: Literal["auto", "plains", "rolling", "hills", "high_himalaya", "remote_high_himalaya"] = "auto"
    remote_or_seasonal: bool = False
    vehicle_range_km: float = Field(default=250, ge=40, le=1000)
    reserve_pct: float = Field(default=20, ge=5, le=50)
    planning_year: Literal[2030, 2035] = 2030
    adoption_scenario: Literal["conservative", "base", "accelerated"] = "base"
    corridor_km: float = Field(default=15, ge=2, le=50)
    traffic_vehicles_per_day: float | None = Field(default=None, ge=0, le=2_000_000)
    current_ev_share_pct: float | None = Field(default=None, ge=0, le=100)
    public_charge_share_pct: float = Field(default=20, ge=0, le=100)
    average_session_kwh: float = Field(default=25, ge=1, le=500)
    annual_traffic_growth_pct: float = Field(default=2.0, ge=-5, le=20)
    annual_ev_share_growth_pct: float = Field(default=18.0, ge=0, le=100)
    assumed_charger_power_kw: float = Field(default=60, ge=3, le=500)
    target_utilization_pct: float = Field(default=25, ge=5, le=90)

    @model_validator(mode="after")
    def validate_demand_inputs(self):
        if (self.traffic_vehicles_per_day is None) != (self.current_ev_share_pct is None):
            raise ValueError("Enter both daily traffic and current EV share to calculate an illustrative demand scenario, or leave both blank.")
        return self


def _num(value: Any) -> float | None:
    try:
        if value is None or str(value).strip().lower() in {"", "nan", "none", "null", "not recorded"}:
            return None
        result = float(value)
        return result if math.isfinite(result) else None
    except (TypeError, ValueError):
        return None


def _normalize_state(value: Any) -> str:
    raw = str(value or "").strip()
    return STATE_ALIASES.get(raw, raw)


@lru_cache(maxsize=1)
def _inventory_groups() -> list[dict[str, Any]]:
    """Load approximate coordinate groups from the dated local inventory."""
    if not DATA_PATH.exists():
        raise HTTPException(status_code=503, detail=f"Charging inventory missing at {DATA_PATH}. Copy north_india_ev_chargers_map.geojson into data/processed/.")
    try:
        with DATA_PATH.open("r", encoding="utf-8-sig") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=500, detail=f"Could not read station GeoJSON: {exc}") from exc
    if data.get("type") != "FeatureCollection":
        raise HTTPException(status_code=500, detail="Station file is not a GeoJSON FeatureCollection.")

    groups: dict[tuple[float, float], list[dict[str, Any]]] = defaultdict(list)
    for feature in data.get("features", []):
        props = feature.get("properties") or {}
        geom = feature.get("geometry") or {}
        coords = geom.get("coordinates") or []
        if geom.get("type") != "Point" or len(coords) < 2:
            continue
        lon, lat = _num(coords[0]), _num(coords[1])
        state = _normalize_state(props.get("state"))
        if lon is None or lat is None or state not in STATE_ORDER or not (-180 <= lon <= 180 and -90 <= lat <= 90):
            continue
        envelope = STATE_ENVELOPES.get(state)
        if envelope and not (envelope[0] <= lat <= envelope[1] and envelope[2] <= lon <= envelope[3]):
            # Keep raw source elsewhere, but do not use obvious coordinate/state mismatches for route coverage.
            continue
        groups[(round(lat, 4), round(lon, 4))].append(props)

    result: list[dict[str, Any]] = []
    for (lat, lon), rows in groups.items():
        states = Counter(_normalize_state(r.get("state")) for r in rows)
        powers = [v for r in rows if (v := _num(r.get("charger_rating_kw"))) is not None and v >= 0]
        connectors = [v for r in rows if (v := _num(r.get("number_of_connectors"))) is not None and v >= 0]
        first = rows[0]
        result.append({
            "lat": lat, "lon": lon, "state": states.most_common(1)[0][0] if states else "Unknown",
            "location": str(first.get("location") or "Location not recorded"),
            "city_village": str(first.get("city_village") or "Not recorded"),
            "district": str(first.get("district") or "Not recorded"),
            "operator": str(first.get("cpo_name") or "Not recorded"),
            "ownership_type": str(first.get("ownership_type") or "Not recorded"),
            "charger_types": sorted({str(r.get("charger_type")) for r in rows if r.get("charger_type")}),
            "max_power_kw": max(powers) if powers else None,
            "reported_connectors": sum(connectors) if connectors else None,
            "reported_rows": len(rows),
            "source_pages": sorted({str(r.get("source_pages")) for r in rows if r.get("source_pages")}),
            "source_snapshot": "2025-10-26",
        })
    if not result:
        raise HTTPException(status_code=422, detail="No valid North India charger coordinate groups found in the GeoJSON.")
    return result


def _geocode_place(query: str) -> dict[str, Any]:
    """Low-volume, cached geocoding. Also accepts a manually entered 'lat, lon'."""
    global _last_geocode_at
    clean = " ".join(query.split())
    if not clean:
        raise HTTPException(status_code=422, detail="Origin and destination are required.")
    m = re.fullmatch(r"\s*(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)\s*", clean)
    if m:
        lat, lon = float(m.group(1)), float(m.group(2))
        if not (-90 <= lat <= 90 and -180 <= lon <= 180):
            raise HTTPException(status_code=422, detail=f"Coordinates out of range for '{clean}'.")
        return {"query": clean, "label": f"Manual coordinates {lat:.5f}, {lon:.5f}", "lat": lat, "lon": lon, "method": "user-supplied coordinates"}

    key = clean.casefold()
    if key in _geocode_cache:
        return _geocode_cache[key]
    with _geocode_lock:
        if key in _geocode_cache:
            return _geocode_cache[key]
        elapsed = time.monotonic() - _last_geocode_at
        if elapsed < GEOCODE_MIN_INTERVAL_S:
            time.sleep(GEOCODE_MIN_INTERVAL_S - elapsed)
        try:
            response = requests.get(
                NOMINATIM_URL,
                params={"q": clean, "format": "jsonv2", "limit": 1, "countrycodes": "in", "addressdetails": 1},
                headers={"User-Agent": APP_UA, "Accept": "application/json"}, timeout=20,
            )
            _last_geocode_at = time.monotonic()
            response.raise_for_status()
            payload = response.json()
        except requests.RequestException as exc:
            raise HTTPException(status_code=502, detail=f"Place lookup failed for '{clean}'. Check internet and retry, or enter latitude, longitude. Provider detail: {str(exc)[:160]}") from exc
        except ValueError as exc:
            raise HTTPException(status_code=502, detail="Place lookup returned invalid JSON. Retry later.") from exc
    if not payload:
        raise HTTPException(status_code=422, detail=f"Could not locate '{clean}'. Add district/state, e.g. 'Narnaul, Haryana, India', or enter latitude, longitude.")
    match = payload[0]
    lat, lon = _num(match.get("lat")), _num(match.get("lon"))
    if lat is None or lon is None:
        raise HTTPException(status_code=502, detail=f"Place lookup returned no coordinates for '{clean}'.")
    value = {"query": clean, "label": str(match.get("display_name") or clean), "lat": lat, "lon": lon, "method": "Nominatim place search"}
    _geocode_cache[key] = value
    return value


def _get_route(origin: dict[str, Any], destination: dict[str, Any]) -> dict[str, Any]:
    global _last_route_request_at
    cache_key = tuple(round(float(v), 5) for v in (origin["lon"], origin["lat"], destination["lon"], destination["lat"]))
    with _route_cache_lock:
        if cache_key in _route_cache:
            return _route_cache[cache_key]
    url = f"{OSRM_URL}/{origin['lon']:.6f},{origin['lat']:.6f};{destination['lon']:.6f},{destination['lat']:.6f}"
    try:
        # Keep calls to the public demo router low-volume (one request per second).
        with _route_request_lock:
            elapsed = time.monotonic() - _last_route_request_at
            if elapsed < 1.1:
                time.sleep(1.1 - elapsed)
            response = requests.get(url, params={"overview": "full", "geometries": "geojson", "steps": "true", "alternatives": "false"}, headers={"User-Agent": APP_UA, "Accept": "application/json"}, timeout=70)
            _last_route_request_at = time.monotonic()
        response.raise_for_status()
        data = response.json()
    except requests.RequestException as exc:
        raise HTTPException(status_code=502, detail=f"Road-routing service unavailable: {str(exc)[:160]}. Retry later or check routing service status.") from exc
    except ValueError as exc:
        raise HTTPException(status_code=502, detail="Road-routing service returned invalid JSON.") from exc
    if data.get("code") != "Ok" or not data.get("routes"):
        raise HTTPException(status_code=422, detail=f"No driving route found. Router returned {data.get('code', 'unknown')}.")
    route = data["routes"][0]
    coords = (route.get("geometry") or {}).get("coordinates") or []
    if len(coords) < 2:
        raise HTTPException(status_code=502, detail="Router returned no route geometry.")
    roads: Counter[str] = Counter()
    for leg in route.get("legs", []):
        for step in leg.get("steps", []):
            name = " ".join(str(step.get("name") or step.get("ref") or "").split())
            if name:
                roads[name] += _num(step.get("distance")) or 0
    value = {
        "coordinates": coords,
        "distance_km": float(route.get("distance", 0)) / 1000.0,
        "duration_hours": float(route.get("duration", 0)) / 3600.0,
        "road_names": [name for name, _ in roads.most_common(12)],
        "geometry_source": "OSRM driving router / OpenStreetMap road graph",
    }
    with _route_cache_lock:
        _route_cache[cache_key] = value
    return value


def _elevations(coords: list[tuple[float, float]]) -> tuple[list[float | None], str]:
    """Fetch elevations in batches of <=100; if unavailable, return unknown rather than hallucinating terrain."""
    global _elevation_cache
    keys = [(round(float(lat), 4), round(float(lon), 4)) for lat, lon in coords]
    out: list[float | None] = [None] * len(keys)
    missing_by_key: dict[tuple[float, float], list[int]] = defaultdict(list)
    with _elevation_lock:
        for i, key in enumerate(keys):
            if key in _elevation_cache:
                out[i] = _elevation_cache[key]
            else:
                missing_by_key[key].append(i)
    unique_missing = list(missing_by_key.keys())
    if not unique_missing:
        return out, "cached"
    failure = False
    for start in range(0, len(unique_missing), 80):
        batch = unique_missing[start:start + 80]
        try:
            response = requests.get(
                ELEVATION_URL,
                params={"latitude": ",".join(f"{p[0]:.4f}" for p in batch), "longitude": ",".join(f"{p[1]:.4f}" for p in batch)},
                headers={"User-Agent": APP_UA, "Accept": "application/json"}, timeout=30,
            )
            response.raise_for_status()
            vals = response.json().get("elevation", [])
            if not isinstance(vals, list) or len(vals) != len(batch):
                raise ValueError("Elevation response length mismatch")
        except (requests.RequestException, ValueError, TypeError):
            failure = True
            vals = [None] * len(batch)
        with _elevation_lock:
            for key, elevation in zip(batch, vals):
                value = _num(elevation)
                _elevation_cache[key] = value
                for i in missing_by_key[key]:
                    out[i] = value
    if failure and any(v is not None for v in out):
        return out, "partial"
    if failure:
        return out, "unavailable"
    return out, "Open-Meteo Copernicus GLO-90 elevation"


def _projected_line(coords: list[list[float]], origin: dict[str, Any], destination: dict[str, Any]):
    wgs84_line = LineString([(float(c[0]), float(c[1])) for c in coords])
    center_lat = (float(origin["lat"]) + float(destination["lat"])) / 2
    center_lon = (float(origin["lon"]) + float(destination["lon"])) / 2
    crs = CRS.from_proj4(f"+proj=aeqd +lat_0={center_lat} +lon_0={center_lon} +datum=WGS84 +units=m +no_defs")
    forward = Transformer.from_crs("EPSG:4326", crs, always_xy=True)
    reverse = Transformer.from_crs(crs, "EPSG:4326", always_xy=True)
    projected = shapely_transform(forward.transform, wgs84_line)
    if projected.length <= 0:
        raise HTTPException(status_code=502, detail="Could not calculate projected route geometry.")
    return projected, forward, reverse


def _route_sample_profile(route_line: LineString, reverse: Transformer, route_distance_km: float, projected_length_m: float) -> tuple[list[dict[str, Any]], str]:
    # 20–100 points, normally no farther than roughly 5 km apart, to retain manageable requests.
    count = max(20, min(100, int(math.ceil(route_distance_km / 5.0)) + 1))
    chainages = np.linspace(0.0, route_distance_km, count)
    locs: list[tuple[float, float]] = []
    for ch in chainages:
        point = route_line.interpolate(float(ch / route_distance_km * projected_length_m))
        lon, lat = reverse.transform(point.x, point.y)
        locs.append((float(lat), float(lon)))
    elevs, elev_source = _elevations(locs)
    samples: list[dict[str, Any]] = []
    for i, ((lat, lon), ch, elev) in enumerate(zip(locs, chainages, elevs)):
        prev_elev = elevs[i - 1] if i > 0 else None
        step_km = (float(chainages[i]) - float(chainages[i - 1])) if i > 0 else None
        grade = (abs(elev - prev_elev) / (step_km * 1000.0) * 100.0) if (elev is not None and prev_elev is not None and step_km and step_km > 0) else None
        samples.append({"route_km": round(float(ch), 2), "lat": round(lat, 6), "lon": round(lon, 6), "elevation_m": round(elev, 1) if elev is not None else None, "absolute_grade_proxy_pct": round(grade, 2) if grade is not None else None})
    return samples, elev_source


def _classify_terrain(elevations: list[float | None], grade_proxy: float | None) -> str:
    valid = [e for e in elevations if e is not None]
    if not valid:
        return "unknown"
    mean_elev, max_elev, relief = float(np.mean(valid)), max(valid), max(valid) - min(valid)
    grade = grade_proxy or 0.0
    if max_elev >= 3000 or mean_elev >= 2800:
        return "high_himalaya"
    if mean_elev >= 1500 or grade >= 5.5 or relief >= 250:
        return "hills"
    if mean_elev >= 600 or grade >= 2.5 or relief >= 100:
        return "rolling"
    return "plains"


def _scenario_demand(req: RouteAnalyzeRequest, scenario: str) -> dict[str, Any]:
    if req.traffic_vehicles_per_day is None or req.current_ev_share_pct is None:
        return {
            "measured_demand_available": False,
            "future_daily_traffic_vehicles": None,
            "future_ev_share_pct": None,
            "estimated_public_charging_sessions_per_day": None,
            "estimated_public_energy_kwh_per_day": None,
            "estimated_plugs_at_assumed_power": None,
            "message": "Demand not calculated: enter road traffic and current EV share. No live traffic/session feed is connected.",
        }
    years = max(0, req.planning_year - 2026)
    sc = SCENARIOS[scenario]
    annual_ev_growth = req.annual_ev_share_growth_pct * sc["growth_multiplier"] / 100.0
    traffic_growth = req.annual_traffic_growth_pct / 100.0
    future_traffic = req.traffic_vehicles_per_day * ((1 + traffic_growth) ** years)
    future_share = min(100.0, req.current_ev_share_pct * ((1 + annual_ev_growth) ** years))
    future_ev_vehicles = future_traffic * future_share / 100.0
    sessions = future_ev_vehicles * req.public_charge_share_pct / 100.0
    energy = sessions * req.average_session_kwh
    daily_plug_energy = req.assumed_charger_power_kw * 24.0 * (req.target_utilization_pct / 100.0)
    plugs = int(math.ceil(energy / daily_plug_energy)) if daily_plug_energy > 0 else None
    return {
        "measured_demand_available": False,
        "is_scenario_estimate": True,
        "base_year": 2026,
        "planning_year": req.planning_year,
        "years_projected": years,
        "input_daily_traffic_vehicles": req.traffic_vehicles_per_day,
        "input_current_ev_share_pct": req.current_ev_share_pct,
        "assumed_annual_traffic_growth_pct": req.annual_traffic_growth_pct,
        "assumed_annual_ev_share_growth_pct_for_scenario": round(annual_ev_growth * 100, 2),
        "assumed_public_charge_share_pct": req.public_charge_share_pct,
        "assumed_average_session_kwh": req.average_session_kwh,
        "future_daily_traffic_vehicles": round(future_traffic, 1),
        "future_ev_share_pct": round(future_share, 3),
        "estimated_ev_vehicles_per_day": round(future_ev_vehicles, 1),
        "estimated_public_charging_sessions_per_day": round(sessions, 2),
        "estimated_public_energy_kwh_per_day": round(energy, 1),
        "estimated_plugs_at_assumed_power": plugs,
        "plug_energy_capacity_assumption_kwh_day": round(daily_plug_energy, 1),
        "message": "Scenario estimate from user-entered traffic/EV share and assumptions; not measured demand or a trained forecast.",
    }


def _demand_density_factor(demand: dict[str, Any]) -> float:
    sessions = demand.get("estimated_public_charging_sessions_per_day")
    if sessions is None:
        return 1.0
    # Transparent screening bands only. Calibrate these from observed charger utilization when available.
    if sessions >= 100:
        return 0.72
    if sessions >= 40:
        return 0.80
    if sessions >= 15:
        return 0.88
    if sessions >= 5:
        return 0.95
    return 1.0


def _spacing_for_terrain(terrain_class: str, req: RouteAnalyzeRequest, scenario: str, demand: dict[str, Any]) -> dict[str, Any]:
    cfg = TERRAIN.get(terrain_class, TERRAIN["unknown"])
    sc = SCENARIOS[scenario]
    demand_factor = _demand_density_factor(demand)
    risk_factor = 0.82 if req.remote_or_seasonal else 1.0
    usable_range = req.vehicle_range_km * (1.0 - req.reserve_pct / 100.0) * cfg["range_factor"]
    range_hop_cap = usable_range * 0.35
    target = min(
        POLICY_GENERAL_SPACING_KM,
        POLICY_GENERAL_SPACING_KM * cfg["spacing_factor"] * sc["density_factor"] * demand_factor * risk_factor,
        range_hop_cap,
    )
    target = max(3.0, target)
    fast = min(
        POLICY_FAST_SPACING_KM,
        POLICY_FAST_SPACING_KM * cfg["fast_factor"] * sc["density_factor"] * demand_factor * risk_factor,
        usable_range * 0.75,
    )
    fast = max(10.0, fast)
    return {
        "terrain_class": terrain_class,
        "terrain_label": cfg["label"],
        "terrain_description": cfg["description"],
        "terrain_spacing_factor": cfg["spacing_factor"],
        "terrain_energy_factor": cfg["range_factor"],
        "adoption_scenario_spacing_factor": sc["density_factor"],
        "demand_density_factor": demand_factor,
        "remote_seasonal_risk_factor": risk_factor,
        "effective_usable_range_km": round(usable_range, 1),
        "range_limited_spacing_cap_km": round(range_hop_cap, 1),
        "adaptive_spacing_km": round(target, 1),
        "adaptive_fast_review_spacing_km": round(fast, 1),
        "policy_general_reference_km": POLICY_GENERAL_SPACING_KM,
        "policy_fast_reference_km": POLICY_FAST_SPACING_KM,
    }


def _build_terrain_segments(samples: list[dict[str, Any]], route_distance_km: float, req: RouteAnalyzeRequest, scenario: str, demand: dict[str, Any], origin: dict[str, Any], destination: dict[str, Any], elevation_status: str) -> list[dict[str, Any]]:
    override = req.terrain_mode != "auto"
    keyword_remote = any(k in (req.origin + " " + req.destination).casefold() for k in ("lahaul", "spiti", "kaza", "keylong", "leh", "zanskar", "baralacha", "kunzum", "rohtang"))
    remote = req.remote_or_seasonal or keyword_remote
    raw_segments: list[dict[str, Any]] = []
    for i in range(len(samples) - 1):
        a, b = samples[i], samples[i + 1]
        elevs = [e for e in (a["elevation_m"], b["elevation_m"]) if e is not None]
        grade = max([v for v in (a["absolute_grade_proxy_pct"], b["absolute_grade_proxy_pct"]) if v is not None], default=None)
        if override:
            terrain_class = req.terrain_mode
        else:
            terrain_class = _classify_terrain(elevs, grade)
            if terrain_class == "high_himalaya" and remote:
                terrain_class = "remote_high_himalaya"
            elif terrain_class == "hills" and remote and (max(elevs) if elevs else 0) >= 1800:
                terrain_class = "remote_high_himalaya"
        raw_segments.append({
            "start_km": a["route_km"], "end_km": b["route_km"],
            "start_elevation_m": a["elevation_m"], "end_elevation_m": b["elevation_m"],
            "mean_elevation_m": round(float(np.mean(elevs)), 1) if elevs else None,
            "grade_proxy_pct": round(grade, 2) if grade is not None else None,
            "terrain_class": terrain_class,
        })
    # Merge adjacent segments of the same class to keep the UI/report readable.
    merged: list[dict[str, Any]] = []
    for seg in raw_segments:
        if merged and merged[-1]["terrain_class"] == seg["terrain_class"]:
            current = merged[-1]
            current["end_km"] = seg["end_km"]
            for f in ("start_elevation_m", "end_elevation_m"):
                # Preserve first start elevation and update final end elevation.
                if f == "end_elevation_m": current[f] = seg[f]
            vals = [v for v in (current.get("mean_elevation_m"), seg.get("mean_elevation_m")) if v is not None]
            current["mean_elevation_m"] = round(float(np.mean(vals)), 1) if vals else None
            grades = [v for v in (current.get("grade_proxy_pct"), seg.get("grade_proxy_pct")) if v is not None]
            current["grade_proxy_pct"] = round(max(grades), 2) if grades else None
        else:
            merged.append(dict(seg))
    for seg in merged:
        model = _spacing_for_terrain(seg["terrain_class"], req, scenario, demand)
        seg.update(model)
        seg["length_km"] = round(seg["end_km"] - seg["start_km"], 2)
    if elevation_status == "unavailable" and not override:
        # Unknown segments use conservative fallback from _classify_terrain.
        for seg in merged:
            seg["terrain_note"] = "Elevation lookup unavailable; terrain class is conservative fallback, not measured classification."
    if remote:
        for seg in merged:
            seg["remote_route_flag"] = True
    return merged


def _haversine_vector(lat: float, lon: float, points: np.ndarray) -> np.ndarray:
    lat1, lon1 = math.radians(lat), math.radians(lon)
    lat2, lon2 = np.radians(points[:, 0]), np.radians(points[:, 1])
    dlat, dlon = lat2 - lat1, lon2 - lon1
    h = np.sin(dlat / 2) ** 2 + math.cos(lat1) * np.cos(lat2) * np.sin(dlon / 2) ** 2
    return 2 * EARTH_RADIUS_KM * np.arcsin(np.sqrt(np.clip(h, 0, 1)))


def _route_side(line: LineString, point: Point, offset_m: float) -> str:
    if offset_m < 40:
        return "centreline_or_side_unknown"
    along = line.project(point)
    before = line.interpolate(max(0.0, along - 30.0))
    after = line.interpolate(min(line.length, along + 30.0))
    near = line.interpolate(along)
    cross = (after.x - before.x) * (point.y - near.y) - (after.y - before.y) * (point.x - near.x)
    return "left" if cross > 0 else "right"


def _terrain_at(chainage: float, segments: list[dict[str, Any]]) -> dict[str, Any]:
    if not segments:
        return TERRAIN["unknown"]
    for seg in segments:
        if seg["start_km"] <= chainage <= seg["end_km"]:
            return seg
    return segments[0] if chainage < segments[0]["start_km"] else segments[-1]


def _conservative_spacing_for_span(left: float, right: float, segments: list[dict[str, Any]], kind: str) -> float:
    overlapping = []
    for seg in segments:
        if seg["end_km"] >= left and seg["start_km"] <= right:
            overlapping.append(float(seg["adaptive_spacing_km"] if kind == "general" else seg["adaptive_fast_review_spacing_km"]))
    return max(3.0 if kind == "general" else 10.0, min(overlapping) if overlapping else (18.0 if kind == "general" else 60.0))


def _candidate_offset_point(line: LineString, chainage_km: float, route_distance_km: float, line_length_m: float, reverse: Transformer, side: str, offset_m: float = 250.0) -> tuple[float, float]:
    along_m = min(line_length_m, max(0.0, chainage_km / max(route_distance_km, 0.001) * line_length_m))
    p = line.interpolate(along_m)
    before = line.interpolate(max(0.0, along_m - 50.0))
    after = line.interpolate(min(line_length_m, along_m + 50.0))
    dx, dy = after.x - before.x, after.y - before.y
    norm = math.hypot(dx, dy) or 1.0
    sign = 1.0 if side == "left" else -1.0
    x = p.x + sign * (-dy / norm) * offset_m
    y = p.y + sign * (dx / norm) * offset_m
    lon, lat = reverse.transform(x, y)
    return float(lat), float(lon)


def _plan_spacing(route_line: LineString, route_distance_km: float, line_length_m: float, reverse: Transformer,
                  corridor_sites: list[dict[str, Any]], all_sites: list[dict[str, Any]], segments: list[dict[str, Any]],
                  req: RouteAnalyzeRequest, scenario: str) -> dict[str, Any]:
    candidates: list[dict[str, Any]] = []
    gaps: list[dict[str, Any]] = []
    fast_gaps: list[dict[str, Any]] = []

    def add_candidate(chainage: float, side: str, category: str, gap_start: float, gap_end: float, gap_length: float, target: float) -> None:
        lat, lon = _candidate_offset_point(route_line, chainage, route_distance_km, line_length_m, reverse, side)
        terrain = _terrain_at(chainage, segments)
        existing = next((c for c in candidates if c["route_side"] == side and abs(c["route_km"] - chainage) <= max(1.0, min(3.0, target / 8.0))), None)
        gap_record = {"start_km": round(gap_start, 2), "end_km": round(gap_end, 2), "gap_km": round(gap_length, 2), "target_spacing_km": round(target, 2)}
        if existing:
            if category not in existing["requirements"]:
                existing["requirements"].append(category)
            existing["related_gaps"].append(gap_record)
            return
        candidates.append({
            "route_km": round(float(chainage), 2), "lat": round(lat, 6), "lon": round(lon, 6),
            "route_side": side, "terrain_class": terrain.get("terrain_class", "unknown"),
            "terrain_label": terrain.get("terrain_label", TERRAIN.get(terrain.get("terrain_class", "unknown"), TERRAIN["unknown"])["label"]),
            "target_spacing_km": round(float(terrain.get("adaptive_spacing_km", target)), 1),
            "target_fast_spacing_km": round(float(terrain.get("adaptive_fast_review_spacing_km", target)), 1),
            "requirements": [category], "related_gaps": [gap_record],
            "status": "SCREENING_CANDIDATE_NOT_SITE_VERIFIED",
        })

    side_inventory: dict[str, list[dict[str, Any]]] = {"left": [], "right": []}
    side_fast: dict[str, list[dict[str, Any]]] = {"left": [], "right": []}
    for s in corridor_sites:
        side = s["route_side"]
        if side in side_inventory:
            side_inventory[side].append(s)
            if (s.get("max_power_kw") or 0) >= 50:
                side_fast[side].append(s)

    # Also report centrelined/side-unknown inventory but do not falsely treat it as both-side highway coverage.
    centreline_sites = [s for s in corridor_sites if s["route_side"] == "centreline_or_side_unknown"]
    for side in ("left", "right"):
        chainages = sorted([float(s["chainage_km"]) for s in side_inventory[side]])
        anchors = [0.0, *chainages, route_distance_km]
        for left, right in zip(anchors, anchors[1:]):
            if right - left < 0.1:
                continue
            target = _conservative_spacing_for_span(left, right, segments, "general")
            policy_additional = max(0, int(math.ceil((right - left) / POLICY_GENERAL_SPACING_KM - 1e-9)) - 1)
            model_additional = max(0, int(math.ceil((right - left) / target - 1e-9)) - 1)
            gaps.append({
                "route_side": side, "from_km": round(left, 2), "to_km": round(right, 2),
                "gap_km": round(right - left, 2), "adaptive_target_spacing_km": round(target, 2),
                "policy_reference_spacing_km": POLICY_GENERAL_SPACING_KM,
                "adaptive_gap_exceeds_target": (right - left) > target + 0.01,
                "policy_reference_gap_exceeds_20km": (right - left) > POLICY_GENERAL_SPACING_KM + 0.01,
                "additional_sites_model": model_additional,
                "additional_sites_policy_reference": policy_additional,
                "boundary_note": "Route endpoints are boundaries, not proof that a charger exists at the origin/destination.",
            })
            # Evenly split each observed gap; spacing does not exceed the selected target.
            for j in range(1, model_additional + 1):
                ch = left + (right - left) * j / (model_additional + 1)
                add_candidate(ch, side, "adaptive general coverage", left, right, right - left, target)

        fast_chainages = sorted([float(s["chainage_km"]) for s in side_fast[side]])
        fast_anchors = [0.0, *fast_chainages, route_distance_km]
        for left, right in zip(fast_anchors, fast_anchors[1:]):
            if right - left < 0.1:
                continue
            target = _conservative_spacing_for_span(left, right, segments, "fast")
            policy_additional = max(0, int(math.ceil((right - left) / POLICY_FAST_SPACING_KM - 1e-9)) - 1)
            model_additional = max(0, int(math.ceil((right - left) / target - 1e-9)) - 1)
            fast_gaps.append({
                "route_side": side, "from_km": round(left, 2), "to_km": round(right, 2),
                "gap_km": round(right - left, 2), "adaptive_fast_target_spacing_km": round(target, 2),
                "policy_reference_fcs_spacing_km": POLICY_FAST_SPACING_KM,
                "adaptive_gap_exceeds_target": (right - left) > target + 0.01,
                "policy_reference_gap_exceeds_100km": (right - left) > POLICY_FAST_SPACING_KM + 0.01,
                "additional_fast_review_sites_model": model_additional,
                "additional_sites_policy_reference": policy_additional,
                "note": "A mapped rating threshold is a screening proxy, not certification that the site meets every FCS configuration requirement.",
            })
            for j in range(1, model_additional + 1):
                ch = left + (right - left) * j / (model_additional + 1)
                add_candidate(ch, side, "fast-charge review (reported site rating >=50 kW)", left, right, right - left, target)

    all_coords = np.array([[s["lat"], s["lon"]] for s in all_sites], dtype=float)
    for cand in candidates:
        distances = _haversine_vector(cand["lat"], cand["lon"], all_coords)
        ni = int(np.argmin(distances))
        near = all_sites[ni]
        cand["nearest_inventory_km"] = round(float(distances[ni]), 2)
        cand["nearest_inventory_state"] = near["state"]
        cand["nearest_inventory_location"] = near["location"]
        cand["requirements_label"] = "; ".join(cand["requirements"])
        cand["reason"] = f"Route screening candidate at route km {cand['route_km']}; nearest reported inventory coordinate is {cand['nearest_inventory_km']} km away."
        cand["grid_readiness"] = "UNVERIFIED — utility feeder/transformer data absent"
    candidates.sort(key=lambda c: c["route_km"])
    for i, cand in enumerate(candidates, 1):
        cand["rank"] = i
        cand["candidate_id"] = f"ROUTE-CAND-{i:03d}"

    max_side_gap = max((g["gap_km"] for g in gaps), default=0.0)
    return {"recommendations": candidates, "coverage_gaps": gaps, "fast_gaps": fast_gaps,
            "centreline_or_side_unknown_inventory_groups": len(centreline_sites),
            "maximum_existing_gap_by_side_km": round(max_side_gap, 2)}


@router.get("/route-planner", response_class=HTMLResponse)
def route_planner_page() -> HTMLResponse:
    if not ROUTE_HTML.exists():
        return HTMLResponse("<h1>Route planner frontend missing</h1><p>app/static/route_planner.html not found.</p>", status_code=500)
    return HTMLResponse(ROUTE_HTML.read_text(encoding="utf-8"))


@router.get("/api/route/info")
def route_model_info() -> dict[str, Any]:
    return {
        "model": "Route coverage screening based on terrain and vehicle range",
        "learning_status": "spacing is calculated using explicit rules and user-selected assumptions; measured route-level charger use and hourly charging sessions are not available",
        "terrain_data": "Open-Meteo elevation API (Copernicus GLO-90); if unavailable, the UI marks terrain as unverified/conservative fallback",
        "routing": "OSRM public driving router based on OpenStreetMap",
        "inventory_snapshot": "BEE public charging station inventory, 26 Oct 2025",
        "policy_references": {"general_public_charging_spacing_km": POLICY_GENERAL_SPACING_KM, "long_range_heavy_duty_fast_charging_reference_km": POLICY_FAST_SPACING_KM},
        "policy_note": "Ministry of Power EVCI-2024 guidance includes a 20 km public charging station spacing reference on both sides of highways/roads and a 100 km fast-charging reference on each side for long-range/heavy-duty EVs. This route screen is not legal certification; interpret against official guidance, road class, local plans and actual side-of-road access.",
        "grid_model": "Not connected: feeder topology, transformer ratings/load, voltage history and outage data must be supplied to calculate electrical feasibility.",
    }


@router.get("/api/route/grid-template.csv")
def route_grid_template() -> StreamingResponse:
    out = io.StringIO()
    fields = ["candidate_id", "route_name", "nearest_substation_id", "feeder_id", "transformer_id", "transformer_rated_kva", "existing_peak_load_kva", "spare_capacity_kva", "feeder_length_km", "feeder_resistance_ohm", "feeder_reactance_ohm", "min_bus_voltage_pu", "peak_bus_voltage_pu", "monthly_outage_hours", "connection_feasibility_kva", "discom", "data_date", "evidence_source"]
    writer = csv.DictWriter(out, fieldnames=fields)
    writer.writeheader()
    writer.writerow({f: "" for f in fields})
    out.seek(0)
    return StreamingResponse(iter([out.getvalue()]), media_type="text/csv", headers={"Content-Disposition": "attachment; filename=grid_feasibility_data_template.csv"})


@router.post("/api/route/analyze")
def analyze_route(request: RouteAnalyzeRequest) -> dict[str, Any]:
    """Calculate route geometry, terrain segments, suggested spacing, and nearby inventory gaps."""
    if request.origin.strip().casefold() == request.destination.strip().casefold():
        raise HTTPException(status_code=422, detail="Origin and destination must be different places.")
    remote_keywords = ("lahaul", "spiti", "kaza", "keylong", "leh", "zanskar", "baralacha", "kunzum", "rohtang")
    if any(k in (request.origin + " " + request.destination).casefold() for k in remote_keywords):
        request.remote_or_seasonal = True
    origin = _geocode_place(request.origin)
    destination = _geocode_place(request.destination)
    route = _get_route(origin, destination)
    coords = route["coordinates"]
    projected_line, forward, reverse = _projected_line(coords, origin, destination)
    route_distance = float(route["distance_km"])
    if route_distance <= 0:
        raise HTTPException(status_code=502, detail="Router returned a zero-length route.")

    samples, elevation_status = _route_sample_profile(projected_line, reverse, route_distance, float(projected_line.length))
    selected_demand = _scenario_demand(request, request.adoption_scenario)
    segments = _build_terrain_segments(samples, route_distance, request, request.adoption_scenario, selected_demand, origin, destination, elevation_status)

    # Spatially project the reported BEE point inventory onto the route to assess corridor proximity and left/right side.
    all_sites = _inventory_groups()
    corridor_sites: list[dict[str, Any]] = []
    side_counts: Counter[str] = Counter()
    for site in all_sites:
        x, y = forward.transform(site["lon"], site["lat"])
        point = Point(x, y)
        offset_m = float(projected_line.distance(point))
        if offset_m > request.corridor_km * 1000:
            continue
        projected_along_m = float(projected_line.project(point))
        chainage = projected_along_m / float(projected_line.length) * route_distance
        side = _route_side(projected_line, point, offset_m)
        side_counts[side] += 1
        corridor_sites.append({
            **site, "chainage_km": round(chainage, 2), "lateral_distance_km": round(offset_m / 1000.0, 2), "route_side": side,
        })
    corridor_sites.sort(key=lambda s: s["chainage_km"])

    selected_plan = _plan_spacing(projected_line, route_distance, float(projected_line.length), reverse, corridor_sites, all_sites, segments, request, request.adoption_scenario)

    scenario_comparison = []
    for scenario in ("conservative", "base", "accelerated"):
        demand = _scenario_demand(request, scenario)
        scenario_segments = _build_terrain_segments(samples, route_distance, request, scenario, demand, origin, destination, elevation_status)
        scenario_plan = _plan_spacing(projected_line, route_distance, float(projected_line.length), reverse, corridor_sites, all_sites, scenario_segments, request, scenario)
        spacings = [s["adaptive_spacing_km"] for s in scenario_segments]
        scenario_comparison.append({
            "scenario": scenario, "label": SCENARIOS[scenario]["label"],
            "recommended_adaptive_candidate_count": len(scenario_plan["recommendations"]),
            "adaptive_general_spacing_min_km": round(min(spacings), 1) if spacings else None,
            "adaptive_general_spacing_max_km": round(max(spacings), 1) if spacings else None,
            "estimated_public_sessions_per_day": demand.get("estimated_public_charging_sessions_per_day"),
            "estimated_public_energy_kwh_per_day": demand.get("estimated_public_energy_kwh_per_day"),
            "status": "scenario estimate; not a trained/validated demand forecast",
        })

    station_features = []
    for s in corridor_sites:
        station_features.append({
            "lat": s["lat"], "lon": s["lon"], "state": s["state"], "location": s["location"],
            "operator": s["operator"], "max_power_kw": s["max_power_kw"], "reported_connectors": s["reported_connectors"],
            "route_km": s["chainage_km"], "lateral_distance_km": s["lateral_distance_km"], "route_side": s["route_side"],
            "charger_types": s["charger_types"], "reported_rows_at_coordinate": s["reported_rows"], "source_pages": s["source_pages"],
        })
    fast_sites = [s for s in corridor_sites if (s.get("max_power_kw") or 0) >= 50]
    terrain_counts = Counter(s["terrain_class"] for s in segments)
    adaptive_values = [s["adaptive_spacing_km"] for s in segments]
    fast_values = [s["adaptive_fast_review_spacing_km"] for s in segments]

    return {
        "status": "ok", "origin": origin, "destination": destination,
        "route_distance_km": round(route_distance, 2), "estimated_driving_hours": round(route["duration_hours"], 2),
        "road_labels": route["road_names"], "route_source": route["geometry_source"],
        "geometry": {"type": "LineString", "coordinates": coords},
        "terrain": {
            "mode": request.terrain_mode, "elevation_status": elevation_status,
            "samples": samples, "segments": segments, "segment_count_by_class": dict(terrain_counts),
            "remote_or_seasonal_flag": request.remote_or_seasonal or any(k in (request.origin + " " + request.destination).casefold() for k in ("lahaul", "spiti", "kaza", "keylong", "leh", "zanskar", "baralacha", "kunzum", "rohtang")),
            "note": "Terrain classes are sampled from a 90 m elevation model and grade proxies; they are not a road-surface, weather, avalanche, road-width or seasonal-closure assessment.",
        },
        "settings": {
            "vehicle_range_km": request.vehicle_range_km, "reserve_pct": request.reserve_pct,
            "planning_year": request.planning_year, "adoption_scenario": request.adoption_scenario,
            "corridor_km": request.corridor_km, "remote_or_seasonal": request.remote_or_seasonal,
            "assumed_charger_power_kw": request.assumed_charger_power_kw, "target_utilization_pct": request.target_utilization_pct,
            "policy_general_reference_spacing_km": POLICY_GENERAL_SPACING_KM,
            "policy_fast_reference_spacing_km": POLICY_FAST_SPACING_KM,
        },
        "demand_scenario": selected_demand,
        "summary": {
            "reported_coordinate_groups_in_route_corridor": len(corridor_sites),
            "reported_fast_capable_groups_ge_50kw_in_route_corridor": len(fast_sites),
            "candidate_coordinates_recommended_for_selected_scenario": len(selected_plan["recommendations"]),
            "left_right_inventory_group_counts": dict(side_counts),
            "segments_with_different_terrain_classes": len(segments),
            "adaptive_general_spacing_min_km": round(min(adaptive_values), 1) if adaptive_values else None,
            "adaptive_general_spacing_max_km": round(max(adaptive_values), 1) if adaptive_values else None,
            "adaptive_fast_spacing_min_km": round(min(fast_values), 1) if fast_values else None,
            "adaptive_fast_spacing_max_km": round(max(fast_values), 1) if fast_values else None,
            "adaptive_general_gap_flags": sum(1 for g in selected_plan["coverage_gaps"] if g["adaptive_gap_exceeds_target"]),
            "policy_reference_20km_gap_flags": sum(1 for g in selected_plan["coverage_gaps"] if g["policy_reference_gap_exceeds_20km"]),
            "adaptive_fast_gap_flags": sum(1 for g in selected_plan["fast_gaps"] if g["adaptive_gap_exceeds_target"]),
            "policy_reference_100km_fast_gap_flags": sum(1 for g in selected_plan["fast_gaps"] if g["policy_reference_gap_exceeds_100km"]),
            "maximum_existing_gap_by_side_km": selected_plan["maximum_existing_gap_by_side_km"],
            "centreline_or_side_unknown_inventory_groups": selected_plan["centreline_or_side_unknown_inventory_groups"],
        },
        "scenario_comparison": scenario_comparison,
        "coverage_gaps": selected_plan["coverage_gaps"],
        "fast_gaps": selected_plan["fast_gaps"],
        "corridor_stations": station_features,
        "recommendations": selected_plan["recommendations"],
        "formula": {
            "general_spacing": "min(20 km EVCI-2024 policy reference, 20 km × terrain_spacing_factor × adoption_scenario_factor × demand_factor × remote_risk_factor, usable_range × terrain_energy_factor × 0.35)",
            "usable_range": "vehicle_range × (1 − reserve_fraction) × terrain_energy_factor",
            "fast_review_spacing": "min(100 km policy reference, 100 km × terrain_fast_factor × adoption_scenario_factor × demand_factor × remote_risk_factor, usable_range × 0.75)",
            "demand_factor_bands": "If sessions estimated: >=100/day => 0.72; >=40 => 0.80; >=15 => 0.88; >=5 => 0.95; otherwise 1.00. Screening bands only; calibrate with measured sessions.",
            "learning_boundary": "Route spacing uses explicit rules and user-selected assumptions; it has not been fitted to measured charging outcomes. DBSCAN is used separately to group nearby station coordinates.",
        },
        "evidence": {
            "inventory": "BEE public charging-station snapshot dated 26 Oct 2025; current operational status is not live-verified.",
            "road_route": "OSRM public driving router / OpenStreetMap; route must be checked for vehicle restrictions, road condition and seasonal closures.",
            "terrain": elevation_status,
            "traffic": "User-entered estimate only if inputs were supplied; no live traffic feed is connected.",
            "grid_capacity": "UNVERIFIED: transformer/feeder topology, spare capacity, voltage profile, power quality and outage history are not present.",
            "physical_site": "Candidate is an offset route-screening coordinate; no land availability, road access, permissions or safety audit is verified.",
        },
        "limitations": [
            "The 20 km general and 100 km long-range/heavy-duty fast-charging values are policy reference benchmarks from EVCI-2024 guidance; the algorithm tightens them for terrain/range/scenario but is not a compliance certificate.",
            "High-altitude and remote-route categories do not automatically determine current EV road legality or seasonal passability. Verify route status with relevant road authorities before travel or deployment.",
            "Elevation is a coarse terrain proxy and does not represent measured road gradient, surface, snow/ice, landslide/avalanche risk or weather.",
            "The inventory is a dated snapshot; currently operating status, both-side site access and route-specific traffic are not independently verified.",
            "Demand and future values are scenario estimates only when user inputs are supplied; this is not a trained forecasting model.",
            "No voltage-drop, transformer-overload, grid hosting-capacity or outage-risk calculation is possible until distribution network data is imported and validated.",
        ],
    }


@router.post("/api/route/export.csv")
def export_route_candidates(request: RouteAnalyzeRequest) -> StreamingResponse:
    # Export uses the same live calculation so the file matches current form inputs.
    result = analyze_route(request)
    buf = io.StringIO()
    fields = ["candidate_id", "route_km", "lat", "lon", "route_side", "terrain_class", "target_spacing_km", "target_fast_spacing_km", "nearest_inventory_km", "nearest_inventory_state", "nearest_inventory_location", "requirements_label", "reason", "grid_readiness", "status"]
    writer = csv.DictWriter(buf, fieldnames=fields, extrasaction="ignore")
    writer.writeheader()
    writer.writerows(result["recommendations"])
    buf.seek(0)
    return StreamingResponse(iter([buf.getvalue()]), media_type="text/csv", headers={"Content-Disposition": "attachment; filename=gridpulse_route_candidate_screening.csv"})
