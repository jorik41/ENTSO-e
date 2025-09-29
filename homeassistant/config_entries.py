"""Test stubs for Home Assistant config entries."""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict


@dataclass
class ConfigEntry:
    """A lightweight stand-in for Home Assistant's ConfigEntry."""

    options: Dict[str, Any] = field(default_factory=dict)
    entry_id: str = "test"

    def add_update_listener(self, listener: Callable[[Any], Any]) -> Callable[[], None]:
        """Return a remover for compatibility with Home Assistant's API."""

        def _remove_listener() -> None:
            return None

        return _remove_listener


class ConfigEntryState(str, Enum):
    LOADED = "loaded"
    NOT_LOADED = "not_loaded"
