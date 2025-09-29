"""Datetime helpers for tests."""

from datetime import datetime


def parse_datetime(value: str | None):
    if value is None:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def now() -> datetime:
    return datetime.utcnow()
