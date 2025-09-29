"""Minimal config validation utilities for tests."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class _TemplateWrapper:
    template: str

    def async_render(self, **kwargs):
        return self.template


def template(value: str | None) -> _TemplateWrapper:
    if value is None:
        value = ""
    return _TemplateWrapper(template=value)
