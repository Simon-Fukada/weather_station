import sqlite3
from datetime import datetime, timezone
from typing import Dict, List, Tuple


class WeatherWriter:
    """Data Access Layer (DAL) strictly for writing to the weather database."""

    def __init__(self, db_path: str):
        self.conn = sqlite3.connect(db_path)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL;")
        self.conn.execute("PRAGMA foreign_keys=ON;")
        self._metric_cache: Dict[str, int] = {}

    @staticmethod
    def _to_epoch(timestamp_str: str) -> int:
        """Converts a UTC ISO timestamp string ('YYYY-MM-DD HH:MM:SS') to Unix epoch."""
        return int(
            datetime.strptime(timestamp_str, "%Y-%m-%d %H:%M:%S")
            .replace(tzinfo=timezone.utc)
            .timestamp()
        )

    def _get_or_create_metric(self, name: str) -> int:
        """Returns the metric_type_id for name, registering it in metric_types if new.
        Results are cached for the lifetime of this connection — subsequent calls for
        the same name are pure dict lookups with no SQL."""
        if name not in self._metric_cache:
            self.conn.execute(
                "INSERT OR IGNORE INTO metric_types (name) VALUES (?)", (name,)
            )
            row = self.conn.execute(
                "SELECT id FROM metric_types WHERE name = ?", (name,)
            ).fetchone()
            self._metric_cache[name] = row["id"]
        return self._metric_cache[name]

    def get_sensor_map(self) -> Dict[str, int]:
        """Returns a dict mapping sensor machine_name to its database ID."""
        cursor = self.conn.cursor()
        cursor.execute("SELECT id, machine_name FROM sensors")
        return {str(row["machine_name"]): row["id"] for row in cursor.fetchall()}

    def get_or_create_sensor(self, machine_name: str, friendly_name: str, location: str) -> int:
        """Returns the sensor ID for machine_name, creating the row if it does not exist."""
        cursor = self.conn.cursor()
        cursor.execute("SELECT id FROM sensors WHERE machine_name = ?", (machine_name,))
        result = cursor.fetchone()

        if result is None:
            cursor.execute(
                "INSERT INTO sensors (machine_name, friendly_name, location) VALUES (?, ?, ?)",
                (machine_name, friendly_name, location),
            )
            self.conn.commit()
            return cursor.lastrowid

        return result["id"]

    def insert_reading(self, sensor_id: int, metric_type: str, value: float, timestamp: str):
        """Inserts a single time-series reading.
        Accepts a string metric name and an ISO timestamp — metric ID resolution
        and epoch conversion are handled internally, so call sites are unchanged."""
        metric_id = self._get_or_create_metric(metric_type)
        self.conn.execute(
            "INSERT OR IGNORE INTO readings (sensor_id, metric_type_id, timestamp, value) "
            "VALUES (?, ?, ?, ?)",
            (sensor_id, metric_id, self._to_epoch(timestamp), value),
        )
        self.conn.commit()

    def insert_readings_bulk(self, readings: List[Tuple[int, str, float, str]]):
        """Bulk insert for (sensor_id, metric_name, value, iso_timestamp) tuples.
        Metric ID resolution and epoch conversion are handled internally."""
        converted = [
            (sid, self._get_or_create_metric(metric), self._to_epoch(ts), val)
            for sid, metric, val, ts in readings
        ]
        self.conn.executemany(
            "INSERT OR IGNORE INTO readings (sensor_id, metric_type_id, timestamp, value) "
            "VALUES (?, ?, ?, ?)",
            converted,
        )
        self.conn.commit()

    def update_health(self, sensor_id: int, battery_ok: int, timestamp: str):
        """Upserts the battery status for a sensor."""
        self.conn.execute(
            """
            INSERT INTO sensor_health (sensor_id, battery_ok, last_updated)
            VALUES (?, ?, ?)
            ON CONFLICT(sensor_id) DO UPDATE SET
                battery_ok   = excluded.battery_ok,
                last_updated = excluded.last_updated
            """,
            (sensor_id, battery_ok, self._to_epoch(timestamp)),
        )
        self.conn.commit()

    def close(self):
        """Safely closes the database connection."""
        self.conn.close()
