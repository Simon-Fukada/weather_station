import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch
from datetime import datetime, timedelta, timezone
import sys
import os

# Ensure 'api' is in the system path so Python can find main.py
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'api')))

from main import app, calculate_mslp, calculate_dew_point, get_quantized_grid

client = TestClient(app)

# --- Unit Tests: Math Functions ---

def test_calculate_mslp_boundaries():
    # 1. Extreme Negative Elevation: The Dead Sea (~ -430.5m)
    assert calculate_mslp(1060.0, 35.0, -430.5) == 1010.4
    
    # 2. Low Negative Elevation: Death Valley (~ -86.0m)
    assert calculate_mslp(1020.0, 45.0, -86.0) == 1010.6

    # 3. Standard Sea Level (0m)
    assert calculate_mslp(1013.25, 15.0, 0.0) == 1013.2

    # 4. Mountain Elevation:(~ 1400.0m)
    # The algorithm specifically evaluates this to 1016.3
    assert calculate_mslp(850.0, -10.0, 1400.0) == 1016.3
    
    # 5. Extreme High Elevation: La Paz, Bolivia (~ 3640.0m)
    # The algorithm specifically evaluates this to 991.1
    assert calculate_mslp(650.0, 10.0, 3640.0) == 991.1

def test_calculate_dew_point_boundaries():
    # Standard: 20C, 50% humidity
    assert calculate_dew_point(20, 50) == 9.3
    
    # 100% humidity (Dew point = Temp)
    assert calculate_dew_point(25, 100) == 25.0
    
    # 0% humidity (Should handle gracefully per our business logic)
    assert calculate_dew_point(20, 0) == 0.0
    
    # Deep freeze (-40°C)
    assert calculate_dew_point(-40, 50) == -46.4

# --- Unit Tests: get_quantized_grid ---

