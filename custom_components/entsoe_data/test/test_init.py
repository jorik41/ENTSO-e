import asyncio
import importlib
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

PACKAGE_ROOT = Path(__file__).resolve().parents[3]
sys.path.append(str(PACKAGE_ROOT))

from custom_components.entsoe_data.const import (
    CONF_API_KEY,
    CONF_AREA,
    CONF_ENABLE_EUROPE_GENERATION,
    CONF_ENABLE_EUROPE_LOAD,
    CONF_ENABLE_EUROPE_WIND_SOLAR_FORECAST,
    CONF_ENABLE_GENERATION,
    CONF_ENABLE_LOAD,
    DOMAIN,
    TOTAL_EUROPE_AREA,
)

entsoe_init = importlib.import_module("custom_components.entsoe_data.__init__")


class DummyEntry:
    def __init__(self, options):
        self.entry_id = "entry"
        self.options = options
        self._unload = None
        self.update_listener = None

    def async_on_unload(self, callback):
        self._unload = callback

    def add_update_listener(self, listener):
        self.update_listener = listener
        return lambda: None


class DummyCoordinator:
    def __init__(self, hass, *, api_key, area):
        self.hass = hass
        self.api_key = api_key
        self.area = area
        self.refresh_calls = 0

    async def async_config_entry_first_refresh(self):
        self.refresh_calls += 1


def test_async_setup_entry_creates_total_europe_coordinators(monkeypatch):
    hass = SimpleNamespace()
    hass.data = {}
    hass.config_entries = SimpleNamespace(
        async_forward_entry_setups=AsyncMock(return_value=None)
    )

    options = {
        CONF_API_KEY: "key",
        CONF_AREA: "BE",
        CONF_ENABLE_GENERATION: False,
        CONF_ENABLE_LOAD: False,
        CONF_ENABLE_EUROPE_GENERATION: True,
        CONF_ENABLE_EUROPE_LOAD: True,
        CONF_ENABLE_EUROPE_WIND_SOLAR_FORECAST: True,
    }
    entry = DummyEntry(options)

    generation_stub = DummyCoordinator
    load_stub = DummyCoordinator
    wind_solar_stub = DummyCoordinator

    monkeypatch.setattr(entsoe_init, "EntsoeGenerationCoordinator", generation_stub)
    monkeypatch.setattr(entsoe_init, "EntsoeLoadCoordinator", load_stub)
    monkeypatch.setattr(
        entsoe_init, "EntsoeWindSolarForecastCoordinator", wind_solar_stub
    )

    result = asyncio.run(entsoe_init.async_setup_entry(hass, entry))
    assert result is True

    stored = hass.data[DOMAIN][entry.entry_id]
    assert "generation" not in stored
    assert "load" not in stored
    assert "generation_europe" in stored
    assert "load_europe" in stored
    assert "wind_solar_forecast_europe" in stored

    generation_europe = stored["generation_europe"]
    load_europe = stored["load_europe"]
    wind_solar_europe = stored["wind_solar_forecast_europe"]

    assert generation_europe.area == TOTAL_EUROPE_AREA
    assert load_europe.area == TOTAL_EUROPE_AREA
    assert wind_solar_europe.area == TOTAL_EUROPE_AREA
    assert generation_europe.refresh_calls == 1
    assert load_europe.refresh_calls == 1
    assert wind_solar_europe.refresh_calls == 1

    assert hass.config_entries.async_forward_entry_setups.await_count == 1
