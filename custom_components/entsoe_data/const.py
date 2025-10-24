from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import Tuple

from .api_client import (
    PROCESS_TYPE_DAY_AHEAD,
    PROCESS_TYPE_MONTH_AHEAD,
    PROCESS_TYPE_WEEK_AHEAD,
    PROCESS_TYPE_YEAR_AHEAD,
)

ATTRIBUTION = "Data provided by ENTSO-e Transparency Platform"
DOMAIN = "entsoe_data"
UNIQUE_ID = f"{DOMAIN}_component"
COMPONENT_TITLE = "ENTSO-e Data"

# Data staleness configuration
# Sensors become unavailable if data hasn't been successfully updated in
# STALENESS_MULTIPLIER times the normal update interval.
# This prevents ML models from training on unreliable/stale data.
# Default: 3x (e.g., for 60min updates, data is stale after 180min)
STALENESS_MULTIPLIER = 3

CONF_API_KEY = "api_key"
CONF_AREA = "area"
CONF_ENABLE_GENERATION = "enable_generation"
CONF_ENABLE_LOAD = "enable_load"
CONF_ENABLE_EUROPE_GENERATION = "enable_europe_generation"
CONF_ENABLE_EUROPE_LOAD = "enable_europe_load"
CONF_ENABLE_GENERATION_FORECAST = "enable_generation_forecast"
CONF_ENABLE_WIND_SOLAR_FORECAST = "enable_wind_solar_forecast"
CONF_ENABLE_EUROPE_WIND_SOLAR_FORECAST = "enable_europe_wind_solar_forecast"
CONF_ENABLE_LOAD_WEEK_AHEAD = "enable_load_week_ahead"
CONF_ENABLE_LOAD_MONTH_AHEAD = "enable_load_month_ahead"
CONF_ENABLE_LOAD_YEAR_AHEAD = "enable_load_year_ahead"
CONF_ENABLE_EUROPE_LOAD_WEEK_AHEAD = "enable_europe_load_week_ahead"
CONF_ENABLE_EUROPE_LOAD_MONTH_AHEAD = "enable_europe_load_month_ahead"
CONF_ENABLE_EUROPE_LOAD_YEAR_AHEAD = "enable_europe_load_year_ahead"
# Legacy option keys kept for backwards compatibility with existing entries
CONF_ENABLE_GENERATION_TOTAL_EUROPE = "enable_generation_total_europe"
CONF_ENABLE_LOAD_TOTAL_EUROPE = "enable_load_total_europe"
TOTAL_EUROPE_AREA = "TOTAL_EUROPE"

DEFAULT_ENABLE_GENERATION = True
DEFAULT_ENABLE_LOAD = True
DEFAULT_ENABLE_EUROPE_GENERATION = False
DEFAULT_ENABLE_EUROPE_LOAD = False
DEFAULT_ENABLE_GENERATION_FORECAST = False
DEFAULT_ENABLE_WIND_SOLAR_FORECAST = False
DEFAULT_ENABLE_EUROPE_WIND_SOLAR_FORECAST = False
DEFAULT_ENABLE_LOAD_WEEK_AHEAD = False
DEFAULT_ENABLE_LOAD_MONTH_AHEAD = False
DEFAULT_ENABLE_LOAD_YEAR_AHEAD = False
DEFAULT_ENABLE_EUROPE_LOAD_WEEK_AHEAD = False
DEFAULT_ENABLE_EUROPE_LOAD_MONTH_AHEAD = False
DEFAULT_ENABLE_EUROPE_LOAD_YEAR_AHEAD = False
DEFAULT_ENABLE_GENERATION_TOTAL_EUROPE = DEFAULT_ENABLE_EUROPE_GENERATION
DEFAULT_ENABLE_LOAD_TOTAL_EUROPE = DEFAULT_ENABLE_EUROPE_LOAD

LOAD_FORECAST_HORIZON_DAY_AHEAD = "day_ahead"
LOAD_FORECAST_HORIZON_WEEK_AHEAD = "week_ahead"
LOAD_FORECAST_HORIZON_MONTH_AHEAD = "month_ahead"
LOAD_FORECAST_HORIZON_YEAR_AHEAD = "year_ahead"


