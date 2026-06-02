import sqlite3
from enum import Enum

import weather_math


def build_metric_enum(conn: sqlite3.Connection):
    """Builds a Metric(str, Enum) class from the metric_types table.

    The returned class is interface-compatible with a static str enum:
      Metric.TEMPERATURE_C == "temperature_c"  # True (str subclass)
      Metric.TEMPERATURE_C.is_stored           # True
      data[Metric.TEMPERATURE_C]               # same key as data["temperature_c"]
    """
    rows = conn.execute(
        "SELECT id, name, constant_name, is_stored FROM metric_types ORDER BY id"
    ).fetchall()

    members = {row["constant_name"]: row["name"] for row in rows}
    stored_values = frozenset(row["name"] for row in rows if row["is_stored"])
    member_ids    = {row["name"]: row["id"] for row in rows}

    MetricEnum = Enum("Metric", members, type=str)

    def _is_stored(self):
        return self.value in stored_values

    def _id(self):
        return member_ids[self.value]

    MetricEnum.is_stored = property(_is_stored)
    MetricEnum.id        = property(_id)

    return MetricEnum


def build_metric_dispatch(conn: sqlite3.Connection) -> dict:
    """Builds the RTL-433 field dispatch table from the rtl_field_map DB table.

    Returns {rtl_field: (metric_name, conversion_fn_or_None)}.
    conversion_fn is resolved via getattr(weather_math, func_name) so that
    adding a new unit conversion only requires a function in weather_math.py
    and a row in rtl_field_map — no code changes here.
    """
    rows = conn.execute("""
        SELECT f.rtl_field, mt.name AS metric_name, f.conversion_func
        FROM rtl_field_map f
        JOIN metric_types mt ON mt.id = f.metric_type_id
    """).fetchall()
    dispatch = {}
    for row in rows:
        fn_name = row["conversion_func"]
        fn = getattr(weather_math, fn_name) if fn_name else None
        dispatch[row["rtl_field"]] = (row["metric_name"], fn)
    return dispatch
