import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import osmnx as ox

from evplanner.config import load_region, project_path
from evplanner.geospatial.io import save_geojson


ENDPOINTS = [
    "https://overpass.private.coffee/api",
    "https://maps.mail.ru/osm/tools/overpass/api",
]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--region")
    parser.add_argument("--radius-m", type=int, default=10000)
    args = parser.parse_args()

    if args.radius_m < 1000 or args.radius_m > 25000:
        parser.error("--radius-m must be between 1000 and 25000")

    region_id, region = load_region(args.region)
    center = tuple(region["center"])

    ox.settings.use_cache = True
    ox.settings.log_console = True
    ox.settings.requests_timeout = 90

    tags = {"amenity": "charging_station"}
    stations = None
    errors = []

    # Search directly around the region centre. Do not query the
    # complete named-place polygon first.
    for endpoint in ENDPOINTS:
        print(f"\nTrying Overpass endpoint: {endpoint}")
        ox.settings.overpass_url = endpoint

        try:
            result = ox.features_from_point(
                center_point=center,
                tags=tags,
                dist=args.radius_m,
            )

            if result is not None and not result.empty:
                stations = result
                print(f"Received {len(stations)} mapped features.")
                break

            print("No matching features returned.")
            errors.append(f"{endpoint}: no matching features")

        except Exception as exc:
            message = f"{type(exc).__name__}: {str(exc)[:250]}"
            errors.append(f"{endpoint}: {message}")
            print(f"Endpoint failed: {message}")

    if stations is None:
        print("\nNo station data was retrieved.")
        print("Endpoint results:")
        for error in errors:
            print(f" - {error}")

        print(
            "\nThis is not proof that the area has no real chargers. "
            "If both endpoints fail, we will switch to an official "
            "station inventory or the Open Charge Map API."
        )
        raise SystemExit(2)

    stations = stations.copy()
    stations["source"] = "OpenStreetMap"
    stations["source_query_scope"] = (
        f"radius_{args.radius_m}m_around_region_centre"
    )
    stations["retrieved_at_utc"] = datetime.now(
        timezone.utc
    ).isoformat(timespec="seconds")

    output = project_path(
        "data", "raw", f"{region_id}_chargers_raw.geojson"
    )
    save_geojson(stations.reset_index(), output)

    print(f"\nSaved {len(stations)} mapped charger features.")
    print(f"File: {output}")
    print("Inventory completeness and operating status are unverified.")


if __name__ == "__main__":
    main()
