"""ENTSO-e sensors for prices, generation, and load forecasts."""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from homeassistant.components.sensor import (
    RestoreSensor,
    SensorDeviceClass,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import PERCENTAGE
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
    CONF_CURRENCY,
    CONF_ENERGY_SCALE,
    CONF_ENTITY_NAME,
    DEFAULT_CURRENCY,
    DEFAULT_ENERGY_SCALE,
    DOMAIN,
)
from .coordinator import (
    EntsoeCoordinator,
    EntsoeGenerationCoordinator,
    EntsoeLoadCoordinator,
)

_LOGGER = logging.getLogger(__name__)

GENERATION_UNIT = "MW"
LOAD_UNIT = "MW"
PRICE_DEVICE_SUFFIX = "price"
GENERATION_DEVICE_SUFFIX = "generation"
LOAD_DEVICE_SUFFIX = "load"
TOTAL_GENERATION_KEY = "total_generation"
DEFAULT_GENERATION_CATEGORIES = sorted(set(PSR_CATEGORY_MAPPING.values()))


@dataclass
class EntsoePriceEntityDescription(SensorEntityDescription):
    """Describes ENTSO-e price sensor entity."""

    value_fn: Callable[[EntsoeCoordinator], StateType] | None = None
    attrs_fn: Callable[[EntsoeCoordinator], dict[str, Any]] | None = None


@dataclass
class EntsoeGenerationEntityDescription(SensorEntityDescription):
    """Describes ENTSO-e generation sensor entity."""

    category: str = ""
    value_fn: Callable[[EntsoeGenerationCoordinator], StateType] | None = None
    attrs_fn: Callable[[EntsoeGenerationCoordinator], dict[str, Any]] | None = None


@dataclass
class EntsoeLoadEntityDescription(SensorEntityDescription):
    """Describes ENTSO-e load forecast sensor entity."""

    value_fn: Callable[[EntsoeLoadCoordinator], StateType] | None = None
    attrs_fn: Callable[[EntsoeLoadCoordinator], dict[str, Any]] | None = None


def price_sensor_descriptions(
    currency: str, energy_scale: str
) -> tuple[EntsoePriceEntityDescription, ...]:
    """Construct price sensor descriptions."""

    def _avg_attrs(coordinator: EntsoeCoordinator) -> dict[str, Any]:
        return {
            "prices_today": coordinator.get_prices_today(),
            "prices_tomorrow": coordinator.get_prices_tomorrow(),
            "prices": coordinator.get_prices(),
        }

    return (
        EntsoePriceEntityDescription(
            key="current_price",
            name="Current electricity market price",
            native_unit_of_measurement=f"{currency}/{energy_scale}",
            state_class=SensorStateClass.MEASUREMENT,
            icon="mdi:currency-eur",
            suggested_display_precision=3,
            value_fn=lambda coordinator: coordinator.get_current_hourprice(),
        ),
        EntsoePriceEntityDescription(
            key="next_hour_price",
            name="Next hour electricity market price",
            native_unit_of_measurement=f"{currency}/{energy_scale}",
            state_class=SensorStateClass.MEASUREMENT,
            icon="mdi:currency-eur",
            suggested_display_precision=3,
            value_fn=lambda coordinator: coordinator.get_next_hourprice(),
        ),
        EntsoePriceEntityDescription(
            key="min_price",
            name="Lowest energy price",
            native_unit_of_measurement=f"{currency}/{energy_scale}",
            state_class=SensorStateClass.MEASUREMENT,
            icon="mdi:currency-eur",
            suggested_display_precision=3,
            value_fn=lambda coordinator: coordinator.get_min_price(),
        ),
        EntsoePriceEntityDescription(
            key="max_price",
            name="Highest energy price",
            native_unit_of_measurement=f"{currency}/{energy_scale}",
            state_class=SensorStateClass.MEASUREMENT,
            icon="mdi:currency-eur",
            suggested_display_precision=3,
            value_fn=lambda coordinator: coordinator.get_max_price(),
        ),
        EntsoePriceEntityDescription(
            key="avg_price",
            name="Average electricity price",
            native_unit_of_measurement=f"{currency}/{energy_scale}",
            state_class=SensorStateClass.MEASUREMENT,
            icon="mdi:currency-eur",
            suggested_display_precision=3,
            value_fn=lambda coordinator: coordinator.get_avg_price(),
            attrs_fn=_avg_attrs,
        ),
        EntsoePriceEntityDescription(
            key="percentage_of_max",
            name="Current percentage of highest electricity price",
            native_unit_of_measurement=f"{PERCENTAGE}",
            icon="mdi:percent",
            suggested_display_precision=1,
            state_class=SensorStateClass.MEASUREMENT,
            value_fn=lambda coordinator: coordinator.get_percentage_of_max(),
        ),
        EntsoePriceEntityDescription(
            key="percentage_of_range",
            name="Current percentage in electricity price range",
            native_unit_of_measurement=f"{PERCENTAGE}",
            icon="mdi:percent",
            suggested_display_precision=1,
            state_class=SensorStateClass.MEASUREMENT,
            value_fn=lambda coordinator: coordinator.get_percentage_of_range(),
        ),
        EntsoePriceEntityDescription(
            key="highest_price_time_today",
            name="Time of highest price",
            device_class=SensorDeviceClass.TIMESTAMP,
            icon="mdi:clock",
            value_fn=lambda coordinator: coordinator.get_max_time(),
        ),
        EntsoePriceEntityDescription(
            key="lowest_price_time_today",
            name="Time of lowest price",
            device_class=SensorDeviceClass.TIMESTAMP,
            icon="mdi:clock",
            value_fn=lambda coordinator: coordinator.get_min_time(),
        ),
    )


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

    coordinators = hass.data[DOMAIN][config_entry.entry_id]

    entities: list[RestoreSensor] = []
    entities.extend(
        _create_price_sensors(
            config_entry,
            coordinators["price"],
        )
    )

    if generation_coordinator := coordinators.get("generation"):
        entities.extend(
            _create_generation_sensors(
                config_entry,
                generation_coordinator,
            )
        )

    if load_coordinator := coordinators.get("load"):
        entities.extend(
            _create_load_sensors(
                config_entry,
                load_coordinator,
            )
        )

    async_add_entities(entities, True)


