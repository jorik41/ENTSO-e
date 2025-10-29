from __future__ import annotations

import enum
import io
import logging
import zipfile
import xml.etree.ElementTree as ET
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Dict, Union

import pytz
import requests
from requests.adapters import HTTPAdapter
from requests import exceptions as requests_exceptions
from urllib3.util.retry import Retry

_LOGGER = logging.getLogger(__name__)
BASE_URLS: tuple[str, ...] = (
    "https://web-api.tp.entsoe.eu/api",
    "https://api.transparency.entsoe.eu/api",
)
REQUEST_TIMEOUT = 30
DATETIMEFORMAT = "%Y%m%d%H00"

DOCUMENT_TYPE_GENERATION_PER_TYPE = "A75"
DOCUMENT_TYPE_GENERATION_FORECAST = "A71"
DOCUMENT_TYPE_TOTAL_LOAD = "A65"
DOCUMENT_TYPE_WIND_SOLAR_FORECAST = "A69"

PROCESS_TYPE_REALISED = "A16"
PROCESS_TYPE_DAY_AHEAD = "A01"
PROCESS_TYPE_INTRADAY = "A18"
PROCESS_TYPE_WEEK_AHEAD = "A31"
PROCESS_TYPE_MONTH_AHEAD = "A32"
PROCESS_TYPE_YEAR_AHEAD = "A33"

PSR_CATEGORY_MAPPING = {
    "B01": "biomass",
    "B02": "coal",
    "B03": "coal",
    "B04": "fossil_gas",
    "B05": "coal",
    "B06": "oil",
    "B07": "oil_shale",
    "B08": "peat",
    "B09": "geothermal",
    "B10": "hydro_pumped_storage",
    "B11": "hydro_run_of_river",
    "B12": "hydro_reservoir",
    "B13": "marine",
    "B14": "nuclear",
    "B15": "other_renewable",
    "B16": "solar",
    "B17": "waste",
    "B18": "wind_offshore",
    "B19": "wind_onshore",
    "B20": "other",
    "B21": "interconnector",
    "B22": "interconnector",
    "B23": "infrastructure",
    "B24": "transformer",
    "B25": "energy_storage",
    "B26": "other",
    "B27": "coal",
    "B28": "hydro",
}


