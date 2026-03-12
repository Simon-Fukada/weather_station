from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
import sqlite3
import os
import math
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

app = FastAPI(title="Weather Station API")

# --- Constants ---
DB_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'data', 'weather_data.db'))
BAROMETER_MACHINE_NAME = os.getenv("BAROMETER_MACHINE_NAME", "bme280_local")
ELEVATION_M = float(os.getenv("STATION_ELEVATION", 0))

# Metric Types
METRIC_TEMP = 'temperature_c'
METRIC_PRESSURE = 'pressure_hpa'
METRIC_HUMIDITY = 'humidity_pct'
METRIC_DEWPOINT = 'dew_point_c'

def get_db_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def calculate_mslp(abs_pressure_hpa: float, temp_c: float, elevation_m: float) -> float:
    """
    Converts absolute station pressure to Mean Sea Level Pressure (MSLP).
    Uses the standard Hypsometric equation.
    """
    temp_component = temp_c + (0.0065 * elevation_m) + 273.15
    base = 1 - ((0.0065 * elevation_m) / temp_component)
    mslp = abs_pressure_hpa * math.pow(base, -5.257)
    return round(mslp, 1)

def calculate_dew_point(temp_c: float, humidity_pct: float) -> float:
    """
    Calculates the dew point using the Magnus-Tetens formula.
    a = 17.27, b = 237.3
    """
    a = 17.27
    b = 237.3
    # Prevent math domain error with log(0)
    if humidity_pct <= 0:
        return 0.0
    alpha = ((a * temp_c) / (b + temp_c)) + math.log(humidity_pct / 100.0)
    dew_point = (b * alpha) / (a - alpha)
    return round(dew_point, 1)

@app.get("/api/macro")
async def get_macro_environment(sensor_id: int = 1):
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Step 1: ALWAYS get pressure from the physical barometer
    cursor.execute("""
        SELECT value, timestamp FROM readings 
        WHERE sensor_id = (SELECT id FROM sensors WHERE machine_name = ?)
        AND metric_type = ?
        ORDER BY timestamp DESC LIMIT 1
    """, (BAROMETER_MACHINE_NAME, METRIC_PRESSURE))
    pressure_row = cursor.fetchone()
    current_pressure = pressure_row["value"] if pressure_row else 100.0 # if no value is returned I want it to be obvious something is wrong
    pressure_timestamp = pressure_row["timestamp"] if pressure_row else None

    # Step 2: Get the temperature dynamically from whichever sensor you specify
    cursor.execute("""
        SELECT value FROM readings
        WHERE sensor_id = ?
        AND metric_type = ?
        ORDER BY timestamp DESC LIMIT 1
    """, (sensor_id, METRIC_TEMP))
    temp_row = cursor.fetchone()
    current_temp = temp_row["value"] if temp_row else -9999
            
    # Step 3: Run the physics calculation
    mslp = calculate_mslp(current_pressure, current_temp, ELEVATION_M)
    
    # Step 4: Get the 72-hour pressure trend
    cursor.execute("""
        SELECT value FROM readings
        WHERE sensor_id = (SELECT id FROM sensors WHERE machine_name = ?)
        AND metric_type = ?
        AND timestamp >= datetime('now', '-72 hours')
        ORDER BY timestamp ASC
    """, (BAROMETER_MACHINE_NAME, METRIC_PRESSURE))
    trend_rows = cursor.fetchall()
    
    # Task 1: Fix the 72-Hour Pressure Graph Data (Absolute to Relative)
    # Convert each absolute pressure point to MSLP using current temperature
    trend_data = [calculate_mslp(row["value"], current_temp, ELEVATION_M) for row in trend_rows]
    pressure_avg = sum(trend_data) / len(trend_data) if trend_data else mslp
    
    conn.close()
    
    return {
        "mslp_hpa": mslp,
        "pressure_trend_72h": trend_data,
        "pressure_average_72h": round(pressure_avg, 1),
        "pressure_timestamp": pressure_timestamp
    }

@app.get("/api/sensors")
async def get_all_sensors():
    """Returns the list of available sensors for the UI toggles."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id, machine_name, friendly_name, location FROM sensors")
    rows = cursor.fetchall()
    conn.close()
    return [dict(row) for row in rows]

@app.get("/api/readings/current/{sensor_id}")
async def get_current_reading(sensor_id: int):
    """
    Fetches the latest metrics dynamically, regardless of how many parameters the sensor has.
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    

    cursor.execute("""
        SELECT metric_type, value, timestamp 
        FROM readings
        WHERE sensor_id = ? 
        AND timestamp = (
            SELECT MAX(timestamp) 
            FROM readings 
            WHERE sensor_id = ?
        )
    """, (sensor_id, sensor_id))
    current_rows = cursor.fetchall()
    
    if not current_rows:
        raise HTTPException(status_code=404, detail="No readings found.")
        
    data = {"sensor_id": sensor_id, "timestamp": current_rows[0]["timestamp"]}
    for row in current_rows:
        data[row["metric_type"]] = round(row["value"], 1)
    
    if METRIC_TEMP in data and METRIC_HUMIDITY in data:
        data[METRIC_DEWPOINT] = calculate_dew_point(data[METRIC_TEMP], data[METRIC_HUMIDITY])
        
    # Grab the 24-hour High and Low using SQLite Aggregate Functions
    cursor.execute("""
        SELECT MAX(value) as high, MIN(value) as low FROM readings
        WHERE sensor_id = ? 
        AND metric_type = ? 
        AND timestamp >= datetime('now', '-24 hours')
    """, (sensor_id, METRIC_TEMP))
    extremes = cursor.fetchone()
    
    data["temp_high_24h"] = round(extremes["high"], 1) if extremes["high"] else data.get("temperature_c")
    data["temp_low_24h"] = round(extremes["low"], 1) if extremes["low"] else data.get("temperature_c")
    
    conn.close()
    return data

@app.get("/api/readings/history/{sensor_id}")
async def get_historical_readings(sensor_id: int, hours: int = 24):
    """Fetches a time-series array of data to feed the Chart.js visualizer."""
    conn = get_db_connection()
    cursor = conn.cursor()
    time_modifier = f"-{hours} hours"
    cursor.execute("""
        SELECT timestamp, metric_type, value FROM readings
        WHERE sensor_id = ? AND timestamp >= datetime('now', ?)
        ORDER BY timestamp ASC
    """, (sensor_id, time_modifier))
    rows = cursor.fetchall()
    conn.close()


    
    history_list = [dict(row) for row in rows]


    grouped_data = {}
    for entry in history_list:
        ts = entry["timestamp"]
        if ts not in grouped_data:
            grouped_data[ts] = {}
        grouped_data[ts][entry["metric_type"]] = entry["value"]
    

    for ts, metrics in grouped_data.items():
        if METRIC_TEMP in metrics and METRIC_HUMIDITY in metrics:
            dew_point = calculate_dew_point(metrics[METRIC_TEMP], metrics[METRIC_HUMIDITY])
            history_list.append({
                "timestamp": ts,
                "metric_type": METRIC_DEWPOINT,
                "value": dew_point
            })

    return history_list

# Resolve the path to your new frontend directory
FRONTEND_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'frontend'))

# Mount the entire directory to the root URL. 
# html=True tells FastAPI to automatically serve index.html when you visit the root IP.
app.mount("/", StaticFiles(directory=FRONTEND_PATH, html=True), name="frontend")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)