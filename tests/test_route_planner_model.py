from pydantic import ValidationError

from app.route_api import (
    RouteAnalyzeRequest,
    _classify_terrain,
    _scenario_demand,
    _spacing_for_terrain,
)


def test_spacing_adapts_to_landscape_not_a_single_distance():
    req = RouteAnalyzeRequest()
    demand = _scenario_demand(req, "base")
    plains = _spacing_for_terrain("plains", req, "base", demand)
    hills = _spacing_for_terrain("hills", req, "base", demand)
    high_himalaya = _spacing_for_terrain("high_himalaya", req, "base", demand)
    remote = _spacing_for_terrain("remote_high_himalaya", req, "base", demand)

    assert plains["adaptive_spacing_km"] <= 20.0  # EVCI-2024 policy reference cap
    assert plains["adaptive_spacing_km"] > hills["adaptive_spacing_km"]
    assert hills["adaptive_spacing_km"] > high_himalaya["adaptive_spacing_km"]
    assert high_himalaya["adaptive_spacing_km"] > remote["adaptive_spacing_km"]


def test_short_range_vehicle_tightens_spacing():
    normal = RouteAnalyzeRequest(vehicle_range_km=300, reserve_pct=15)
    short = RouteAnalyzeRequest(vehicle_range_km=65, reserve_pct=25)
    normal_target = _spacing_for_terrain("high_himalaya", normal, "base", _scenario_demand(normal, "base"))["adaptive_spacing_km"]
    short_target = _spacing_for_terrain("high_himalaya", short, "base", _scenario_demand(short, "base"))["adaptive_spacing_km"]
    assert short_target < normal_target


def test_accelerated_scenario_is_denser_than_conservative():
    req = RouteAnalyzeRequest()
    demand = _scenario_demand(req, "base")
    low = _spacing_for_terrain("rolling", req, "conservative", demand)["adaptive_spacing_km"]
    high = _spacing_for_terrain("rolling", req, "accelerated", demand)["adaptive_spacing_km"]
    assert high < low


def test_demand_is_not_invented_without_traffic_inputs():
    req = RouteAnalyzeRequest()
    demand = _scenario_demand(req, "base")
    assert demand["estimated_public_charging_sessions_per_day"] is None
    assert demand["estimated_public_energy_kwh_per_day"] is None


def test_demand_projection_is_explicitly_scenario_estimated():
    req = RouteAnalyzeRequest(
        planning_year=2030,
        traffic_vehicles_per_day=25000,
        current_ev_share_pct=1.2,
        public_charge_share_pct=20,
        average_session_kwh=30,
    )
    demand = _scenario_demand(req, "base")
    assert demand["is_scenario_estimate"] is True
    assert demand["estimated_public_charging_sessions_per_day"] > 0
    assert demand["estimated_public_energy_kwh_per_day"] > demand["estimated_public_charging_sessions_per_day"]


def test_traffic_and_ev_share_must_be_supplied_together():
    try:
        RouteAnalyzeRequest(traffic_vehicles_per_day=10000)
    except ValidationError:
        pass
    else:
        raise AssertionError("Traffic without current EV share must fail validation.")


def test_elevation_terrain_classifier():
    assert _classify_terrain([200, 230], 0.5) == "plains"
    assert _classify_terrain([800, 950], 2.8) == "rolling"
    assert _classify_terrain([1700, 1850], 4.0) == "hills"
    assert _classify_terrain([3200, 3400], 3.0) == "high_himalaya"
    assert _classify_terrain([None, None], None) == "unknown"


def test_route_endpoint_with_mocked_services(monkeypatch):
    import app.route_api as module

    monkeypatch.setattr(module, "_geocode_place", lambda q: {
        "query": q, "label": q, "lat": 28.04 if q.startswith("Narnaul") else 32.73,
        "lon": 76.1 if q.startswith("Narnaul") else 74.86, "method": "test"
    })
    monkeypatch.setattr(module, "_get_route", lambda origin, destination: {
        "coordinates": [[76.10, 28.04], [76.5, 29.5], [76.0, 30.5], [75.2, 31.5], [74.86, 32.73]],
        "distance_km": 620.0, "duration_hours": 8.0, "road_names": ["Test Highway"],
        "geometry_source": "test router",
    })
    monkeypatch.setattr(module, "_inventory_groups", lambda: [
        {"lat": 28.04, "lon": 76.10, "state": "Haryana", "location": "Start", "operator": "Test",
         "max_power_kw": 60, "reported_connectors": 2, "reported_rows": 1, "charger_types": ["CCS-II"], "source_pages": ["1"]},
        {"lat": 29.50, "lon": 76.50, "state": "Haryana", "location": "Station A", "operator": "Test",
         "max_power_kw": 22, "reported_connectors": 2, "reported_rows": 1, "charger_types": ["Type-II"], "source_pages": ["1"]},
        {"lat": 30.50, "lon": 76.00, "state": "Punjab", "location": "Station B", "operator": "Test",
         "max_power_kw": 60, "reported_connectors": 1, "reported_rows": 1, "charger_types": ["CCS-II"], "source_pages": ["2"]},
        {"lat": 31.50, "lon": 75.20, "state": "Jammu and Kashmir", "location": "Station C", "operator": "Test",
         "max_power_kw": 22, "reported_connectors": 1, "reported_rows": 1, "charger_types": ["Type-II"], "source_pages": ["3"]},
        {"lat": 32.73, "lon": 74.86, "state": "Jammu and Kashmir", "location": "Destination", "operator": "Test",
         "max_power_kw": 60, "reported_connectors": 2, "reported_rows": 1, "charger_types": ["CCS-II"], "source_pages": ["4"]},
    ])
    monkeypatch.setattr(module, "_route_sample_profile", lambda line, reverse, distance, length: (
        [
            {"route_km": 0.0, "lat": 28.04, "lon": 76.1, "elevation_m": 300.0, "absolute_grade_proxy_pct": 0.0},
            {"route_km": 310.0, "lat": 30.5, "lon": 76.0, "elevation_m": 700.0, "absolute_grade_proxy_pct": 4.0},
            {"route_km": 620.0, "lat": 32.73, "lon": 74.86, "elevation_m": 1800.0, "absolute_grade_proxy_pct": 5.5},
        ],
        "test elevation profile",
    ))

    result = module.analyze_route(RouteAnalyzeRequest())
    assert result["status"] == "ok"
    assert result["route_distance_km"] == 620.0
    assert len(result["terrain"]["segments"]) >= 1
    assert result["summary"]["candidate_coordinates_recommended_for_selected_scenario"] >= 0
    assert result["evidence"]["grid_capacity"].startswith("UNVERIFIED")
