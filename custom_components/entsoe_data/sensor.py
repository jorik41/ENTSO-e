"""ENTSO-e sensors for generation and load forecasts."""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import timedelta
from typing import Any

from homeassistant.components.sensor import (
    RestoreSensor,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HassJob, HomeAssistant
from homeassistant.helpers import event
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.typing import StateType
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import utcnow

from .const import (
    AREA_INFO,
    ATTRIBUTION,
    CONF_AREA,
    DOMAIN,
    LOAD_FORECAST_HORIZON_DAY_AHEAD,
    LOAD_FORECAST_HORIZON_MAP,
    LOAD_FORECAST_HORIZONS,
    TOTAL_EUROPE_AREA,
)
from .coordinator import (
    EntsoeGenerationCoordinator,
    EntsoeGenerationForecastCoordinator,
    EntsoeLoadCoordinator,
    EntsoeWindSolarForecastCoordinator,
)

_LOGGER = logging.getLogger(__name__)

GENERATION_UNIT = "MW"
LOAD_UNIT = "MW"
GENERATION_DEVICE_SUFFIX = "generation"
LOAD_DEVICE_SUFFIX = "load"
TOTAL_EUROPE_CONTEXT = "total_europe"
GENERATION_EUROPE_DEVICE_SUFFIX = f"{TOTAL_EUROPE_CONTEXT}_{GENERATION_DEVICE_SUFFIX}"
TOTAL_GENERATION_KEY = "total_generation"
GENERATION_FORECAST_DEVICE_SUFFIX = "generation_forecast"
WIND_SOLAR_DEVICE_SUFFIX = "wind_solar_forecast"
WIND_SOLAR_EUROPE_DEVICE_SUFFIX = f"{TOTAL_EUROPE_CONTEXT}_{WIND_SOLAR_DEVICE_SUFFIX}"

@dataclass
class EntsoeGenerationEntityDescription(SensorEntityDescription):
    """Describes ENTSO-e generation sensor entity."""

    category: str = ""
    value_fn: Callable[[EntsoeGenerationCoordinator], StateType] | None = None
    attrs_fn: Callable[[EntsoeGenerationCoordinator], dict[str, Any]] | None = None
    device_suffix: str = GENERATION_DEVICE_SUFFIX


@dataclass
class EntsoeLoadEntityDescription(SensorEntityDescription):
    """Describes ENTSO-e load forecast sensor entity."""

    value_fn: Callable[[EntsoeLoadCoordinator], StateType] | None = None
    attrs_fn: Callable[[EntsoeLoadCoordinator], dict[str, Any]] | None = None
    device_suffix: str = LOAD_DEVICE_SUFFIX


@dataclass
class EntsoeGenerationForecastEntityDescription(SensorEntityDescription):
    """Describes ENTSO-e generation forecast sensor entity."""

    value_fn: Callable[[EntsoeGenerationForecastCoordinator], StateType] | None = None
    attrs_fn: Callable[
        [EntsoeGenerationForecastCoordinator], dict[str, Any]
    ] | None = None
    device_suffix: str = GENERATION_FORECAST_DEVICE_SUFFIX


@dataclass
class EntsoeWindSolarEntityDescription(SensorEntityDescription):
    """Describes ENTSO-e wind and solar forecast sensor entity."""

    category: str = ""
    value_fn: Callable[[EntsoeWindSolarForecastCoordinator], StateType] | None = None
    attrs_fn: Callable[
        [EntsoeWindSolarForecastCoordinator], dict[str, Any]
    ] | None = None
    device_suffix: str = WIND_SOLAR_DEVICE_SUFFIX

def generation_sensor_descriptions(
    coordinator: EntsoeGenerationCoordinator,
) -> list[EntsoeGenerationEntityDescription]:
    """Create generation sensor descriptions for all categories."""

    categories = set(coordinator.categories())
    categories.add(TOTAL_GENERATION_KEY)

    descriptions: list[EntsoeGenerationEntityDescription] = []
    for category in sorted(categories):
        key = f"generation_{category}"
        name = "Total generation" if category == TOTAL_GENERATION_KEY else _format_category_name(category)
        descriptions.append(
            EntsoeGenerationEntityDescription(
                key=key,
                name=f"{name.title()} output",
                native_unit_of_measurement=GENERATION_UNIT,
                state_class=SensorStateClass.MEASUREMENT,
                icon="mdi:factory",
                category=category,
                value_fn=lambda coordinator, cat=category: coordinator.current_value(cat),
                attrs_fn=lambda coordinator, cat=category: _generation_attrs(coordinator, cat),
            )
        )
    return descriptions


def generation_total_europe_descriptions(
    coordinator: EntsoeGenerationCoordinator,
) -> list[EntsoeGenerationEntityDescription]:
    """Create generation sensor descriptions for Total Europe totals."""

    categories = set(coordinator.categories())
    categories.add(TOTAL_GENERATION_KEY)

    descriptions: list[EntsoeGenerationEntityDescription] = []
    for category in sorted(categories):
        name = (
            "Total generation"
            if category == TOTAL_GENERATION_KEY
            else _format_category_name(category)
        )
        key = (
            f"{TOTAL_EUROPE_CONTEXT}_generation_total"
            if category == TOTAL_GENERATION_KEY
            else f"{TOTAL_EUROPE_CONTEXT}_generation_{category}"
        )
        descriptions.append(
            EntsoeGenerationEntityDescription(
                key=key,
                name=f"{name.title()} output",
                native_unit_of_measurement=GENERATION_UNIT,
                state_class=SensorStateClass.MEASUREMENT,
                icon="mdi:factory",
                category=category,
                value_fn=lambda coordinator, cat=category: coordinator.current_value(cat),
                attrs_fn=lambda coordinator, cat=category: _generation_attrs(
                    coordinator, cat
                ),
                device_suffix=GENERATION_EUROPE_DEVICE_SUFFIX,
            )
        )

    return descriptions


def _generation_attrs(
    coordinator: EntsoeGenerationCoordinator, category: str
) -> dict[str, Any]:
    current_ts = coordinator.current_timestamp()
    next_ts = coordinator.next_timestamp()
    attrs: dict[str, Any] = {
        "timeline": coordinator.timeline(category),
    }
    next_value = coordinator.next_value(category)
    if next_value is not None:
        attrs["next_value"] = next_value
    if current_ts:
        attrs["current_timestamp"] = current_ts.isoformat()
    if next_ts:
        attrs["next_timestamp"] = next_ts.isoformat()
    # Add per-area timelines for Total Europe sensors
    if coordinator.area_key == TOTAL_EUROPE_AREA:
        area_timelines = coordinator.get_all_area_timelines(category)
        if area_timelines:
            attrs["area_timelines"] = area_timelines
    return attrs


def generation_per_area_descriptions(
    coordinator: EntsoeGenerationCoordinator,
) -> list[EntsoeGenerationEntityDescription]:
    """Create generation sensor descriptions for each individual area in Total Europe."""
    
    descriptions: list[EntsoeGenerationEntityDescription] = []
    area_keys = coordinator.get_area_keys()
    
    if not area_keys:
        return descriptions
    
    categories = set(coordinator.categories())
    categories.add(TOTAL_GENERATION_KEY)
    
    for area_key in area_keys:
        area_name = AREA_INFO.get(area_key, {}).get("name", area_key)
        for category in sorted(categories):
            cat_name = (
                "Total generation"
                if category == TOTAL_GENERATION_KEY
                else _format_category_name(category)
            )
            key = (
                f"{TOTAL_EUROPE_CONTEXT}_{area_key.lower()}_generation_total"
                if category == TOTAL_GENERATION_KEY
                else f"{TOTAL_EUROPE_CONTEXT}_{area_key.lower()}_generation_{category}"
            )
            descriptions.append(
                EntsoeGenerationEntityDescription(
                    key=key,
                    name=f"{area_name} {cat_name.lower()} output",
                    native_unit_of_measurement=GENERATION_UNIT,
                    state_class=SensorStateClass.MEASUREMENT,
                    icon="mdi:factory",
                    category=category,
                    value_fn=lambda coord, ak=area_key, cat=category: coord.get_area_current_value(ak, cat),
                    attrs_fn=lambda coord, ak=area_key, cat=category: _generation_per_area_attrs(coord, ak, cat),
                    device_suffix=f"{GENERATION_EUROPE_DEVICE_SUFFIX}_per_area",
                )
            )
    
    return descriptions


def _generation_per_area_attrs(
    coordinator: EntsoeGenerationCoordinator, area_key: str, category: str
) -> dict[str, Any]:
    """Generate attributes for per-area generation sensors."""
    attrs: dict[str, Any] = {
        "timeline": coordinator.get_area_timeline(area_key, category),
        "area": area_key,
        "area_name": AREA_INFO.get(area_key, {}).get("name", area_key),
    }
    return attrs


_LOAD_SENSOR_TEMPLATES: tuple[
    tuple[
        str,
        str,
        str,
        Callable[[EntsoeLoadCoordinator], StateType],
        Callable[[EntsoeLoadCoordinator], dict[str, Any]],
    ],
    ...,
] = (
    (
        "current",
        "Current load forecast",
        "mdi:transmission-tower",
        lambda coordinator: coordinator.current_value(),
        lambda coordinator: _load_attrs(coordinator, include_next=True),
    ),
    (
        "next",
        "Next hour load forecast",
        "mdi:transmission-tower-export",
        lambda coordinator: coordinator.next_value(),
        lambda coordinator: _load_attrs(coordinator, include_next=False),
    ),
    (
        "min",
        "Minimum load forecast",
        "mdi:arrow-collapse-down",
        lambda coordinator: coordinator.min_value(),
        lambda coordinator: {"timeline": coordinator.timeline()},
    ),
    (
        "max",
        "Maximum load forecast",
        "mdi:arrow-expand-up",
        lambda coordinator: coordinator.max_value(),
        lambda coordinator: {"timeline": coordinator.timeline()},
    ),
    (
        "avg",
        "Average load forecast",
        "mdi:chart-bell-curve",
        lambda coordinator: coordinator.average_value(),
        lambda coordinator: _load_attrs(coordinator, include_next=True),
    ),
)


def load_sensor_descriptions(
    horizon: str = LOAD_FORECAST_HORIZON_DAY_AHEAD,
) -> tuple[EntsoeLoadEntityDescription, ...]:
    """Construct load forecast sensor descriptions for a given horizon."""

    config = LOAD_FORECAST_HORIZON_MAP[horizon]
    descriptions: list[EntsoeLoadEntityDescription] = []

    for suffix, base_name, icon, value_fn, attrs_fn in _LOAD_SENSOR_TEMPLATES:
        key = f"{config.sensor_key_prefix}_{suffix}"
        name = (
            base_name
            if config.sensor_name_suffix is None
            else f"{base_name} ({config.sensor_name_suffix})"
        )
        descriptions.append(
            EntsoeLoadEntityDescription(
                key=key,
                name=name,
                native_unit_of_measurement=LOAD_UNIT,
                state_class=SensorStateClass.MEASUREMENT,
                icon=icon,
                value_fn=value_fn,
                attrs_fn=attrs_fn,
                device_suffix=config.device_suffix,
            )
        )

    return tuple(descriptions)


def load_total_europe_descriptions(
    horizon: str = LOAD_FORECAST_HORIZON_DAY_AHEAD,
) -> tuple[EntsoeLoadEntityDescription, ...]:
    """Construct load forecast sensor descriptions for Total Europe totals."""

    config = LOAD_FORECAST_HORIZON_MAP[horizon]
    return tuple(
        replace(
            description,
            key=f"{TOTAL_EUROPE_CONTEXT}_{description.key}",
            device_suffix=config.europe_device_suffix,
        )
        for description in load_sensor_descriptions(horizon)
    )


def generation_forecast_sensor_descriptions() -> tuple[
    EntsoeGenerationForecastEntityDescription, ...
]:
    """Construct generation forecast sensor descriptions."""

    return (
        EntsoeGenerationForecastEntityDescription(
            key="generation_forecast_current",
            name="Current generation forecast",
            native_unit_of_measurement=GENERATION_UNIT,
            state_class=SensorStateClass.MEASUREMENT,
            icon="mdi:factory",
            value_fn=lambda coordinator: coordinator.current_value(),
            attrs_fn=lambda coordinator: _generation_forecast_attrs(
                coordinator, include_next=True
            ),
        ),
        EntsoeGenerationForecastEntityDescription(
            key="generation_forecast_next",
            name="Next hour generation forecast",
            native_unit_of_measurement=GENERATION_UNIT,
            state_class=SensorStateClass.MEASUREMENT,
            icon="mdi:factory",
            value_fn=lambda coordinator: coordinator.next_value(),
            attrs_fn=lambda coordinator: _generation_forecast_attrs(
                coordinator, include_next=False
            ),
        ),
        EntsoeGenerationForecastEntityDescription(
            key="generation_forecast_min",
            name="Minimum generation forecast",
            native_unit_of_measurement=GENERATION_UNIT,
            state_class=SensorStateClass.MEASUREMENT,
            icon="mdi:arrow-collapse-down",
            value_fn=lambda coordinator: coordinator.min_value(),
            attrs_fn=lambda coordinator: {"timeline": coordinator.timeline()},
        ),
        EntsoeGenerationForecastEntityDescription(
            key="generation_forecast_max",
            name="Maximum generation forecast",
            native_unit_of_measurement=GENERATION_UNIT,
            state_class=SensorStateClass.MEASUREMENT,
            icon="mdi:arrow-expand-up",
            value_fn=lambda coordinator: coordinator.max_value(),
            attrs_fn=lambda coordinator: {"timeline": coordinator.timeline()},
        ),
        EntsoeGenerationForecastEntityDescription(
            key="generation_forecast_avg",
            name="Average generation forecast",
            native_unit_of_measurement=GENERATION_UNIT,
            state_class=SensorStateClass.MEASUREMENT,
            icon="mdi:chart-bell-curve",
            value_fn=lambda coordinator: coordinator.average_value(),
            attrs_fn=lambda coordinator: _generation_forecast_attrs(
                coordinator, include_next=True
            ),
        ),
    )


def wind_solar_sensor_descriptions(
    coordinator: EntsoeWindSolarForecastCoordinator,
) -> list[EntsoeWindSolarEntityDescription]:
    """Construct wind and solar forecast sensor descriptions."""

    categories = set(coordinator.categories())

    descriptions: list[EntsoeWindSolarEntityDescription] = []
    for category in sorted(categories):
        key = f"wind_solar_{category}"
        name = f"{_format_category_name(category).title()} forecast"
        descriptions.append(
            EntsoeWindSolarEntityDescription(
                key=key,
                name=name,
                native_unit_of_measurement=GENERATION_UNIT,
                state_class=SensorStateClass.MEASUREMENT,
                icon="mdi:weather-windy"
                if "wind" in category
                else "mdi:weather-sunny",
                category=category,
                value_fn=lambda coordinator, cat=category: coordinator.current_value(cat),
                attrs_fn=lambda coordinator, cat=category: _wind_solar_attrs(
                    coordinator, cat
                ),
            )
        )
    return descriptions


def wind_solar_total_europe_descriptions(
    coordinator: EntsoeWindSolarForecastCoordinator,
) -> list[EntsoeWindSolarEntityDescription]:
    """Construct wind and solar forecast sensor descriptions for Total Europe."""

    return [
        EntsoeWindSolarEntityDescription(
            key=f"{TOTAL_EUROPE_CONTEXT}_{description.key}",
            name=description.name,
            native_unit_of_measurement=description.native_unit_of_measurement,
            state_class=description.state_class,
            icon=description.icon,
            category=description.category,
            value_fn=description.value_fn,
            attrs_fn=description.attrs_fn,
            device_suffix=WIND_SOLAR_EUROPE_DEVICE_SUFFIX,
        )
        for description in wind_solar_sensor_descriptions(coordinator)
    ]


def _load_attrs(
    coordinator: EntsoeLoadCoordinator, include_next: bool
) -> dict[str, Any]:
    attrs: dict[str, Any] = {"timeline": coordinator.timeline()}
    current_ts = coordinator.current_timestamp()
    next_ts = coordinator.next_timestamp()
    if include_next:
        next_value = coordinator.next_value()
        if next_value is not None:
            attrs["next_value"] = next_value
    if current_ts:
        attrs["current_timestamp"] = current_ts.isoformat()
    if next_ts:
        attrs["next_timestamp"] = next_ts.isoformat()
    # Add per-area timelines for Total Europe sensors
    if coordinator.area_key == TOTAL_EUROPE_AREA:
        area_timelines = coordinator.get_all_area_timelines()
        if area_timelines:
            attrs["area_timelines"] = area_timelines
    return attrs


def load_per_area_descriptions(
    coordinator: EntsoeLoadCoordinator,
    horizon: str = LOAD_FORECAST_HORIZON_DAY_AHEAD,
) -> list[EntsoeLoadEntityDescription]:
    """Create load forecast sensor descriptions for each individual area in Total Europe."""
    
    descriptions: list[EntsoeLoadEntityDescription] = []
    area_keys = coordinator.get_area_keys()
    
    if not area_keys:
        return descriptions
    
    config = LOAD_FORECAST_HORIZON_MAP[horizon]
    
    for area_key in area_keys:
        area_name = AREA_INFO.get(area_key, {}).get("name", area_key)
        
        # Create current load sensor for this area
        key = f"{TOTAL_EUROPE_CONTEXT}_{area_key.lower()}_{config.sensor_key_prefix}_current"
        name = f"{area_name} current load forecast"
        if config.sensor_name_suffix:
            name = f"{name} ({config.sensor_name_suffix})"
        
        descriptions.append(
            EntsoeLoadEntityDescription(
                key=key,
                name=name,
                native_unit_of_measurement=LOAD_UNIT,
                state_class=SensorStateClass.MEASUREMENT,
                icon="mdi:transmission-tower",
                value_fn=lambda coord, ak=area_key: coord.get_area_current_value(ak),
                attrs_fn=lambda coord, ak=area_key: _load_per_area_attrs(coord, ak),
                device_suffix=f"{config.europe_device_suffix}_per_area",
            )
        )
    
    return descriptions


def _load_per_area_attrs(
    coordinator: EntsoeLoadCoordinator, area_key: str
) -> dict[str, Any]:
    """Generate attributes for per-area load forecast sensors."""
    attrs: dict[str, Any] = {
        "timeline": coordinator.get_area_timeline(area_key),
        "area": area_key,
        "area_name": AREA_INFO.get(area_key, {}).get("name", area_key),
    }
    return attrs


def _generation_forecast_attrs(
    coordinator: EntsoeGenerationForecastCoordinator, include_next: bool
) -> dict[str, Any]:
    attrs: dict[str, Any] = {"timeline": coordinator.timeline()}
    current_ts = coordinator.current_timestamp()
    next_ts = coordinator.next_timestamp()
    if include_next:
        next_value = coordinator.next_value()
        if next_value is not None:
            attrs["next_value"] = next_value
    if current_ts:
        attrs["current_timestamp"] = current_ts.isoformat()
    if next_ts:
        attrs["next_timestamp"] = next_ts.isoformat()
    return attrs


def _wind_solar_attrs(
    coordinator: EntsoeWindSolarForecastCoordinator, category: str
) -> dict[str, Any]:
    attrs: dict[str, Any] = {"timeline": coordinator.timeline(category)}
    current_ts = coordinator.current_timestamp()
    next_ts = coordinator.next_timestamp()
    next_value = coordinator.next_value(category)
    if next_value is not None:
        attrs["next_value"] = next_value
    if current_ts:
        attrs["current_timestamp"] = current_ts.isoformat()
    if next_ts:
        attrs["next_timestamp"] = next_ts.isoformat()
    # Add per-area timelines for Total Europe sensors
    if coordinator.area_key == TOTAL_EUROPE_AREA:
        area_timelines = coordinator.get_all_area_timelines(category)
        if area_timelines:
            attrs["area_timelines"] = area_timelines
    return attrs


def wind_solar_per_area_descriptions(
    coordinator: EntsoeWindSolarForecastCoordinator,
) -> list[EntsoeWindSolarEntityDescription]:
    """Create wind/solar forecast sensor descriptions for each individual area in Total Europe."""
    
    descriptions: list[EntsoeWindSolarEntityDescription] = []
    area_keys = coordinator.get_area_keys()
    
    if not area_keys:
        return descriptions
    
    categories = set(coordinator.categories())
    
    for area_key in area_keys:
        area_name = AREA_INFO.get(area_key, {}).get("name", area_key)
        for category in sorted(categories):
            cat_name = _format_category_name(category)
            key = f"{TOTAL_EUROPE_CONTEXT}_{area_key.lower()}_wind_solar_{category}"
            descriptions.append(
                EntsoeWindSolarEntityDescription(
                    key=key,
                    name=f"{area_name} {cat_name.lower()} forecast",
                    native_unit_of_measurement=GENERATION_UNIT,
                    state_class=SensorStateClass.MEASUREMENT,
                    icon="mdi:weather-windy" if "wind" in category else "mdi:solar-power",
                    category=category,
                    value_fn=lambda coord, ak=area_key, cat=category: coord.get_area_current_value(ak, cat),
                    attrs_fn=lambda coord, ak=area_key, cat=category: _wind_solar_per_area_attrs(coord, ak, cat),
                    device_suffix=f"{WIND_SOLAR_EUROPE_DEVICE_SUFFIX}_per_area",
                )
            )
    
    return descriptions


def _wind_solar_per_area_attrs(
    coordinator: EntsoeWindSolarForecastCoordinator, area_key: str, category: str
) -> dict[str, Any]:
    """Generate attributes for per-area wind/solar forecast sensors."""
    attrs: dict[str, Any] = {
        "timeline": coordinator.get_area_timeline(area_key, category),
        "area": area_key,
        "area_name": AREA_INFO.get(area_key, {}).get("name", area_key),
    }
    return attrs


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up ENTSO-e sensor entries."""

    coordinators = hass.data.get(DOMAIN, {}).get(config_entry.entry_id, {})

    entities: list[RestoreSensor] = []

    if generation_coordinator := coordinators.get("generation"):
        entities.extend(
            _create_generation_sensors(
                config_entry,
                generation_coordinator,
            )
        )

    if generation_europe_coordinator := coordinators.get("generation_europe"):
        entities.extend(
            _create_generation_sensors(
                config_entry,
                generation_europe_coordinator,
                area_name=AREA_INFO.get(TOTAL_EUROPE_AREA, {}).get("name", ""),
                descriptions=generation_total_europe_descriptions(
                    generation_europe_coordinator
                ),
            )
        )
        # Add per-area sensors for Total Europe
        entities.extend(
            _create_generation_sensors(
                config_entry,
                generation_europe_coordinator,
                area_name=AREA_INFO.get(TOTAL_EUROPE_AREA, {}).get("name", ""),
                descriptions=generation_per_area_descriptions(
                    generation_europe_coordinator
                ),
            )
        )

    europe_area_name = AREA_INFO.get(TOTAL_EUROPE_AREA, {}).get("name", "")

    for horizon in LOAD_FORECAST_HORIZONS:
        if load_coordinator := coordinators.get(horizon.coordinator_key):
            entities.extend(
                _create_load_sensors(
                    config_entry,
                    load_coordinator,
                    descriptions=load_sensor_descriptions(horizon.horizon),
                )
            )

        europe_key = horizon.europe_coordinator_key
        if europe_load_coordinator := coordinators.get(europe_key):
            entities.extend(
                _create_load_sensors(
                    config_entry,
                    europe_load_coordinator,
                    area_name=europe_area_name,
                    descriptions=load_total_europe_descriptions(horizon.horizon),
                )
            )
            # Add per-area sensors for Total Europe
            entities.extend(
                _create_load_sensors(
                    config_entry,
                    europe_load_coordinator,
                    area_name=europe_area_name,
                    descriptions=load_per_area_descriptions(
                        europe_load_coordinator, horizon.horizon
                    ),
                )
            )

    if generation_forecast_coordinator := coordinators.get("generation_forecast"):
        entities.extend(
            _create_generation_forecast_sensors(
                config_entry,
                generation_forecast_coordinator,
            )
        )

    if wind_solar_forecast_coordinator := coordinators.get("wind_solar_forecast"):
        entities.extend(
            _create_wind_solar_sensors(
                config_entry,
                wind_solar_forecast_coordinator,
            )
        )

    if wind_solar_forecast_europe_coordinator := coordinators.get(
        "wind_solar_forecast_europe"
    ):
        entities.extend(
            _create_wind_solar_sensors(
                config_entry,
                wind_solar_forecast_europe_coordinator,
                area_name=AREA_INFO.get(TOTAL_EUROPE_AREA, {}).get("name", ""),
                descriptions=wind_solar_total_europe_descriptions(
                    wind_solar_forecast_europe_coordinator
                ),
            )
        )
        # Add per-area sensors for Total Europe
        entities.extend(
            _create_wind_solar_sensors(
                config_entry,
                wind_solar_forecast_europe_coordinator,
                area_name=AREA_INFO.get(TOTAL_EUROPE_AREA, {}).get("name", ""),
                descriptions=wind_solar_per_area_descriptions(
                    wind_solar_forecast_europe_coordinator
                ),
            )
        )

    if entities:
        async_add_entities(entities, True)
def _create_generation_sensors(
    config_entry: ConfigEntry,
    coordinator: EntsoeGenerationCoordinator,
    *,
    area_name: str | None = None,
    descriptions: list[EntsoeGenerationEntityDescription] | None = None,
) -> list[RestoreSensor]:
    if not coordinator.data and getattr(coordinator, "last_successful_update", None) is None:
        return []
    area_key = config_entry.options.get(CONF_AREA)
    resolved_area_name = (
        area_name
        if area_name is not None
        else AREA_INFO.get(area_key, {}).get("name", area_key or "")
    )

    selected_descriptions = descriptions or generation_sensor_descriptions(coordinator)

    return [
        EntsoeGenerationSensor(
            coordinator,
            description,
            config_entry,
            resolved_area_name,
        )
        for description in selected_descriptions
    ]


def _create_load_sensors(
    config_entry: ConfigEntry,
    coordinator: EntsoeLoadCoordinator,
    *,
    area_name: str | None = None,
    descriptions: tuple[EntsoeLoadEntityDescription, ...] | None = None,
) -> list[RestoreSensor]:
    if not coordinator.data and getattr(coordinator, "last_successful_update", None) is None:
        return []
    area_key = config_entry.options.get(CONF_AREA)
    resolved_area_name = (
        area_name
        if area_name is not None
        else AREA_INFO.get(area_key, {}).get("name", area_key or "")
    )

    selected_descriptions = descriptions or load_sensor_descriptions()

    return [
        EntsoeLoadSensor(
            coordinator,
            description,
            config_entry,
            resolved_area_name,
        )
        for description in selected_descriptions
    ]


def _create_generation_forecast_sensors(
    config_entry: ConfigEntry,
    coordinator: EntsoeGenerationForecastCoordinator,
    *,
    area_name: str | None = None,
    descriptions: tuple[
        EntsoeGenerationForecastEntityDescription, ...
    ] | None = None,
) -> list[RestoreSensor]:
    if not coordinator.data and getattr(coordinator, "last_successful_update", None) is None:
        return []
    area_key = config_entry.options.get(CONF_AREA)
    resolved_area_name = (
        area_name
        if area_name is not None
        else AREA_INFO.get(area_key, {}).get("name", area_key or "")
    )

    selected_descriptions = descriptions or generation_forecast_sensor_descriptions()

    return [
        EntsoeGenerationForecastSensor(
            coordinator,
            description,
            config_entry,
            resolved_area_name,
        )
        for description in selected_descriptions
    ]


def _create_wind_solar_sensors(
    config_entry: ConfigEntry,
    coordinator: EntsoeWindSolarForecastCoordinator,
    *,
    area_name: str | None = None,
    descriptions: list[EntsoeWindSolarEntityDescription] | None = None,
) -> list[RestoreSensor]:
    if not coordinator.data and getattr(coordinator, "last_successful_update", None) is None:
        return []
    area_key = config_entry.options.get(CONF_AREA)
    resolved_area_name = (
        area_name
        if area_name is not None
        else AREA_INFO.get(area_key, {}).get("name", area_key or "")
    )

    selected_descriptions = descriptions or wind_solar_sensor_descriptions(coordinator)

    return [
        EntsoeWindSolarForecastSensor(
            coordinator,
            description,
            config_entry,
            resolved_area_name,
        )
        for description in selected_descriptions
    ]


class _HourlyCoordinatorSensor(CoordinatorEntity, RestoreSensor):
    """Base sensor that refreshes state every hour to reflect timeline changes."""

    _attr_attribution = ATTRIBUTION

    def __init__(self, coordinator):
        super().__init__(coordinator)
        self._update_job = HassJob(self.async_schedule_update_ha_state)
        self._unsub_update: Callable[[], None] | None = None
        self._last_update_success = True

    async def async_will_remove_from_hass(self) -> None:
        if self._unsub_update:
            self._unsub_update()
            self._unsub_update = None
        await super().async_will_remove_from_hass()

    async def async_update(self) -> None:
        if self._unsub_update:
            self._unsub_update()
            self._unsub_update = None

        self._unsub_update = event.async_track_point_in_utc_time(
            self.hass,
            self._update_job,
            utcnow().replace(minute=0, second=0, microsecond=0) + timedelta(hours=1),
        )

        try:
            await self._async_handle_coordinator_update()
            self._last_update_success = True
        except Exception as exc:  # pragma: no cover - defensive safeguard
            self._last_update_success = False
            _LOGGER.warning("Unable to update entity '%s': %s", self.entity_id, exc)

    async def _async_handle_coordinator_update(self) -> None:
        raise NotImplementedError

    @property
    def available(self) -> bool:
        """Check if sensor is available.

        A sensor is unavailable if:
        1. The last update failed
        2. The coordinator is unavailable
        3. The coordinator's data is stale (prevents ML training on bad data)
        """
        if not self._last_update_success:
            return False
        if not super().available:
            return False
        # Check if coordinator data is stale (important for ML model training)
        if hasattr(self.coordinator, 'is_data_stale') and self.coordinator.is_data_stale():
            return False
        return True

    def _handle_coordinator_update(self) -> None:
        super()._handle_coordinator_update()
        if self.hass.is_running:
            self.hass.async_create_task(self.async_update())


class EntsoeGenerationSensor(_HourlyCoordinatorSensor):
    """Representation of a generation sensor."""

    entity_description: EntsoeGenerationEntityDescription

    def __init__(
        self,
        coordinator: EntsoeGenerationCoordinator,
        description: EntsoeGenerationEntityDescription,
        config_entry: ConfigEntry,
        area_name: str,
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        device_suffix = description.device_suffix or GENERATION_DEVICE_SUFFIX
        self._attr_unique_id = (
            f"entsoe_data.{config_entry.entry_id}.{device_suffix}.{description.key}"
        )
        self._attr_name = (
            f"{description.name} ({area_name})" if area_name else description.name
        )
        self._attr_icon = description.icon
        self.entity_id = f"{DOMAIN}.{description.key}"
        self._attr_device_info = DeviceInfo(
            entry_type=DeviceEntryType.SERVICE,
            identifiers={(DOMAIN, f"{config_entry.entry_id}_{device_suffix}")},
            manufacturer="entso-e",
            name="ENTSO-e Generation"
            + ((f" ({area_name})") if area_name else ""),
        )

    async def _async_handle_coordinator_update(self) -> None:
        if not self.coordinator.data:
            # No fresh data available
            # If we had successful updates before, keep showing the last known value
            # until the API connection is restored (sensor will be marked unavailable if stale)
            if hasattr(self.coordinator, 'last_successful_update') and self.coordinator.last_successful_update:
                # Keep the previous sensor value - it will show correct forecast for current time
                # The available property will mark sensor as unavailable if data is too stale
                return
            # First run with no data yet - set to None
            self._attr_native_value = None
            self._attr_extra_state_attributes = {}
            return

        if self.entity_description.value_fn is None:
            raise RuntimeError("Missing value function")

        value = self.entity_description.value_fn(self.coordinator)
        self._attr_native_value = value

        if self.entity_description.attrs_fn is not None:
            self._attr_extra_state_attributes = self.entity_description.attrs_fn(
                self.coordinator
            )


class EntsoeLoadSensor(_HourlyCoordinatorSensor):
    """Representation of a total load forecast sensor."""

    entity_description: EntsoeLoadEntityDescription

    def __init__(
        self,
        coordinator: EntsoeLoadCoordinator,
        description: EntsoeLoadEntityDescription,
        config_entry: ConfigEntry,
        area_name: str,
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        device_suffix = description.device_suffix or LOAD_DEVICE_SUFFIX
        self._attr_unique_id = (
            f"entsoe_data.{config_entry.entry_id}.{device_suffix}.{description.key}"
        )
        self._attr_name = (
            f"{description.name} ({area_name})" if area_name else description.name
        )
        self._attr_icon = description.icon
        self.entity_id = f"{DOMAIN}.{description.key}"
        self._attr_device_info = DeviceInfo(
            entry_type=DeviceEntryType.SERVICE,
            identifiers={(DOMAIN, f"{config_entry.entry_id}_{device_suffix}")},
            manufacturer="entso-e",
            name="ENTSO-e Load forecast"
            + ((f" ({area_name})") if area_name else ""),
        )

    async def _async_handle_coordinator_update(self) -> None:
        if not self.coordinator.data:
            # No fresh data available
            # If we had successful updates before, keep showing the last known value
            # until the API connection is restored (sensor will be marked unavailable if stale)
            if hasattr(self.coordinator, 'last_successful_update') and self.coordinator.last_successful_update:
                # Keep the previous sensor value - it will show correct forecast for current time
                # The available property will mark sensor as unavailable if data is too stale
                return
            # First run with no data yet - set to None
            self._attr_native_value = None
            self._attr_extra_state_attributes = {}
            return

        if self.entity_description.value_fn is None:
            raise RuntimeError("Missing value function")

        value = self.entity_description.value_fn(self.coordinator)
        self._attr_native_value = value

        if self.entity_description.attrs_fn is not None:
            self._attr_extra_state_attributes = self.entity_description.attrs_fn(
                self.coordinator
            )


class EntsoeGenerationForecastSensor(_HourlyCoordinatorSensor):
    """Representation of a generation forecast sensor."""

    entity_description: EntsoeGenerationForecastEntityDescription

    def __init__(
        self,
        coordinator: EntsoeGenerationForecastCoordinator,
        description: EntsoeGenerationForecastEntityDescription,
        config_entry: ConfigEntry,
        area_name: str,
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        device_suffix = description.device_suffix or GENERATION_FORECAST_DEVICE_SUFFIX
        self._attr_unique_id = (
            f"entsoe_data.{config_entry.entry_id}.{device_suffix}.{description.key}"
        )
        self._attr_name = (
            f"{description.name} ({area_name})" if area_name else description.name
        )
        self._attr_icon = description.icon
        self.entity_id = f"{DOMAIN}.{description.key}"
        self._attr_device_info = DeviceInfo(
            entry_type=DeviceEntryType.SERVICE,
            identifiers={(DOMAIN, f"{config_entry.entry_id}_{device_suffix}")},
            manufacturer="entso-e",
            name="ENTSO-e Generation forecast"
            + ((f" ({area_name})") if area_name else ""),
        )

    async def _async_handle_coordinator_update(self) -> None:
        if not self.coordinator.data:
            # No fresh data available
            # If we had successful updates before, keep showing the last known value
            # until the API connection is restored (sensor will be marked unavailable if stale)
            if hasattr(self.coordinator, 'last_successful_update') and self.coordinator.last_successful_update:
                # Keep the previous sensor value - it will show correct forecast for current time
                # The available property will mark sensor as unavailable if data is too stale
                return
            # First run with no data yet - set to None
            self._attr_native_value = None
            self._attr_extra_state_attributes = {}
            return

        if self.entity_description.value_fn is None:
            raise RuntimeError("Missing value function")

        value = self.entity_description.value_fn(self.coordinator)
        self._attr_native_value = value

        if self.entity_description.attrs_fn is not None:
            self._attr_extra_state_attributes = self.entity_description.attrs_fn(
                self.coordinator
            )


class EntsoeWindSolarForecastSensor(_HourlyCoordinatorSensor):
    """Representation of a wind and solar forecast sensor."""

    entity_description: EntsoeWindSolarEntityDescription

    def __init__(
        self,
        coordinator: EntsoeWindSolarForecastCoordinator,
        description: EntsoeWindSolarEntityDescription,
        config_entry: ConfigEntry,
        area_name: str,
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        device_suffix = description.device_suffix or WIND_SOLAR_DEVICE_SUFFIX
        self._attr_unique_id = (
            f"entsoe_data.{config_entry.entry_id}.{device_suffix}.{description.key}"
        )
        self._attr_name = (
            f"{description.name} ({area_name})" if area_name else description.name
        )
        self._attr_icon = description.icon
        self.entity_id = f"{DOMAIN}.{description.key}"
        self._attr_device_info = DeviceInfo(
            entry_type=DeviceEntryType.SERVICE,
            identifiers={(DOMAIN, f"{config_entry.entry_id}_{device_suffix}")},
            manufacturer="entso-e",
            name="ENTSO-e Wind and solar forecast"
            + ((f" ({area_name})") if area_name else ""),
        )

    async def _async_handle_coordinator_update(self) -> None:
        if not self.coordinator.data:
            # No fresh data available
            # If we had successful updates before, keep showing the last known value
            # until the API connection is restored (sensor will be marked unavailable if stale)
            if hasattr(self.coordinator, 'last_successful_update') and self.coordinator.last_successful_update:
                # Keep the previous sensor value - it will show correct forecast for current time
                # The available property will mark sensor as unavailable if data is too stale
                return
            # First run with no data yet - set to None
            self._attr_native_value = None
            self._attr_extra_state_attributes = {}
            return

        if self.entity_description.value_fn is None:
            raise RuntimeError("Missing value function")

        value = self.entity_description.value_fn(self.coordinator)
        self._attr_native_value = value

        if self.entity_description.attrs_fn is not None:
            self._attr_extra_state_attributes = self.entity_description.attrs_fn(
                self.coordinator
            )


def _format_category_name(category: str) -> str:
    return category.replace("_", " ")
