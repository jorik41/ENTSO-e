from __future__ import annotations

import logging
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Any, Iterable

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt
from requests import exceptions as requests_exceptions
from requests.exceptions import HTTPError

from .api_client import EntsoeClient, PROCESS_TYPE_DAY_AHEAD
from .const import (
    AREA_INFO,
    LOAD_FORECAST_HORIZON_DAY_AHEAD,
    LOAD_FORECAST_HORIZONS,
    STALENESS_MULTIPLIER,
    TOTAL_EUROPE_AREA,
)


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
        self.last_successful_update: datetime | None = None

    def _copy_data(self) -> dict[datetime, Any]:
        if not self.data:
            return {}
        copied: dict[datetime, Any] = {}
        for timestamp, value in self.data.items():
            if isinstance(value, dict):
                copied[timestamp] = dict(value)
            else:
                copied[timestamp] = value
        return copied

    def _cached_data_if_sufficient(
        self,
        start: datetime,
        end: datetime,
        *,
        margin: timedelta = timedelta(hours=1),
    ) -> dict[datetime, Any] | None:
        timestamps = self._sorted_timestamps()
        if not timestamps:
            return None

        earliest, latest = timestamps[0], timestamps[-1]
        if earliest <= start and latest >= end - margin:
            self.logger.debug(
                "Using cached ENTSO-e data spanning %s – %s for the requested window %s – %s",
                earliest,
                latest,
                start,
                end,
            )
            return self._copy_data()

        return None

    def _sorted_timestamps(self) -> list[datetime]:
        if not self.data:
            return []
        return sorted(self.data.keys())

    def _format_area_names(self, areas: Iterable[str]) -> str:
        names: list[str] = []
        for area_key in sorted(areas):
            info = AREA_INFO.get(area_key)
            if info and info.get("name"):
                names.append(info["name"])
            else:
                names.append(area_key)
        return ", ".join(names)

    def _handle_total_europe_issues(
        self,
        missing_areas: set[str],
        zero_only_areas: set[str],
        dataset_description: str,
        has_fresh_data: bool,
    ) -> dict[datetime, Any] | None:
        if not missing_areas and not zero_only_areas:
            return None

        fallback_required = False

        if missing_areas:
            self.logger.warning(
                "Missing ENTSO-e %s data for: %s.",
                dataset_description,
                self._format_area_names(missing_areas),
            )
            fallback_required = True

        if zero_only_areas:
            self.logger.warning(
                "ENTSO-e %s data returned zero-only values for: %s.",
                dataset_description,
                self._format_area_names(zero_only_areas),
            )

        if not fallback_required:
            return None

        if has_fresh_data:
            self.logger.debug(
                "Continuing with partial ENTSO-e %s data for Europe due to missing areas.",
                dataset_description,
            )
            return None

        if self.data:
            self.logger.warning(
                "Retaining cached ENTSO-e %s data until full European coverage is restored.",
                dataset_description,
            )
            return self._copy_data()

        raise UpdateFailed(
            f"Incomplete ENTSO-e {dataset_description} data for Europe; see logs for details."
        )

    def _reference_time(self, reference: datetime | None = None) -> datetime:
        if reference is not None:
            return reference
        return dt.now()

    def is_data_stale(self) -> bool:
        """Check if the data is stale based on last successful update.

        Data is considered stale if we haven't successfully updated in
        STALENESS_MULTIPLIER times the normal update interval.
        This prevents ML models from training on unreliable data.
        """
        if self.last_successful_update is None:
            # No successful update yet - data is stale
            return True

        if not self.data:
            # No data available - considered stale
            return True

        # Check if we're past the staleness threshold
        staleness_threshold = self.update_interval * STALENESS_MULTIPLIER
        time_since_update = dt.now() - self.last_successful_update

        return time_since_update > staleness_threshold

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

        cached = self._cached_data_if_sufficient(start, end)
        if cached is not None:
            return cached

        try:
            if self.area_key == TOTAL_EUROPE_AREA:
                (
                    response,
                    missing_areas,
                    zero_only_areas,
                ) = await self.hass.async_add_executor_job(
                    self._query_total_europe_generation,
                    start,
                    end,
                )
                fallback = self._handle_total_europe_issues(
                    missing_areas,
                    zero_only_areas,
                    "generation",
                    bool(response),
                )
                if fallback is not None:
                    return fallback
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
        except requests_exceptions.RequestException as exc:
            if self.data:
                self.logger.warning(
                    "Network error while updating ENTSO-e generation data: %s. Using cached values until the connection is restored.",
                    exc,
                )
                return self._copy_data()
            raise UpdateFailed("Failed to retrieve ENTSO-e generation data.") from exc

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
        self.last_successful_update = dt.now()
        return normalized

    def _query_total_europe_generation(
        self, start: datetime, end: datetime
    ) -> tuple[dict[datetime, dict[str, float]], set[str], set[str]]:
        aggregate: defaultdict[datetime, defaultdict[str, float]] = defaultdict(
            lambda: defaultdict(float)
        )
        seen_codes: set[str] = set()
        missing_areas: set[str] = set()
        zero_only_areas: set[str] = set()

        for area_key, info in AREA_INFO.items():
            if area_key == TOTAL_EUROPE_AREA:
                continue

            code = info["code"]
            if code in seen_codes:
                continue
            seen_codes.add(code)

            response = self._client.query_generation_per_type(code, start, end)
            if not response:
                missing_areas.add(area_key)
                continue

            has_non_zero = False
            for timestamp, values in response.items():
                for category, value in values.items():
                    aggregate[timestamp][category] += value
                    if value:
                        has_non_zero = True

            if not has_non_zero:
                zero_only_areas.add(area_key)

        aggregated = {
            timestamp: dict(values) for timestamp, values in aggregate.items()
        }
        return aggregated, missing_areas, zero_only_areas

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

    def __init__(
        self,
        hass: HomeAssistant,
        api_key: str,
        area: str,
        *,
        process_type: str = PROCESS_TYPE_DAY_AHEAD,
        look_ahead: timedelta | None = None,
        update_interval: timedelta | None = None,
        horizon: str = LOAD_FORECAST_HORIZON_DAY_AHEAD,
    ) -> None:
        self.api_key = api_key
        self.area_key = area
        self.area = AREA_INFO[area]["code"]
        self._client = EntsoeClient(api_key=api_key)
        self.process_type = process_type
        self._look_ahead = look_ahead or timedelta(days=3)
        self.horizon = horizon
        interval = update_interval or timedelta(minutes=60)
        logger = logging.getLogger(f"{__name__}.load.{horizon}")
        super().__init__(
            hass,
            logger,
            name=f"ENTSO-e load {horizon} coordinator",
            update_interval=interval,
        )

    async def _async_update_data(self) -> dict[datetime, float]:
        start = dt.now() - timedelta(days=1)
        end = start + self._look_ahead

        cached = self._cached_data_if_sufficient(start, end)
        if cached is not None:
            return cached

        try:
            if self.area_key == TOTAL_EUROPE_AREA:
                (
                    response,
                    missing_areas,
                    zero_only_areas,
                ) = await self.hass.async_add_executor_job(
                    self._query_total_europe_load,
                    start,
                    end,
                )
                fallback = self._handle_total_europe_issues(
                    missing_areas,
                    zero_only_areas,
                    f"load {self.horizon}",
                    bool(response),
                )
                if fallback is not None:
                    return fallback
            else:
                response = await self.hass.async_add_executor_job(
                    self._client.query_total_load_forecast,
                    self.area,
                    start,
                    end,
                    self.process_type,
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
        except requests_exceptions.RequestException as exc:
            if self.data:
                self.logger.warning(
                    "Network error while updating ENTSO-e load data: %s. Using cached values until the connection is restored.",
                    exc,
                )
                return self._copy_data()
            raise UpdateFailed("Failed to retrieve ENTSO-e load data.") from exc

        if response is not None:
            self.last_successful_update = dt.now()
        return response or {}

    def _query_total_europe_load(
        self, start: datetime, end: datetime
    ) -> tuple[dict[datetime, float], set[str], set[str]]:
        aggregate: defaultdict[datetime, float] = defaultdict(float)
        seen_codes: set[str] = set()
        missing_areas: set[str] = set()
        zero_only_areas: set[str] = set()

        for area_key, info in AREA_INFO.items():
            if area_key == TOTAL_EUROPE_AREA:
                continue

            code = info["code"]
            if code in seen_codes:
                continue
            seen_codes.add(code)

            response = self._client.query_total_load_forecast(
                code, start, end, self.process_type
            )
            if not response:
                missing_areas.add(area_key)
                continue

            has_non_zero = any(value for value in response.values())
            for timestamp, value in response.items():
                aggregate[timestamp] += value

            if not has_non_zero:
                zero_only_areas.add(area_key)

        return dict(aggregate), missing_areas, zero_only_areas

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


class EntsoeGenerationForecastCoordinator(EntsoeBaseCoordinator):
    """Coordinator handling generation forecast queries."""

    def __init__(self, hass: HomeAssistant, api_key: str, area: str) -> None:
        self.api_key = api_key
        self.area = AREA_INFO[area]["code"]
        self._client = EntsoeClient(api_key=api_key)
        logger = logging.getLogger(f"{__name__}.generation_forecast")
        super().__init__(
            hass,
            logger,
            name="ENTSO-e generation forecast coordinator",
            update_interval=timedelta(minutes=60),
        )

    async def _async_update_data(self) -> dict[datetime, float]:
        start = dt.now() - timedelta(days=1)
        end = start + timedelta(days=3)

        cached = self._cached_data_if_sufficient(start, end)
        if cached is not None:
            return cached

        try:
            response: dict[datetime, float] | None = await self.hass.async_add_executor_job(
                self._client.query_generation_forecast,
                self.area,
                start,
                end,
            )
        except HTTPError as exc:  # pragma: no cover - matching behaviour of base coordinator
            if getattr(exc.response, "status_code", None) == 401:
                raise UpdateFailed("Unauthorized: Please check your API-key.") from exc
            raise
        except requests_exceptions.RequestException as exc:
            if self.data:
                self.logger.warning(
                    "Network error while updating ENTSO-e generation forecast data: %s. Using cached values until the connection is restored.",
                    exc,
                )
                return self._copy_data()
            raise UpdateFailed("Failed to retrieve ENTSO-e generation forecast data.") from exc

        if response:
            self.last_successful_update = dt.now()
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


class EntsoeWindSolarForecastCoordinator(EntsoeBaseCoordinator):
    """Coordinator handling wind and solar forecast queries."""

    def __init__(self, hass: HomeAssistant, api_key: str, area: str) -> None:
        self.api_key = api_key
        self.area_key = area
        self.area = AREA_INFO[area]["code"]
        self._client = EntsoeClient(api_key=api_key)
        self._available_categories: set[str] = set()
        logger = logging.getLogger(f"{__name__}.wind_solar_forecast")
        super().__init__(
            hass,
            logger,
            name="ENTSO-e wind and solar forecast coordinator",
            update_interval=timedelta(minutes=60),
        )

    async def _async_update_data(self) -> dict[datetime, dict[str, float]]:
        start = dt.now() - timedelta(days=1)
        end = start + timedelta(days=3)

        cached = self._cached_data_if_sufficient(start, end)
        if cached is not None:
            return cached

        try:
            if self.area_key == TOTAL_EUROPE_AREA:
                (
                    response,
                    missing_areas,
                    zero_only_areas,
                ) = await self.hass.async_add_executor_job(
                    self._query_total_europe_wind_solar_forecast,
                    start,
                    end,
                )
                fallback = self._handle_total_europe_issues(
                    missing_areas,
                    zero_only_areas,
                    "wind and solar forecast",
                    bool(response),
                )
                if fallback is not None:
                    return fallback
            else:
                response = await self.hass.async_add_executor_job(
                    self._client.query_wind_solar_forecast,
                    self.area,
                    start,
                    end,
                )
        except HTTPError as exc:  # pragma: no cover - matching behaviour of base coordinator
            if getattr(exc.response, "status_code", None) == 401:
                raise UpdateFailed("Unauthorized: Please check your API-key.") from exc
            raise
        except requests_exceptions.RequestException as exc:
            if self.data:
                self.logger.warning(
                    "Network error while updating ENTSO-e wind and solar forecast data: %s. Using cached values until the connection is restored.",
                    exc,
                )
                return self._copy_data()
            raise UpdateFailed(
                "Failed to retrieve ENTSO-e wind and solar forecast data."
            ) from exc

        if not response:
            self._available_categories = set()
            return {}

        normalized: dict[datetime, dict[str, float]] = {}
        categories: set[str] = set()
        for timestamp, values in response.items():
            normalized[timestamp] = dict(values)
            categories.update(values.keys())

        self._available_categories = categories
        self.last_successful_update = dt.now()
        return normalized

    def _query_total_europe_wind_solar_forecast(
        self, start: datetime, end: datetime
    ) -> tuple[dict[datetime, dict[str, float]], set[str], set[str]]:
        aggregate: defaultdict[datetime, defaultdict[str, float]] = defaultdict(
            lambda: defaultdict(float)
        )
        seen_codes: set[str] = set()
        missing_areas: set[str] = set()
        zero_only_areas: set[str] = set()

        for area_key, info in AREA_INFO.items():
            if area_key == TOTAL_EUROPE_AREA:
                continue

            code = info["code"]
            if code in seen_codes:
                continue
            seen_codes.add(code)

            response = self._client.query_wind_solar_forecast(code, start, end)
            if not response:
                missing_areas.add(area_key)
                continue

            has_non_zero = False
            for timestamp, values in response.items():
                for category, value in values.items():
                    aggregate[timestamp][category] += value
                    if value:
                        has_non_zero = True

            if not has_non_zero:
                zero_only_areas.add(area_key)

        aggregated = {
            timestamp: dict(values) for timestamp, values in aggregate.items()
        }
        return aggregated, missing_areas, zero_only_areas

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