def _create_price_sensors(
    config_entry: ConfigEntry, coordinator: EntsoeCoordinator
) -> list[RestoreSensor]:
    name = config_entry.options.get(CONF_ENTITY_NAME, "")
    currency = config_entry.options.get(CONF_CURRENCY, DEFAULT_CURRENCY)
    energy_scale = config_entry.options.get(CONF_ENERGY_SCALE, DEFAULT_ENERGY_SCALE)

    return [
        EntsoePriceSensor(coordinator, description, config_entry, name)
        for description in price_sensor_descriptions(currency, energy_scale)
    ]


def _create_generation_sensors(
    config_entry: ConfigEntry,
    coordinator: EntsoeGenerationCoordinator,
) -> list[RestoreSensor]:
    area = config_entry.options.get(CONF_AREA)
    area_name = AREA_INFO.get(area, {}).get("name", area or "")

    return [
        EntsoeGenerationSensor(coordinator, description, config_entry, area_name)
        for description in generation_sensor_descriptions(coordinator)
    ]


def _create_load_sensors(
    config_entry: ConfigEntry, coordinator: EntsoeLoadCoordinator
) -> list[RestoreSensor]:
    area = config_entry.options.get(CONF_AREA)
    area_name = AREA_INFO.get(area, {}).get("name", area or "")

    return [
        EntsoeLoadSensor(coordinator, description, config_entry, area_name)
        for description in load_sensor_descriptions()
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


class EntsoePriceSensor(_HourlyCoordinatorSensor):
    """Representation of an ENTSO-e price sensor."""

    entity_description: EntsoePriceEntityDescription

    def __init__(
        self,
        coordinator: EntsoeCoordinator,
        description: EntsoePriceEntityDescription,
        config_entry: ConfigEntry,
        name: str,
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._config_entry = config_entry
        self._name_suffix = name

        if name:
            self.entity_id = f"{DOMAIN}.{name}_{description.name}"
            self._attr_unique_id = (
                f"entsoe.{config_entry.entry_id}.{PRICE_DEVICE_SUFFIX}.{name}.{description.key}"
            )
            self._attr_name = f"{description.name} ({name})"
        else:
            self.entity_id = f"{DOMAIN}.{description.name}"
            self._attr_unique_id = (
                f"entsoe.{config_entry.entry_id}.{PRICE_DEVICE_SUFFIX}.{description.key}"
            )
            self._attr_name = description.name

        self._attr_icon = description.icon
        self._attr_suggested_display_precision = (
            description.suggested_display_precision
            if description.suggested_display_precision is not None
            else 2
        )
        self._attr_device_info = DeviceInfo(
            entry_type=DeviceEntryType.SERVICE,
            identifiers={(DOMAIN, f"{config_entry.entry_id}_{PRICE_DEVICE_SUFFIX}")},
            manufacturer="entso-e",
            name="ENTSO-e Prices"
            + ((f" ({name})") if name else ""),
        )

    async def _async_handle_coordinator_update(self) -> None:
        if (
            self.coordinator.data is None
            or not self.coordinator.today_data_available()
        ):
            raise RuntimeError("No valid data for today available.")

        self.coordinator.sync_calculator()
        if self.entity_description.value_fn is None:
            raise RuntimeError("Missing value function")

        value: Any = self.entity_description.value_fn(self.coordinator)
        self._attr_native_value = value

        if self.entity_description.attrs_fn is not None:
            try:
                self._attr_extra_state_attributes = self.entity_description.attrs_fn(
                    self.coordinator
                )
            except Exception as exc:  # pragma: no cover - defensive safeguard
                _LOGGER.warning(
                    "Unable to update attributes for '%s': %s",
                    self.entity_id,
                    exc,
                )


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
        self._attr_unique_id = (
            f"entsoe.{config_entry.entry_id}.{GENERATION_DEVICE_SUFFIX}.{description.key}"
        )
        self._attr_name = (
            f"{description.name} ({area_name})" if area_name else description.name
        )
        self._attr_icon = description.icon
        self.entity_id = f"{DOMAIN}.{description.key}"
        self._attr_device_info = DeviceInfo(
            entry_type=DeviceEntryType.SERVICE,
            identifiers={(DOMAIN, f"{config_entry.entry_id}_{GENERATION_DEVICE_SUFFIX}")},
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
        self._attr_unique_id = (
            f"entsoe.{config_entry.entry_id}.{LOAD_DEVICE_SUFFIX}.{description.key}"
        )
        self._attr_name = (
            f"{description.name} ({area_name})" if area_name else description.name
        )
        self._attr_icon = description.icon
        self.entity_id = f"{DOMAIN}.{description.key}"
        self._attr_device_info = DeviceInfo(
            entry_type=DeviceEntryType.SERVICE,
            identifiers={(DOMAIN, f"{config_entry.entry_id}_{LOAD_DEVICE_SUFFIX}")},
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
