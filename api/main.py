from fastapi import FastAPI, HTTPException, Depends
from fastapi.staticfiles import StaticFiles
import sqlite3
import os
import math
from dotenv import load_dotenv
from datetime import datetime, timedelta
import sys

# Explicitly add the current 'api' directory to Python's system path
# so systemd can find repository.py regardless of where it executes from.
current_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.append(current_dir)

import repository

load_dotenv()

app = FastAPI(title="Weather Station API")

# --- Constants ---
DB_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'data', 'weather_data.db'))
BAROMETER_MACHINE_ID = os.getenv("BAROMETER_MACHINE_ID")
WINDSPEED_MACHINE_ID = os.getenv("WINDSPEED_MACHINE_ID")
ELEVATION_M = float(os.getenv("STATION_ELEVATION", 0))

METRIC_TEMP = 'temperature_c'
METRIC_PRESSURE = 'pressure_hpa'
METRIC_HUMIDITY = 'humidity_pct'
METRIC_DEWPOINT = 'dew_point_c'
METRIC_WIND = 'wind_kmh'

# --- Database Dependency (With Threading Fix) ---
def get_db():
    # Fix applied here: check_same_thread=False prevents FastAPI worker thread jumping from crashing SQLite
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()

# --- Business Logic & Math ---
def calculate_mslp(abs_pressure_hpa: float, temp_c: float, elevation_m: float) -> float:
    temp_component = temp_c + (0.0065 * elevation_m) + 273.15
    base = 1 - ((0.0065 * elevation_m) / temp_component)
    mslp = abs_pressure_hpa * math.pow(base, -5.257)
    return round(mslp, 1)

def calculate_dew_point(temp_c: float, humidity_pct: float) -> float:
    a = 17.27
    b = 237.3
    if humidity_pct <= 0:
        return 0.0
    alpha = ((a * temp_c) / (b + temp_c)) + math.log(humidity_pct / 100.0)
    dew_point = (b * alpha) / (a - alpha)
    return round(dew_point, 1)

