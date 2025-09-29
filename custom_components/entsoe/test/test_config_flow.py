from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, Mock, patch

import sys
import types

import pytest


if "hass_nabucasa" not in sys.modules:
    hass_nabucasa = types.ModuleType("hass_nabucasa")
    remote_module = types.ModuleType("hass_nabucasa.remote")
    acme_module = types.ModuleType("hass_nabucasa.acme")

    class _RemoteUI:  # pragma: no cover - simple stub
        pass

    remote_module.RemoteUI = _RemoteUI
    acme_module.AcmeHandler = type("AcmeHandler", (), {})
    acme_module.AcmeClientError = type("AcmeClientError", (Exception,), {})
    hass_nabucasa.remote = remote_module
    hass_nabucasa.acme = acme_module
    sys.modules["hass_nabucasa"] = hass_nabucasa
    sys.modules["hass_nabucasa.remote"] = remote_module
    sys.modules["hass_nabucasa.acme"] = acme_module

from homeassistant.data_entry_flow import FlowResultType
from homeassistant.exceptions import TemplateError

from custom_components.entsoe.config_flow import EntsoeFlowHandler
from custom_components.entsoe.const import (
    CALCULATION_MODE,
    CONF_CALCULATION_MODE,
    CONF_CURRENCY,
    CONF_ENTITY_NAME,
    CONF_ENERGY_SCALE,
    CONF_MODIFYER,
    CONF_VAT_VALUE,
    DEFAULT_CURRENCY,
    DEFAULT_ENERGY_SCALE,
)


@pytest.fixture
def flow_handler():
    flow = EntsoeFlowHandler()
    flow.hass = MagicMock()
    flow.area = "DE"
    flow.api_key = "test-key"
    flow.name = "Test"
    flow.async_set_unique_id = AsyncMock()
    flow._abort_if_unique_id_configured = Mock()
    return flow


async def _call_extra_step(flow: EntsoeFlowHandler, modifyer: str):
    return await flow.async_step_extra(
        {
            CONF_VAT_VALUE: 0,
            CONF_MODIFYER: modifyer,
            CONF_CURRENCY: DEFAULT_CURRENCY,
            CONF_ENERGY_SCALE: DEFAULT_ENERGY_SCALE,
            CONF_CALCULATION_MODE: CALCULATION_MODE["publish"],
            CONF_ENTITY_NAME: flow.name,
        }
    )


def test_async_step_extra_missing_current_price(flow_handler: EntsoeFlowHandler):
    async def run_test():
        with patch("custom_components.entsoe.config_flow.Template") as mock_template:
            template_instance = mock_template.return_value
            template_instance.async_render = AsyncMock(side_effect=TemplateError("undefined"))

            result = await _call_extra_step(flow_handler, "{{ price }}")

        assert result["type"] == FlowResultType.FORM
        assert result["errors"]["base"] == "invalid_template"

    import asyncio

    asyncio.run(run_test())


def test_async_step_extra_non_numeric_render(flow_handler: EntsoeFlowHandler):
    async def run_test():
        with patch("custom_components.entsoe.config_flow.Template") as mock_template:
            template_instance = mock_template.return_value
            template_instance.async_render = AsyncMock(return_value="abc")

            result = await _call_extra_step(flow_handler, "{{ 'abc' }}")

        assert result["type"] == FlowResultType.FORM
        assert result["errors"]["base"] == "invalid_template"

    import asyncio

    asyncio.run(run_test())
