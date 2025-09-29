"""Selector stubs for Home Assistant tests."""

from dataclasses import dataclass
from typing import Any, Dict


@dataclass
class ConfigEntrySelector:
    config: Dict[str, Any]
