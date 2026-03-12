import sqlite3
import os

def init_db():
    db_path = 'data/weather_data.db'
    
    # Ensure data directory exists (just in case)
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
    
    # Table 2: readings
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
    
    conn.commit()
    conn.close()
    print(f"Database initialized at {db_path}")

if __name__ == "__main__":
    init_db()
