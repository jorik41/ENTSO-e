"""Minimal constants used by the integration under test."""

from enum import Enum


class Platform(str, Enum):
    """Subset of the Platform enum required for tests."""

    SENSOR = "sensor"


CURRENCY_EURO = "EUR"
