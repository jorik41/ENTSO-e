"""Configuration flow for the ENTSO-e Data integration."""

from typing import Any

import voluptuous as vol
from homeassistant.config_entries import ConfigEntry, ConfigFlow, OptionsFlow
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers.selector import SelectOptionDict, SelectSelector, SelectSelectorConfig

from .const import (
    AREA_INFO,
    COMPONENT_TITLE,
    CONF_API_KEY,
    CONF_AREA,
    CONF_ENABLE_GENERATION,
    CONF_ENABLE_LOAD,
    DEFAULT_ENABLE_GENERATION,
    DEFAULT_ENABLE_LOAD,
    DOMAIN,
    UNIQUE_ID,
)


class EntsoeFlowHandler(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for the ENTSO-e Data integration."""

    VERSION = 1

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> "EntsoeOptionFlowHandler":
        """Return the options flow handler for this integration."""

        return EntsoeOptionFlowHandler(config_entry)

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle a flow initiated by the user."""

        errors: dict[str, str] = {}

        if user_input is not None:
            area: str = user_input[CONF_AREA]
            unique_id = f"{area}_{UNIQUE_ID}"
            try:
                await self.async_set_unique_id(unique_id)
                self._abort_if_unique_id_configured()
            except Exception:  # pragma: no cover - defensive safeguard
                errors["base"] = "already_configured"
            else:
                title = AREA_INFO.get(area, {}).get("name", area)
                options = {
                    CONF_API_KEY: user_input[CONF_API_KEY],
                    CONF_AREA: area,
                    CONF_ENABLE_GENERATION: user_input.get(
                        CONF_ENABLE_GENERATION, DEFAULT_ENABLE_GENERATION
                    ),
                    CONF_ENABLE_LOAD: user_input.get(
                        CONF_ENABLE_LOAD, DEFAULT_ENABLE_LOAD
                    ),
                }
                return self.async_create_entry(
                    title=title or COMPONENT_TITLE,
                    data={},
                    options=options,
                )

        return self.async_show_form(
            step_id="user",
            errors=errors,
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_API_KEY): vol.All(vol.Coerce(str)),
                    vol.Required(CONF_AREA): SelectSelector(
                        SelectSelectorConfig(
                            options=[
                                SelectOptionDict(value=country, label=info["name"])
                                for country, info in AREA_INFO.items()
                            ]
                        ),
                    ),
                    vol.Optional(
                        CONF_ENABLE_GENERATION, default=DEFAULT_ENABLE_GENERATION
                    ): bool,
                    vol.Optional(CONF_ENABLE_LOAD, default=DEFAULT_ENABLE_LOAD): bool,
                }
            ),
        )


class EntsoeOptionFlowHandler(OptionsFlow):
    """Handle options for the ENTSO-e Data integration."""

    def __init__(self, config_entry: ConfigEntry) -> None:
        """Initialize the options flow handler."""

        super().__init__(config_entry)

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the options flow."""

        errors: dict[str, str] = {}

        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        options = self.config_entry.options

        return self.async_show_form(
            step_id="init",
            errors=errors,
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_API_KEY, default=options.get(CONF_API_KEY, "")): vol.All(
                        vol.Coerce(str)
                    ),
                    vol.Required(CONF_AREA, default=options.get(CONF_AREA)): SelectSelector(
                        SelectSelectorConfig(
                            options=[
                                SelectOptionDict(value=country, label=info["name"])
                                for country, info in AREA_INFO.items()
                            ]
                        ),
                    ),
                    vol.Optional(
                        CONF_ENABLE_GENERATION,
                        default=options.get(
                            CONF_ENABLE_GENERATION, DEFAULT_ENABLE_GENERATION
                        ),
                    ): bool,
                    vol.Optional(
                        CONF_ENABLE_LOAD,
                        default=options.get(CONF_ENABLE_LOAD, DEFAULT_ENABLE_LOAD),
                    ): bool,
                }
            ),
        )
