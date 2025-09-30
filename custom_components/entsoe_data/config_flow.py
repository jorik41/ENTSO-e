"""Configuration flow for the ENTSO-e Data integration."""

from typing import Any

import voluptuous as vol
from homeassistant.config_entries import (
    SOURCE_RECONFIGURE,
    ConfigEntry,
    ConfigFlow,
    OptionsFlow,
)
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

        reconfigure_entry: ConfigEntry | None = None
        if self.context.get("source") == SOURCE_RECONFIGURE:
            reconfigure_entry = self.hass.config_entries.async_get_entry(
                self.context["entry_id"]
            )

        current_options = dict(reconfigure_entry.options) if reconfigure_entry else {}
        defaults = {
            CONF_API_KEY: current_options.get(CONF_API_KEY, ""),
            CONF_AREA: current_options.get(CONF_AREA),
            CONF_ENABLE_GENERATION: current_options.get(
                CONF_ENABLE_GENERATION, DEFAULT_ENABLE_GENERATION
            ),
            CONF_ENABLE_LOAD: current_options.get(CONF_ENABLE_LOAD, DEFAULT_ENABLE_LOAD),
        }

        if user_input is not None:
            area: str = user_input[CONF_AREA]
            unique_id = f"{area}_{UNIQUE_ID}"

            if reconfigure_entry is None:
                try:
                    await self.async_set_unique_id(unique_id)
                    self._abort_if_unique_id_configured()
                except Exception:  # pragma: no cover - defensive safeguard
                    errors["base"] = "already_configured"
            else:
                for existing_entry in self._async_current_entries():
                    if (
                        existing_entry.entry_id != reconfigure_entry.entry_id
                        and existing_entry.unique_id == unique_id
                    ):
                        errors["base"] = "already_configured"
                        break

            if not errors:
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

                if reconfigure_entry is not None:
                    self.hass.config_entries.async_update_entry(
                        reconfigure_entry,
                        title=title or COMPONENT_TITLE,
                        data={},
                        options=options,
                        unique_id=unique_id,
                    )
                    await self.hass.config_entries.async_reload(
                        reconfigure_entry.entry_id
                    )
                    return self.async_abort(reason="reconfigure_successful")

                return self.async_create_entry(
                    title=title or COMPONENT_TITLE,
                    data={},
                    options=options,
                )

        form_values = {**defaults, **(user_input or {})}

        area_field = (
            vol.Required(CONF_AREA, default=form_values[CONF_AREA])
            if form_values.get(CONF_AREA) is not None
            else vol.Required(CONF_AREA)
        )

        return self.async_show_form(
            step_id="user",
            errors=errors,
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_API_KEY, default=form_values[CONF_API_KEY]): vol.All(
                        vol.Coerce(str)
                    ),
                    area_field: SelectSelector(
                        SelectSelectorConfig(
                            options=[
                                SelectOptionDict(value=country, label=info["name"])
                                for country, info in AREA_INFO.items()
                            ]
                        ),
                    ),
                    vol.Optional(
                        CONF_ENABLE_GENERATION,
                        default=form_values[CONF_ENABLE_GENERATION],
                    ): bool,
                    vol.Optional(
                        CONF_ENABLE_LOAD, default=form_values[CONF_ENABLE_LOAD]
                    ): bool,
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