class EntsoeClient:

    def __init__(self, api_key: str):
        if api_key == "":
            raise TypeError("API key cannot be empty")
        self.api_key = api_key
        self._session: requests.Session = requests.Session()
        retry = Retry(
            total=3,
            connect=3,
            read=3,
            status=3,
            status_forcelist=(500, 502, 503, 504),
            backoff_factor=1.0,
            allowed_methods=["GET", "HEAD", "OPTIONS"],
            raise_on_status=False,
        )
        adapter = HTTPAdapter(max_retries=retry)
        self._session.mount("https://", adapter)
        self._session.mount("http://", adapter)

    def _base_request(
        self, params: Dict, start: datetime, end: datetime
    ) -> requests.Response:

        base_params = {
            "securityToken": self.api_key,
            "periodStart": start.strftime(DATETIMEFORMAT),
            "periodEnd": end.strftime(DATETIMEFORMAT),
        }
        params.update(base_params)

        last_error: Exception | None = None

        for url in BASE_URLS:
            _LOGGER.debug("Performing request to %s with params %s", url, params)
            try:
                response = self._session.get(
                    url=url,
                    params=params,
                    timeout=REQUEST_TIMEOUT,
                )
                response.raise_for_status()
                return response
            except requests_exceptions.HTTPError as exc:
                status = exc.response.status_code if exc.response is not None else None
                if status in (500, 502, 503, 504):
                    _LOGGER.warning(
                        "Received %s from %s, trying next ENTSO-e endpoint", status, url
                    )
                    last_error = exc
                    continue
                raise
            except requests_exceptions.RequestException as exc:  # includes timeouts
                _LOGGER.warning("Error contacting %s: %s", url, exc)
                last_error = exc
                continue

        if last_error is None:  # pragma: no cover - defensive guard
            raise RuntimeError(
                "All ENTSO-e endpoints failed, but no error was captured."
            )
        raise last_error

    def _iter_response_documents(self, response: requests.Response) -> list[bytes]:
        content_type = response.headers.get("Content-Type", "")
        treat_as_zip = "zip" in content_type.lower()
        content = response.content

        buffer = io.BytesIO(content)
        if not treat_as_zip:
            treat_as_zip = zipfile.is_zipfile(buffer)
        if not treat_as_zip:
            return [content]

        buffer.seek(0)

        try:
            with zipfile.ZipFile(buffer) as archive:
                members = [name for name in archive.namelist() if not name.endswith("/")]
                if not members:
                    raise ValueError("Zip archive did not contain any files")

                xml_members = [name for name in members if name.lower().endswith(".xml")]
                selected_members = sorted(xml_members or members)

                return [archive.read(name) for name in selected_members]
        except zipfile.BadZipFile as exc:  # pragma: no cover - defensive guard
            _LOGGER.error("Failed to read ENTSO-e zip response: %s", exc)
            raise ValueError("ENTSO-e response payload is not a valid ZIP archive") from exc

    def _remove_namespace(self, tree):
        """Remove namespaces in the passed XML tree for easier tag searching."""
        for elem in tree.iter():
            # Remove the namespace if present
            if "}" in elem.tag:
                elem.tag = elem.tag.split("}", 1)[1]
        return tree

    def _parse_timestamp(self, value: str) -> datetime:
        return (
            datetime.strptime(value, "%Y-%m-%dT%H:%MZ")
            .replace(tzinfo=pytz.UTC)
            .astimezone()
        )

    def _normalize_resolution(self, resolution: str) -> str:
        if resolution in ("PT60M", "PT1H"):
            return "PT60M"
        if resolution == "PT15M":
            return "PT15M"
        raise ValueError(f"Unsupported resolution {resolution}")

    def _fill_missing_hours(
        self, series: Dict[datetime, float], start_time: datetime, end_time: datetime
    ) -> Dict[datetime, float]:
        current_time = start_time
        last_value = series.get(current_time)

        while current_time < end_time:
            if current_time in series:
                last_value = series[current_time]
            elif last_value is not None:
                _LOGGER.debug(
                    "Extending value %s of the previous hour to %s",
                    last_value,
                    current_time,
                )
                series[current_time] = last_value
            current_time += timedelta(hours=1)

        return series

    def query_day_ahead_prices(
        self, country_code: Union[Area, str], start: datetime, end: datetime
    ) -> str:
        """
        Parameters
        ----------
        country_code : Area|str
        start : datetime
        end : datetime

        Returns
        -------
        str
        """
        area = Area.from_identifier(country_code)
        params = {
            "documentType": "A44",
            "in_Domain": area.code,
            "out_Domain": area.code,
        }
        response = self._base_request(params=params, start=start, end=end)

        if response.status_code == 200:
            try:
                series: Dict[datetime, float] = {}
                for document in self._iter_response_documents(response):
                    series.update(self.parse_price_document(document))
                return dict(sorted(series.items()))

            except Exception as exc:
                _LOGGER.debug(f"Failed to parse response content:{response.content}")
                raise exc
        else:
            print(f"Failed to retrieve data: {response.status_code}")
            return None

    def query_generation_per_type(
        self,
        country_code: Union[Area, str],
        start: datetime,
        end: datetime,
        process_type: str = PROCESS_TYPE_REALISED,
    ) -> Dict[datetime, Dict[str, float]]:
        """Return generation per type aggregated across ENTSO-e publications.

        When the Transparency Platform responds with multiple documents, including
        ZIP archives, values for matching timestamps and categories are summed to
        produce a single consolidated series.
        """
        area = Area.from_identifier(country_code)
        process = process_type
        if not isinstance(process, str):
            process = str(process)

        normalized = process.upper()

        if normalized in ("REALIZED", "REALISED"):
            process = PROCESS_TYPE_REALISED
        elif normalized in ("DAY_AHEAD", "DAYAHEAD"):
            process = PROCESS_TYPE_DAY_AHEAD
        elif normalized == "INTRADAY":
            process = PROCESS_TYPE_INTRADAY
        elif normalized in (
            PROCESS_TYPE_REALISED,
            PROCESS_TYPE_DAY_AHEAD,
            PROCESS_TYPE_INTRADAY,
        ):
            process = normalized

        params = {
            "documentType": DOCUMENT_TYPE_GENERATION_PER_TYPE,
            "processType": process,
            "in_Domain": area.code,
            "out_Domain": area.code,
        }

        response = self._base_request(params=params, start=start, end=end)

        if response.status_code == 200:
            try:
                generation = defaultdict(lambda: defaultdict(float))
                for document in self._iter_response_documents(response):
                    parsed = self.parse_generation_per_type_document(document)
                    for timestamp, categories in parsed.items():
                        for category, value in categories.items():
                            generation[timestamp][category] += float(value)

                result: Dict[datetime, Dict[str, float]] = {}
                for timestamp in sorted(generation):
                    result[timestamp] = dict(sorted(generation[timestamp].items()))
                return result
            except Exception as exc:
                _LOGGER.debug(f"Failed to parse response content:{response.content}")
                raise exc
        else:
            print(f"Failed to retrieve data: {response.status_code}")
            return None

    def query_total_load_forecast(
        self,
        country_code: Union[Area, str],
        start: datetime,
        end: datetime,
        process_type: str = PROCESS_TYPE_DAY_AHEAD,
    ) -> Dict[datetime, float]:
        """Return aggregated total load forecasts for the requested area.

        Multiple publications returned by the API, including entries inside ZIP
        archives, are merged by summing values per timestamp.
        """
        area = Area.from_identifier(country_code)
        params = {
            "documentType": DOCUMENT_TYPE_TOTAL_LOAD,
            "processType": process_type,
            "outBiddingZone_Domain": area.code,
        }

        response = self._base_request(params=params, start=start, end=end)

        if response.status_code == 200:
            try:
                load = defaultdict(float)
                for document in self._iter_response_documents(response):
                    parsed = self.parse_total_load_document(document)
                    for timestamp, value in parsed.items():
                        load[timestamp] += float(value)

                return {timestamp: load[timestamp] for timestamp in sorted(load)}
            except Exception as exc:
                _LOGGER.debug(f"Failed to parse response content:{response.content}")
                raise exc
        else:
            print(f"Failed to retrieve data: {response.status_code}")
            return None

    def query_generation_forecast(
        self, country_code: Union[Area, str], start: datetime, end: datetime
    ) -> Dict[datetime, float]:
        """Return aggregated generation forecasts for the requested area.

        Values are summed per timestamp so responses that span multiple
        publications (e.g. ZIP archives) are combined into a single time series.
        """
        area = Area.from_identifier(country_code)
        params = {
            "documentType": DOCUMENT_TYPE_GENERATION_FORECAST,
            "processType": PROCESS_TYPE_DAY_AHEAD,
            "in_Domain": area.code,
            "out_Domain": area.code,
        }

        response = self._base_request(params=params, start=start, end=end)

        if response.status_code == 200:
            try:
                forecast = defaultdict(float)
                for document in self._iter_response_documents(response):
                    parsed = self.parse_generation_forecast_document(document)
                    for timestamp, value in parsed.items():
                        forecast[timestamp] += float(value)

                return {timestamp: float(forecast[timestamp]) for timestamp in sorted(forecast)}
            except Exception as exc:
                _LOGGER.debug(f"Failed to parse response content:{response.content}")
                raise exc
        else:
            print(f"Failed to retrieve data: {response.status_code}")
            return None

    def query_wind_solar_forecast(
        self, country_code: Union[Area, str], start: datetime, end: datetime
    ) -> Dict[datetime, Dict[str, float]]:
        """Return aggregated wind and solar forecasts for the requested area.

        Supports multi-document responses by summing values for each timestamp
        and technology across all publications delivered by the API.
        """
        area = Area.from_identifier(country_code)
        params = {
            "documentType": DOCUMENT_TYPE_WIND_SOLAR_FORECAST,
            "processType": PROCESS_TYPE_DAY_AHEAD,
            "in_Domain": area.code,
            "out_Domain": area.code,
        }

        response = self._base_request(params=params, start=start, end=end)

        if response.status_code == 200:
            try:
                forecast = defaultdict(lambda: defaultdict(float))
                for document in self._iter_response_documents(response):
                    parsed = self.parse_wind_solar_document(document)
                    for timestamp, categories in parsed.items():
                        for category, value in categories.items():
                            forecast[timestamp][category] += float(value)

                result: Dict[datetime, Dict[str, float]] = {}
                for timestamp in sorted(forecast):
                    result[timestamp] = dict(sorted(forecast[timestamp].items()))
                return result
            except Exception as exc:
                _LOGGER.debug(f"Failed to parse response content:{response.content}")
                raise exc
        else:
            print(f"Failed to retrieve data: {response.status_code}")
            return None

    # lets process the received document
    def parse_price_document(self, document: Union[str, bytes]) -> Dict[datetime, float]:

        root = self._remove_namespace(ET.fromstring(document))
        _LOGGER.debug(f"content: {root}")
        series = {}

        # for all given timeseries in this response
        # There may be overlapping times in the repsonse. For now we skip timeseries which we already processed
        for timeseries in root.findall(".//TimeSeries"):

            # for all periods in this timeseries.....-> we still asume the time intervals do not overlap, and are in sequence
            for period in timeseries.findall(".//Period"):
                # there can be different resolutions for each period (BE casus in which historical is quarterly and future is hourly)
                resolution_raw = period.find(".//resolution").text

                try:
                    resolution = self._normalize_resolution(resolution_raw)
                except ValueError:
                    continue

                start_time = self._parse_timestamp(
                    period.find(".//timeInterval/start").text
                )
                start_time.replace(minute=0)

                end_time = self._parse_timestamp(
                    period.find(".//timeInterval/end").text
                )
                _LOGGER.debug(
                    f"Period found is from {start_time} till {end_time} with resolution {resolution}"
                )
                if start_time in series:
                    _LOGGER.debug(
                        "We found a duplicate period in the response, possibly with another resolution. We skip this period"
                    )
                    continue

                if resolution == "PT60M":
                    series.update(self.process_PT60M_points(period, start_time))
                else:
                    series.update(self.process_PT15M_points(period, start_time))

                self._fill_missing_hours(series, start_time, end_time)

        return series

    # processing hourly prices info -> thats easy
    def process_PT60M_points(
        self,
        period,
        start_time: datetime,
        value_tag: str = "price.amount",
        round_digits: int | None = 2,
    ):
        data: Dict[datetime, float] = {}
        for point in period.findall(".//Point"):
            position_text = point.find(".//position")
            value_element = point.find(f".//{value_tag}")

            if position_text is None or value_element is None:
                continue

            hour = int(position_text.text) - 1
            value = float(value_element.text)
            if round_digits is not None:
                value = round(value, round_digits)
            time = start_time + timedelta(hours=hour)
            data[time] = value
        return data

    # processing quarterly prices -> this is more complex
    def process_PT15M_points(
        self,
        period,
        start_time: datetime,
        value_tag: str = "price.amount",
        round_digits: int | None = 2,
    ):
        positions: Dict[int, float] = {}

        # first store all positions
        for point in period.findall(".//Point"):
            position_element = point.find(".//position")
            value_element = point.find(f".//{value_tag}")

            if position_element is None or value_element is None:
                continue

            positions[int(position_element.text)] = float(value_element.text)

        if not positions:
            return {}

        # now calculate hourly averages based on available points
        data: Dict[datetime, float] = {}
        last_hour = (max(positions.keys()) + 3) // 4
        last_value = positions[min(positions.keys())]

        for hour in range(last_hour):
            sum_values = 0.0
            count = 0
            for idx in range(hour * 4 + 1, hour * 4 + 5):
                last_value = positions.get(idx, last_value)
                sum_values += last_value
                count += 1

            average = sum_values / max(count, 1)
            if round_digits is not None:
                average = round(average, round_digits)

            time = start_time + timedelta(hours=hour)
            data[time] = average

        return data

    def parse_generation_per_type_document(
        self, document: Union[str, bytes]
    ) -> Dict[datetime, Dict[str, float]]:
        root = self._remove_namespace(ET.fromstring(document))
        generation = defaultdict(lambda: defaultdict(float))

        for timeseries in root.findall(".//TimeSeries"):
            psr_type = timeseries.findtext(".//MktPSRType/psrType")
            category = PSR_CATEGORY_MAPPING.get(psr_type, "other")

            for period in timeseries.findall(".//Period"):
                resolution_raw = period.find(".//resolution").text

                try:
                    resolution = self._normalize_resolution(resolution_raw)
                except ValueError:
                    continue

                start_time = self._parse_timestamp(
                    period.find(".//timeInterval/start").text
                )
                end_time = self._parse_timestamp(period.find(".//timeInterval/end").text)

                if resolution == "PT60M":
                    points = self.process_PT60M_points(
                        period,
                        start_time,
                        value_tag="quantity",
                        round_digits=None,
                    )
                else:
                    points = self.process_PT15M_points(
                        period,
                        start_time,
                        value_tag="quantity",
                        round_digits=None,
                    )

                points = self._fill_missing_hours(points, start_time, end_time)

                for timestamp, value in points.items():
                    generation[timestamp][category] += value

        result: Dict[datetime, Dict[str, float]] = {}
        for timestamp in sorted(generation.keys()):
            result[timestamp] = dict(sorted(generation[timestamp].items()))

        return result

    def parse_generation_forecast_document(
        self, document: Union[str, bytes]
    ) -> Dict[datetime, float]:
        root = self._remove_namespace(ET.fromstring(document))
        forecast = defaultdict(float)

        for timeseries in root.findall(".//TimeSeries"):
            for period in timeseries.findall(".//Period"):
                resolution_raw = period.find(".//resolution").text

                try:
                    resolution = self._normalize_resolution(resolution_raw)
                except ValueError:
                    continue

                start_time = self._parse_timestamp(
                    period.find(".//timeInterval/start").text
                )
                end_time = self._parse_timestamp(
                    period.find(".//timeInterval/end").text
                )

                if resolution == "PT60M":
                    points = self.process_PT60M_points(
                        period,
                        start_time,
                        value_tag="quantity",
                        round_digits=None,
                    )
                else:
                    points = self.process_PT15M_points(
                        period,
                        start_time,
                        value_tag="quantity",
                        round_digits=None,
                    )

                points = self._fill_missing_hours(points, start_time, end_time)

                for timestamp, value in points.items():
                    forecast[timestamp] += value

        return {timestamp: float(forecast[timestamp]) for timestamp in sorted(forecast)}

    def parse_wind_solar_document(
        self, document: Union[str, bytes]
    ) -> Dict[datetime, Dict[str, float]]:
        root = self._remove_namespace(ET.fromstring(document))
        forecast = defaultdict(lambda: defaultdict(float))

        for timeseries in root.findall(".//TimeSeries"):
            psr_type = timeseries.findtext(".//MktPSRType/psrType")
            category = PSR_CATEGORY_MAPPING.get(psr_type, "other")

            for period in timeseries.findall(".//Period"):
                resolution_raw = period.find(".//resolution").text

                try:
                    resolution = self._normalize_resolution(resolution_raw)
                except ValueError:
                    continue

                start_time = self._parse_timestamp(
                    period.find(".//timeInterval/start").text
                )
                end_time = self._parse_timestamp(
                    period.find(".//timeInterval/end").text
                )

                if resolution == "PT60M":
                    points = self.process_PT60M_points(
                        period,
                        start_time,
                        value_tag="quantity",
                        round_digits=None,
                    )
                else:
                    points = self.process_PT15M_points(
                        period,
                        start_time,
                        value_tag="quantity",
                        round_digits=None,
                    )

                points = self._fill_missing_hours(points, start_time, end_time)

                for timestamp, value in points.items():
                    forecast[timestamp][category] += value

        result: Dict[datetime, Dict[str, float]] = {}
        for timestamp in sorted(forecast.keys()):
            result[timestamp] = dict(sorted(forecast[timestamp].items()))

        return result

    def parse_total_load_document(
        self, document: Union[str, bytes]
    ) -> Dict[datetime, float]:
        root = self._remove_namespace(ET.fromstring(document))
        load = defaultdict(float)

        for timeseries in root.findall(".//TimeSeries"):
            for period in timeseries.findall(".//Period"):
                resolution_raw = period.find(".//resolution").text

                try:
                    resolution = self._normalize_resolution(resolution_raw)
                except ValueError:
                    continue

                start_time = self._parse_timestamp(
                    period.find(".//timeInterval/start").text
                )
                end_time = self._parse_timestamp(period.find(".//timeInterval/end").text)

                if resolution == "PT60M":
                    points = self.process_PT60M_points(
                        period,
                        start_time,
                        value_tag="quantity",
                        round_digits=None,
                    )
                else:
                    points = self.process_PT15M_points(
                        period,
                        start_time,
                        value_tag="quantity",
                        round_digits=None,
                    )

                points = self._fill_missing_hours(points, start_time, end_time)

                for timestamp, value in points.items():
                    load[timestamp] += value

        return {timestamp: load[timestamp] for timestamp in sorted(load.keys())}


