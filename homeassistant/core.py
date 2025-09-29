"""Minimal HomeAssistant core stub."""

from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, Optional


class _ConfigEntries:
    def __init__(self) -> None:
        self._entries: Dict[str, Any] = {}

    async def async_forward_entry_setups(self, *args: Any, **kwargs: Any) -> None:
        return None

    async def async_unload_platforms(self, *args: Any, **kwargs: Any) -> bool:
        return True

    async def async_reload(self, *args: Any, **kwargs: Any) -> None:
        return None

    def async_get_entry(self, entry_id: str) -> Optional[Any]:
        return self._entries.get(entry_id)

    def add_entry(self, entry_id: str, entry: Any) -> None:
        self._entries[entry_id] = entry


class _Services:
    async def async_register(
        self,
        domain: str,
        service: str,
        handler: Any,
        schema: Any = None,
        supports_response: Any = None,
    ) -> None:
        return None


class SupportsResponse(Enum):
    ONLY = "only"


ServiceResponse = Dict[str, Any]


@dataclass
class ServiceCall:
    data: Dict[str, Any]


def callback(func):
    return func


class HomeAssistant:
    """Simplified HomeAssistant container for tests."""

    def __init__(self) -> None:
        self.data: Dict[str, Any] = {}
        self.config_entries = _ConfigEntries()
        self.services = _Services()
