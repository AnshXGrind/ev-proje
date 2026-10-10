import json
from pathlib import Path

import geopandas as gpd
import pandas as pd

def _safe_value(value):
    if isinstance(value, (dict, list, tuple, set)):
        return json.dumps(value, ensure_ascii=False, default=str)

    if value is None:
        return None

    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass

    return value

def save_geojson(gdf: gpd.GeoDataFrame, path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    safe = gdf.copy()

    for column in safe.columns:
        if column != safe.geometry.name:
            safe[column] = safe[column].map(_safe_value)

    safe.to_file(path, driver="GeoJSON", index=False)