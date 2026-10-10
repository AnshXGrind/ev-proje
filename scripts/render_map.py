import argparse
import sys
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import folium
import geopandas as gpd
import pandas as pd

from evplanner.config import load_region, project_path

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--region")
    args = parser.parse_args()

    region_id, region = load_region(args.region)
    center = region.get("center", [20.5937, 78.9629])

    stations_csv = project_path(
        "data", "processed", f"{region_id}_chargers_clean.csv"
    )
    stations_geojson = project_path(
        "data", "processed", f"{region_id}_chargers_clean.geojson"
    )
    roads_path = project_path(
        "data", "raw", f"{region_id}_road_edges.geojson"
    )
    candidates_path = project_path(
        "data", "processed", f"{region_id}_candidates.geojson"
    )

    if stations_csv.exists():
        stations = pd.read_csv(stations_csv)
        if not stations.empty:
            center = [
                float(stations["lat"].median()),
                float(stations["lon"].median())
            ]

    fmap = folium.Map(
        location=center,
        zoom_start=11,
        control_scale=True,
        tiles=None
    )

    folium.TileLayer(
        tiles="https://services.arcgisonline.com/ArcGIS/rest/services/World_Street_Map/MapServer/tile/{z}/{y}/{x}",
        attr="Tiles &copy; Esri; Sources: Esri, TomTom, Garmin, FAO, NOAA, USGS, and the GIS User Community",
        name="Esri World Street Map",
        overlay=False,
        control=True,
        max_zoom=19
    ).add_to(fmap)

    if roads_path.exists():
        folium.GeoJson(
            data=json.loads(roads_path.read_text(encoding="utf-8")),
            name="Mapped road network",
            style_function=lambda _: {
                "color": "#64748b",
                "weight": 1,
                "opacity": 0.55
            }
        ).add_to(fmap)

    if stations_csv.exists():
        stations = pd.read_csv(stations_csv)
        layer = folium.FeatureGroup(name="Mapped EV chargers")

        for _, row in stations.iterrows():
            if pd.isna(row["lat"]) or pd.isna(row["lon"]):
                continue

            name = str(row.get("name") or "Name not mapped")
            operator = str(row.get("operator") or "Operator unknown")
            popup = f"{name}<br>Operator: {operator}<br>Source: OpenStreetMap"

            folium.CircleMarker(
                location=[row["lat"], row["lon"]],
                radius=5,
                color="#167d43",
                fill=True,
                fill_opacity=0.8,
                popup=folium.Popup(popup, max_width=260)
            ).add_to(layer)

        layer.add_to(fmap)

    if candidates_path.exists():
        candidates = gpd.read_file(candidates_path).to_crs("EPSG:4326")
        layer = folium.FeatureGroup(name="Candidate POIs")

        for _, row in candidates.iterrows():
            point = row.geometry.representative_point()
            label = str(row.get("candidate_type", "Candidate POI"))

            folium.CircleMarker(
                location=[point.y, point.x],
                radius=4,
                color="#bc6715",
                fill=True,
                fill_opacity=0.65,
                popup=label + " â€” site and grid feasibility unverified"
            ).add_to(layer)

        layer.add_to(fmap)

    folium.LayerControl().add_to(fmap)
    output = project_path(
        "outputs", "maps", f"{region_id}_map.html"
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    fmap.save(str(output))

    print(f"Saved interactive map: {output}")
    print("The map does not represent measured traffic or verified grid capacity.")

if __name__ == "__main__":
    main()

