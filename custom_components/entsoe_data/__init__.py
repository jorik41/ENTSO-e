"""The ENTSO-e data component."""

from __future__ import annotations

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
    CONF_ENABLE_GENERATION,
    CONF_ENABLE_LOAD,
    DEFAULT_ENABLE_GENERATION,
    DEFAULT_ENABLE_LOAD,
    DOMAIN,
)
from .coordinator import (
    EntsoeGenerationCoordinator,
    EntsoeLoadCoordinator,
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
    enable_load = entry.options.get(CONF_ENABLE_LOAD, DEFAULT_ENABLE_LOAD)

    data: dict[str, Any] = {}

    if enable_generation:
        generation_coordinator = EntsoeGenerationCoordinator(
            hass,
            api_key=api_key,
            area=area,
        )
        data["generation"] = generation_coordinator

    if enable_load:
        load_coordinator = EntsoeLoadCoordinator(
            hass,
            api_key=api_key,
            area=area,
        )
        data["load"] = load_coordinator

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = data

    if enable_generation:
        await generation_coordinator.async_config_entry_first_refresh()

    if enable_load:
        await load_coordinator.async_config_entry_first_refresh()
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
