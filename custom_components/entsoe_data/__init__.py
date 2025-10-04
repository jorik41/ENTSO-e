"""The ENTSO-e data component."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

try:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.const import Platform
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.typing import ConfigType
except ModuleNotFoundError:  # pragma: no cover - used only in unit tests
    from .test.hass_stubs import install_hass_stubs

    install_hass_stubs()

    from homeassistant.config_entries import ConfigEntry
    from homeassistant.const import Platform
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.typing import ConfigType

from .const import (
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
    TOTAL_EUROPE_AREA,
)
from .coordinator import (
    EntsoeGenerationCoordinator,
    EntsoeGenerationForecastCoordinator,
    EntsoeLoadCoordinator,
    EntsoeWindSolarForecastCoordinator,
)

_LOGGER = logging.getLogger(__name__)
PLATFORMS = [Platform.SENSOR]


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up the ENTSO-e integration."""

    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up the ENTSO-e data component from a config entry."""

    api_key = entry.options[CONF_API_KEY]
    area = entry.options[CONF_AREA]
    enable_generation = entry.options.get(
        CONF_ENABLE_GENERATION, DEFAULT_ENABLE_GENERATION
    )
    enable_europe_generation = entry.options.get(
        CONF_ENABLE_EUROPE_GENERATION,
        entry.options.get(
            CONF_ENABLE_GENERATION_TOTAL_EUROPE, DEFAULT_ENABLE_EUROPE_GENERATION
        ),
    )
    enable_generation_forecast = entry.options.get(
        CONF_ENABLE_GENERATION_FORECAST, DEFAULT_ENABLE_GENERATION_FORECAST
    )
    enable_wind_solar_forecast = entry.options.get(
        CONF_ENABLE_WIND_SOLAR_FORECAST, DEFAULT_ENABLE_WIND_SOLAR_FORECAST
    )
    enable_europe_wind_solar_forecast = entry.options.get(
        CONF_ENABLE_EUROPE_WIND_SOLAR_FORECAST,
        DEFAULT_ENABLE_EUROPE_WIND_SOLAR_FORECAST,
    )

    data: dict[str, Any] = {}

    refresh_tasks: list[Any] = []

    if enable_generation:
        generation_coordinator = EntsoeGenerationCoordinator(
            hass,
            api_key=api_key,
            area=area,
        )
        data["generation"] = generation_coordinator
        refresh_tasks.append(generation_coordinator.async_config_entry_first_refresh())

    if enable_generation_forecast:
        generation_forecast_coordinator = EntsoeGenerationForecastCoordinator(
            hass,
            api_key=api_key,
            area=area,
        )
        data["generation_forecast"] = generation_forecast_coordinator
        refresh_tasks.append(
            generation_forecast_coordinator.async_config_entry_first_refresh()
        )

    if enable_wind_solar_forecast:
        wind_solar_forecast_coordinator = EntsoeWindSolarForecastCoordinator(
            hass,
            api_key=api_key,
            area=area,
        )
        data["wind_solar_forecast"] = wind_solar_forecast_coordinator
        refresh_tasks.append(
            wind_solar_forecast_coordinator.async_config_entry_first_refresh()
        )

    if enable_europe_wind_solar_forecast:
        wind_solar_forecast_europe_coordinator = (
            EntsoeWindSolarForecastCoordinator(
                hass,
                api_key=api_key,
                area=TOTAL_EUROPE_AREA,
            )
        )
        data["wind_solar_forecast_europe"] = (
            wind_solar_forecast_europe_coordinator
        )
        refresh_tasks.append(
            wind_solar_forecast_europe_coordinator.async_config_entry_first_refresh()
        )

    if enable_europe_generation:
        generation_europe_coordinator = EntsoeGenerationCoordinator(
            hass,
            api_key=api_key,
            area=TOTAL_EUROPE_AREA,
        )
        data["generation_europe"] = generation_europe_coordinator
        refresh_tasks.append(
            generation_europe_coordinator.async_config_entry_first_refresh()
        )

    for horizon in LOAD_FORECAST_HORIZONS:
        enabled = entry.options.get(horizon.option_key, horizon.default_enabled)
        if enabled:
            coordinator = EntsoeLoadCoordinator(
                hass,
                api_key=api_key,
                area=area,
                process_type=horizon.process_type,
                look_ahead=horizon.look_ahead,
                update_interval=horizon.update_interval,
                horizon=horizon.horizon,
            )
            data[horizon.coordinator_key] = coordinator
            refresh_tasks.append(coordinator.async_config_entry_first_refresh())

        europe_default = horizon.europe_default_enabled
        for legacy_key in horizon.legacy_europe_option_keys:
            if legacy_key in entry.options:
                europe_default = entry.options[legacy_key]
                break

        europe_enabled = entry.options.get(
            horizon.europe_option_key,
            europe_default,
        )

        if europe_enabled:
            coordinator = EntsoeLoadCoordinator(
                hass,
                api_key=api_key,
                area=TOTAL_EUROPE_AREA,
                process_type=horizon.process_type,
                look_ahead=horizon.look_ahead,
                update_interval=horizon.update_interval,
                horizon=horizon.horizon,
            )
            data[horizon.europe_coordinator_key] = coordinator
            refresh_tasks.append(coordinator.async_config_entry_first_refresh())

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = data

    if refresh_tasks:
        await asyncio.gather(*refresh_tasks)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(async_update_options))

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    if unload_ok := await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        hass.data[DOMAIN].pop(entry.entry_id)
    return unload_ok


async def async_update_options(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Update options."""
    await hass.config_entries.async_reload(entry.entry_id)
