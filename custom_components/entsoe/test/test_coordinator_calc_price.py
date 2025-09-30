from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

PACKAGE_ROOT = Path(__file__).resolve().parent.parent
if str(PACKAGE_ROOT) not in sys.path:
    sys.path.append(str(PACKAGE_ROOT))

from homeassistant.core import HomeAssistant

from ..coordinator import EntsoeCoordinator


def test_calc_price_without_fake_dt_supplies_context(monkeypatch):
    hass = HomeAssistant()
    coordinator = EntsoeCoordinator(
        hass=hass,
        api_key="token",
        area="BE",
        energy_scale="kWh",
        modifyer="{{ current_price }}",
    )

    captured: dict[str, Any] = {}

    def fake_render(**kwargs):
        captured.update(kwargs)
        now_cb = kwargs["now"]
        aligned = now_cb(None)
        assert aligned.minute == 0
        assert aligned.second == 0
        assert aligned.microsecond == 0
        return kwargs["current_price"]

    monkeypatch.setattr(coordinator.modifyer, "async_render", fake_render)

    result = coordinator.calc_price(1200, fake_dt=None)

    assert result == 1.2
    assert "current_price" in captured
    assert captured["current_price"] == 1.2
    assert "now" in captured
