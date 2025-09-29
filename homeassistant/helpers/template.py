"""Minimal template stub for Home Assistant tests."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Template:
    template: str

    def async_render(self, **kwargs):
        return self.template