@dataclass(frozen=True)
class LoadForecastHorizonConfig:
    horizon: str
    option_key: str
    default_enabled: bool
    coordinator_key: str
    process_type: str
    update_interval: timedelta
    look_ahead: timedelta
    sensor_key_prefix: str
    sensor_name_suffix: str | None
    device_suffix: str
    europe_option_key: str
    europe_default_enabled: bool
    europe_coordinator_key: str
    europe_device_suffix: str
    legacy_europe_option_keys: Tuple[str, ...] = ()


LOAD_FORECAST_HORIZONS: Tuple[LoadForecastHorizonConfig, ...] = (
    LoadForecastHorizonConfig(
        horizon=LOAD_FORECAST_HORIZON_DAY_AHEAD,
        option_key=CONF_ENABLE_LOAD,
        default_enabled=DEFAULT_ENABLE_LOAD,
        coordinator_key="load",
        process_type=PROCESS_TYPE_DAY_AHEAD,
        update_interval=timedelta(minutes=60),
        look_ahead=timedelta(days=3),
        sensor_key_prefix="load",
        sensor_name_suffix=None,
        device_suffix="load",
        europe_option_key=CONF_ENABLE_EUROPE_LOAD,
        europe_default_enabled=DEFAULT_ENABLE_EUROPE_LOAD,
        europe_coordinator_key="load_europe",
        europe_device_suffix="total_europe_load",
        legacy_europe_option_keys=(CONF_ENABLE_LOAD_TOTAL_EUROPE,),
    ),
    LoadForecastHorizonConfig(
        horizon=LOAD_FORECAST_HORIZON_WEEK_AHEAD,
        option_key=CONF_ENABLE_LOAD_WEEK_AHEAD,
        default_enabled=DEFAULT_ENABLE_LOAD_WEEK_AHEAD,
        coordinator_key="load_week_ahead",
        process_type=PROCESS_TYPE_WEEK_AHEAD,
        update_interval=timedelta(hours=6),
        look_ahead=timedelta(days=14),
        sensor_key_prefix="load_week_ahead",
        sensor_name_suffix="Week-ahead",
        device_suffix="load_week_ahead",
        europe_option_key=CONF_ENABLE_EUROPE_LOAD_WEEK_AHEAD,
        europe_default_enabled=DEFAULT_ENABLE_EUROPE_LOAD_WEEK_AHEAD,
        europe_coordinator_key="load_week_ahead_europe",
        europe_device_suffix="total_europe_load_week_ahead",
    ),
    LoadForecastHorizonConfig(
        horizon=LOAD_FORECAST_HORIZON_MONTH_AHEAD,
        option_key=CONF_ENABLE_LOAD_MONTH_AHEAD,
        default_enabled=DEFAULT_ENABLE_LOAD_MONTH_AHEAD,
        coordinator_key="load_month_ahead",
        process_type=PROCESS_TYPE_MONTH_AHEAD,
        update_interval=timedelta(hours=12),
        look_ahead=timedelta(days=62),
        sensor_key_prefix="load_month_ahead",
        sensor_name_suffix="Month-ahead",
        device_suffix="load_month_ahead",
        europe_option_key=CONF_ENABLE_EUROPE_LOAD_MONTH_AHEAD,
        europe_default_enabled=DEFAULT_ENABLE_EUROPE_LOAD_MONTH_AHEAD,
        europe_coordinator_key="load_month_ahead_europe",
        europe_device_suffix="total_europe_load_month_ahead",
    ),
    LoadForecastHorizonConfig(
        horizon=LOAD_FORECAST_HORIZON_YEAR_AHEAD,
        option_key=CONF_ENABLE_LOAD_YEAR_AHEAD,
        default_enabled=DEFAULT_ENABLE_LOAD_YEAR_AHEAD,
        coordinator_key="load_year_ahead",
        process_type=PROCESS_TYPE_YEAR_AHEAD,
        update_interval=timedelta(hours=24),
        look_ahead=timedelta(days=370),
        sensor_key_prefix="load_year_ahead",
        sensor_name_suffix="Year-ahead",
        device_suffix="load_year_ahead",
        europe_option_key=CONF_ENABLE_EUROPE_LOAD_YEAR_AHEAD,
        europe_default_enabled=DEFAULT_ENABLE_EUROPE_LOAD_YEAR_AHEAD,
        europe_coordinator_key="load_year_ahead_europe",
        europe_device_suffix="total_europe_load_year_ahead",
    ),
)

