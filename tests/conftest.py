import pytest
import sqlite3
import os
import sys
from datetime import datetime, timedelta, timezone

# Ensure the tests can find the 'api' directory for imports
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'api')))

@pytest.fixture
def db_connection():
    """
    A pytest fixture that creates a fresh, temporary, in-memory SQLite database.
    Injects dynamic, relative timestamps to prevent time-coupled test failures.
    """
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    # 1. Build the Schema
    cursor.execute('''
        CREATE TABLE sensors (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            machine_name TEXT UNIQUE NOT NULL,
            friendly_name TEXT,
            location TEXT
        )
    ''')
    cursor.execute('''
        CREATE TABLE readings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            sensor_id INTEGER NOT NULL,
            metric_type TEXT NOT NULL,
            value REAL NOT NULL,
            FOREIGN KEY (sensor_id) REFERENCES sensors(id)
        )
    ''')
    cursor.execute('''
        CREATE TABLE sensor_health (
            sensor_id INTEGER PRIMARY KEY,
            battery_ok INTEGER,
            last_updated DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (sensor_id) REFERENCES sensors(id)
        )
    ''')

    # 2. Inject Concrete Dummy Data with Dynamic Relative Time
    # Using UTC to perfectly align with the backend's datetime.utcnow() logic
    now = datetime.now(timezone.utc)
    two_hours_ago = (now - timedelta(hours=2)).strftime('%Y-%m-%d %H:%M:%S')

    cursor.execute("""
        INSERT INTO sensors (id, machine_name, friendly_name, location) 
        VALUES (1, 'rtl_433_outdoor', 'Outdoor Fence', 'Backyard')
    """)
    
    # This -15.5 reading will ALWAYS be exactly 2 hours old, guaranteeing the 24h query finds it.
    cursor.execute("""
        INSERT INTO readings (sensor_id, metric_type, value, timestamp) 
        VALUES (1, 'temperature_c', -15.5, ?)
    """, (two_hours_ago,))
    
    cursor.execute("""
        INSERT INTO sensor_health (sensor_id, battery_ok, last_updated) 
        VALUES (1, 1, ?)
    """, (two_hours_ago,))
    
    conn.commit()

    yield conn

    conn.close()