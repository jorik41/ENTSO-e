"""Minimal Home Assistant stubs for unit tests.

This module installs lightweight stand-ins for the Home Assistant and
Jinja2 symbols that the ENTSO-e integration imports.  The stubs only
implement the behaviour that the unit tests rely on and are registered
inside :mod:`sys.modules` so the production code can import them as if
Home Assistant was installed.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from types import ModuleType
from typing import Any, Awaitable, Callable, Dict, Generic, TypeVar
import sys

T = TypeVar("T")


def _ensure_module(name: str) -> ModuleType:
    """Ensure that a module with ``name`` exists in :mod:`sys.modules`."""

    module = sys.modules.get(name)
    if module is None:
        module = ModuleType(name)
        sys.modules[name] = module
    return module


def install_hass_stubs() -> None:
    """Install Home Assistant and Jinja2 stubs used during testing."""

    if "homeassistant" in sys.modules:
        return

    # Root package
    ha = _ensure_module("homeassistant")
    ha.__path__ = []  # mark as package

    # ------------------------------------------------------------------
    # Components > sensor
    components = _ensure_module("homeassistant.components")
    components.__path__ = []
    sensor = _ensure_module("homeassistant.components.sensor")

    class SensorDeviceClass:
        TIMESTAMP = "timestamp"

    class SensorStateClass:
        MEASUREMENT = "measurement"

    @dataclass
    class SensorEntityDescription:
        key: str
        name: str
        native_unit_of_measurement: str | None = None
        state_class: str | None = None
        icon: str | None = None
        suggested_display_precision: int | None = None
        device_class: str | None = None

    class RestoreSensor:
        def __init__(self) -> None:
            self._attr_native_value: Any = None
            self._attr_extra_state_attributes: Dict[str, Any] = {}
            self._attr_icon: str | None = None
            self._attr_name: str | None = None
            self._attr_unique_id: str | None = None
            self._attr_device_info: Any = None
            self._attr_suggested_display_precision: int | None = None
            self.entity_id: str | None = None
            self.hass: Any = None

        async def async_update(self) -> None:  # pragma: no cover - stub
            return None

        def async_schedule_update_ha_state(self, force_refresh: bool = False):
            return None

        @property
        def native_value(self):
            return self._attr_native_value

        @property
        def extra_state_attributes(self):
            return getattr(self, "_attr_extra_state_attributes", {})

    sensor.SensorDeviceClass = SensorDeviceClass
    sensor.SensorStateClass = SensorStateClass
    sensor.SensorEntityDescription = SensorEntityDescription
    sensor.RestoreSensor = RestoreSensor

    # ------------------------------------------------------------------
    # Config entries
    config_entries = _ensure_module("homeassistant.config_entries")

    class ConfigEntry:  # pragma: no cover - simple container
        entry_id: str
        data: dict[str, Any]
        options: dict[str, Any]

    config_entries.ConfigEntry = ConfigEntry
    config_entries.SOURCE_RECONFIGURE = "reconfigure"

    # ------------------------------------------------------------------
    # Constants
    const = _ensure_module("homeassistant.const")
    const.PERCENTAGE = "%"
    const.CURRENCY_EURO = "EUR"

    class Platform(str, Enum):
        SENSOR = "sensor"

    const.Platform = Platform

    exceptions_mod = _ensure_module("homeassistant.exceptions")

    class ServiceValidationError(Exception):  # pragma: no cover - stub
        def __init__(
            self,
            *args,
            translation_domain: str | None = None,
            translation_key: str | None = None,
            translation_placeholders: Dict[str, Any] | None = None,
            **kwargs,
        ) -> None:
            super().__init__(*args)
            self.translation_domain = translation_domain
            self.translation_key = translation_key
            self.translation_placeholders = translation_placeholders or {}

    exceptions_mod.ServiceValidationError = ServiceValidationError

    config_entries.ConfigEntryState = Enum(  # type: ignore[attr-defined]
        "ConfigEntryState",
        {"LOADED": "loaded"},
    )

    # ------------------------------------------------------------------
    # Core helpers
    core = _ensure_module("homeassistant.core")

    class HassJob:  # pragma: no cover - minimal wrapper
        def __init__(self, action: Callable) -> None:
            self.action = action

    @dataclass
    class ServiceCall:  # pragma: no cover - unused stub
        data: dict[str, Any]

    class ServiceResponse(dict):  # pragma: no cover - unused stub
        pass

    class SupportsResponse(Enum):  # pragma: no cover - stub enum
        ONLY = "only"

    def callback(func: Callable) -> Callable:  # pragma: no cover - stub decorator
        return func

    class HomeAssistant:  # pragma: no cover - simple placeholder
        def __init__(self) -> None:
            self.data: dict[str, Any] = {}
            self.loop = None

        async def async_add_executor_job(self, func: Callable, *args, **kwargs):
            return func(*args, **kwargs)

    core.HassJob = HassJob
    core.ServiceCall = ServiceCall
    core.ServiceResponse = ServiceResponse
    core.SupportsResponse = SupportsResponse
    core.callback = callback
    core.HomeAssistant = HomeAssistant

    # ------------------------------------------------------------------
    # Helpers package
    helpers = _ensure_module("homeassistant.helpers")
    helpers.__path__ = []

    template_mod = _ensure_module("homeassistant.helpers.template")

    class Template:
        def __init__(self, template: str, hass: Any | None = None) -> None:
            self.template = template
            self.hass = hass

        def async_render(self, *args, **kwargs):  # pragma: no cover - stub
            return kwargs.get("current_price", self.template)

    template_mod.Template = Template

    config_validation = _ensure_module("homeassistant.helpers.config_validation")

    def template(value):  # pragma: no cover - stub validator
        if isinstance(value, Template):
            return value
        return Template(value)

    config_validation.template = template

    device_registry = _ensure_module("homeassistant.helpers.device_registry")

    class DeviceEntryType:
        SERVICE = "service"

    class DeviceInfo:
        def __init__(self, **kwargs) -> None:
            self.__dict__.update(kwargs)

    device_registry.DeviceEntryType = DeviceEntryType
    device_registry.DeviceInfo = DeviceInfo

    entity_platform = _ensure_module("homeassistant.helpers.entity_platform")
    entity_platform.AddEntitiesCallback = Callable

    typing_mod = _ensure_module("homeassistant.helpers.typing")
    typing_mod.StateType = Any
    typing_mod.ConfigType = Dict[str, Any]

    selector = _ensure_module("homeassistant.helpers.selector")

    class ConfigEntrySelector:  # pragma: no cover - stub selector
        def __init__(self, config: Dict[str, Any] | None = None) -> None:
            self.config = config or {}

    selector.ConfigEntrySelector = ConfigEntrySelector

    event = _ensure_module("homeassistant.helpers.event")

    async def async_track_point_in_utc_time(  # pragma: no cover - stub
        hass, job: Callable[..., Awaitable], when
    ):
        return lambda: None

    event.async_track_point_in_utc_time = async_track_point_in_utc_time

    update_coordinator = _ensure_module("homeassistant.helpers.update_coordinator")

    class UpdateFailed(Exception):
        pass

    class DataUpdateCoordinator(Generic[T]):
        def __init__(self, hass, logger, name: str, update_interval) -> None:
            self.hass = hass
            self.logger = logger
            self.name = name
            self.update_interval = update_interval
            self.data: Any = None

        async def async_config_entry_first_refresh(self):  # pragma: no cover - stub
            self.data = await self._async_update_data()

    class CoordinatorEntity(Generic[T]):
        def __init__(self, coordinator: DataUpdateCoordinator) -> None:
            self.coordinator = coordinator
            self.hass = getattr(coordinator, "hass", None)

        @property
        def available(self) -> bool:  # pragma: no cover - stub
            return True

    update_coordinator.UpdateFailed = UpdateFailed
    update_coordinator.DataUpdateCoordinator = DataUpdateCoordinator
    update_coordinator.CoordinatorEntity = CoordinatorEntity

    # ------------------------------------------------------------------
    # Utilities
    util = _ensure_module("homeassistant.util")

    def utcnow():
        return datetime.now(timezone.utc)

    util.utcnow = utcnow

    dt_module = _ensure_module("homeassistant.util.dt")

    def now():
        return datetime.now().astimezone()

    dt_module.now = now

    # ------------------------------------------------------------------
    # Voluptuous stub used in service schema
    voluptuous = _ensure_module("voluptuous")

    class Schema:
        def __init__(self, schema: Dict[str, Any]) -> None:
            self.schema = schema

        def __call__(self, value: Dict[str, Any]) -> Dict[str, Any]:  # pragma: no cover - stub
            return value

    def Required(key):  # pragma: no cover - stub
        return key

    def Optional(key):  # pragma: no cover - stub
        return key

    voluptuous.Schema = Schema
    voluptuous.Required = Required
    voluptuous.Optional = Optional

    # ------------------------------------------------------------------
    # Jinja2 stub
    jinja2 = _ensure_module("jinja2")

    def pass_context(func: Callable) -> Callable:  # pragma: no cover - stub
        return func

    jinja2.pass_context = pass_context

    # ------------------------------------------------------------------
    # Requests stub (provides HTTPError used in coordinators)
    requests = _ensure_module("requests")
    exceptions = _ensure_module("requests.exceptions")

    class _Response:
        def __init__(self, status_code: int = 0) -> None:
            self.status_code = status_code

    class HTTPError(Exception):
        def __init__(self, response: Any | None = None) -> None:
            super().__init__("HTTPError")
            self.response = response or _Response()

    class RequestException(Exception):
        """Base requests exception used by the integration."""

    exceptions.HTTPError = HTTPError
    exceptions.RequestException = RequestException
    requests.exceptions = exceptions

    class Session:  # pragma: no cover - stub
        def get(self, *args: Any, **kwargs: Any) -> Any:
            raise NotImplementedError

    requests.Session = Session

    # ------------------------------------------------------------------
    # pytz stub used by the API client
    pytz = _ensure_module("pytz")
    pytz.UTC = timezone.utc


__all__ = ["install_hass_stubs"]
