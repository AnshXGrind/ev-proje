import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import geopandas as gpd
import pandas as pd

from evplanner.config import load_region, project_path
from evplanner.geospatial.io import save_geojson

def text_value(row, field):
    value = row.get(field)
    if value is None or pd.isna(value) or str(value).strip() == "":
        return None
    return str(value).strip()

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--region")
    args = parser.parse_args()

    region_id, _ = load_region(args.region)
    source = project_path(
        "data", "raw", f"{region_id}_chargers_raw.geojson"
    )

    if not source.exists():
        raise FileNotFoundError(
            f"{source} not found. Run fetch_chargers.py first."
        )

    raw = gpd.read_file(source)
    if raw.empty:
        raise RuntimeError("Source charger file is empty.")

    raw = raw.loc[
        raw.geometry.notna() & ~raw.geometry.is_empty
    ].copy()

    if raw.crs is None:
        raw = raw.set_crs("EPSG:4326")

    raw = raw.to_crs("EPSG:4326")
    metric_crs = raw.estimate_utm_crs() or "EPSG:3857"
    points = (
        raw.to_crs(metric_crs)
        .geometry.representative_point()
        .to_crs("EPSG:4326")
    )

    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    records = []

    for index, row in raw.iterrows():
        point = points.loc[index]
        osm_id = row.get("osmid", index)

        records.append({
            "station_id": f"osm:{osm_id}",
            "name": text_value(row, "name"),
            "operator": text_value(row, "operator"),
            "access": text_value(row, "access"),
            "connector_type2": text_value(row, "socket:type2"),
            "connector_ccs": text_value(row, "socket:ccs"),
            "capacity_raw": text_value(row, "capacity"),
            "lat": float(point.y),
            "lon": float(point.x),
            "source": "OpenStreetMap",
            "retrieved_at_utc": now,
            "power_rating_status": "unknown"
        })

    cleaned = gpd.GeoDataFrame(
        records,
        geometry=[points.loc[index] for index in raw.index],
        crs="EPSG:4326"
    )

    geojson_path = project_path(
        "data", "processed", f"{region_id}_chargers_clean.geojson"
    )
    csv_path = project_path(
        "data", "processed", f"{region_id}_chargers_clean.csv"
    )

    save_geojson(cleaned, geojson_path)
    cleaned.drop(columns="geometry").to_csv(
        csv_path, index=False, encoding="utf-8"
    )

    print(f"Cleaned {len(cleaned)} mapped charger records.")
    print(f"GeoJSON: {geojson_path}")
    print(f"CSV: {csv_path}")
    print("Unknown power is retained as unknown, not guessed.")

if __name__ == "__main__":
    main()