class Area(enum.Enum):
    """
    ENUM containing 3 things about an Area: CODE, Meaning, Timezone
    """

    def __new__(cls, *args, **kwds):
        obj = object.__new__(cls)
        obj._value_ = args[0]
        return obj

    # ignore the first param since it's already set by __new__
    def __init__(self, _: str, meaning: str, tz: str):
        self._meaning = meaning
        self._tz = tz

    def __str__(self):
        return self.value

    @property
    def meaning(self):
        return self._meaning

    @property
    def tz(self):
        return self._tz

    @property
    def code(self):
        return self.value

    @classmethod
    def has_code(cls, code: str) -> bool:
        if not isinstance(code, str):
            return False

        normalized = code.upper()

        return (
            normalized in cls.__members__
            or code in cls._value2member_map_
            or normalized in cls._value2member_map_
        )

    @classmethod
    def from_identifier(cls, value: Union["Area", str]) -> "Area":
        """Resolve an ``Area`` from either an enum member, name or EIC code."""

        if isinstance(value, cls):
            return value

        if not isinstance(value, str):
            raise KeyError(f"Unknown area identifier: {value}")

        name = value.upper()
        if name in cls.__members__:
            return cls[name]

        if value in cls._value2member_map_:
            return cls._value2member_map_[value]

        if name in cls._value2member_map_:
            return cls._value2member_map_[name]

        raise KeyError(f"Unknown area identifier: {value}")

    # List taken directly from the API Docs
    DE_50HZ = (
        "10YDE-VE-------2",
        "50Hertz CA, DE(50HzT) BZA",
        "Europe/Berlin",
    )
    AL = (
        "10YAL-KESH-----5",
        "Albania, OST BZ / CA / MBA",
        "Europe/Tirane",
    )
    DE_AMPRION = (
        "10YDE-RWENET---I",
        "Amprion CA",
        "Europe/Berlin",
    )
    AT = (
        "10YAT-APG------L",
        "Austria, APG BZ / CA / MBA",
        "Europe/Vienna",
    )
    BY = (
        "10Y1001A1001A51S",
        "Belarus BZ / CA / MBA",
        "Europe/Minsk",
    )
    BE = (
        "10YBE----------2",
        "Belgium, Elia BZ / CA / MBA",
        "Europe/Brussels",
    )
    BA = (
        "10YBA-JPCC-----D",
        "Bosnia Herzegovina, NOS BiH BZ / CA / MBA",
        "Europe/Sarajevo",
    )
    BG = (
        "10YCA-BULGARIA-R",
        "Bulgaria, ESO BZ / CA / MBA",
        "Europe/Sofia",
    )
    CZ_DE_SK = (
        "10YDOM-CZ-DE-SKK",
        "BZ CZ+DE+SK BZ / BZA",
        "Europe/Prague",
    )
    HR = (
        "10YHR-HEP------M",
        "Croatia, HOPS BZ / CA / MBA",
        "Europe/Zagreb",
    )
    CWE = (
        "10YDOM-REGION-1V",
        "CWE Region",
        "Europe/Brussels",
    )
    TOTAL_EUROPE = (
        "10Y1001A1001A876",
        "Total Europe",
        "Europe/Brussels",
    )
    CY = (
        "10YCY-1001A0003J",
        "Cyprus, Cyprus TSO BZ / CA / MBA",
        "Asia/Nicosia",
    )
    CZ = (
        "10YCZ-CEPS-----N",
        "Czech Republic, CEPS BZ / CA/ MBA",
        "Europe/Prague",
    )
    DE_AT_LU = (
        "10Y1001A1001A63L",
        "DE-AT-LU BZ",
        "Europe/Berlin",
    )
    DE_LU = (
        "10Y1001A1001A82H",
        "DE-LU BZ / MBA",
        "Europe/Berlin",
    )
    DK = (
        "10Y1001A1001A65H",
        "Denmark",
        "Europe/Copenhagen",
    )
    DK_1 = (
        "10YDK-1--------W",
        "DK1 BZ / MBA",
        "Europe/Copenhagen",
    )
    DK_1_NO_1 = (
        "46Y000000000007M",
        "DK1 NO1 BZ",
        "Europe/Copenhagen",
    )
    DK_2 = (
        "10YDK-2--------M",
        "DK2 BZ / MBA",
        "Europe/Copenhagen",
    )
    DK_CA = (
        "10Y1001A1001A796",
        "Denmark, Energinet CA",
        "Europe/Copenhagen",
    )
    EE = (
        "10Y1001A1001A39I",
        "Estonia, Elering BZ / CA / MBA",
        "Europe/Tallinn",
    )
    FI = (
        "10YFI-1--------U",
        "Finland, Fingrid BZ / CA / MBA",
        "Europe/Helsinki",
    )
    MK = (
        "10YMK-MEPSO----8",
        "Former Yugoslav Republic of Macedonia, MEPSO BZ / CA / MBA",
        "Europe/Skopje",
    )
    FR = (
        "10YFR-RTE------C",
        "France, RTE BZ / CA / MBA",
        "Europe/Paris",
    )
    DE = "10Y1001A1001A83F", "Germany", "Europe/Berlin"
    GR = (
        "10YGR-HTSO-----Y",
        "Greece, IPTO BZ / CA/ MBA",
        "Europe/Athens",
    )
    HU = (
        "10YHU-MAVIR----U",
        "Hungary, MAVIR CA / BZ / MBA",
        "Europe/Budapest",
    )
    IS = (
        "IS",
        "Iceland",
        "Atlantic/Reykjavik",
    )
    IE_SEM = (
        "10Y1001A1001A59C",
        "Ireland (SEM) BZ / MBA",
        "Europe/Dublin",
    )
    IE = (
        "10YIE-1001A00010",
        "Ireland, EirGrid CA",
        "Europe/Dublin",
    )
    IT = (
        "10YIT-GRTN-----B",
        "Italy, IT CA / MBA",
        "Europe/Rome",
    )
    IT_SACO_AC = (
        "10Y1001A1001A885",
        "Italy_Saco_AC",
        "Europe/Rome",
    )
    IT_CALA = (
        "10Y1001C--00096J",
        "IT-Calabria BZ",
        "Europe/Rome",
    )
    IT_SACO_DC = (
        "10Y1001A1001A893",
        "Italy_Saco_DC",
        "Europe/Rome",
    )
    IT_BRNN = (
        "10Y1001A1001A699",
        "IT-Brindisi BZ",
        "Europe/Rome",
    )
    IT_CNOR = (
        "10Y1001A1001A70O",
        "IT-Centre-North BZ",
        "Europe/Rome",
    )
    IT_CSUD = (
        "10Y1001A1001A71M",
        "IT-Centre-South BZ",
        "Europe/Rome",
    )
    IT_FOGN = (
        "10Y1001A1001A72K",
        "IT-Foggia BZ",
        "Europe/Rome",
    )
    IT_GR = (
        "10Y1001A1001A66F",
        "IT-GR BZ",
        "Europe/Rome",
    )
    IT_MACRO_NORTH = (
        "10Y1001A1001A84D",
        "IT-MACROZONE NORTH MBA",
        "Europe/Rome",
    )
    IT_MACRO_SOUTH = (
        "10Y1001A1001A85B",
        "IT-MACROZONE SOUTH MBA",
        "Europe/Rome",
    )
    IT_MALTA = (
        "10Y1001A1001A877",
        "IT-Malta BZ",
        "Europe/Rome",
    )
    IT_NORD = (
        "10Y1001A1001A73I",
        "IT-North BZ",
        "Europe/Rome",
    )
    IT_NORD_AT = (
        "10Y1001A1001A80L",
        "IT-North-AT BZ",
        "Europe/Rome",
    )
    IT_NORD_CH = (
        "10Y1001A1001A68B",
        "IT-North-CH BZ",
        "Europe/Rome",
    )
    IT_NORD_FR = (
        "10Y1001A1001A81J",
        "IT-North-FR BZ",
        "Europe/Rome",
    )
    IT_NORD_SI = (
        "10Y1001A1001A67D",
        "IT-North-SI BZ",
        "Europe/Rome",
    )
    IT_PRGP = (
        "10Y1001A1001A76C",
        "IT-Priolo BZ",
        "Europe/Rome",
    )
    IT_ROSN = (
        "10Y1001A1001A77A",
        "IT-Rossano BZ",
        "Europe/Rome",
    )
    IT_SARD = (
        "10Y1001A1001A74G",
        "IT-Sardinia BZ",
        "Europe/Rome",
    )
    IT_SICI = (
        "10Y1001A1001A75E",
        "IT-Sicily BZ",
        "Europe/Rome",
    )
    IT_SUD = (
        "10Y1001A1001A788",
        "IT-South BZ",
        "Europe/Rome",
    )
    RU_KGD = (
        "10Y1001A1001A50U",
        "Kaliningrad BZ / CA / MBA",
        "Europe/Kaliningrad",
    )
    LV = (
        "10YLV-1001A00074",
        "Latvia, AST BZ / CA / MBA",
        "Europe/Riga",
    )
    LT = (
        "10YLT-1001A0008Q",
        "Lithuania, Litgrid BZ / CA / MBA",
        "Europe/Vilnius",
    )
    LU = (
        "10YLU-CEGEDEL-NQ",
        "Luxembourg, CREOS CA",
        "Europe/Luxembourg",
    )
    LU_BZN = (
        "10Y1001A1001A82H",
        "Luxembourg",
        "Europe/Luxembourg",
    )
    MT = (
        "10Y1001A1001A93C",
        "Malta, Malta BZ / CA / MBA",
        "Europe/Malta",
    )
    ME = (
        "10YCS-CG-TSO---S",
        "Montenegro, CGES BZ / CA / MBA",
        "Europe/Podgorica",
    )
    GB = (
        "10YGB----------A",
        "National Grid BZ / CA/ MBA",
        "Europe/London",
    )
    GE = (
        "10Y1001A1001B012",
        "Georgia",
        "Asia/Tbilisi",
    )
    GB_IFA = (
        "10Y1001C--00098F",
        "GB(IFA) BZN",
        "Europe/London",
    )
    GB_IFA2 = (
        "17Y0000009369493",
        "GB(IFA2) BZ",
        "Europe/London",
    )
    GB_ELECLINK = (
        "11Y0-0000-0265-K",
        "GB(ElecLink) BZN",
        "Europe/London",
    )
    UK = (
        "10Y1001A1001A92E",
        "United Kingdom",
        "Europe/London",
    )
    NL = (
        "10YNL----------L",
        "Netherlands, TenneT NL BZ / CA/ MBA",
        "Europe/Amsterdam",
    )
    NO_1 = (
        "10YNO-1--------2",
        "NO1 BZ / MBA",
        "Europe/Oslo",
    )
    NO_1A = (
        "10Y1001A1001A64J",
        "NO1 A BZ",
        "Europe/Oslo",
    )
    NO_2 = (
        "10YNO-2--------T",
        "NO2 BZ / MBA",
        "Europe/Oslo",
    )
    NO_2_NSL = (
        "50Y0JVU59B4JWQCU",
        "NO2 NSL BZ / MBA",
        "Europe/Oslo",
    )
    NO_2A = (
        "10Y1001C--001219",
        "NO2 A BZ",
        "Europe/Oslo",
    )
    NO_3 = (
        "10YNO-3--------J",
        "NO3 BZ / MBA",
        "Europe/Oslo",
    )
    NO_4 = (
        "10YNO-4--------9",
        "NO4 BZ / MBA",
        "Europe/Oslo",
    )
    NO_5 = (
        "10Y1001A1001A48H",
        "NO5 BZ / MBA",
        "Europe/Oslo",
    )
    NO = (
        "10YNO-0--------C",
        "Norway, Norway MBA, Stattnet CA",
        "Europe/Oslo",
    )
    PL_CZ = (
        "10YDOM-1001A082L",
        "PL-CZ BZA / CA",
        "Europe/Warsaw",
    )
    PL = (
        "10YPL-AREA-----S",
        "Poland, PSE SA BZ / BZA / CA / MBA",
        "Europe/Warsaw",
    )
    PT = (
        "10YPT-REN------W",
        "Portugal, REN BZ / CA / MBA",
        "Europe/Lisbon",
    )
    MD = (
        "10Y1001A1001A990",
        "Republic of Moldova, Moldelectica BZ/CA/MBA",
        "Europe/Chisinau",
    )
    RO = (
        "10YRO-TEL------P",
        "Romania, Transelectrica BZ / CA/ MBA",
        "Europe/Bucharest",
    )
    RU = (
        "10Y1001A1001A49F",
        "Russia BZ / CA / MBA",
        "Europe/Moscow",
    )
    SE_1 = (
        "10Y1001A1001A44P",
        "SE1 BZ / MBA",
        "Europe/Stockholm",
    )
    SE_2 = (
        "10Y1001A1001A45N",
        "SE2 BZ / MBA",
        "Europe/Stockholm",
    )
    SE_3 = (
        "10Y1001A1001A46L",
        "SE3 BZ / MBA",
        "Europe/Stockholm",
    )
    SE_4 = (
        "10Y1001A1001A47J",
        "SE4 BZ / MBA",
        "Europe/Stockholm",
    )
    RS = (
        "10YCS-SERBIATSOV",
        "Serbia, EMS BZ / CA / MBA",
        "Europe/Belgrade",
    )
    SK = (
        "10YSK-SEPS-----K",
        "Slovakia, SEPS BZ / CA / MBA",
        "Europe/Bratislava",
    )
    SI = (
        "10YSI-ELES-----O",
        "Slovenia, ELES BZ / CA / MBA",
        "Europe/Ljubljana",
    )
    GB_NIR = (
        "10Y1001A1001A016",
        "Northern Ireland, SONI CA",
        "Europe/Belfast",
    )
    ES = (
        "10YES-REE------0",
        "Spain, REE BZ / CA / MBA",
        "Europe/Madrid",
    )
    SE = (
        "10YSE-1--------K",
        "Sweden, Sweden MBA, SvK CA",
        "Europe/Stockholm",
    )
    CH = (
        "10YCH-SWISSGRIDZ",
        "Switzerland, Swissgrid BZ / CA / MBA",
        "Europe/Zurich",
    )
    DE_TENNET = (
        "10YDE-EON------1",
        "TenneT GER CA",
        "Europe/Berlin",
    )
    DE_TRANSNET = (
        "10YDE-ENBW-----N",
        "TransnetBW CA",
        "Europe/Berlin",
    )
    TR = (
        "10YTR-TEIAS----W",
        "Turkey BZ / CA / MBA",
        "Europe/Istanbul",
    )
    UA = (
        "10Y1001C--00003F",
        "Ukraine, Ukraine BZ, MBA",
        "Europe/Kiev",
    )
    UA_DOBTPP = (
        "10Y1001A1001A869",
        "Ukraine-DobTPP CTA",
        "Europe/Kiev",
    )
    UA_BEI = (
        "10YUA-WEPS-----0",
        "Ukraine BEI CTA",
        "Europe/Kiev",
    )
    UA_IPS = (
        "10Y1001C--000182",
        "Ukraine IPS CTA",
        "Europe/Kiev",
    )
    XK = (
        "10Y1001C--00100H",
        "Kosovo/ XK CA / XK BZN",
        "Europe/Rome",
    )
    DE_AMP_LU = "10Y1001C--00002H", "Amprion LU CA", "Europe/Berlin"
