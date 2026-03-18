import sqlite3
import os

def init_db():
    db_path = 'data/weather_data.db'
    
    # Ensure data directory exists
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # Enable Foreign Key enforcement
    cursor.execute('PRAGMA foreign_keys = ON;')
    
    # Table 1: sensors
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS sensors (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            machine_name TEXT UNIQUE NOT NULL,
            friendly_name TEXT,
            location TEXT
        )
    ''')
    
    # Table 2: readings (Time-Series Data)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS readings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            sensor_id INTEGER NOT NULL,
            metric_type TEXT NOT NULL,
            value REAL NOT NULL,
            FOREIGN KEY (sensor_id) REFERENCES sensors(id)
        )
    ''')

    # Table 3: sensor_health (State Data / Upsert Pattern)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS sensor_health (
            sensor_id INTEGER PRIMARY KEY,
            battery_ok INTEGER,
            last_updated DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (sensor_id) REFERENCES sensors(id)
        )
    ''')

    # --- PERFORMANCE UPGRADE ---
    # Create a composite index to massively speed up historical data retrieval
    cursor.execute('''
        CREATE INDEX IF NOT EXISTS idx_sensor_metric_time 
        ON readings (sensor_id, metric_type, timestamp DESC);
    ''')
    
    conn.commit()
    conn.close()
    print(f"Database initialized at {db_path} with performance indexes and health tables.")

if __name__ == "__main__":
    init_db()