from __future__ import annotations

import html
import json
from collections import Counter
from pathlib import Path

import folium
from folium.plugins import MarkerCluster

ROOT = Path(__file__).resolve().parents[1]
INPUT = ROOT / "data" / "processed" / "north_india_ev_chargers_map.geojson"
OUTPUT = ROOT / "outputs" / "maps" / "north_india_ev_chargers_map.html"

STATE_ORDER = [
    "Delhi",
    "Haryana",
    "Punjab",
    "Himachal Pradesh",
    "Uttarakhand",
    "Jammu and Kashmir",
    "Ladakh",
]
STATE_COLORS = {
    "Delhi": "red",
    "Haryana": "blue",
    "Punjab": "green",
    "Himachal Pradesh": "orange",
    "Uttarakhand": "purple",
    "Jammu and Kashmir": "darkred",
    "Ladakh": "cadetblue",
}


def clean_text(value, fallback="Not recorded") -> str:
    if value is None or str(value).strip() in {"", "nan", "None"}:
        value = fallback
    return html.escape(str(value))


def main() -> None:
    if not INPUT.exists():
        raise FileNotFoundError(
            f"Inventory GeoJSON not found: {INPUT}\n"
            "Download north_india_ev_chargers_map.geojson and place it in data/processed/."
        )

    with INPUT.open("r", encoding="utf-8-sig") as f:
        data = json.load(f)

    features = data.get("features", [])
    if not features:
        raise ValueError(f"No GeoJSON features found in {INPUT}")

    fmap = folium.Map(
        location=[31.0, 77.0],
        zoom_start=5,
        control_scale=True,
        tiles=None,
        prefer_canvas=True,
    )

    folium.TileLayer(
        tiles="https://services.arcgisonline.com/ArcGIS/rest/services/World_Street_Map/MapServer/tile/{z}/{y}/{x}",
        attr="Tiles &copy; Esri; Sources: Esri, TomTom, Garmin, FAO, NOAA, USGS, and the GIS User Community",
        name="Esri World Street Map",
        overlay=False,
        control=True,
        max_zoom=19,
    ).add_to(fmap)

    layer_clusters = {}
    counts = Counter()
    bounds = []

    for state in STATE_ORDER:
        group = folium.FeatureGroup(name=state, show=True)
        cluster = MarkerCluster(
            name=f"{state} station markers",
            options={"disableClusteringAtZoom": 14, "spiderfyOnMaxZoom": True},
        )
        cluster.add_to(group)
        group.add_to(fmap)
        layer_clusters[state] = cluster

    for feature in features:
        props = feature.get("properties") or {}
        geom = feature.get("geometry") or {}
        coords = geom.get("coordinates") or []
        state = str(props.get("state", "")).strip()

        if state == "Jammu & Kashmir":
            state = "Jammu and Kashmir"
        if state == "Uttrakhand":
            state = "Uttarakhand"

        if state not in layer_clusters or geom.get("type") != "Point" or len(coords) < 2:
            continue

        lon, lat = coords[0], coords[1]
        try:
            lon, lat = float(lon), float(lat)
        except (TypeError, ValueError):
            continue
        if not (-90 <= lat <= 90 and -180 <= lon <= 180):
            continue

        cpo = clean_text(props.get("cpo_name"))
        ownership = clean_text(props.get("ownership_type"))
        district = clean_text(props.get("district"))
        city = clean_text(props.get("city_village"))
        location = clean_text(props.get("location"))
        charger_type = clean_text(props.get("charger_type"))
        rating = clean_text(props.get("charger_rating_kw"))
        connector_rating = clean_text(props.get("connector_rating_kw"))
        connectors = clean_text(props.get("number_of_connectors"))
        pages = clean_text(props.get("source_pages"))
        occurrences = clean_text(props.get("duplicate_occurrences", 1))

        popup_html = f"""
        <div style="font-family:Arial,sans-serif;min-width:240px;max-width:360px">
          <h4 style="margin:0 0 8px">{location}</h4>
          <b>Operator:</b> {cpo}<br>
          <b>Ownership:</b> {ownership}<br>
          <b>State / district:</b> {clean_text(state)}, {district}<br>
          <b>City / village:</b> {city}<br>
          <b>Charger type:</b> {charger_type}<br>
          <b>Charger rating (source field):</b> {rating}<br>
          <b>Connector rating (source field):</b> {connector_rating}<br>
          <b>Connector count (source field):</b> {connectors}<br>
          <b>Identical source-row occurrences:</b> {occurrences}<br>
          <b>PDF source page(s):</b> {pages}
          <hr style="margin:8px 0">
          <small>Source snapshot: 26 Oct 2025. Current operational status and local grid capacity are not verified.</small>
        </div>
        """

        folium.Marker(
            location=[lat, lon],
            tooltip=f"{state} | {cpo} | {charger_type}",
            popup=folium.Popup(popup_html, max_width=400),
            icon=folium.Icon(color=STATE_COLORS[state], icon="bolt", prefix="fa"),
        ).add_to(layer_clusters[state])

        counts[state] += 1
        bounds.append([lat, lon])

    folium.LayerControl(collapsed=False).add_to(fmap)
    if bounds:
        fmap.fit_bounds(bounds, padding=(20, 20))

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    fmap.save(str(OUTPUT))

    print("North India charging-station map generated.")
    print(f"Input features in source file: {len(features)}")
    for state in STATE_ORDER:
        print(f"  {state}: {counts[state]} mapped records")
    print(f"Total mapped records: {sum(counts.values())}")
    print(f"Output: {OUTPUT}")
    print("Note: map records represent a dated source inventory, not live station status.")


if __name__ == "__main__":
    main()
