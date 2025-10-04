import asyncio
import sys
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
import requests

PACKAGE_ROOT = Path(__file__).resolve().parents[3]
sys.path.append(str(PACKAGE_ROOT))

from custom_components.entsoe_data.api_client import EntsoeClient
from custom_components.entsoe_data.const import AREA_INFO, CONF_AREA, DOMAIN, TOTAL_EUROPE_AREA
from custom_components.entsoe_data.coordinator import (
    EntsoeGenerationCoordinator,
    EntsoeGenerationForecastCoordinator,
    EntsoeLoadCoordinator,
    EntsoeWindSolarForecastCoordinator,
)
from custom_components.entsoe_data.sensor import (
    TOTAL_GENERATION_KEY,
    EntsoeGenerationSensor,
    EntsoeGenerationForecastSensor,
    EntsoeLoadSensor,
    EntsoeWindSolarForecastSensor,
    generation_forecast_sensor_descriptions,
    generation_sensor_descriptions,
    generation_total_europe_descriptions,
    load_sensor_descriptions,
    load_total_europe_descriptions,
    wind_solar_sensor_descriptions,
    wind_solar_total_europe_descriptions,
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
        "custom_components.entsoe_data.sensor.event.async_track_point_in_utc_time",
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


def test_generation_coordinator_total_europe_aggregates(monkeypatch, hass):
    minimal_area_info = {
        TOTAL_EUROPE_AREA: {"code": "10Y1001A1001A876"},
        "DE": {"code": "DE_LU"},
        "LU": {"code": "DE_LU"},
        "FR": {"code": "FR"},
    }
    monkeypatch.setattr(
        "custom_components.entsoe_data.coordinator.AREA_INFO",
        minimal_area_info,
        raising=False,
    )

    coordinator = EntsoeGenerationCoordinator(hass, "test", TOTAL_EUROPE_AREA)

    timestamp = datetime.now().astimezone().replace(minute=0, second=0, microsecond=0)
    responses = {
        "DE_LU": {
            timestamp: {
                "wind_onshore": 100.0,
                "solar": 50.0,
            }
        },
        "FR": {
            timestamp: {
                "wind_onshore": 200.0,
                "nuclear": 300.0,
            }
        },
    }
    called_codes: list[str] = []

    def _fake_query(area_code, start, end):
        called_codes.append(area_code)
        return responses.get(area_code, {})

    monkeypatch.setattr(
        coordinator._client, "query_generation_per_type", _fake_query
    )

    data = asyncio.run(coordinator._async_update_data())

    assert data
    assert len(called_codes) == 2
    assert set(called_codes) == {"DE_LU", "FR"}

    values = data[timestamp]
    assert values["wind_onshore"] == pytest.approx(300.0)
    assert values["solar"] == pytest.approx(50.0)
    assert values["nuclear"] == pytest.approx(300.0)
    assert values[TOTAL_GENERATION_KEY] == pytest.approx(650.0)
    assert TOTAL_GENERATION_KEY in coordinator.categories()


def test_wind_solar_coordinator_total_europe_aggregates(monkeypatch, hass):
    minimal_area_info = {
        TOTAL_EUROPE_AREA: {"code": "10Y1001A1001A876"},
        "DE": {"code": "DE_LU"},
        "LU": {"code": "DE_LU"},
        "FR": {"code": "FR"},
    }
    monkeypatch.setattr(
        "custom_components.entsoe_data.coordinator.AREA_INFO",
        minimal_area_info,
        raising=False,
    )

    coordinator = EntsoeWindSolarForecastCoordinator(hass, "test", TOTAL_EUROPE_AREA)

    timestamp = datetime.now().astimezone().replace(minute=0, second=0, microsecond=0)
    responses = {
        "DE_LU": {
            timestamp: {
                "wind_onshore": 20.0,
                "solar": 10.0,
            }
        },
        "FR": {
            timestamp: {
                "wind_offshore": 5.0,
                "solar": 30.0,
            }
        },
    }
    called_codes: list[str] = []

    def _fake_query(area_code, start, end):
        called_codes.append(area_code)
        return responses.get(area_code, {})

    monkeypatch.setattr(
        coordinator._client, "query_wind_solar_forecast", _fake_query
    )

    data = asyncio.run(coordinator._async_update_data())

    assert data
    assert len(called_codes) == 2
    assert set(called_codes) == {"DE_LU", "FR"}

    values = data[timestamp]
    assert values["wind_onshore"] == pytest.approx(20.0)
    assert values["wind_offshore"] == pytest.approx(5.0)
    assert values["solar"] == pytest.approx(40.0)
    assert set(coordinator.categories()) == {"wind_offshore", "wind_onshore", "solar"}


def test_load_coordinator_total_europe_aggregates(monkeypatch, hass):
    minimal_area_info = {
        TOTAL_EUROPE_AREA: {"code": "10Y1001A1001A876"},
        "DE": {"code": "DE_LU"},
        "LU": {"code": "DE_LU"},
        "FR": {"code": "FR"},
    }
    monkeypatch.setattr(
        "custom_components.entsoe_data.coordinator.AREA_INFO",
        minimal_area_info,
        raising=False,
    )

    coordinator = EntsoeLoadCoordinator(hass, "test", TOTAL_EUROPE_AREA)

    timestamp = datetime.now().astimezone().replace(minute=0, second=0, microsecond=0)
    responses = {
        "DE_LU": {
            timestamp: 100.0,
        },
        "FR": {
            timestamp: 200.0,
        },
    }
    called_codes: list[str] = []

    def _fake_query(area_code, start, end):
        called_codes.append(area_code)
        return responses.get(area_code, {})

    monkeypatch.setattr(
        coordinator._client,
        "query_total_load_forecast",
        _fake_query,
    )

    data = asyncio.run(coordinator._async_update_data())

    assert data
    assert len(called_codes) == 2
    assert set(called_codes) == {"DE_LU", "FR"}
    assert data[timestamp] == pytest.approx(300.0)


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


def test_total_europe_generation_sensor_grouping(hass):
    coordinator = EntsoeGenerationCoordinator(hass, "test", TOTAL_EUROPE_AREA)
    timestamp = datetime.now().astimezone().replace(minute=0, second=0, microsecond=0)
    coordinator.data = {
        timestamp: {
            TOTAL_GENERATION_KEY: 6400.0,
            "wind_onshore": 1500.0,
        }
    }
    coordinator._available_categories = {TOTAL_GENERATION_KEY, "wind_onshore"}

    descriptions = generation_total_europe_descriptions(coordinator)
    assert {desc.key for desc in descriptions} == {
        "total_europe_generation_total",
        "total_europe_generation_wind_onshore",
    }

    descriptions_by_category = {description.category: description for description in descriptions}

    total_description = descriptions_by_category[TOTAL_GENERATION_KEY]
    wind_description = descriptions_by_category["wind_onshore"]

    config_entry = type(
        "ConfigEntry",
        (),
        {
            "entry_id": "entry",
            "options": {CONF_AREA: "BE"},
        },
    )()

    area_name = AREA_INFO[TOTAL_EUROPE_AREA]["name"]
    sensors = [
        EntsoeGenerationSensor(coordinator, total_description, config_entry, area_name),
        EntsoeGenerationSensor(coordinator, wind_description, config_entry, area_name),
    ]

    for sensor in sensors:
        sensor.hass = hass
        asyncio.run(sensor.async_update())

    total_sensor, wind_sensor = sensors

    assert total_sensor.entity_id == "entsoe_data.total_europe_generation_total"
    assert total_sensor._attr_unique_id.endswith(
        "total_europe_generation.total_europe_generation_total"
    )
    assert total_sensor._attr_device_info.identifiers == {
        (DOMAIN, "entry_total_europe_generation")
    }
    assert total_sensor.native_value == 6400.0
    assert total_sensor._attr_name == "Total Generation output (Total Europe)"

    assert wind_sensor.entity_id == "entsoe_data.total_europe_generation_wind_onshore"
    assert wind_sensor._attr_unique_id.endswith(
        "total_europe_generation.total_europe_generation_wind_onshore"
    )
    assert wind_sensor.native_value == 1500.0
    assert wind_sensor._attr_name == "Wind Onshore output (Total Europe)"

    unique_ids = {sensor._attr_unique_id for sensor in sensors}
    assert len(unique_ids) == len(sensors)

    entity_ids = {sensor.entity_id for sensor in sensors}
    assert len(entity_ids) == len(sensors)


def test_total_europe_wind_solar_sensor_grouping(hass):
    coordinator = EntsoeWindSolarForecastCoordinator(hass, "test", TOTAL_EUROPE_AREA)
    timestamp = datetime.now().astimezone().replace(minute=0, second=0, microsecond=0)
    coordinator.data = {
        timestamp: {
            "solar": 320.0,
        }
    }
    coordinator._available_categories = {"solar"}

    descriptions = wind_solar_total_europe_descriptions(coordinator)
    description = next(desc for desc in descriptions if desc.category == "solar")

    config_entry = type(
        "ConfigEntry",
        (),
        {
            "entry_id": "entry",
            "options": {CONF_AREA: "BE"},
        },
    )()

    area_name = AREA_INFO[TOTAL_EUROPE_AREA]["name"]
    sensor = EntsoeWindSolarForecastSensor(
        coordinator, description, config_entry, area_name
    )
    sensor.hass = hass

    asyncio.run(sensor.async_update())

    assert sensor.entity_id == "entsoe_data.total_europe_wind_solar_solar"
    assert sensor._attr_unique_id.endswith(
        "total_europe_wind_solar_forecast.total_europe_wind_solar_solar"
    )
    assert sensor._attr_device_info.identifiers == {
        (DOMAIN, "entry_total_europe_wind_solar_forecast")
    }
    assert sensor.native_value == 320.0


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


def test_total_europe_load_sensor_grouping(hass):
    coordinator = EntsoeLoadCoordinator(hass, "test", TOTAL_EUROPE_AREA)
    timestamp = datetime.now().astimezone().replace(minute=0, second=0, microsecond=0)
    coordinator.data = {timestamp: 18250.0}

    description = load_total_europe_descriptions()[0]

    config_entry = type(
        "ConfigEntry",
        (),
        {
            "entry_id": "entry",
            "options": {CONF_AREA: "BE"},
        },
    )()

    area_name = AREA_INFO[TOTAL_EUROPE_AREA]["name"]
    sensor = EntsoeLoadSensor(coordinator, description, config_entry, area_name)
    sensor.hass = hass

    asyncio.run(sensor.async_update())

    assert sensor.entity_id == "entsoe_data.total_europe_load_current"
    assert sensor._attr_unique_id.endswith(
        "total_europe_load.total_europe_load_current"
    )
    assert sensor._attr_device_info.identifiers == {
        (DOMAIN, "entry_total_europe_load")
    }
    assert sensor.native_value == 18250.0


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


def test_generation_forecast_sensor_attrs(hass):
    coordinator = EntsoeGenerationForecastCoordinator(hass, "test", "BE")
    timestamp = datetime.now().astimezone().replace(minute=0, second=0, microsecond=0)
    next_timestamp = timestamp + timedelta(hours=1)
    coordinator.data = {
        timestamp: 1450.0,
        next_timestamp: 1500.0,
    }

    description = generation_forecast_sensor_descriptions()[0]

    config_entry = type(
        "ConfigEntry",
        (),
        {
            "entry_id": "entry",
            "options": {CONF_AREA: "BE"},
        },
    )()

    sensor = EntsoeGenerationForecastSensor(
        coordinator, description, config_entry, "Belgium"
    )
    sensor.hass = hass

    asyncio.run(sensor.async_update())

    assert sensor.native_value == 1450.0
    attrs = sensor.extra_state_attributes
    assert attrs["timeline"] == coordinator.timeline()
    assert attrs["next_value"] == 1500.0


def test_wind_solar_sensor_category_handling(hass):
    coordinator = EntsoeWindSolarForecastCoordinator(hass, "test", "BE")
    timestamp = datetime.now().astimezone().replace(minute=0, second=0, microsecond=0)
    coordinator.data = {
        timestamp: {"solar": 320.0, "wind_onshore": 450.0},
        timestamp + timedelta(hours=1): {"solar": 330.0},
    }
    coordinator._available_categories = {"solar", "wind_onshore"}

    descriptions = wind_solar_sensor_descriptions(coordinator)
    description = next(desc for desc in descriptions if desc.category == "solar")

    config_entry = type(
        "ConfigEntry",
        (),
        {
            "entry_id": "entry",
            "options": {CONF_AREA: "BE"},
        },
    )()

    sensor = EntsoeWindSolarForecastSensor(
        coordinator, description, config_entry, "Belgium"
    )
    sensor.hass = hass

    asyncio.run(sensor.async_update())

    assert sensor.native_value == 320.0
    attrs = sensor.extra_state_attributes
    assert attrs["timeline"] == coordinator.timeline("solar")
    assert attrs["next_value"] == 330.0


