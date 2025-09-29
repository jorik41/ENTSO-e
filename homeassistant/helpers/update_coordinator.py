"""Minimal update coordinator stubs."""

from __future__ import annotations

from typing import Any


class UpdateFailed(Exception):
    """Exception raised when an update fails."""


class DataUpdateCoordinator:
    def __init__(self, hass: Any, logger: Any, name: str, update_interval: Any) -> None:
        self.hass = hass
        self.logger = logger
        self.name = name
        self.update_interval = update_interval
        self.data = {}

    async def async_config_entry_first_refresh(self) -> None:
        return None

    async def _async_update_data(self) -> Any:  # pragma: no cover - interface stub
        raise NotImplementedError
