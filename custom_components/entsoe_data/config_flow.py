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
    CONF_ENABLE_EUROPE_GENERATION,
    CONF_ENABLE_EUROPE_LOAD,
    CONF_ENABLE_GENERATION,
    CONF_ENABLE_GENERATION_TOTAL_EUROPE,
    CONF_ENABLE_LOAD,
    CONF_ENABLE_LOAD_TOTAL_EUROPE,
    DEFAULT_ENABLE_EUROPE_GENERATION,
    DEFAULT_ENABLE_EUROPE_LOAD,
    DEFAULT_ENABLE_GENERATION,
    DEFAULT_ENABLE_LOAD,
    DOMAIN,
    UNIQUE_ID,
)


SENSOR_GROUP_LOCAL = "local_sensors"
SENSOR_GROUP_EUROPE = "europe_sensors"

SENSOR_FLAG_GROUPS: tuple[tuple[str, str], ...] = (
    (CONF_ENABLE_GENERATION, SENSOR_GROUP_LOCAL),
    (CONF_ENABLE_LOAD, SENSOR_GROUP_LOCAL),
    (CONF_ENABLE_EUROPE_GENERATION, SENSOR_GROUP_EUROPE),
    (CONF_ENABLE_EUROPE_LOAD, SENSOR_GROUP_EUROPE),
)


def _build_defaults(options: dict[str, Any] | None) -> dict[str, Any]:
    """Build default values for the configuration forms."""

    options = options or {}

    return {
        CONF_API_KEY: options.get(CONF_API_KEY, ""),
        CONF_AREA: options.get(CONF_AREA),
        CONF_ENABLE_GENERATION: options.get(
            CONF_ENABLE_GENERATION, DEFAULT_ENABLE_GENERATION
        ),
        CONF_ENABLE_LOAD: options.get(CONF_ENABLE_LOAD, DEFAULT_ENABLE_LOAD),
        CONF_ENABLE_EUROPE_GENERATION: options.get(
            CONF_ENABLE_EUROPE_GENERATION,
            options.get(
                CONF_ENABLE_GENERATION_TOTAL_EUROPE,
                DEFAULT_ENABLE_EUROPE_GENERATION,
            ),
        ),
        CONF_ENABLE_EUROPE_LOAD: options.get(
            CONF_ENABLE_EUROPE_LOAD,
            options.get(
                CONF_ENABLE_LOAD_TOTAL_EUROPE, DEFAULT_ENABLE_EUROPE_LOAD
            ),
        ),
    }


def _resolve_flag(
    data: dict[str, Any], option_key: str, group: str, fallback: bool
) -> bool:
    """Resolve a boolean flag from grouped user input."""

    group_data = data.get(group)
    if isinstance(group_data, dict) and option_key in group_data:
        return bool(group_data[option_key])

    if option_key in data:
        return bool(data[option_key])

    return fallback


def _extract_sensor_values(
    data: dict[str, Any], defaults: dict[str, Any]
) -> dict[str, bool]:
    """Extract sensor enable flags from the submitted form data."""

    return {
        option_key: _resolve_flag(data, option_key, group, defaults[option_key])
        for option_key, group in SENSOR_FLAG_GROUPS
    }


def _group_defaults(
    user_input: dict[str, Any] | None, defaults: dict[str, Any], group: str
) -> dict[str, bool]:
    """Generate default values for a sensor group."""

    values: dict[str, bool] = {}
    nested: dict[str, Any] | None = None

    if user_input is not None and isinstance(user_input.get(group), dict):
        nested = user_input[group]

    for option_key, option_group in SENSOR_FLAG_GROUPS:
        if option_group != group:
            continue

        if nested and option_key in nested:
            values[option_key] = bool(nested[option_key])
            continue

        if user_input and option_key in user_input:
            values[option_key] = bool(user_input[option_key])
            continue

        values[option_key] = defaults[option_key]

    return values


def _build_form_schema(
    defaults: dict[str, Any], user_input: dict[str, Any] | None
) -> vol.Schema:
    """Construct the schema for the configuration and options forms."""

    api_key_default = (user_input or {}).get(CONF_API_KEY, defaults[CONF_API_KEY])
    area_default = (user_input or {}).get(CONF_AREA, defaults[CONF_AREA])

    local_defaults = _group_defaults(user_input, defaults, SENSOR_GROUP_LOCAL)
    europe_defaults = _group_defaults(user_input, defaults, SENSOR_GROUP_EUROPE)

    area_field = (
        vol.Required(CONF_AREA, default=area_default)
        if area_default is not None
        else vol.Required(CONF_AREA)
    )

    return vol.Schema(
        {
            vol.Required(CONF_API_KEY, default=api_key_default): vol.All(
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
                SENSOR_GROUP_LOCAL,
                default=local_defaults,
            ): vol.Schema(
                {
                    vol.Optional(
                        CONF_ENABLE_GENERATION,
                        default=local_defaults[CONF_ENABLE_GENERATION],
                    ): bool,
                    vol.Optional(
                        CONF_ENABLE_LOAD, default=local_defaults[CONF_ENABLE_LOAD]
                    ): bool,
                }
            ),
            vol.Optional(
                SENSOR_GROUP_EUROPE,
                default=europe_defaults,
            ): vol.Schema(
                {
                    vol.Optional(
                        CONF_ENABLE_EUROPE_GENERATION,
                        default=europe_defaults[CONF_ENABLE_EUROPE_GENERATION],
                    ): bool,
                    vol.Optional(
                        CONF_ENABLE_EUROPE_LOAD,
                        default=europe_defaults[CONF_ENABLE_EUROPE_LOAD],
                    ): bool,
                }
            ),
        }
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
        defaults = _build_defaults(current_options)

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
                sensor_values = _extract_sensor_values(user_input, defaults)
                options = {
                    CONF_API_KEY: user_input[CONF_API_KEY],
                    CONF_AREA: area,
                    **sensor_values,
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

        return self.async_show_form(
            step_id="user",
            errors=errors,
            data_schema=_build_form_schema(defaults, user_input),
        )


class EntsoeOptionFlowHandler(OptionsFlow):
    """Handle options for the ENTSO-e Data integration."""

    def __init__(self, config_entry: ConfigEntry) -> None:
        """Initialize the options flow handler."""

        self.config_entry = config_entry

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the options flow."""

        errors: dict[str, str] = {}

        defaults = _build_defaults(self.config_entry.options)

        if user_input is not None:
            sensor_values = _extract_sensor_values(user_input, defaults)
            data = {
                CONF_API_KEY: user_input[CONF_API_KEY],
                CONF_AREA: user_input[CONF_AREA],
                **sensor_values,
            }
            return self.async_create_entry(title="", data=data)

        return self.async_show_form(
            step_id="init",
            errors=errors,
            data_schema=_build_form_schema(defaults, user_input),
        )
