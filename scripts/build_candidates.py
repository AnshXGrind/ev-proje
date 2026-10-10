import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import geopandas as gpd
import osmnx as ox

from evplanner.config import load_region, project_path
from evplanner.geospatial.io import save_geojson

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--region")
    args = parser.parse_args()

    region_id, region = load_region(args.region)
    ox.settings.use_cache = True
    ox.settings.log_console = True

    features = ox.features_from_place(
        region["place"],
        tags={
            "amenity": ["fuel", "parking"],
            "highway": "services",
            "tourism": "hotel"
        }
    )

    if features.empty:
        raise RuntimeError("No candidate POIs found in this OSM query.")

    features = features.reset_index()
    metric_crs = features.estimate_utm_crs() or "EPSG:3857"
    features = features.to_crs(metric_crs)
    features["geometry"] = features.geometry.representative_point()
    features = features.to_crs("EPSG:4326")

    def classify(row):
        if row.get("amenity") in ("fuel", "parking"):
            return str(row.get("amenity"))
        if row.get("highway") == "services":
            return "highway_services"
        if row.get("tourism") == "hotel":
            return "hotel"
        return "other_poi"

    features["candidate_type"] = [
        classify(row) for _, row in features.iterrows()
    ]
    features["source"] = "OpenStreetMap"
    features["screening_status"] = "requires_manual_verification"
    features["selection_note"] = (
        "POI only; land rights, site suitability and grid connection "
        "are not verified."
    )

    output = project_path(
        "data", "processed", f"{region_id}_candidates.geojson"
    )
    save_geojson(features, output)
    print(f"Saved {len(features)} candidate POIs: {output}")

if __name__ == "__main__":
    main()