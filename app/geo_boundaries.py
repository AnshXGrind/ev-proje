from __future__ import annotations

import json
import re
import unicodedata
from functools import lru_cache
from pathlib import Path
from typing import Any

from shapely.geometry import Point, shape
from shapely.ops import unary_union

ROOT = Path(__file__).resolve().parents[1]
BOUNDARY_PATH = ROOT / "data" / "processed" / "india_state_boundaries.geojson"

STATE_NAMES = [
    "Andaman and Nicobar Islands", "Andhra Pradesh", "Arunachal Pradesh", "Assam",
    "Bihar", "Chandigarh", "Chhattisgarh", "Dadra and Nagar Haveli and Daman and Diu",
    "Delhi", "Goa", "Gujarat", "Haryana", "Himachal Pradesh", "Jammu and Kashmir",
    "Jharkhand", "Karnataka", "Kerala", "Ladakh", "Lakshadweep", "Madhya Pradesh",
    "Maharashtra", "Manipur", "Meghalaya", "Mizoram", "Nagaland", "Odisha",
    "Puducherry", "Punjab", "Rajasthan", "Sikkim", "Tamil Nadu", "Telangana",
    "Tripura", "Uttar Pradesh", "Uttarakhand", "West Bengal",
]


def _fold_state_key(value: Any) -> str:
    """Normalize spelling variants from GIS attributes without changing canonical output names."""
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(character for character in text if not unicodedata.combining(character))
    text = text.casefold().replace("&", " and ")
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


_CANONICAL = {_fold_state_key(name): name for name in STATE_NAMES}
_ALIAS_SOURCE = {
    "andaman & nicobar": "Andaman and Nicobar Islands",
    "andaman and nicobar": "Andaman and Nicobar Islands",
    "andaman & nicobar islands": "Andaman and Nicobar Islands",
    "andaman and nicobar island": "Andaman and Nicobar Islands",
    "andaman & nicobar island": "Andaman and Nicobar Islands",
    "nct of delhi": "Delhi",
    "national capital territory of delhi": "Delhi",
    "jammu & kashmir": "Jammu and Kashmir",
    "j&k": "Jammu and Kashmir",
    "uttrakhand": "Uttarakhand",
    "uttaranchal": "Uttarakhand",
    "pondicherry": "Puducherry",
    "orissa": "Odisha",
    "dadra & nagar haveli and daman & diu": "Dadra and Nagar Haveli and Daman and Diu",
    "dadra and nagar haveli, daman and diu": "Dadra and Nagar Haveli and Daman and Diu",
    "dadra and nagar haveli and daman and diu": "Dadra and Nagar Haveli and Daman and Diu",
    "ut of d&nh and d&d": "Dadra and Nagar Haveli and Daman and Diu",
    "ut of d&nh and d&d.": "Dadra and Nagar Haveli and Daman and Diu",
    "dadra and nagar haveli": "Dadra and Nagar Haveli and Daman and Diu",
    "dadra & nagar haveli": "Dadra and Nagar Haveli and Daman and Diu",
    "dadra & nagar haveli and daman & diu": "Dadra and Nagar Haveli and Daman and Diu",
    "daman and diu": "Dadra and Nagar Haveli and Daman and Diu",
}
_ALIASES = {_fold_state_key(alias): canonical for alias, canonical in _ALIAS_SOURCE.items()}


def normalize_state_name(value: Any) -> str:
    text = re.sub(r"\s+", " ", str(value or "").strip()).strip(" ,.;")
    key = _fold_state_key(text)
    if key in _CANONICAL:
        return _CANONICAL[key]
    if key in _ALIASES:
        return _ALIASES[key]
    # Collapses common extraction artefacts such as "Maharashtra Maharashtra".
    words = text.split()
    if len(words) > 1 and len(words) % 2 == 0:
        half = len(words) // 2
        if [w.casefold() for w in words[:half]] == [w.casefold() for w in words[half:]]:
            return normalize_state_name(" ".join(words[:half]))
    # Boundary files sometimes provide a multipart UT with a descriptive prefix.
    for alias, canonical in sorted(_ALIASES.items(), key=lambda item: len(item[0]), reverse=True):
        if key in {f"state of {alias}", f"union territory of {alias}"}:
            return canonical
    return ""


def _feature_state(properties: dict[str, Any]) -> str:
    # Try common administrative-name fields first, then any string property.
    preferred = ("state", "state_name", "state/ut", "state_ut", "st_nm", "st_name",
                 "name_1", "shapeName", "shapeName_en", "admin1Name", "NAME_1", "NAME")
    for key in preferred:
        if key in properties:
            normalized = normalize_state_name(properties[key])
            if normalized:
                return normalized
    for value in properties.values():
        if isinstance(value, str):
            normalized = normalize_state_name(value)
            if normalized:
                return normalized
    return ""


@lru_cache(maxsize=4)
def _load_state_boundaries_cached(path_text: str):
    path = Path(path_text)
    if not path.exists():
        raise FileNotFoundError(
            f"Authoritative India state/UT boundary file not found: {path}. "
            "Run scripts/prepare_india_inventory.py to download and load the Survey of India/NWIC boundary."
        )
    with path.open("r", encoding="utf-8-sig") as stream:
        data = json.load(stream)
    if data.get("type") != "FeatureCollection":
        raise RuntimeError(f"Boundary file is not a GeoJSON FeatureCollection: {path}")
    polygons: dict[str, Any] = {}
    for feature in data.get("features", []):
        if not isinstance(feature, dict):
            continue
        state = _feature_state(feature.get("properties") or {})
        geometry = feature.get("geometry")
        if not state or not geometry:
            continue
        try:
            geom = shape(geometry)
            if geom.is_empty:
                continue
            if not geom.is_valid:
                geom = geom.buffer(0)
            if geom.is_empty or not geom.is_valid:
                continue
        except Exception:
            continue
        polygons[state] = unary_union([polygons[state], geom]) if state in polygons else geom
    missing = sorted(set(STATE_NAMES) - set(polygons))
    if len(polygons) < 36:
        raise RuntimeError(
            f"Boundary file resolved only {len(polygons)}/36 current states/UTs. Missing: {', '.join(missing)}. "
            "Refusing boundary validation against an incomplete India boundary."
        )
    country = unary_union(list(polygons.values()))
    if country.is_empty or not country.is_valid:
        country = country.buffer(0)
    return polygons, country, missing


def load_state_boundaries(path: str | Path | None = None):
    return _load_state_boundaries_cached(str(Path(path or BOUNDARY_PATH).resolve()))


def boundary_file_ready(path: str | Path | None = None) -> bool:
    try:
        load_state_boundaries(path)
        return True
    except (FileNotFoundError, RuntimeError, OSError, json.JSONDecodeError):
        return False


def point_inside_india(lat: float, lon: float, path: str | Path | None = None) -> bool:
    _, country, _ = load_state_boundaries(path)
    return bool(country.covers(Point(float(lon), float(lat))))


def matching_states(lat: float, lon: float, path: str | Path | None = None) -> list[str]:
    polygons, _, _ = load_state_boundaries(path)
    point = Point(float(lon), float(lat))
    return sorted(name for name, polygon in polygons.items() if polygon.covers(point))


def point_inside_state(state: str, lat: float, lon: float, path: str | Path | None = None) -> bool:
    polygons, _, _ = load_state_boundaries(path)
    canonical = normalize_state_name(state)
    polygon = polygons.get(canonical)
    return bool(polygon and polygon.covers(Point(float(lon), float(lat))))
