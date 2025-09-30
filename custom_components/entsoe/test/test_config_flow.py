"""Tests for the ENTSO-e config flow template validation."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace

from custom_components.entsoe.config_flow import (
    EntsoeFlowHandler,
    EntsoeOptionFlowHandler,
)
from custom_components.entsoe.const import (
    AREA_INFO,
    CALCULATION_MODE,
    CONF_API_KEY,
    CONF_AREA,
    CONF_AGGREGATE_AREAS,
    CONF_AGGREGATE_EUROPE,
    CONF_CALCULATION_MODE,
    CONF_CURRENCY,
    CONF_ENERGY_SCALE,
    CONF_ENTITY_NAME,
    CONF_ENABLE_GENERATION,
    CONF_ENABLE_LOAD,
    CONF_MODIFYER,
    CONF_VAT_VALUE,
    DEFAULT_CURRENCY,
    DEFAULT_ENERGY_SCALE,
    DEFAULT_ENABLE_GENERATION,
    DEFAULT_ENABLE_LOAD,
    DEFAULT_MODIFYER,
)
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import TemplateError
from homeassistant.helpers.template import Template
from homeassistant.util import dt as dt_util


def _capture_render_call(monkeypatch, expected_now):
    captured = {}

    async def capture(self, **kwargs):
        captured.update(kwargs)
        return "0"

    monkeypatch.setattr(Template, "async_render", capture, raising=False)
    monkeypatch.setattr(dt_util, "now", lambda: expected_now)

    return captured


def test_async_step_extra_rejects_template_without_current_price(monkeypatch):
    """Templates raising during rendering should surface the invalid_template error."""

    flow = EntsoeFlowHandler()
    flow.hass = HomeAssistant()
    flow.area = "DE"
    flow.api_key = "token"
    flow.name = "Test"

    async def raise_template_error(self, *args, **kwargs):
        raise TemplateError("undefined variable")

    monkeypatch.setattr(Template, "async_render", raise_template_error, raising=False)

    user_input = {
        CONF_VAT_VALUE: AREA_INFO[flow.area]["VAT"],
        CONF_MODIFYER: "{{ price_without_current_price }}",
        CONF_CURRENCY: DEFAULT_CURRENCY,
        CONF_ENERGY_SCALE: DEFAULT_ENERGY_SCALE,
        CONF_ENTITY_NAME: flow.name,
        CONF_CALCULATION_MODE: CALCULATION_MODE["rotation"],
        CONF_ENABLE_GENERATION: DEFAULT_ENABLE_GENERATION,
        CONF_ENABLE_LOAD: DEFAULT_ENABLE_LOAD,
    }

    result = asyncio.run(flow.async_step_extra(user_input))

    assert result["type"] == "form"
    assert result["errors"]["base"] == "invalid_template"


def test_async_step_extra_valid_template_passes_context(monkeypatch):
    """Valid templates receive the shared context including current_price and now."""

    flow = EntsoeFlowHandler()
    flow.hass = HomeAssistant()
    flow.area = "DE"
    flow.api_key = "token"
    flow.name = "Test"

    fixed_now = datetime(2024, 1, 1, 10, 15, 30, tzinfo=timezone.utc)
    captured = _capture_render_call(monkeypatch, fixed_now)

    assert asyncio.run(flow._valid_template("{{ current_price }}"))
    assert captured["current_price"] == 0
    assert callable(captured["now"])
    assert (
        captured["now"](None)
        == fixed_now.replace(minute=0, second=0, microsecond=0)
    )


def test_options_flow_rejects_non_numeric_template(monkeypatch):
    """Non-numeric template output should surface the invalid_template error."""

    options_flow = EntsoeOptionFlowHandler()
    hass = HomeAssistant()
    options_flow.hass = hass

    config_entry = SimpleNamespace(
        options={
            CONF_API_KEY: "token",
            CONF_AREA: "DE",
            CONF_VAT_VALUE: 0,
            CONF_MODIFYER: DEFAULT_MODIFYER,
            CONF_ENTITY_NAME: "Test",
            CONF_CURRENCY: DEFAULT_CURRENCY,
            CONF_ENERGY_SCALE: DEFAULT_ENERGY_SCALE,
            CONF_CALCULATION_MODE: CALCULATION_MODE["publish"],
            CONF_ENABLE_GENERATION: DEFAULT_ENABLE_GENERATION,
            CONF_ENABLE_LOAD: DEFAULT_ENABLE_LOAD,
        }
    )

    hass.config_entries = SimpleNamespace(async_get_entry=lambda handler: config_entry)
    options_flow.handler = "test"

    async def render_non_numeric(self, *args, **kwargs):
        return "not-a-number"

    monkeypatch.setattr(Template, "async_render", render_non_numeric, raising=False)

    user_input = {
        CONF_API_KEY: "token",
        CONF_AREA: "DE",
        CONF_VAT_VALUE: 0,
        CONF_MODIFYER: "{{ 'invalid' }}",
        CONF_CURRENCY: DEFAULT_CURRENCY,
        CONF_ENERGY_SCALE: DEFAULT_ENERGY_SCALE,
        CONF_CALCULATION_MODE: CALCULATION_MODE["rotation"],
        CONF_ENABLE_GENERATION: DEFAULT_ENABLE_GENERATION,
        CONF_ENABLE_LOAD: DEFAULT_ENABLE_LOAD,
    }

    result = asyncio.run(options_flow.async_step_init(user_input))

    assert result["type"] == "form"
    assert result["errors"]["base"] == "invalid_template"


def test_options_flow_valid_template_passes_context(monkeypatch):
    """Valid option templates receive the shared context including current_price and now."""

    options_flow = EntsoeOptionFlowHandler()
    hass = HomeAssistant()
    options_flow.hass = hass

    fixed_now = datetime(2024, 1, 1, 22, 45, 0, tzinfo=timezone.utc)
    captured = _capture_render_call(monkeypatch, fixed_now)

    assert asyncio.run(options_flow._valid_template("{{ current_price }}"))
    assert captured["current_price"] == 0
    assert callable(captured["now"])
    assert (
        captured["now"](None)
        == fixed_now.replace(minute=0, second=0, microsecond=0)
    )


def test_options_flow_submits_prefilled_multi_line_template(monkeypatch):
    """Submitting options with a stored multi-line template should pass validation unchanged."""

    options_flow = EntsoeOptionFlowHandler()
    hass = HomeAssistant()
    options_flow.hass = hass

    multi_line_template = (
        "{% set adjustment = 0.5 %}\n{{ (current_price + adjustment)|round(2) }}"
    )

    config_entry = SimpleNamespace(
        options={
            CONF_API_KEY: "token",
            CONF_AREA: "DE",
            CONF_VAT_VALUE: 0,
            CONF_MODIFYER: multi_line_template,
            CONF_ENTITY_NAME: "Test",
            CONF_CURRENCY: DEFAULT_CURRENCY,
            CONF_ENERGY_SCALE: DEFAULT_ENERGY_SCALE,
            CONF_CALCULATION_MODE: CALCULATION_MODE["publish"],
            CONF_ENABLE_GENERATION: DEFAULT_ENABLE_GENERATION,
            CONF_ENABLE_LOAD: DEFAULT_ENABLE_LOAD,
            CONF_AGGREGATE_EUROPE: False,
            CONF_AGGREGATE_AREAS: [],
        }
    )

    hass.config_entries = SimpleNamespace(async_get_entry=lambda handler: config_entry)
    options_flow.handler = "test"

    captured_templates: list[str] = []

    async def capture(self, *args, **kwargs):
        captured_templates.append(self.template)
        return "1.23"

    monkeypatch.setattr(Template, "async_render", capture, raising=False)

    user_input = {
        CONF_API_KEY: "token",
        CONF_AREA: "DE",
        CONF_VAT_VALUE: 0,
        CONF_MODIFYER: multi_line_template,
        CONF_CURRENCY: DEFAULT_CURRENCY,
        CONF_ENERGY_SCALE: DEFAULT_ENERGY_SCALE,
        CONF_CALCULATION_MODE: CALCULATION_MODE["publish"],
        CONF_ENABLE_GENERATION: DEFAULT_ENABLE_GENERATION,
        CONF_ENABLE_LOAD: DEFAULT_ENABLE_LOAD,
        CONF_AGGREGATE_EUROPE: False,
        CONF_AGGREGATE_AREAS: [],
    }

    result = asyncio.run(options_flow.async_step_init(user_input))

    assert result["type"] == "create_entry"
    assert result["data"][CONF_MODIFYER] == multi_line_template
    assert captured_templates == [multi_line_template]
