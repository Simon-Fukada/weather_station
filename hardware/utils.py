from datetime import datetime, timedelta


def snap_to_interval_ceiling(dt: datetime, interval_minutes: int) -> datetime:
    """Snaps a datetime to the next interval boundary (ceiling).
    A reading taken at 8:07 with a 5-minute interval is labelled 8:10 —
    the end of its collection window. Both hardware scripts call this with
    BUCKET_INTERVAL_MINUTES from config so the bucket size is defined once."""
    remainder = dt.minute % interval_minutes
    if remainder == 0:
        return dt.replace(second=0, microsecond=0)
    return dt.replace(second=0, microsecond=0) + timedelta(minutes=(interval_minutes - remainder))
