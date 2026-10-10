import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import osmnx as ox
import geopandas as gpd

from evplanner.config import load_region, project_path
from evplanner.geospatial.io import save_geojson


def main():
    region_id, region = load_region("himachal_manali")

    graph_path = project_path(
        "data", "raw", f"{region_id}_roads.graphml"
    )

    if not graph_path.exists():
        raise FileNotFoundError(f"Road graph not found: {graph_path}")

    print("Loading existing road network...")
    graph = ox.load_graphml(filepath=str(graph_path))
    nodes, _ = ox.graph_to_gdfs(graph)

    print(f"Road nodes loaded: {len(nodes)}")

    nodes["degree"] = [
        graph.degree(node_id) for node_id in nodes.index
    ]

    # Select junction-like road nodes as preliminary candidates.
    candidates = nodes[nodes["degree"] >= 3].copy()

    if candidates.empty:
        raise RuntimeError("No junction candidates found.")

    # Reduce nearby candidates using a metric coordinate system.
    metric_crs = candidates.estimate_utm_crs()
    candidates = candidates.to_crs(metric_crs)

    spacing = 2000  # Approximate 2 km grid spacing.
    candidates["cell_x"] = (
        candidates.geometry.x // spacing
    ).astype(int)
    candidates["cell_y"] = (
        candidates.geometry.y // spacing
    ).astype(int)

    candidates = candidates.drop_duplicates(
        ["cell_x", "cell_y"]
    ).copy()

    candidates["candidate_type"] = "road_junction_proxy"
    candidates["source"] = "OpenStreetMap road graph"
    candidates["status"] = "unverified"
    candidates["limitation"] = (
        "Not a verified station site; traffic, land access and "
        "electrical capacity have not been checked."
    )

    candidates = candidates.to_crs("EPSG:4326")

    output = project_path(
        "data", "processed", f"{region_id}_candidates.geojson"
    )

    save_geojson(candidates.reset_index(), output)

    print(f"Candidates generated: {len(candidates)}")
    print(f"Saved to: {output}")


if __name__ == "__main__":
    main()