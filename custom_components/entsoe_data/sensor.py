"""ENTSO-e sensors for generation and load forecasts."""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
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

from .api_client import PSR_CATEGORY_MAPPING
from .const import (
    AREA_INFO,
    ATTRIBUTION,
    CONF_AREA,
    DOMAIN,
    TOTAL_EUROPE_AREA,
)
from .coordinator import (
    EntsoeGenerationCoordinator,
    EntsoeLoadCoordinator,
)

_LOGGER = logging.getLogger(__name__)

GENERATION_UNIT = "MW"
LOAD_UNIT = "MW"
GENERATION_DEVICE_SUFFIX = "generation"
LOAD_DEVICE_SUFFIX = "load"
TOTAL_EUROPE_CONTEXT = "total_europe"
GENERATION_EUROPE_DEVICE_SUFFIX = f"{TOTAL_EUROPE_CONTEXT}_{GENERATION_DEVICE_SUFFIX}"
LOAD_EUROPE_DEVICE_SUFFIX = f"{TOTAL_EUROPE_CONTEXT}_{LOAD_DEVICE_SUFFIX}"
TOTAL_GENERATION_KEY = "total_generation"
DEFAULT_GENERATION_CATEGORIES = sorted(set(PSR_CATEGORY_MAPPING.values()))

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

def generation_sensor_descriptions(
    coordinator: EntsoeGenerationCoordinator,
) -> list[EntsoeGenerationEntityDescription]:
    """Create generation sensor descriptions for all categories."""

    categories = set(DEFAULT_GENERATION_CATEGORIES)
    categories.update(coordinator.categories())
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
    return attrs


def load_sensor_descriptions() -> tuple[EntsoeLoadEntityDescription, ...]:
    """Construct load forecast sensor descriptions."""

    return (
        EntsoeLoadEntityDescription(
            key="load_current",
            name="Current load forecast",
            native_unit_of_measurement=LOAD_UNIT,
            state_class=SensorStateClass.MEASUREMENT,
            icon="mdi:transmission-tower",
            value_fn=lambda coordinator: coordinator.current_value(),
            attrs_fn=lambda coordinator: _load_attrs(coordinator, include_next=True),
        ),
        EntsoeLoadEntityDescription(
            key="load_next",
            name="Next hour load forecast",
            native_unit_of_measurement=LOAD_UNIT,
            state_class=SensorStateClass.MEASUREMENT,
            icon="mdi:transmission-tower-export",
            value_fn=lambda coordinator: coordinator.next_value(),
            attrs_fn=lambda coordinator: _load_attrs(coordinator, include_next=False),
        ),
        EntsoeLoadEntityDescription(
            key="load_min",
            name="Minimum load forecast",
            native_unit_of_measurement=LOAD_UNIT,
            state_class=SensorStateClass.MEASUREMENT,
            icon="mdi:arrow-collapse-down",
            value_fn=lambda coordinator: coordinator.min_value(),
            attrs_fn=lambda coordinator: {"timeline": coordinator.timeline()},
        ),
        EntsoeLoadEntityDescription(
            key="load_max",
            name="Maximum load forecast",
            native_unit_of_measurement=LOAD_UNIT,
            state_class=SensorStateClass.MEASUREMENT,
            icon="mdi:arrow-expand-up",
            value_fn=lambda coordinator: coordinator.max_value(),
            attrs_fn=lambda coordinator: {"timeline": coordinator.timeline()},
        ),
        EntsoeLoadEntityDescription(
            key="load_avg",
            name="Average load forecast",
            native_unit_of_measurement=LOAD_UNIT,
            state_class=SensorStateClass.MEASUREMENT,
            icon="mdi:chart-bell-curve",
            value_fn=lambda coordinator: coordinator.average_value(),
            attrs_fn=lambda coordinator: _load_attrs(coordinator, include_next=True),
        ),
    )


def load_total_europe_descriptions() -> tuple[EntsoeLoadEntityDescription, ...]:
    """Construct load forecast sensor descriptions for Total Europe totals."""

    return tuple(
        EntsoeLoadEntityDescription(
            key=f"{TOTAL_EUROPE_CONTEXT}_{description.key}",
            name=description.name,
            native_unit_of_measurement=description.native_unit_of_measurement,
            state_class=description.state_class,
            icon=description.icon,
            value_fn=description.value_fn,
            attrs_fn=description.attrs_fn,
            device_suffix=LOAD_EUROPE_DEVICE_SUFFIX,
        )
        for description in load_sensor_descriptions()
    )


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

    if load_coordinator := coordinators.get("load"):
        entities.extend(
            _create_load_sensors(
                config_entry,
                load_coordinator,
            )
        )

    if load_europe_coordinator := coordinators.get("load_europe"):
        entities.extend(
            _create_load_sensors(
                config_entry,
                load_europe_coordinator,
                area_name=AREA_INFO.get(TOTAL_EUROPE_AREA, {}).get("name", ""),
                descriptions=load_total_europe_descriptions(),
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
        return self._last_update_success and super().available

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
            raise RuntimeError("No generation data available")

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
            raise RuntimeError("No load forecast data available")

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
