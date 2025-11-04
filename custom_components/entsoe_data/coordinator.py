from __future__ import annotations

import logging
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Any, Iterable

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt
from requests import exceptions as requests_exceptions

REQUEST_TIMEOUT_ERRORS: tuple[type[requests_exceptions.RequestException], ...] = (
    requests_exceptions.Timeout,
    requests_exceptions.ReadTimeout,
    requests_exceptions.ConnectTimeout,
)
from requests.exceptions import HTTPError

from .api_client import EntsoeClient, PROCESS_TYPE_DAY_AHEAD
from .const import (
    AREA_INFO,
    LOAD_FORECAST_HORIZON_DAY_AHEAD,
    LOAD_FORECAST_HORIZON_MONTH_AHEAD,
    LOAD_FORECAST_HORIZONS,
    LOAD_FORECAST_HORIZON_WEEK_AHEAD,
    LOAD_FORECAST_HORIZON_YEAR_AHEAD,
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
        self._last_total_europe_issues: dict[
            str, tuple[frozenset[str], frozenset[str]]
        ] = {}
        self._last_total_europe_fallback: dict[str, bool] = {}
        self._last_total_europe_no_data: dict[str, bool] = {}

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
        missing_set = set(missing_areas)
        zero_set = set(zero_only_areas)

        previous_missing, previous_zero = self._last_total_europe_issues.get(
            dataset_description, (frozenset(), frozenset())
        )
        prev_missing_set = set(previous_missing)
        prev_zero_set = set(previous_zero)

        new_missing = missing_set - prev_missing_set
        resolved_missing = prev_missing_set - missing_set
        new_zero_only = zero_set - prev_zero_set
        resolved_zero_only = prev_zero_set - zero_set

        if new_missing:
            self.logger.warning(
                "Missing ENTSO-e %s data for: %s.",
                dataset_description,
                self._format_area_names(new_missing),
            )
        if resolved_missing:
            self.logger.info(
                "ENTSO-e %s data restored for: %s.",
                dataset_description,
                self._format_area_names(resolved_missing),
            )

        if new_zero_only:
            self.logger.warning(
                "ENTSO-e %s data returned zero-only values for: %s.",
                dataset_description,
                self._format_area_names(new_zero_only),
            )
        if resolved_zero_only:
            self.logger.info(
                "ENTSO-e %s data no longer returns zero-only values for: %s.",
                dataset_description,
                self._format_area_names(resolved_zero_only),
            )

        self._last_total_europe_issues[dataset_description] = (
            frozenset(missing_set),
            frozenset(zero_set),
        )

        fallback_required = bool(missing_set)
        fallback_active = fallback_required and not has_fresh_data
        previous_fallback = self._last_total_europe_fallback.get(
            dataset_description, False
        )

        if not fallback_required:
            if previous_fallback or self._last_total_europe_no_data.get(dataset_description):
                self.logger.info(
                    "Resumed live ENTSO-e %s data for Europe.",
                    dataset_description,
                )
            self._last_total_europe_fallback[dataset_description] = False
            self._last_total_europe_no_data[dataset_description] = False
            return None

        if fallback_active:
            if not previous_fallback and self.data:
                self.logger.warning(
                    "Retaining cached ENTSO-e %s data until full European coverage is restored.",
                    dataset_description,
                )
            if not previous_fallback and not self.data:
                if not self._last_total_europe_no_data.get(dataset_description):
                    self.logger.warning(
                        "ENTSO-e %s data is currently unavailable for all European areas. "
                        "Sensors will report as unknown until ENTSO-e publishes this dataset again.",
                        dataset_description,
                    )
                    self._last_total_europe_no_data[dataset_description] = True
            self._last_total_europe_fallback[dataset_description] = True
            if self.data:
                self._last_total_europe_no_data[dataset_description] = False
                return self._copy_data()
            return {}

        if previous_fallback:
            self.logger.info(
                "Resumed live ENTSO-e %s data for Europe.",
                dataset_description,
            )
        elif new_missing:
            self.logger.debug(
                "Continuing with partial ENTSO-e %s data for Europe due to missing areas.",
                dataset_description,
            )

        self._last_total_europe_fallback[dataset_description] = False
        self._last_total_europe_no_data[dataset_description] = False
        return None

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
        # Track failed areas for robust retry handling
        self._area_missing_counts: defaultdict[str, int] = defaultdict(int)
        self._area_suppressed_until: dict[str, datetime] = {}
        self._area_last_suppressed: dict[str, datetime | None] = {}
        self._missing_threshold = 3  # Number of failures before suppression
        # Store per-area data for Total Europe queries
        self._area_data: dict[str, dict[datetime, dict[str, float]]] = {}

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
        suppressed_this_run: list[str] = []
        recovered_this_run: list[str] = []
        now = dt.now()
        suppression_duration = timedelta(hours=6)  # Retry after 6 hours

        for area_key, info in AREA_INFO.items():
            if area_key == TOTAL_EUROPE_AREA:
                continue

            code = info["code"]
            if code in seen_codes:
                continue
            seen_codes.add(code)

            # Check if area is currently suppressed (being retried later)
            suppress_until = self._area_suppressed_until.get(area_key)
            if suppress_until and suppress_until > now:
                missing_areas.add(area_key)
                continue
            if suppress_until and suppress_until <= now:
                del self._area_suppressed_until[area_key]

            try:
                response = self._client.query_generation_per_type(code, start, end)
                if not response:
                    missing_areas.add(area_key)
                    self._area_missing_counts[area_key] += 1
                    if self._area_missing_counts[area_key] >= self._missing_threshold:
                        until = now + suppression_duration
                        self._area_suppressed_until[area_key] = until
                        self._area_last_suppressed[area_key] = now
                        suppressed_this_run.append(area_key)
                        self._area_missing_counts[area_key] = 0
                    continue

                # Success - reset counters and track recovery
                self._area_missing_counts[area_key] = 0
                if self._area_last_suppressed.get(area_key) is not None:
                    recovered_this_run.append(area_key)
                    self._area_last_suppressed[area_key] = None

                # Store per-area data for individual sensors
                self._area_data[area_key] = response

                has_non_zero = False
                for timestamp, values in response.items():
                    for category, value in values.items():
                        aggregate[timestamp][category] += value
                        if value:
                            has_non_zero = True

                if not has_non_zero:
                    zero_only_areas.add(area_key)
            except requests_exceptions.RequestException as exc:
                self.logger.debug(
                    "Failed to fetch ENTSO-e generation data for %s: %s. Skipping this area.",
                    area_key,
                    exc,
                )
                missing_areas.add(area_key)
                self._area_missing_counts[area_key] += 1
                if self._area_missing_counts[area_key] >= self._missing_threshold:
                    until = now + suppression_duration
                    self._area_suppressed_until[area_key] = until
                    self._area_last_suppressed[area_key] = now
                    suppressed_this_run.append(area_key)
                    self._area_missing_counts[area_key] = 0
                continue

        # Log suppressed and recovered areas
        if suppressed_this_run:
            self.logger.info(
                "ENTSO-e generation data unavailable for %s; retrying in 6h.",
                self._format_area_names(suppressed_this_run),
            )

        if recovered_this_run:
            self.logger.info(
                "ENTSO-e generation data resumed for: %s.",
                self._format_area_names(recovered_this_run),
            )

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

    def get_area_keys(self) -> list[str]:
        """Return list of areas with available data."""
        return sorted(self._area_data.keys())

    def get_area_current_value(self, area_key: str, category: str, reference: datetime | None = None) -> float | None:
        """Get current value for a specific area and category."""
        if area_key not in self._area_data:
            return None
        timestamp = self._select_current_timestamp(reference)
        if timestamp is None:
            return None
        return self._area_data[area_key].get(timestamp, {}).get(category)

    def get_area_timeline(self, area_key: str, category: str) -> dict[str, float]:
        """Get timeline for a specific area and category."""
        if area_key not in self._area_data:
            return {}
        timeline: dict[str, float] = {}
        for timestamp, values in sorted(self._area_data[area_key].items()):
            if category not in values:
                continue
            timeline[timestamp.isoformat()] = float(values[category])
        return timeline

    def get_all_area_timelines(self, category: str) -> dict[str, dict[str, float]]:
        """Get timelines for all areas for a specific category."""
        result: dict[str, dict[str, float]] = {}
        for area_key in self._area_data:
            timeline = self.get_area_timeline(area_key, category)
            if timeline:
                result[area_key] = timeline
        return result


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
        self._area_missing_counts: defaultdict[str, int] = defaultdict(int)
        self._area_suppressed_until: dict[str, datetime] = {}
        self._area_last_suppressed: dict[str, datetime | None] = {}
        self._all_suppressed_logged = False
        self._area_keys: tuple[str, ...] = tuple(
            key for key in AREA_INFO if key != TOTAL_EUROPE_AREA
        )
        self._missing_threshold = (
            3 if horizon == LOAD_FORECAST_HORIZON_DAY_AHEAD else 1
        )
        # Store per-area data for Total Europe queries
        self._area_data: dict[str, dict[datetime, float]] = {}

    def _suppression_duration(self) -> timedelta:
        if self.horizon == LOAD_FORECAST_HORIZON_DAY_AHEAD:
            return timedelta(hours=6)
        if self.horizon == LOAD_FORECAST_HORIZON_WEEK_AHEAD:
            return timedelta(hours=12)
        if self.horizon == LOAD_FORECAST_HORIZON_MONTH_AHEAD:
            return timedelta(days=1)
        return timedelta(days=3)

    def _format_duration(self, duration: timedelta) -> str:
        total_seconds = int(duration.total_seconds())
        days, remainder = divmod(total_seconds, 86400)
        hours, remainder = divmod(remainder, 3600)
        minutes = remainder // 60
        parts: list[str] = []
        if days:
            parts.append(f"{days}d")
        if hours:
            parts.append(f"{hours}h")
        if minutes and not days:
            parts.append(f"{minutes}m")
        if not parts:
            parts.append("0m")
        return " ".join(parts)

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

        if response:
            self.last_successful_update = dt.now()
        return response or {}

    def _query_total_europe_load(
        self, start: datetime, end: datetime
    ) -> tuple[dict[datetime, float], set[str], set[str]]:
        aggregate: defaultdict[datetime, float] = defaultdict(float)
        seen_codes: set[str] = set()
        missing_areas: set[str] = set()
        zero_only_areas: set[str] = set()
        suppressed_this_run: list[str] = []
        recovered_this_run: list[str] = []
        now = dt.now()
        suppression_duration = self._suppression_duration()

        for area_key, info in AREA_INFO.items():
            if area_key == TOTAL_EUROPE_AREA:
                continue

            code = info["code"]
            if code in seen_codes:
                continue
            seen_codes.add(code)

            suppress_until = self._area_suppressed_until.get(area_key)
            if suppress_until and suppress_until > now:
                missing_areas.add(area_key)
                continue
            if suppress_until and suppress_until <= now:
                del self._area_suppressed_until[area_key]

            try:
                response = self._client.query_total_load_forecast(
                    code, start, end, self.process_type
                )
                if not response:
                    missing_areas.add(area_key)
                    self._area_missing_counts[area_key] += 1
                    if self._area_missing_counts[area_key] >= self._missing_threshold:
                        until = now + suppression_duration
                        self._area_suppressed_until[area_key] = until
                        self._area_last_suppressed[area_key] = now
                        suppressed_this_run.append(area_key)
                        self._area_missing_counts[area_key] = 0
                    continue

                self._area_missing_counts[area_key] = 0
                if self._area_last_suppressed.get(area_key) is not None:
                    recovered_this_run.append(area_key)
                    self._area_last_suppressed[area_key] = None

                # Store per-area data for individual sensors
                self._area_data[area_key] = response

                has_non_zero = any(value for value in response.values())
                for timestamp, value in response.items():
                    aggregate[timestamp] += value

                if not has_non_zero:
                    zero_only_areas.add(area_key)
            except requests_exceptions.RequestException as exc:
                self.logger.debug(
                    "Failed to fetch ENTSO-e load data for %s: %s. Skipping this area.",
                    area_key,
                    exc,
                )
                missing_areas.add(area_key)
                self._area_missing_counts[area_key] += 1
                if self._area_missing_counts[area_key] >= self._missing_threshold:
                    until = now + suppression_duration
                    self._area_suppressed_until[area_key] = until
                    self._area_last_suppressed[area_key] = now
                    suppressed_this_run.append(area_key)
                    self._area_missing_counts[area_key] = 0
                continue

        if suppressed_this_run:
            self.logger.info(
                "ENTSO-e load %s data unavailable for %s; retrying in %s.",
                self.horizon.replace("_", " "),
                self._format_area_names(suppressed_this_run),
                self._format_duration(suppression_duration),
            )

        if recovered_this_run:
            self.logger.info(
                "ENTSO-e load %s data resumed for: %s.",
                self.horizon.replace("_", " "),
                self._format_area_names(recovered_this_run),
            )

        active_area_exists = any(
            (area_key not in self._area_suppressed_until)
            or (self._area_suppressed_until[area_key] <= now)
            for area_key in self._area_keys
        )
        if not active_area_exists and self._area_suppressed_until:
            next_retry = min(self._area_suppressed_until.values())
            if not self._all_suppressed_logged:
                self.logger.warning(
                    "ENTSO-e load %s data currently unavailable for all configured European areas; next retry scheduled at %s.",
                    self.horizon.replace("_", " "),
                    next_retry.isoformat(),
                )
                self._all_suppressed_logged = True
        else:
            self._all_suppressed_logged = False

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

    def get_area_keys(self) -> list[str]:
        """Return list of areas with available data."""
        return sorted(self._area_data.keys())

    def get_area_current_value(self, area_key: str, reference: datetime | None = None) -> float | None:
        """Get current value for a specific area."""
        if area_key not in self._area_data:
            return None
        timestamp = self._select_current_timestamp(reference)
        if timestamp is None:
            return None
        return self._area_data[area_key].get(timestamp)

    def get_area_timeline(self, area_key: str) -> dict[str, float]:
        """Get timeline for a specific area."""
        if area_key not in self._area_data:
            return {}
        return {
            timestamp.isoformat(): float(value)
            for timestamp, value in sorted(self._area_data[area_key].items())
        }

    def get_all_area_timelines(self) -> dict[str, dict[str, float]]:
        """Get timelines for all areas."""
        result: dict[str, dict[str, float]] = {}
        for area_key in self._area_data:
            timeline = self.get_area_timeline(area_key)
            if timeline:
                result[area_key] = timeline
        return result


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
        except REQUEST_TIMEOUT_ERRORS as exc:
            self.logger.warning(
                "Timed out while updating ENTSO-e generation forecast data: %s. Retrying with smaller windows.",
                exc,
            )
            try:
                response = await self._fetch_generation_forecast_in_chunks(start, end)
            except requests_exceptions.RequestException as chunk_exc:
                if self.data:
                    self.logger.warning(
                        "Network error while updating ENTSO-e generation forecast data: %s. Using cached values until the connection is restored.",
                        chunk_exc,
                    )
                    return self._copy_data()
                raise UpdateFailed("Failed to retrieve ENTSO-e generation forecast data.") from chunk_exc
        except HTTPError as exc:  # pragma: no cover - matching behaviour of base coordinator
            status_code = getattr(exc.response, "status_code", None)
            if status_code == 401:
                raise UpdateFailed("Unauthorized: Please check your API-key.") from exc
            if status_code == 400:
                self.logger.warning(
                    "ENTSO-e generation forecast data unavailable for area %s (HTTP 400).",
                    self.area,
                )
                return {}
            raise
        except requests_exceptions.RequestException as exc:
            if self.data:
                self.logger.warning(
                    "Network error while updating ENTSO-e generation forecast data: %s. Using cached values until the connection is restored.",
                    exc,
                )
                return self._copy_data()
            raise UpdateFailed("Failed to retrieve ENTSO-e generation forecast data.") from exc

        if response is not None:
            self.last_successful_update = dt.now()
        return response or {}

    async def _fetch_generation_forecast_in_chunks(
        self,
        start: datetime,
        end: datetime,
        *,
        chunk_size: timedelta = timedelta(days=1),
    ) -> dict[datetime, float]:
        """Fetch generation forecast data in smaller windows to avoid timeouts."""

        aggregate: defaultdict[datetime, float] = defaultdict(float)
        cursor = start
        last_error: requests_exceptions.RequestException | None = None
        had_success = False

        while cursor < end:
            chunk_end = min(cursor + chunk_size, end)
            try:
                chunk = await self.hass.async_add_executor_job(
                    self._client.query_generation_forecast,
                    self.area,
                    cursor,
                    chunk_end,
                )
            except REQUEST_TIMEOUT_ERRORS as exc:
                self.logger.warning(
                    "Timed out while fetching ENTSO-e generation forecast chunk %s – %s: %s",
                    cursor,
                    chunk_end,
                    exc,
                )
                last_error = exc
            except requests_exceptions.RequestException as exc:
                last_error = exc
                break
            else:
                if chunk:
                    had_success = True
                    for timestamp, value in chunk.items():
                        aggregate[timestamp] += float(value)

            cursor = chunk_end

        if not had_success and last_error is not None:
            raise last_error

        return {timestamp: aggregate[timestamp] for timestamp in sorted(aggregate)}

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
        # Track failed areas for robust retry handling
        self._area_missing_counts: defaultdict[str, int] = defaultdict(int)
        self._area_suppressed_until: dict[str, datetime] = {}
        self._area_last_suppressed: dict[str, datetime | None] = {}
        self._missing_threshold = 3  # Number of failures before suppression
        # Store per-area data for Total Europe queries
        self._area_data: dict[str, dict[datetime, dict[str, float]]] = {}

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
        suppressed_this_run: list[str] = []
        recovered_this_run: list[str] = []
        now = dt.now()
        suppression_duration = timedelta(hours=6)  # Retry after 6 hours

        for area_key, info in AREA_INFO.items():
            if area_key == TOTAL_EUROPE_AREA:
                continue

            code = info["code"]
            if code in seen_codes:
                continue
            seen_codes.add(code)

            # Check if area is currently suppressed (being retried later)
            suppress_until = self._area_suppressed_until.get(area_key)
            if suppress_until and suppress_until > now:
                missing_areas.add(area_key)
                continue
            if suppress_until and suppress_until <= now:
                del self._area_suppressed_until[area_key]

            try:
                response = self._client.query_wind_solar_forecast(code, start, end)
                if not response:
                    missing_areas.add(area_key)
                    self._area_missing_counts[area_key] += 1
                    if self._area_missing_counts[area_key] >= self._missing_threshold:
                        until = now + suppression_duration
                        self._area_suppressed_until[area_key] = until
                        self._area_last_suppressed[area_key] = now
                        suppressed_this_run.append(area_key)
                        self._area_missing_counts[area_key] = 0
                    continue

                # Success - reset counters and track recovery
                self._area_missing_counts[area_key] = 0
                if self._area_last_suppressed.get(area_key) is not None:
                    recovered_this_run.append(area_key)
                    self._area_last_suppressed[area_key] = None

                # Store per-area data for individual sensors
                self._area_data[area_key] = response

                has_non_zero = False
                for timestamp, values in response.items():
                    for category, value in values.items():
                        aggregate[timestamp][category] += value
                        if value:
                            has_non_zero = True

                if not has_non_zero:
                    zero_only_areas.add(area_key)
            except requests_exceptions.RequestException as exc:
                self.logger.debug(
                    "Failed to fetch ENTSO-e wind and solar forecast data for %s: %s. Skipping this area.",
                    area_key,
                    exc,
                )
                missing_areas.add(area_key)
                self._area_missing_counts[area_key] += 1
                if self._area_missing_counts[area_key] >= self._missing_threshold:
                    until = now + suppression_duration
                    self._area_suppressed_until[area_key] = until
                    self._area_last_suppressed[area_key] = now
                    suppressed_this_run.append(area_key)
                    self._area_missing_counts[area_key] = 0
                continue

        # Log suppressed and recovered areas
        if suppressed_this_run:
            self.logger.info(
                "ENTSO-e wind and solar forecast data unavailable for %s; retrying in 6h.",
                self._format_area_names(suppressed_this_run),
            )

        if recovered_this_run:
            self.logger.info(
                "ENTSO-e wind and solar forecast data resumed for: %s.",
                self._format_area_names(recovered_this_run),
            )

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

    def get_area_keys(self) -> list[str]:
        """Return list of areas with available data."""
        return sorted(self._area_data.keys())

    def get_area_current_value(self, area_key: str, category: str, reference: datetime | None = None) -> float | None:
        """Get current value for a specific area and category."""
        if area_key not in self._area_data:
            return None
        timestamp = self._select_current_timestamp(reference)
        if timestamp is None:
            return None
        return self._area_data[area_key].get(timestamp, {}).get(category)

    def get_area_timeline(self, area_key: str, category: str) -> dict[str, float]:
        """Get timeline for a specific area and category."""
        if area_key not in self._area_data:
            return {}
        timeline: dict[str, float] = {}
        for timestamp, values in sorted(self._area_data[area_key].items()):
            if category not in values:
                continue
            timeline[timestamp.isoformat()] = float(values[category])
        return timeline

    def get_all_area_timelines(self, category: str) -> dict[str, dict[str, float]]:
        """Get timelines for all areas for a specific category."""
        result: dict[str, dict[str, float]] = {}
        for area_key in self._area_data:
            timeline = self.get_area_timeline(area_key, category)
            if timeline:
                result[area_key] = timeline
        return result
