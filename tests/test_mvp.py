from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)

def test_health_loads_inventory():
    response = client.get('/api/health')
    assert response.status_code == 200
    body = response.json()
    assert body['inventory_loaded'] is True
    assert body['inventory_records'] > 0
    assert 7 <= body['states'] <= 18
    assert 'northeast_inventory_loaded' in body
    assert 'northeast_records' in body
    assert 'central_inventory_loaded' in body
    assert 'central_records' in body

def test_station_filter_returns_north_india_records():
    response = client.get('/api/stations', params={'state': 'Himachal Pradesh', 'limit': 5})
    assert response.status_code == 200
    body = response.json()
    assert 0 < len(body['features']) <= 5
    assert all(f['properties']['state'] == 'Himachal Pradesh' for f in body['features'])

def test_dbscan_endpoint():
    response = client.get('/api/clusters', params={'state': 'Haryana', 'eps_km': 3, 'min_samples': 4})
    assert response.status_code == 200
    assert response.json()['coordinate_groups'] > 0

def test_planner_has_explicit_assumption_and_limitations():
    response = client.post('/api/plan', json={
        'state': 'Himachal Pradesh', 'budget_lakh': 150,
        'target_gap_km': 20, 'charger_power_kw': 60,
        'cost_per_site_lakh': 25, 'max_sites': 6
    })
    assert response.status_code == 200
    body = response.json()
    assert 'limitations' in body
    assert body['assumed_cost_per_site_lakh'] == 25
    assert len(body['recommendations']) <= 6