def get_quantized_grid(raw_rows, hours_back=72, interval_minutes=5):
    now = datetime.utcnow()
    end_minute = (now.minute // interval_minutes) * interval_minutes
    end_time = now.replace(minute=end_minute, second=0, microsecond=0)
    start_time = end_time - timedelta(hours=hours_back)

    grid = {}
    current = start_time
    while current <= end_time:
        grid[current] = {}
        current += timedelta(minutes=interval_minutes)

    for row in raw_rows:
        safe_iso_string = row["timestamp"].replace(" ", "T")
        dt = datetime.fromisoformat(safe_iso_string)
        if dt >= start_time:
            snapped_minute = (dt.minute // interval_minutes) * interval_minutes
            snapped_dt = dt.replace(minute=snapped_minute, second=0, microsecond=0)
            
            if snapped_dt > end_time:
                snapped_dt = end_time

            if snapped_dt in grid:
                metric = row["metric_type"]
                if metric not in grid[snapped_dt]:
                    grid[snapped_dt][metric] = []
                grid[snapped_dt][metric].append(row["value"])

    averaged_grid = []
    for current_time in sorted(grid.keys()):
        time_str = current_time.strftime("%Y-%m-%d %H:%M:%S")
        bucket = {"timestamp": time_str}
        for metric, values in grid[current_time].items():
            bucket[metric] = sum(values) / len(values) if values else None
        averaged_grid.append(bucket)
        
    return averaged_grid

# --- API Endpoints ---

@app.get("/api/sensors")
async def get_all_sensors(conn: sqlite3.Connection = Depends(get_db)):
    rows = repository.get_all_sensors(conn)
    return [dict(row) for row in rows]

@app.get("/api/readings/current/{sensor_id}")
async def get_current_reading(sensor_id: int, conn: sqlite3.Connection = Depends(get_db)):
    current_rows = repository.get_latest_sensor_readings(conn, sensor_id)
    
    if not current_rows:
        raise HTTPException(status_code=404, detail="No readings found.")
        
    data = {"sensor_id": sensor_id, "timestamp": current_rows[0]["timestamp"]}
    for row in current_rows:
        data[row["metric_type"]] = round(row["value"], 1)
    
    if METRIC_TEMP in data and METRIC_HUMIDITY in data:
        data[METRIC_DEWPOINT] = calculate_dew_point(data[METRIC_TEMP], data[METRIC_HUMIDITY])
        
    extremes = repository.get_24h_extremes(conn, sensor_id, METRIC_TEMP)
    
    data["temp_high_24h"] = round(extremes["high"], 1) if extremes and extremes["high"] else data.get("temperature_c")
    data["temp_low_24h"] = round(extremes["low"], 1) if extremes and extremes["low"] else data.get("temperature_c")
    
    # --- NEW: Battery Health Integration ---
    health_row = repository.get_sensor_health(conn, sensor_id)
    # If the sensor has never reported a battery state, default to None
    data["battery_ok"] = health_row["battery_ok"] if health_row else None
    
    return data

@app.get("/api/fixed_sensors")
async def get_fixed_sensor_data(sensor_id: int = 1, conn: sqlite3.Connection = Depends(get_db)):
    
    # Delegate all database fetching to the repository
    pressure_row = repository.get_latest_single_metric(conn, BAROMETER_MACHINE_ID, METRIC_PRESSURE)
    current_pressure = pressure_row["value"] if pressure_row else 100.0
    pressure_timestamp = pressure_row["timestamp"] if pressure_row else None

    temp_row = repository.get_latest_single_metric(conn, str(sensor_id), METRIC_TEMP)
    current_temp = temp_row["value"] if temp_row else -9999
            
    trend_rows = repository.get_historical_trend(conn, BAROMETER_MACHINE_ID, METRIC_PRESSURE, hours_back=72)
    sustained_wind = repository.get_sustained_wind(conn, WINDSPEED_MACHINE_ID, METRIC_WIND)
    max_gust = repository.get_max_wind_gust(conn, WINDSPEED_MACHINE_ID, METRIC_WIND)

    # Apply business logic
    if max_gust is not None and sustained_wind is not None and max_gust <= sustained_wind + 2.0:
        max_gust = None

    mslp = calculate_mslp(current_pressure, current_temp, ELEVATION_M)
    averaged_grid = get_quantized_grid(trend_rows, hours_back=72)
    
    trend_data = []
    valid_pressures = []
    
    for bucket in averaged_grid:
        ts = bucket["timestamp"]
        abs_pressure = bucket.get(METRIC_PRESSURE)
        
        if abs_pressure is not None:
            mslp_val = calculate_mslp(abs_pressure, current_temp, ELEVATION_M)
            valid_pressures.append(mslp_val)
        else:
            mslp_val = None
            
        trend_data.append({"timestamp": ts, "value": mslp_val})
        
    pressure_avg = sum(valid_pressures) / len(valid_pressures) if valid_pressures else mslp
    
    return {
        "mslp_hpa": mslp,
        "pressure_trend_72h": trend_data,
        "pressure_average_72h": round(pressure_avg, 1),
        "pressure_timestamp": pressure_timestamp,
        "wind_sustained_kmh": sustained_wind,
        "wind_gust_kmh": max_gust
    }

@app.get("/api/readings/history/{sensor_id}")
async def get_historical_readings(sensor_id: int, hours: int = 72, conn: sqlite3.Connection = Depends(get_db)):
    rows = repository.get_multi_metric_history(conn, sensor_id, hours)
    averaged_grid = get_quantized_grid(rows, hours_back=hours)
    
    final_history = []
    for bucket in averaged_grid:
        ts = bucket["timestamp"]
        temp = bucket.get(METRIC_TEMP)
        hum = bucket.get(METRIC_HUMIDITY)
        
        final_history.append({"timestamp": ts, "metric_type": METRIC_TEMP, "value": temp})
            
        dew_point = calculate_dew_point(temp, hum) if (temp is not None and hum is not None) else None
        final_history.append({"timestamp": ts, "metric_type": METRIC_DEWPOINT, "value": dew_point})

    return final_history

FRONTEND_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'frontend'))
app.mount("/", StaticFiles(directory=FRONTEND_PATH, html=True), name="frontend")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)