LOAD_FORECAST_HORIZON_MAP = {
    horizon.horizon: horizon for horizon in LOAD_FORECAST_HORIZONS
}

LOAD_FORECAST_OPTION_KEYS: Tuple[str, ...] = tuple(
    horizon.option_key for horizon in LOAD_FORECAST_HORIZONS
)

LOAD_FORECAST_EUROPE_OPTION_KEYS: Tuple[str, ...] = tuple(
    horizon.europe_option_key for horizon in LOAD_FORECAST_HORIZONS
)

# Commented ones are not working at entsoe
AREA_INFO = {
    TOTAL_EUROPE_AREA: {
        "code": "10Y1001A1001A876",
        "name": "Total Europe",
        "VAT": 0.0,
        "Currency": "EUR",
    },
    "AT": {"code": "AT", "name": "Austria", "VAT": 0.21, "Currency": "EUR"},
    "BE": {"code": "BE", "name": "Belgium", "VAT": 0.06, "Currency": "EUR"},
    "BG": {"code": "BG", "name": "Bulgaria", "VAT": 0.21, "Currency": "EUR"},
    "HR": {"code": "HR", "name": "Croatia", "VAT": 0.21, "Currency": "EUR"},
    "CZ": {"code": "CZ", "name": "Czech Republic", "VAT": 0.21, "Currency": "EUR"},
    "DK_1": {
        "code": "DK_1",
        "name": "Denmark Western (DK1)",
        "VAT": 0.21,
        "Currency": "EUR",
    },
    "DK_2": {
        "code": "DK_2",
        "name": "Denmark Eastern (DK2)",
        "VAT": 0.21,
        "Currency": "EUR",
    },
    "EE": {"code": "EE", "name": "Estonia", "VAT": 0.21, "Currency": "EUR"},
    "FI": {"code": "FI", "name": "Finland", "VAT": 0.255, "Currency": "EUR"},
    "FR": {"code": "FR", "name": "France", "VAT": 0.21, "Currency": "EUR"},
    "LU": {"code": "DE_LU", "name": "Luxembourg", "VAT": 0.21, "Currency": "EUR"},
    "DE": {"code": "DE_LU", "name": "Germany", "VAT": 0.21, "Currency": "EUR"},
    "GR": {"code": "GR", "name": "Greece", "VAT": 0.21, "Currency": "EUR"},
    "HU": {"code": "HU", "name": "Hungary", "VAT": 0.21, "Currency": "EUR"},
    "IT_CNOR": {
        "code": "IT_CNOR",
        "name": "Italy Centre North",
        "VAT": 0.21,
        "Currency": "EUR",
    },
    "IT_CSUD": {
        "code": "IT_CSUD",
        "name": "Italy Centre South",
        "VAT": 0.21,
        "Currency": "EUR",
    },
    "IT_NORD": {
        "code": "IT_NORD",
        "name": "Italy North",
        "VAT": 0.21,
        "Currency": "EUR",
    },
    "IT_SUD": {"code": "IT_SUD", "name": "Italy South", "VAT": 0.21, "Currency": "EUR"},
    "IT_SICI": {
        "code": "IT_SICI",
        "name": "Italy Sicilia",
        "VAT": 0.21,
        "Currency": "EUR",
    },
    "IT_SARD": {
        "code": "IT_SARD",
        "name": "Italy Sardinia",
        "VAT": 0.21,
        "Currency": "EUR",
    },
    "IT_CALA": {
        "code": "IT_CALA",
        "name": "Italy Calabria",
        "VAT": 0.21,
        "Currency": "EUR",
    },
    "LV": {"code": "LV", "name": "Latvia", "VAT": 0.21, "Currency": "EUR"},
    "LT": {"code": "LT", "name": "Lithuania", "VAT": 0.21, "Currency": "EUR"},
    "NL": {"code": "NL", "name": "Netherlands", "VAT": 0.21, "Currency": "EUR"},
    "NO_1": {
        "code": "NO_1",
        "name": "Norway Oslo (NO1)",
        "VAT": 0.25,
        "Currency": "EUR",
    },
    "NO_2": {
        "code": "NO_2",
        "name": "Norway Kr.Sand (NO2)",
        "VAT": 0.25,
        "Currency": "EUR",
    },
    "NO_3": {
        "code": "NO_3",
        "name": "Norway Tr.heim (NO3)",
        "VAT": 0.25,
        "Currency": "EUR",
    },
    "NO_4": {
        "code": "NO_4",
        "name": "Norway Tromsø (NO4)",
        "VAT": 0,
        "Currency": "EUR",
    },
    "NO_5": {
        "code": "NO_5",
        "name": "Norway Bergen (NO5)",
        "VAT": 0.25,
        "Currency": "EUR",
    },
    "PL": {"code": "PL", "name": "Poland", "VAT": 0.21, "Currency": "EUR"},
    "PT": {"code": "PT", "name": "Portugal", "VAT": 0.21, "Currency": "EUR"},
    "RO": {"code": "RO", "name": "Romania", "VAT": 0.21, "Currency": "EUR"},
    "RS": {"code": "RS", "name": "Serbia", "VAT": 0.21, "Currency": "EUR"},
    "SK": {"code": "SK", "name": "Slovakia", "VAT": 0.21, "Currency": "EUR"},
    "SI": {"code": "SI", "name": "Slovenia", "VAT": 0.21, "Currency": "EUR"},
    "ES": {"code": "ES", "name": "Spain", "VAT": 0.21, "Currency": "EUR"},
    "SE_1": {
        "code": "SE_1",
        "name": "Sweden Luleå (SE1)",
        "VAT": 0.25,
        "Currency": "EUR",
    },
    "SE_2": {
        "code": "SE_2",
        "name": "Sweden Sundsvall (SE2)",
        "VAT": 0.25,
        "Currency": "EUR",
    },
    "SE_3": {
        "code": "SE_3",
        "name": "Sweden Stockholm (SE3)",
        "VAT": 0.25,
        "Currency": "EUR",
    },
    "SE_4": {
        "code": "SE_4",
        "name": "Sweden Malmö (SE4)",
        "VAT": 0.25,
        "Currency": "EUR",
    },
    "CH": {"code": "CH", "name": "Switzerland", "VAT": 0.21, "Currency": "EUR"},
    #  "UK":{"code":"UK", "name":"United Kingdom", "VAT":0.21, "Currency":"EUR"},
    #  "AL":{"code":"AL", "name":"Albania", "VAT":0.21, "Currency":"EUR"},
    #  "BA":{"code":"BA", "name":"Bosnia and Herz.", "VAT":0.21, "Currency":"EUR"},
    #  "CY":{"code":"CY", "name":"Cyprus", "VAT":0.21, "Currency":"EUR"},
    #  "GE":{"code":"GE", "name":"Georgia", "VAT":0.21, "Currency":"EUR"},
    #  "IE":{"code":"IE", "name":"Ireland", "VAT":0.21, "Currency":"EUR"},
    #  "XK":{"code":"XK", "name":"Kosovo", "VAT":0.21, "Currency":"EUR"},
    #  "MT":{"code":"MT", "name":"Malta", "VAT":0.21, "Currency":"EUR"},
    #  "MD":{"code":"MD", "name":"Moldova", "VAT":0.21, "Currency":"EUR"},
    #  "ME":{"code":"ME", "name":"Montenegro", "VAT":0.21, "Currency":"EUR"},
    #  "MK":{"code":"MK", "name":"North Macedonia", "VAT":0.21, "Currency":"EUR"},
    #  "TR":{"code":"TR", "name":"Turkey", "VAT":0.21, "Currency":"EUR"},
    #  "UA":{"code":"UA", "name":"Ukraine", "VAT":0.21, "Currency":"EUR"},
}