def test_get_quantized_grid_bucketing():
    # To prevent flaky tests, we calculate the EXACT current 5-minute bucket base
    now = datetime.now(timezone.utc)
    current_bucket_min = (now.minute // 5) * 5
    base_time = now.replace(minute=current_bucket_min, second=0, microsecond=0)
    
    # Row 1 & 2: Placed squarely in the CURRENT 5-minute bucket
    row1_time = base_time.strftime("%Y-%m-%d %H:%M:%S")
    row2_time = (base_time + timedelta(minutes=1)).strftime("%Y-%m-%d %H:%M:%S")
    
    # Row 3: Placed squarely in the PREVIOUS 5-minute bucket
    row3_time = (base_time - timedelta(minutes=5)).strftime("%Y-%m-%d %H:%M:%S")
    
    raw_rows = [
        {"timestamp": row1_time, "metric_type": "temp", "value": 20.0},
        {"timestamp": row2_time, "metric_type": "temp", "value": 21.0},
        {"timestamp": row3_time, "metric_type": "temp", "value": 10.0}
    ]
    
    grid = get_quantized_grid(raw_rows, hours_back=1, interval_minutes=5)
    filled_buckets = [b for b in grid if b.get("temp") is not None]
    
    # We mathematically forced the data into exactly 2 buckets
    assert len(filled_buckets) == 2
    
    metrics = [b["temp"] for b in filled_buckets]
    # The current bucket must average 20.0 and 21.0
    assert 20.5 in metrics
    # The previous bucket must be exactly 10.0
    assert 10.0 in metrics

# --- Integration Tests: FastAPI Endpoints (Mocked Repository) ---

@patch("repository.get_all_sensors")
def test_get_all_sensors_endpoint(mock_get_all):
    mock_get_all.return_value = [
        {"id": 1, "machine_name": "test_sensor", "friendly_name": "Test", "location": "Lab"}
    ]
    
    response = client.get("/api/sensors")
    assert response.status_code == 200
    assert response.json() == [{"id": 1, "machine_name": "test_sensor", "friendly_name": "Test", "location": "Lab"}]

@patch("repository.get_latest_sensor_readings")
@patch("repository.get_24h_extremes")
@patch("repository.get_sensor_health")
def test_get_current_reading_endpoint(mock_health, mock_extremes, mock_readings):
    mock_readings.return_value = [
        {"metric_type": "temperature_c", "value": 22.5, "timestamp": "2026-03-19 12:00:00"},
        {"metric_type": "humidity_pct", "value": 45.0, "timestamp": "2026-03-19 12:00:00"}
    ]
    mock_extremes.return_value = {"high": 25.0, "low": 18.0}
    mock_health.return_value = {"battery_ok": 1}
    
    response = client.get("/api/readings/current/1")
    assert response.status_code == 200
    data = response.json()
    assert data["temperature_c"] == 22.5
    assert data["humidity_pct"] == 45.0
    assert data["dew_point_c"] == 10.0 # Mathematically proven dew point calculation
    assert data["temp_high_24h"] == 25.0
    assert data["battery_ok"] == 1

@patch("repository.get_latest_sensor_readings")
def test_get_current_reading_not_found(mock_readings):
    mock_readings.return_value = []
    response = client.get("/api/readings/current/999")
    assert response.status_code == 404
    assert response.json()["detail"] == "No readings found."

@patch("repository.get_latest_single_metric")
@patch("repository.get_historical_trend")
@patch("repository.get_sustained_wind")
@patch("repository.get_max_wind_gust")
def test_get_fixed_sensor_data_endpoint(mock_gust, mock_sustained, mock_trend, mock_latest):
    # Mocking single metrics for pressure and temperature
    mock_latest.side_effect = [
        {"value": 1010.0, "timestamp": "2026-03-19 12:00:00"}, # Pressure
        {"value": 15.0, "timestamp": "2026-03-19 12:00:00"}    # Temperature
    ]
    mock_trend.return_value = [
        {"timestamp": "2026-03-19 11:00:00", "metric_type": "pressure_hpa", "value": 1005.0}
    ]
    mock_sustained.return_value = 10.0
    mock_gust.return_value = 20.0
    
    response = client.get("/api/fixed_sensors?sensor_id=1")
    assert response.status_code == 200
    data = response.json()
    assert "mslp_hpa" in data
    assert data["wind_sustained_kmh"] == 10.0
    assert data["wind_gust_kmh"] == 20.0
    assert len(data["pressure_trend_72h"]) > 0

@patch("repository.get_latest_single_metric")
@patch("repository.get_historical_trend")
@patch("repository.get_sustained_wind")
@patch("repository.get_max_wind_gust")
def test_get_fixed_sensor_data_gust_suppression(mock_gust, mock_sustained, mock_trend, mock_latest):
    """Proves that wind gusts are suppressed if they are not >2.0 km/h above sustained wind."""
    mock_latest.return_value = None
    mock_trend.return_value = []
    
    # Boundary: Gust is only 1.5 km/h higher than sustained (should be suppressed)
    mock_sustained.return_value = 10.0
    mock_gust.return_value = 11.5 
    
    response = client.get("/api/fixed_sensors?sensor_id=1")
    assert response.status_code == 200
    
    data = response.json()
    assert data["wind_sustained_kmh"] == 10.0
    assert data["wind_gust_kmh"] is None  # Mathematically proven to filter the noise!

@patch("repository.get_multi_metric_history")
def test_get_historical_readings_endpoint(mock_history):
    now = datetime.now(timezone.utc)
    now_str = now.strftime("%Y-%m-%d %H:%M:%S")
    
    mock_history.return_value = [
        {"timestamp": now_str, "metric_type": "temperature_c", "value": 20.0},
        {"timestamp": now_str, "metric_type": "humidity_pct", "value": 50.0}
    ]
    
    response = client.get("/api/readings/history/1?hours=1")
    assert response.status_code == 200
    data = response.json()
    
    # We expect temperature_c and dew_point_c entries for the bucket
    metrics = [item["metric_type"] for item in data if item["value"] is not None]
    assert "temperature_c" in metrics
    assert "dew_point_c" in metrics