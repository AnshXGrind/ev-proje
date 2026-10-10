import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import pandas as pd
from evplanner.config import load_region, project_path

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--region")
    args = parser.parse_args()

    region_id, region = load_region(args.region)
    source = project_path(
        "data", "processed", f"{region_id}_chargers_clean.csv"
    )

    if not source.exists():
        raise FileNotFoundError("Run clean_data.py first.")

    data = pd.read_csv(source)
    lat = pd.to_numeric(data["lat"], errors="coerce")
    lon = pd.to_numeric(data["lon"], errors="coerce")

    invalid = (
        lat.isna() | lon.isna()
        | ~lat.between(-90, 90)
        | ~lon.between(-180, 180)
    )
    duplicates = pd.DataFrame({
        "lat": lat.round(5),
        "lon": lon.round(5)
    }).duplicated(keep=False) & ~invalid

    report = {
        "region_id": region_id,
        "region": region["display_name"],
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "records": len(data),
        "invalid_coordinates": int(invalid.sum()),
        "duplicate_coordinate_records_for_review": int(duplicates.sum()),
        "missing_names": int(data["name"].isna().sum()),
        "missing_operators": int(data["operator"].isna().sum()),
        "note": (
            "Coordinate matches need manual review; they do not prove "
            "duplicate stations. OSM coverage may be incomplete."
        )
    }

    output = project_path(
        "data", "reports", f"{region_id}_quality_report.json"
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2), encoding="utf-8")

    print(json.dumps(report, indent=2))
    print(f"Saved report: {output}")

if __name__ == "__main__":
    main()