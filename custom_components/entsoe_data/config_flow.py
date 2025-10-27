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
    CONF_ENABLE_EUROPE_WIND_SOLAR_FORECAST,
    CONF_ENABLE_GENERATION,
    CONF_ENABLE_GENERATION_FORECAST,
    CONF_ENABLE_GENERATION_TOTAL_EUROPE,
    CONF_ENABLE_WIND_SOLAR_FORECAST,
    DEFAULT_ENABLE_EUROPE_GENERATION,
    DEFAULT_ENABLE_EUROPE_WIND_SOLAR_FORECAST,
    DEFAULT_ENABLE_GENERATION,
    DEFAULT_ENABLE_GENERATION_FORECAST,
    DEFAULT_ENABLE_WIND_SOLAR_FORECAST,
    DOMAIN,
    LOAD_FORECAST_HORIZONS,
    LOAD_FORECAST_OPTION_KEYS,
    LOAD_FORECAST_EUROPE_OPTION_KEYS,
    UNIQUE_ID,
)


SENSOR_FLAG_KEYS: tuple[str, ...] = (
    (CONF_ENABLE_GENERATION,)
    + LOAD_FORECAST_OPTION_KEYS
    + (
        CONF_ENABLE_GENERATION_FORECAST,
        CONF_ENABLE_WIND_SOLAR_FORECAST,
        CONF_ENABLE_EUROPE_GENERATION,
    )
    + LOAD_FORECAST_EUROPE_OPTION_KEYS
    + (CONF_ENABLE_EUROPE_WIND_SOLAR_FORECAST,)
)


def _build_defaults(options: dict[str, Any] | None) -> dict[str, Any]:
    """Build default values for the configuration forms."""

    options = options or {}

    defaults = {
        CONF_API_KEY: options.get(CONF_API_KEY, ""),
        CONF_AREA: options.get(CONF_AREA),
        CONF_ENABLE_GENERATION: options.get(
            CONF_ENABLE_GENERATION, DEFAULT_ENABLE_GENERATION
        ),
        CONF_ENABLE_GENERATION_FORECAST: options.get(
            CONF_ENABLE_GENERATION_FORECAST, DEFAULT_ENABLE_GENERATION_FORECAST
        ),
        CONF_ENABLE_WIND_SOLAR_FORECAST: options.get(
            CONF_ENABLE_WIND_SOLAR_FORECAST, DEFAULT_ENABLE_WIND_SOLAR_FORECAST
        ),
        CONF_ENABLE_EUROPE_GENERATION: options.get(
            CONF_ENABLE_EUROPE_GENERATION,
            options.get(
                CONF_ENABLE_GENERATION_TOTAL_EUROPE,
                DEFAULT_ENABLE_EUROPE_GENERATION,
            ),
        ),
        CONF_ENABLE_EUROPE_WIND_SOLAR_FORECAST: options.get(
            CONF_ENABLE_EUROPE_WIND_SOLAR_FORECAST,
            DEFAULT_ENABLE_EUROPE_WIND_SOLAR_FORECAST,
        ),
    }

    for horizon in LOAD_FORECAST_HORIZONS:
        defaults[horizon.option_key] = options.get(
            horizon.option_key, horizon.default_enabled
        )

        europe_default = horizon.europe_default_enabled
        for legacy_key in horizon.legacy_europe_option_keys:
            if legacy_key in options:
                europe_default = options[legacy_key]
                break

        defaults[horizon.europe_option_key] = options.get(
            horizon.europe_option_key,
            europe_default,
        )

    return defaults


def _extract_sensor_values(
    data: dict[str, Any], defaults: dict[str, Any]
) -> dict[str, bool]:
    """Extract sensor enable flags from the submitted form data."""

    return {
        option_key: bool(data.get(option_key, defaults[option_key]))
        for option_key in SENSOR_FLAG_KEYS
    }


def _build_form_schema(
    defaults: dict[str, Any], user_input: dict[str, Any] | None
) -> vol.Schema:
    """Construct the schema for the configuration and options forms."""

    api_key_default = (user_input or {}).get(CONF_API_KEY, defaults[CONF_API_KEY])
    area_default = (user_input or {}).get(CONF_AREA, defaults[CONF_AREA])

    schema: dict[Any, Any] = {
        vol.Required(CONF_API_KEY, default=api_key_default): vol.All(vol.Coerce(str)),
    }

    area_field = vol.Required(CONF_AREA)
    if area_default is not None:
        area_field = vol.Required(CONF_AREA, default=area_default)

    schema[area_field] = SelectSelector(
        SelectSelectorConfig(
            options=[
                SelectOptionDict(value=country, label=info["name"])
                for country, info in AREA_INFO.items()
            ]
        ),
    )

    for option_key in SENSOR_FLAG_KEYS:
        option_default = (user_input or {}).get(option_key, defaults[option_key])
        schema[vol.Optional(option_key, default=option_default)] = bool

    return vol.Schema(schema)


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
                    CONF_API_KEY: user_input[CONF_API_KEY].strip(),
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

        self._config_entry = config_entry

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the options flow."""

        errors: dict[str, str] = {}

        defaults = _build_defaults(self._config_entry.options)

        if user_input is not None:
            sensor_values = _extract_sensor_values(user_input, defaults)
            data = {
                CONF_API_KEY: user_input[CONF_API_KEY].strip(),
                CONF_AREA: user_input[CONF_AREA],
                **sensor_values,
            }
            return self.async_create_entry(title="", data=data)

        return self.async_show_form(
            step_id="init",
            errors=errors,
            data_schema=_build_form_schema(defaults, user_input),
        )
