"""Pytest configuration that installs Home Assistant stubs."""

from __future__ import annotations

import sys
from pathlib import Path

TEST_DIR = Path(__file__).resolve().parent
PACKAGE_ROOT = TEST_DIR.parent

if str(PACKAGE_ROOT) not in sys.path:
    sys.path.append(str(PACKAGE_ROOT))

if str(TEST_DIR) not in sys.path:
    sys.path.append(str(TEST_DIR))

from hass_stubs import install_hass_stubs

install_hass_stubs()
