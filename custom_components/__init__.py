"""Custom components package helper for tests."""

from __future__ import annotations

import importlib.machinery
import sys
import types


def _ensure_module(name: str, *, is_package: bool = False) -> types.ModuleType:
    module = types.ModuleType(name)
    module.__spec__ = importlib.machinery.ModuleSpec(
        name, loader=None, is_package=is_package
    )
    if is_package:
        module.__path__ = []
    sys.modules[name] = module
    return module


if "homeassistant" not in sys.modules:  # pragma: no cover - test support only
    ha_module = _ensure_module("homeassistant", is_package=True)

    ha_const = _ensure_module("homeassistant.const")
    ha_const.CURRENCY_EURO = "EUR"
    ha_const.Platform = type("Platform", (), {"SENSOR": "sensor"})

    ha_exceptions = _ensure_module("homeassistant.exceptions")
    ha_exceptions.TemplateError = type("TemplateError", (Exception,), {})
    ha_exceptions.ServiceValidationError = type(
        "ServiceValidationError", (Exception,), {}
    )

    ha_core = _ensure_module("homeassistant.core")

    def callback(func):
        return func

    ha_core.callback = callback

    class _HomeAssistant:  # pragma: no cover - stub
        def __init__(self):
            self.config_entries = types.SimpleNamespace(
                async_get_entry=lambda *_args, **_kwargs: None,
                async_forward_entry_setups=lambda *_args, **_kwargs: None,
                async_unload_platforms=lambda *_args, **_kwargs: True,
                async_reload=lambda *_args, **_kwargs: None,
            )
            self.services = types.SimpleNamespace(
                async_register=lambda *_args, **_kwargs: None
            )
            self.data = {}

    ha_core.HomeAssistant = _HomeAssistant
    ha_core.ServiceCall = type("ServiceCall", (), {"data": {}})
    ha_core.ServiceResponse = dict
    ha_core.SupportsResponse = type("SupportsResponse", (), {"ONLY": "only"})

    ha_config_entries = _ensure_module("homeassistant.config_entries")

    class _BaseFlow:
        async def async_set_unique_id(self, _):
            return None

        def _abort_if_unique_id_configured(self):
            return None

    class ConfigEntry:  # pragma: no cover - stub
        pass

    class ConfigFlow(_BaseFlow):
        def __init_subclass__(cls, *, domain: str | None = None, **kwargs):
            super().__init_subclass__(**kwargs)
            cls.domain = domain

        def async_show_form(self, *, step_id: str, errors: dict | None = None, data_schema=None):
            return {"type": FlowResultType.FORM, "step_id": step_id, "errors": errors or {}, "data_schema": data_schema}

        async def async_create_entry(self, *, title: str, data: dict, options: dict):
            return {"type": "create_entry", "title": title, "data": data, "options": options}

    class OptionsFlow(_BaseFlow):
        pass

    ha_config_entries.ConfigEntry = ConfigEntry
    ha_config_entries.ConfigFlow = ConfigFlow
    ha_config_entries.OptionsFlow = OptionsFlow
    ha_config_entries.ConfigEntryState = type(
        "ConfigEntryState",
        (),
        {"LOADED": "loaded", "NOT_LOADED": "not_loaded"},
    )

    ha_data_entry_flow = _ensure_module("homeassistant.data_entry_flow")

    class FlowResultType(str):
        FORM = "form"

    ha_data_entry_flow.FlowResultType = FlowResultType
    ha_data_entry_flow.FlowResult = dict

    ha_helpers = _ensure_module("homeassistant.helpers", is_package=True)

    ha_helpers_typing = _ensure_module("homeassistant.helpers.typing")
    ha_helpers_typing.ConfigType = dict

    ha_cv = _ensure_module("homeassistant.helpers.config_validation")
    ha_cv.boolean = lambda value: bool(value)
    ha_cv.multi_select = lambda value: value
    ha_cv.string = lambda value: str(value)

    ha_update_coordinator = _ensure_module("homeassistant.helpers.update_coordinator")

    class DataUpdateCoordinator:  # pragma: no cover - stub
        async def async_config_entry_first_refresh(self):
            return None

    class UpdateFailed(Exception):  # pragma: no cover - stub
        pass

    ha_update_coordinator.DataUpdateCoordinator = DataUpdateCoordinator
    ha_update_coordinator.UpdateFailed = UpdateFailed

    ha_util = _ensure_module("homeassistant.util", is_package=True)
    ha_util_dt = _ensure_module("homeassistant.util.dt")
    ha_util_dt.utcnow = staticmethod(lambda: None)

    ha_selector = _ensure_module("homeassistant.helpers.selector")

    class _Selector:
        def __init__(self, *_args, **_kwargs):
            pass

    class SelectOptionDict(dict):
        pass

    class SelectSelectorConfig(dict):
        pass

    class SelectSelector(_Selector):
        def __voluptuous_compile__(self, _schema):
            return lambda _path, value: value

    class TemplateSelectorConfig(dict):
        pass

    class TemplateSelector(_Selector):
        def __voluptuous_compile__(self, _schema):
            return lambda _path, value: value

    ha_selector.SelectOptionDict = SelectOptionDict
    ha_selector.SelectSelector = SelectSelector
    ha_selector.SelectSelectorConfig = SelectSelectorConfig
    def ConfigEntrySelector(*_args, **_kwargs):
        return str

    ha_selector.ConfigEntrySelector = ConfigEntrySelector
    ha_selector.TemplateSelector = TemplateSelector
    ha_selector.TemplateSelectorConfig = TemplateSelectorConfig

    ha_template = _ensure_module("homeassistant.helpers.template")

    class Template:  # pragma: no cover - stub
        async def async_render(self, **_kwargs):
            raise NotImplementedError

    ha_template.Template = Template

if "josepy" not in sys.modules:
    josepy = _ensure_module("josepy")
    josepy.ComparableX509 = type("ComparableX509", (), {})
