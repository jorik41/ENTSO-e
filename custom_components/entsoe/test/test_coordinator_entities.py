import asyncio
import sys
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
import requests

PACKAGE_ROOT = Path(__file__).resolve().parent.parent
sys.path.append(str(PACKAGE_ROOT))

from custom_components.entsoe.api_client import EntsoeClient
from custom_components.entsoe.const import CONF_AREA
from custom_components.entsoe.coordinator import (
    EntsoeGenerationCoordinator,
    EntsoeLoadCoordinator,
)
from custom_components.entsoe.sensor import (
    TOTAL_GENERATION_KEY,
    EntsoeGenerationSensor,
    EntsoeLoadSensor,
    generation_sensor_descriptions,
    load_sensor_descriptions,
)

DATASET_DIR = Path(__file__).parent / "datasets"


class DummyHass:
    def __init__(self) -> None:
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        self.is_running = True

    async def async_add_executor_job(self, func, *args, **kwargs):
        return func(*args, **kwargs)

    def async_create_task(self, coro):
        return self.loop.create_task(coro)


@pytest.fixture
def hass():
    return DummyHass()


@pytest.fixture(autouse=True)
def patch_track_point(monkeypatch):
    def _fake_track_point(hass, job, when):
        return lambda: None

    monkeypatch.setattr(
        "custom_components.entsoe.sensor.event.async_track_point_in_utc_time",
        _fake_track_point,
    )


def test_generation_coordinator_filters_categories(monkeypatch, hass):
    coordinator = EntsoeGenerationCoordinator(hass, "test", "BE")
    client = EntsoeClient("test")

    with open(DATASET_DIR / "EU_generation.xml") as handle:
        payload = handle.read()

    parsed = client.parse_generation_per_type_document(payload)

    monkeypatch.setattr(
        coordinator._client,
        "query_generation_per_type",
        lambda *args, **kwargs: parsed,
    )

    data = asyncio.run(coordinator._async_update_data())

    assert data
    first_timestamp = sorted(data.keys())[0]
    total = data[first_timestamp][TOTAL_GENERATION_KEY]
    subtotal = sum(
        value for key, value in data[first_timestamp].items() if key != TOTAL_GENERATION_KEY
    )
    assert pytest.approx(total) == subtotal
    assert TOTAL_GENERATION_KEY in coordinator.categories()


def test_generation_sensor_availability(hass):
    coordinator = EntsoeGenerationCoordinator(hass, "test", "BE")
    timestamp = datetime.now().astimezone().replace(minute=0, second=0, microsecond=0)
    coordinator.data = {
        timestamp: {
            "wind_onshore": 1500.0,
            TOTAL_GENERATION_KEY: 3200.0,
        }
    }
    coordinator._available_categories = {"wind_onshore", TOTAL_GENERATION_KEY}

    descriptions = generation_sensor_descriptions(coordinator)
    description = next(desc for desc in descriptions if desc.category == "wind_onshore")

    config_entry = type(
        "ConfigEntry",
        (),
        {
            "entry_id": "entry",
            "options": {CONF_AREA: "BE"},
        },
    )()

    sensor = EntsoeGenerationSensor(coordinator, description, config_entry, "Belgium")
    sensor.hass = hass

    asyncio.run(sensor.async_update())
    assert sensor.available is True
    assert sensor.native_value == 1500.0
    assert sensor.extra_state_attributes["timeline"] == {
        timestamp.isoformat(): 1500.0
    }
    assert "current_timestamp" in sensor.extra_state_attributes

    coordinator.data = {}
    asyncio.run(sensor.async_update())
    assert sensor.available is False


def test_load_sensor_timeline_from_mixed_resolution(hass):
    coordinator = EntsoeLoadCoordinator(hass, "test", "BE")
    client = EntsoeClient("test")

    with open(DATASET_DIR / "BE_total_load.xml") as handle:
        payload = handle.read()

    coordinator.data = client.parse_total_load_document(payload)

    description = load_sensor_descriptions()[0]

    config_entry = type(
        "ConfigEntry",
        (),
        {
            "entry_id": "entry",
            "options": {CONF_AREA: "BE"},
        },
    )()

    sensor = EntsoeLoadSensor(coordinator, description, config_entry, "Belgium")
    sensor.hass = hass

    asyncio.run(sensor.async_update())
    assert sensor.available is True
    timeline = sensor.extra_state_attributes["timeline"]
    assert timeline == coordinator.timeline()
    assert len(timeline) == len(coordinator.data)


def test_load_coordinator_handles_http_400(monkeypatch, hass):
    coordinator = EntsoeLoadCoordinator(hass, "test", "BE")

    response = SimpleNamespace(status_code=400)

    def _raise(*args, **kwargs):
        raise requests.exceptions.HTTPError(response=response)

    monkeypatch.setattr(
        coordinator._client, "query_total_load_forecast", _raise
    )

    data = asyncio.run(coordinator._async_update_data())

    assert data == {}
