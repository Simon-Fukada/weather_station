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

    def _get_metric_id(self, name: str) -> int:
        """Returns the metric_type_id for name. Results are cached for the lifetime
        of this connection — subsequent calls for the same name are pure dict lookups.
        Raises ValueError for unrecognised metric names: run init_db.py to register new ones."""
        if name not in self._metric_cache:
            row = self.conn.execute(
                "SELECT id FROM metric_types WHERE name = ?", (name,)
            ).fetchone()
            if row is None:
                raise ValueError(f"Unknown metric '{name}' — add it to init_db.py and re-run init_db.py.")
            self._metric_cache[name] = row["id"]
        return self._metric_cache[name]

    def get_sensor_map(self) -> Dict[str, int]:
        """Returns a dict mapping sensor machine_name to its database ID."""
        cursor = self.conn.cursor()
        cursor.execute("SELECT id, machine_name FROM sensors")
        return {str(row["machine_name"]): row["id"] for row in cursor.fetchall()}

    def insert_readings_bulk(self, readings: List[Tuple[int, str, float, str]]):
        """Bulk insert for (sensor_id, metric_name, value, iso_timestamp) tuples.
        Metric ID resolution and epoch conversion are handled internally."""
        converted = [
            (sid, self._get_metric_id(metric), self._to_epoch(ts), val)
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
