from __future__ import annotations

import logging
from collections import defaultdict
from datetime import datetime, timedelta

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt
from requests.exceptions import HTTPError

from .api_client import EntsoeClient
from .const import AREA_INFO, TOTAL_EUROPE_AREA


class EntsoeBaseCoordinator(DataUpdateCoordinator[dict]):
    """Base coordinator providing helper selection utilities."""

    def __init__(
        self,
        hass: HomeAssistant,
        logger: logging.Logger,
        name: str,
        update_interval: timedelta,
    ) -> None:
        super().__init__(hass, logger, name=name, update_interval=update_interval)

    def _sorted_timestamps(self) -> list[datetime]:
        if not self.data:
            return []
        return sorted(self.data.keys())

    def _reference_time(self, reference: datetime | None = None) -> datetime:
        if reference is not None:
            return reference
        return dt.now()

    def _select_current_timestamp(self, reference: datetime | None = None) -> datetime | None:
        ref = self._reference_time(reference)
        for timestamp in reversed(self._sorted_timestamps()):
            if timestamp <= ref:
                return timestamp
        timestamps = self._sorted_timestamps()
        if timestamps:
            return timestamps[-1]
        return None

    def _select_next_timestamp(self, reference: datetime | None = None) -> datetime | None:
        ref = self._reference_time(reference)
        for timestamp in self._sorted_timestamps():
            if timestamp > ref:
                return timestamp
        return None

    def current_timestamp(self, reference: datetime | None = None) -> datetime | None:
        return self._select_current_timestamp(reference)

    def next_timestamp(self, reference: datetime | None = None) -> datetime | None:
        return self._select_next_timestamp(reference)


class EntsoeGenerationCoordinator(EntsoeBaseCoordinator):
    """Coordinator handling generation per type queries."""

    _total_key = "total_generation"

    def __init__(self, hass: HomeAssistant, api_key: str, area: str) -> None:
        self.api_key = api_key
        self.area_key = area
        self.area = AREA_INFO[area]["code"]
        self._client = EntsoeClient(api_key=api_key)
        self._available_categories: set[str] = set()
        logger = logging.getLogger(f"{__name__}.generation")
        super().__init__(
            hass,
            logger,
            name="ENTSO-e generation coordinator",
            update_interval=timedelta(minutes=60),
        )

    async def _async_update_data(self) -> dict[datetime, dict[str, float]]:
        start = dt.now() - timedelta(days=1)
        end = start + timedelta(days=3)

        try:
            if self.area_key == TOTAL_EUROPE_AREA:
                response = await self.hass.async_add_executor_job(
                    self._query_total_europe_generation,
                    start,
                    end,
                )
            else:
                response = await self.hass.async_add_executor_job(
                    self._client.query_generation_per_type,
                    self.area,
                    start,
                    end,
                )
        except HTTPError as exc:  # pragma: no cover - matching behaviour of base coordinator
            if exc.response.status_code == 401:
                raise UpdateFailed("Unauthorized: Please check your API-key.") from exc
            raise

        if not response:
            self._available_categories = set()
            return {}

        normalized: dict[datetime, dict[str, float]] = {}
        categories: set[str] = set()
        for timestamp, values in response.items():
            normalized_values: dict[str, float] = defaultdict(float)
            total = 0.0
            for category, value in values.items():
                normalized_values[category] += value
                total += value
            normalized_values[self._total_key] = total
            normalized[timestamp] = dict(normalized_values)
            categories.update(normalized_values.keys())

        self._available_categories = categories
        return normalized

    def _query_total_europe_generation(
        self, start: datetime, end: datetime
    ) -> dict[datetime, dict[str, float]]:
        aggregate: defaultdict[datetime, defaultdict[str, float]] = defaultdict(
            lambda: defaultdict(float)
        )
        seen_codes: set[str] = set()

        for area_key, info in AREA_INFO.items():
            if area_key == TOTAL_EUROPE_AREA:
                continue

            code = info["code"]
            if code in seen_codes:
                continue
            seen_codes.add(code)

            response = self._client.query_generation_per_type(code, start, end)
            if not response:
                continue

            for timestamp, values in response.items():
                for category, value in values.items():
                    aggregate[timestamp][category] += value

        return {timestamp: dict(values) for timestamp, values in aggregate.items()}

    def categories(self) -> list[str]:
        return sorted(self._available_categories)

    def current_value(self, category: str, reference: datetime | None = None) -> float | None:
        timestamp = self._select_current_timestamp(reference)
        if timestamp is None or not self.data:
            return None
        return self.data.get(timestamp, {}).get(category)

    def next_value(self, category: str, reference: datetime | None = None) -> float | None:
        timestamp = self._select_next_timestamp(reference)
        if timestamp is None or not self.data:
            return None
        return self.data.get(timestamp, {}).get(category)

    def timeline(self, category: str) -> dict[str, float]:
        if not self.data:
            return {}
        timeline: dict[str, float] = {}
        for timestamp, values in sorted(self.data.items()):
            if category not in values:
                continue
            timeline[timestamp.isoformat()] = float(values[category])
        return timeline


class EntsoeLoadCoordinator(EntsoeBaseCoordinator):
    """Coordinator handling total load forecast queries."""

    def __init__(self, hass: HomeAssistant, api_key: str, area: str) -> None:
        self.api_key = api_key
        self.area = AREA_INFO[area]["code"]
        self._client = EntsoeClient(api_key=api_key)
        logger = logging.getLogger(f"{__name__}.load")
        super().__init__(
            hass,
            logger,
            name="ENTSO-e load coordinator",
            update_interval=timedelta(minutes=60),
        )

    async def _async_update_data(self) -> dict[datetime, float]:
        start = dt.now() - timedelta(days=1)
        end = start + timedelta(days=3)

        try:
            response: dict[datetime, float] | None = await self.hass.async_add_executor_job(
                self._client.query_total_load_forecast,
                self.area,
                start,
                end,
            )
        except HTTPError as exc:  # pragma: no cover - matching behaviour of base coordinator
            status_code = getattr(exc.response, "status_code", None)
            if status_code == 401:
                raise UpdateFailed("Unauthorized: Please check your API-key.") from exc
            if status_code == 400:
                self.logger.warning(
                    "ENTSO-e load data unavailable for area %s (HTTP 400).",
                    self.area,
                )
                return {}
            raise

        return response or {}

    def current_value(self, reference: datetime | None = None) -> float | None:
        timestamp = self._select_current_timestamp(reference)
        if timestamp is None or not self.data:
            return None
        return float(self.data[timestamp])

    def next_value(self, reference: datetime | None = None) -> float | None:
        timestamp = self._select_next_timestamp(reference)
        if timestamp is None or not self.data:
            return None
        return float(self.data[timestamp])

    def min_value(self) -> float | None:
        if not self.data:
            return None
        return float(min(self.data.values()))

    def max_value(self) -> float | None:
        if not self.data:
            return None
        return float(max(self.data.values()))

    def average_value(self) -> float | None:
        if not self.data:
            return None
        values = list(self.data.values())
        return float(sum(values) / len(values))

    def timeline(self) -> dict[str, float]:
        if not self.data:
            return {}
        return {
            timestamp.isoformat(): float(value)
            for timestamp, value in sorted(self.data.items())
        }
