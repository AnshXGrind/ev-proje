import argparse
import sys

ROOT = __import__("pathlib").Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

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

    print(f"Downloading drivable roads for: {region['place']}")
    graph = ox.graph_from_place(
        region["place"],
        network_type="drive",
        simplify=True,
        retain_all=True
    )

    raw = project_path("data", "raw")
    raw.mkdir(parents=True, exist_ok=True)

    graph_path = raw / f"{region_id}_roads.graphml"
    edges_path = raw / f"{region_id}_road_edges.geojson"

    ox.save_graphml(graph, filepath=str(graph_path))
    _, edges = ox.graph_to_gdfs(graph)
    save_geojson(edges.reset_index(), edges_path)

    print(f"Saved road graph: {graph_path}")
    print(f"Saved {len(edges)} road segments: {edges_path}")
    print("OSM road geometry is not a measured traffic dataset.")

if __name__ == "__main__":
    main()