import io
import os
import sys
import unittest
import zipfile
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

PACKAGE_ROOT = Path(__file__).resolve().parents[3]
sys.path.append(str(PACKAGE_ROOT))

import requests

from custom_components.entsoe_data.api_client import (
    BASE_URLS,
    DOCUMENT_TYPE_GENERATION_PER_TYPE,
    DOCUMENT_TYPE_GENERATION_FORECAST,
    DOCUMENT_TYPE_TOTAL_LOAD,
    DOCUMENT_TYPE_WIND_SOLAR_FORECAST,
    PROCESS_TYPE_DAY_AHEAD,
    PROCESS_TYPE_MONTH_AHEAD,
    PROCESS_TYPE_REALISED,
    PROCESS_TYPE_WEEK_AHEAD,
    PROCESS_TYPE_YEAR_AHEAD,
    EntsoeClient,
    Area,
)
from custom_components.entsoe_data.const import AREA_INFO, TOTAL_EUROPE_AREA


DATASET_DIR = Path(__file__).parent / "datasets"


class TestDocumentParsing(unittest.TestCase):
    client: EntsoeClient

    def setUp(self) -> None:
        self.client = EntsoeClient("fake-key")
        return super().setUp()

    def _zip_documents(self, *documents: str) -> bytes:
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive:
            for idx, document in enumerate(documents, start=1):
                archive.writestr(f"doc{idx}.xml", document)
        return buffer.getvalue()

    @patch("custom_components.entsoe_data.api_client.requests.Session")
    def test_base_request_retries_on_connection_error(self, session_cls):
        session = session_cls.return_value

        # Simulate a ConnectionError (which includes RemoteDisconnected)
        connection_error = requests.exceptions.ConnectionError("Remote end closed connection without response")

        response_ok = MagicMock()
        response_ok.status_code = 200
        response_ok.raise_for_status.return_value = None

        # First call raises ConnectionError, second succeeds
        session.get.side_effect = [connection_error, response_ok]

        client = EntsoeClient("fake-key")
        result = client._base_request({}, datetime(2024, 10, 7), datetime(2024, 10, 8))

        self.assertIs(result, response_ok)
        self.assertEqual(session.get.call_count, 2)
        self.assertEqual(session.get.call_args_list[0][1]["url"], BASE_URLS[0])
        self.assertEqual(session.get.call_args_list[1][1]["url"], BASE_URLS[1])

    @patch("custom_components.entsoe_data.api_client.requests.Session")
    def test_base_request_retries_on_server_error(self, session_cls):
        session = session_cls.return_value
        response_503 = MagicMock()
        response_503.status_code = 503
        http_error = requests.exceptions.HTTPError(response=response_503)
        response_503.raise_for_status.side_effect = http_error

        response_ok = MagicMock()
        response_ok.status_code = 200
        response_ok.raise_for_status.return_value = None

        session.get.side_effect = [response_503, response_ok]

        client = EntsoeClient("fake-key")
        result = client._base_request({}, datetime(2024, 10, 7), datetime(2024, 10, 8))

        self.assertIs(result, response_ok)
        self.assertEqual(session.get.call_count, 2)
        self.assertEqual(session.get.call_args_list[0][1]["url"], BASE_URLS[0])
        self.assertEqual(session.get.call_args_list[1][1]["url"], BASE_URLS[1])

    @patch("custom_components.entsoe_data.api_client.requests.Session")
    def test_base_request_raises_last_error(self, session_cls):
        session = session_cls.return_value
        response_503 = MagicMock()
        response_503.status_code = 503
        http_error = requests.exceptions.HTTPError(response=response_503)
        response_503.raise_for_status.side_effect = http_error
        session.get.side_effect = [response_503, response_503]

        client = EntsoeClient("fake-key")

        with self.assertRaises(requests.exceptions.HTTPError) as ctx:
            client._base_request({}, datetime(2024, 10, 7), datetime(2024, 10, 8))

        self.assertIs(ctx.exception.response, response_503)
        self.assertEqual(session.get.call_count, len(BASE_URLS))

    @patch("custom_components.entsoe_data.api_client.time.sleep")
    @patch("custom_components.entsoe_data.api_client.time.time")
    @patch("custom_components.entsoe_data.api_client.requests.Session")
    def test_rate_limiting_applies_delay(self, session_cls, time_mock, sleep_mock):
        """Test that rate limiting applies a delay between consecutive requests."""
        from custom_components.entsoe_data.api_client import REQUEST_DELAY
        
        session = session_cls.return_value
        response_ok = MagicMock()
        response_ok.status_code = 200
        response_ok.raise_for_status.return_value = None
        session.get.return_value = response_ok

        # Simulate time progression: 
        # First request starts, sets _last_request_time to 0.0
        # Second request checks elapsed time, gets 0.1, needs to sleep
        # After sleep, sets _last_request_time
        elapsed_time = 0.1
        time_values = [0.0, elapsed_time, 0.6]
        time_mock.side_effect = time_values

        client = EntsoeClient("fake-key")
        
        # First request - no delay expected
        client._base_request({}, datetime(2024, 10, 7), datetime(2024, 10, 8))
        sleep_mock.assert_not_called()
        
        # Second request - delay expected since only elapsed_time seconds passed
        client._base_request({}, datetime(2024, 10, 7), datetime(2024, 10, 8))
        sleep_mock.assert_called_once()
        
        # Verify the delay is REQUEST_DELAY - elapsed_time
        expected_delay = REQUEST_DELAY - elapsed_time
        called_delay = sleep_mock.call_args[0][0]
        self.assertAlmostEqual(called_delay, expected_delay, places=5)

    def test_query_total_load_forecast_handles_zip_payload(self):
        xml_doc = """
        <?xml version="1.0" encoding="UTF-8"?>
        <GL_MarketDocument>
          <TimeSeries>
            <Period>
              <timeInterval>
                <start>2024-10-01T00:00Z</start>
                <end>2024-10-01T01:00Z</end>
              </timeInterval>
              <resolution>PT60M</resolution>
              <Point>
                <position>1</position>
                <quantity>1000</quantity>
              </Point>
            </Period>
          </TimeSeries>
        </GL_MarketDocument>
        """.strip()

        second_doc = """
        <?xml version="1.0" encoding="UTF-8"?>
        <GL_MarketDocument>
          <TimeSeries>
            <Period>
              <timeInterval>
                <start>2024-10-01T01:00Z</start>
                <end>2024-10-01T02:00Z</end>
              </timeInterval>
              <resolution>PT60M</resolution>
              <Point>
                <position>1</position>
                <quantity>1100</quantity>
              </Point>
            </Period>
          </TimeSeries>
        </GL_MarketDocument>
        """.strip()

        payload = self._zip_documents(xml_doc, second_doc)

        response = MagicMock()
        response.status_code = 200
        response.headers = {"Content-Type": "application/zip"}
        response.content = payload

        with patch.object(self.client, "_base_request", return_value=response):
            result = self.client.query_total_load_forecast(
                "BE",
                datetime(2024, 10, 1),
                datetime(2024, 10, 2),
            )

        expected = {
            self.client._parse_timestamp("2024-10-01T00:00Z"): 1000.0,
            self.client._parse_timestamp("2024-10-01T01:00Z"): 1100.0,
        }

        self.assertDictEqual(result, expected)

    def test_be_60m(self):
        with open(DATASET_DIR / "BE_60M.xml") as f:
            data = f.read()

        self.maxDiff = None
        self.assertDictEqual(
            self.client.parse_price_document(data),
            {
                datetime.fromisoformat("2024-10-07T22:00:00Z"): 64.98,
                datetime.fromisoformat("2024-10-07T23:00:00Z"): 57.86,
                datetime.fromisoformat("2024-10-08T00:00:00Z"): 53.73,
                datetime.fromisoformat("2024-10-08T01:00:00Z"): 47.52,
                datetime.fromisoformat("2024-10-08T02:00:00Z"): 47.05,
                datetime.fromisoformat("2024-10-08T03:00:00Z"): 56.89,
                datetime.fromisoformat("2024-10-08T04:00:00Z"): 77.77,
                datetime.fromisoformat("2024-10-08T05:00:00Z"): 88.24,
                datetime.fromisoformat("2024-10-08T06:00:00Z"): 100,
                datetime.fromisoformat("2024-10-08T07:00:00Z"): 84.92,
                datetime.fromisoformat("2024-10-08T08:00:00Z"): 74.6,
                datetime.fromisoformat("2024-10-08T09:00:00Z"): 68.82,
                datetime.fromisoformat("2024-10-08T10:00:00Z"): 60.56,
                datetime.fromisoformat("2024-10-08T11:00:00Z"): 63.86,
                datetime.fromisoformat("2024-10-08T12:00:00Z"): 68.1,
                datetime.fromisoformat("2024-10-08T13:00:00Z"): 68.37,
                datetime.fromisoformat("2024-10-08T14:00:00Z"): 76.35,
                datetime.fromisoformat("2024-10-08T15:00:00Z"): 54.04,
                datetime.fromisoformat("2024-10-08T16:00:00Z"): 98.97,
                datetime.fromisoformat("2024-10-08T17:00:00Z"): 115.47,
                datetime.fromisoformat("2024-10-08T18:00:00Z"): 86.85,
                datetime.fromisoformat("2024-10-08T19:00:00Z"): 69.59,
                datetime.fromisoformat("2024-10-08T20:00:00Z"): 57.42,
                datetime.fromisoformat("2024-10-08T21:00:00Z"): 50,
            },
        )

    def test_be_60m_15m_mix(self):
        with open(DATASET_DIR / "BE_60M_15M_mix.xml") as f:
            data = f.read()

        self.maxDiff = None
        self.assertDictEqual(
            self.client.parse_price_document(data),
            {
                # part 1 - 15M resolution
                datetime.fromisoformat("2024-10-05T22:00:00Z"): 55.35,
                datetime.fromisoformat("2024-10-05T23:00:00Z"): 44.22,
                datetime.fromisoformat("2024-10-06T00:00:00Z"): 40.32,
                datetime.fromisoformat("2024-10-06T01:00:00Z"): 31.86,
                datetime.fromisoformat("2024-10-06T02:00:00Z"): 28.37,
                datetime.fromisoformat("2024-10-06T03:00:00Z"): 28.71,
                datetime.fromisoformat("2024-10-06T04:00:00Z"): 31.75,
                datetime.fromisoformat("2024-10-06T05:00:00Z"): 35.47,
                datetime.fromisoformat("2024-10-06T06:00:00Z"): 37.8,
                datetime.fromisoformat("2024-10-06T07:00:00Z"): 33.31,
                datetime.fromisoformat("2024-10-06T08:00:00Z"): 33.79,
                datetime.fromisoformat("2024-10-06T09:00:00Z"): 16.68,
                datetime.fromisoformat("2024-10-06T10:00:00Z"): 5.25,
                datetime.fromisoformat("2024-10-06T11:00:00Z"): -0.01,
                datetime.fromisoformat(
                    "2024-10-06T12:00:00Z"
                ): -0.01,  # repeated value, not present in the dataset!
                datetime.fromisoformat("2024-10-06T13:00:00Z"): 0.2,
                datetime.fromisoformat("2024-10-06T14:00:00Z"): 48.4,
                datetime.fromisoformat("2024-10-06T15:00:00Z"): 50.01,
                datetime.fromisoformat("2024-10-06T16:00:00Z"): 65.63,
                datetime.fromisoformat("2024-10-06T17:00:00Z"): 77.18,
                datetime.fromisoformat("2024-10-06T18:00:00Z"): 81.92,
                datetime.fromisoformat("2024-10-06T19:00:00Z"): 64.36,
                datetime.fromisoformat("2024-10-06T20:00:00Z"): 60.79,
                datetime.fromisoformat("2024-10-06T21:00:00Z"): 52.33,
                # part 2 - 15M resolution
                datetime.fromisoformat("2024-10-06T22:00:00Z"): 34.58,
                datetime.fromisoformat("2024-10-06T23:00:00Z"): 35.34,
                datetime.fromisoformat("2024-10-07T00:00:00Z"): 33.25,
                datetime.fromisoformat("2024-10-07T01:00:00Z"): 29.48,
                datetime.fromisoformat("2024-10-07T02:00:00Z"): 31.88,
                datetime.fromisoformat("2024-10-07T03:00:00Z"): 41.35,
                datetime.fromisoformat("2024-10-07T04:00:00Z"): 57.14,
                datetime.fromisoformat("2024-10-07T05:00:00Z"): 91.84,
                datetime.fromisoformat("2024-10-07T06:00:00Z"): 108.32,
                datetime.fromisoformat("2024-10-07T07:00:00Z"): 91.8,
                datetime.fromisoformat("2024-10-07T08:00:00Z"): 66.05,
                datetime.fromisoformat("2024-10-07T09:00:00Z"): 60.21,
                datetime.fromisoformat("2024-10-07T10:00:00Z"): 56.02,
                datetime.fromisoformat("2024-10-07T11:00:00Z"): 43.29,
                datetime.fromisoformat("2024-10-07T12:00:00Z"): 55,
                datetime.fromisoformat("2024-10-07T13:00:00Z"): 57.6,
                datetime.fromisoformat("2024-10-07T14:00:00Z"): 81.16,
                datetime.fromisoformat("2024-10-07T15:00:00Z"): 104.54,
                datetime.fromisoformat("2024-10-07T16:00:00Z"): 159.2,
                datetime.fromisoformat("2024-10-07T17:00:00Z"): 149.41,
                datetime.fromisoformat("2024-10-07T18:00:00Z"): 121.49,
                datetime.fromisoformat("2024-10-07T19:00:00Z"): 90,
                datetime.fromisoformat("2024-10-07T20:00:00Z"): 90.44,
                datetime.fromisoformat("2024-10-07T21:00:00Z"): 77.18,
                # part 3 - 60M resolution
                datetime.fromisoformat("2024-10-07T22:00:00Z"): 64.98,
                datetime.fromisoformat("2024-10-07T23:00:00Z"): 57.86,
                datetime.fromisoformat("2024-10-08T00:00:00Z"): 53.73,
                datetime.fromisoformat("2024-10-08T01:00:00Z"): 47.52,
                datetime.fromisoformat("2024-10-08T02:00:00Z"): 47.05,
                datetime.fromisoformat("2024-10-08T03:00:00Z"): 56.89,
                datetime.fromisoformat("2024-10-08T04:00:00Z"): 77.77,
                datetime.fromisoformat("2024-10-08T05:00:00Z"): 88.24,
                datetime.fromisoformat("2024-10-08T06:00:00Z"): 100,
                datetime.fromisoformat("2024-10-08T07:00:00Z"): 84.92,
                datetime.fromisoformat("2024-10-08T08:00:00Z"): 74.6,
                datetime.fromisoformat("2024-10-08T09:00:00Z"): 68.82,
                datetime.fromisoformat("2024-10-08T10:00:00Z"): 60.56,
                datetime.fromisoformat("2024-10-08T11:00:00Z"): 63.86,
                datetime.fromisoformat("2024-10-08T12:00:00Z"): 68.1,
                datetime.fromisoformat("2024-10-08T13:00:00Z"): 68.37,
                datetime.fromisoformat("2024-10-08T14:00:00Z"): 76.35,
                datetime.fromisoformat("2024-10-08T15:00:00Z"): 54.04,
                datetime.fromisoformat("2024-10-08T16:00:00Z"): 98.97,
                datetime.fromisoformat("2024-10-08T17:00:00Z"): 115.47,
                datetime.fromisoformat("2024-10-08T18:00:00Z"): 86.85,
                datetime.fromisoformat("2024-10-08T19:00:00Z"): 69.59,
                datetime.fromisoformat("2024-10-08T20:00:00Z"): 57.42,
                datetime.fromisoformat("2024-10-08T21:00:00Z"): 50,
            },
        )

    def test_de_60m_15m_overlap(self):
        with open(DATASET_DIR / "DE_60M_15M_overlap.xml") as f:
            data = f.read()

        self.maxDiff = None
        self.assertDictEqual(
            self.client.parse_price_document(data),
            {
                # part 1 - 60M resolution
                datetime.fromisoformat("2024-10-05T22:00:00Z"): 67.04,
                datetime.fromisoformat("2024-10-05T23:00:00Z"): 63.97,
                datetime.fromisoformat("2024-10-06T00:00:00Z"): 62.83,
                datetime.fromisoformat("2024-10-06T01:00:00Z"): 63.35,
                datetime.fromisoformat("2024-10-06T02:00:00Z"): 62.71,
                datetime.fromisoformat("2024-10-06T03:00:00Z"): 63.97,
                datetime.fromisoformat("2024-10-06T04:00:00Z"): 63.41,
                datetime.fromisoformat("2024-10-06T05:00:00Z"): 72.81,
                datetime.fromisoformat("2024-10-06T06:00:00Z"): 77.2,
                datetime.fromisoformat("2024-10-06T07:00:00Z"): 66.06,
                datetime.fromisoformat("2024-10-06T08:00:00Z"): 35.28,
                datetime.fromisoformat("2024-10-06T09:00:00Z"): 16.68,
                datetime.fromisoformat("2024-10-06T10:00:00Z"): 5.25,
                datetime.fromisoformat("2024-10-06T11:00:00Z"): -0.01,
                datetime.fromisoformat(
                    "2024-10-06T12:00:00Z"
                ): -0.01,  # repeated value, not present in the dataset!
                datetime.fromisoformat("2024-10-06T13:00:00Z"): 0.2,
                datetime.fromisoformat("2024-10-06T14:00:00Z"): 59.6,
                datetime.fromisoformat("2024-10-06T15:00:00Z"): 90.94,
                datetime.fromisoformat("2024-10-06T16:00:00Z"): 106.3,
                datetime.fromisoformat("2024-10-06T17:00:00Z"): 97.22,
                datetime.fromisoformat("2024-10-06T18:00:00Z"): 72.98,
                datetime.fromisoformat("2024-10-06T19:00:00Z"): 59.37,
                datetime.fromisoformat("2024-10-06T20:00:00Z"): 58.69,
                datetime.fromisoformat("2024-10-06T21:00:00Z"): 51.71,
                # part 2 - 60M resolution
                datetime.fromisoformat("2024-10-06T22:00:00Z"): 34.58,
                datetime.fromisoformat("2024-10-06T23:00:00Z"): 35.34,
                datetime.fromisoformat("2024-10-07T00:00:00Z"): 33.25,
                datetime.fromisoformat("2024-10-07T01:00:00Z"): 30.15,
                datetime.fromisoformat("2024-10-07T02:00:00Z"): 36.09,
                datetime.fromisoformat("2024-10-07T03:00:00Z"): 46.73,
                datetime.fromisoformat("2024-10-07T04:00:00Z"): 67.59,
                datetime.fromisoformat("2024-10-07T05:00:00Z"): 100.92,
                datetime.fromisoformat("2024-10-07T06:00:00Z"): 108.32,
                datetime.fromisoformat("2024-10-07T07:00:00Z"): 91.86,
                datetime.fromisoformat("2024-10-07T08:00:00Z"): 66.09,
                datetime.fromisoformat("2024-10-07T09:00:00Z"): 60.22,
                datetime.fromisoformat("2024-10-07T10:00:00Z"): 54.11,
                datetime.fromisoformat("2024-10-07T11:00:00Z"): 43.29,
                datetime.fromisoformat("2024-10-07T12:00:00Z"): 55,
                datetime.fromisoformat("2024-10-07T13:00:00Z"): 67.01,
                datetime.fromisoformat("2024-10-07T14:00:00Z"): 97.9,
                datetime.fromisoformat("2024-10-07T15:00:00Z"): 120.71,
                datetime.fromisoformat("2024-10-07T16:00:00Z"): 237.65,
                datetime.fromisoformat("2024-10-07T17:00:00Z"): 229.53,
                datetime.fromisoformat("2024-10-07T18:00:00Z"): 121.98,
                datetime.fromisoformat("2024-10-07T19:00:00Z"): 99.93,
                datetime.fromisoformat("2024-10-07T20:00:00Z"): 91.91,
                datetime.fromisoformat("2024-10-07T21:00:00Z"): 79.12,
            },
        )

    def test_total_europe_area_mapping(self):
        area = Area["TOTAL_EUROPE"]
        self.assertIn(TOTAL_EUROPE_AREA, AREA_INFO)
        self.assertEqual(area.code, AREA_INFO[TOTAL_EUROPE_AREA]["code"])
        self.assertEqual(area.meaning, "Total Europe")

    def test_parse_generation_per_type_be(self):
        with open(DATASET_DIR / "BE_generation.xml") as f:
            document = f.read()

        series = self.client.parse_generation_per_type_document(document)

        self.assertDictEqual(
            series,
            {
                datetime.fromisoformat("2024-10-01T00:00:00Z"): {
                    "coal": 100.0,
                    "fossil_gas": 200.0,
                    "interconnector": 5.0,
                    "nuclear": 400.0,
                    "solar": 120.0,
                    "wind_onshore": 46.0,
                },
                datetime.fromisoformat("2024-10-01T01:00:00Z"): {
                    "coal": 120.0,
                    "fossil_gas": 210.0,
                    "interconnector": 5.0,
                    "nuclear": 405.0,
                    "solar": 130.0,
                    "wind_onshore": 66.0,
                },
            },
        )

    def test_parse_generation_per_type_eu(self):
        with open(DATASET_DIR / "EU_generation.xml") as f:
            document = f.read()

        series = self.client.parse_generation_per_type_document(document)

        self.assertDictEqual(
            series,
            {
                datetime.fromisoformat("2024-10-01T00:00:00Z"): {
                    "biomass": 90.0,
                    "energy_storage": 20.0,
                    "fossil_gas": 227.5,
                    "hydro_pumped_storage": 300.0,
                    "hydro_run_of_river": 250.0,
                    "other": 5.0,
                    "solar": 0.0,
                    "wind_offshore": 82.0,
                },
                datetime.fromisoformat("2024-10-01T01:00:00Z"): {
                    "biomass": 95.0,
                    "energy_storage": 15.0,
                    "fossil_gas": 247.5,
                    "hydro_pumped_storage": 310.0,
                    "hydro_run_of_river": 245.0,
                    "other": 5.0,
                    "solar": 0.0,
                    "wind_offshore": 93.0,
                },
                datetime.fromisoformat("2024-10-01T02:00:00Z"): {
                    "biomass": 100.0,
                    "energy_storage": 10.0,
                    "fossil_gas": 260.0,
                    "hydro_pumped_storage": 315.0,
                    "hydro_run_of_river": 240.0,
                    "other": 5.0,
                    "solar": 10.0,
                    "wind_offshore": 106.0,
                },
            },
        )

    def test_parse_total_load_forecast(self):
        with open(DATASET_DIR / "BE_total_load.xml") as f:
            document = f.read()

        series = self.client.parse_total_load_document(document)

        self.assertDictEqual(
            series,
            {
                datetime.fromisoformat("2024-10-01T00:00:00Z"): 1040.0,
                datetime.fromisoformat("2024-10-01T01:00:00Z"): 1130.0,
                datetime.fromisoformat("2024-10-01T02:00:00Z"): 1200.0,
                datetime.fromisoformat("2024-10-01T03:00:00Z"): 1250.0,
            },
        )

    def test_parse_generation_forecast(self):
        with open(DATASET_DIR / "BE_generation_forecast.xml") as f:
            document = f.read()

        series = self.client.parse_generation_forecast_document(document)

        self.assertDictEqual(
            series,
            {
                datetime.fromisoformat("2024-10-02T00:00:00Z"): 120.0,
                datetime.fromisoformat("2024-10-02T01:00:00Z"): 175.0,
                datetime.fromisoformat("2024-10-02T02:00:00Z"): 180.0,
            },
        )

    def test_parse_wind_solar_forecast(self):
        with open(DATASET_DIR / "BE_wind_solar_forecast.xml") as f:
            document = f.read()

        series = self.client.parse_wind_solar_document(document)

        self.assertDictEqual(
            series,
            {
                datetime.fromisoformat("2024-10-02T00:00:00Z"): {
                    "solar": 50.0,
                    "wind_onshore": 80.0,
                },
                datetime.fromisoformat("2024-10-02T01:00:00Z"): {
                    "solar": 60.0,
                    "wind_onshore": 90.0,
                },
                datetime.fromisoformat("2024-10-02T02:00:00Z"): {
                    "solar": 70.0,
                },
            },
        )

    def test_query_generation_per_type_uses_process_mapping(self):
        response = MagicMock()
        response.status_code = 200
        response.content = b"<root />"

        with patch.object(self.client, "_base_request", return_value=response) as base_mock, patch.object(
            self.client,
            "parse_generation_per_type_document",
            return_value={},
        ) as parse_mock:
            result = self.client.query_generation_per_type(
                "be",
                datetime(2024, 10, 1),
                datetime(2024, 10, 2),
                process_type="day_ahead",
            )

        self.assertEqual(result, {})
        base_args = base_mock.call_args.kwargs
        self.assertEqual(base_args["params"]["documentType"], DOCUMENT_TYPE_GENERATION_PER_TYPE)
        self.assertEqual(base_args["params"]["processType"], PROCESS_TYPE_DAY_AHEAD)
        self.assertEqual(base_args["params"]["in_Domain"], "10YBE----------2")
        self.assertEqual(base_args["params"]["out_Domain"], "10YBE----------2")
        parse_mock.assert_called_once()

    def test_query_total_load_forecast_params(self):
        response = MagicMock()
        response.status_code = 200
        response.content = b"<root />"

        with patch.object(self.client, "_base_request", return_value=response) as base_mock, patch.object(
            self.client,
            "parse_total_load_document",
            return_value={},
        ) as parse_mock:
            result = self.client.query_total_load_forecast(
                "BE", datetime(2024, 10, 1), datetime(2024, 10, 2)
            )

        self.assertEqual(result, {})
        params = base_mock.call_args.kwargs["params"]
        self.assertEqual(params["documentType"], DOCUMENT_TYPE_TOTAL_LOAD)
        self.assertEqual(params["processType"], PROCESS_TYPE_DAY_AHEAD)
        self.assertNotIn("in_Domain", params)
        self.assertNotIn("out_Domain", params)
        self.assertEqual(params["outBiddingZone_Domain"], "10YBE----------2")
        parse_mock.assert_called_once()

    def test_query_total_load_forecast_uses_custom_process_type(self):
        response = MagicMock()
        response.status_code = 200
        response.content = b"<root />"

        with patch.object(self.client, "_base_request", return_value=response) as base_mock, patch.object(
            self.client,
            "parse_total_load_document",
            return_value={},
        ):
            result = self.client.query_total_load_forecast(
                "BE",
                datetime(2024, 10, 1),
                datetime(2024, 10, 2),
                process_type=PROCESS_TYPE_WEEK_AHEAD,
            )

        self.assertEqual(result, {})
        params = base_mock.call_args.kwargs["params"]
        self.assertEqual(params["processType"], PROCESS_TYPE_WEEK_AHEAD)

    def test_query_generation_forecast_params(self):
        response = MagicMock()
        response.status_code = 200
        response.content = b"<root />"

        with patch.object(self.client, "_base_request", return_value=response) as base_mock, patch.object(
            self.client,
            "parse_generation_forecast_document",
            return_value={},
        ) as parse_mock:
            result = self.client.query_generation_forecast(
                "BE", datetime(2024, 10, 2), datetime(2024, 10, 3)
            )

        self.assertEqual(result, {})
        params = base_mock.call_args.kwargs["params"]
        self.assertEqual(params["documentType"], DOCUMENT_TYPE_GENERATION_FORECAST)
        self.assertEqual(params["processType"], PROCESS_TYPE_DAY_AHEAD)
        self.assertEqual(params["in_Domain"], "10YBE----------2")
        self.assertEqual(params["out_Domain"], "10YBE----------2")
        parse_mock.assert_called_once()

    def test_query_wind_solar_forecast_params(self):
        response = MagicMock()
        response.status_code = 200
        response.content = b"<root />"

        with patch.object(self.client, "_base_request", return_value=response) as base_mock, patch.object(
            self.client,
            "parse_wind_solar_document",
            return_value={},
        ) as parse_mock:
            result = self.client.query_wind_solar_forecast(
                "BE", datetime(2024, 10, 2), datetime(2024, 10, 3)
            )

        self.assertEqual(result, {})
        params = base_mock.call_args.kwargs["params"]
        self.assertEqual(params["documentType"], DOCUMENT_TYPE_WIND_SOLAR_FORECAST)
        self.assertEqual(params["processType"], PROCESS_TYPE_DAY_AHEAD)
        self.assertEqual(params["in_Domain"], "10YBE----------2")
        self.assertEqual(params["out_Domain"], "10YBE----------2")
        parse_mock.assert_called_once()

    def test_area_from_identifier_accepts_eic_code(self):
        area = Area.from_identifier("10Y1001A1001A876")

        self.assertEqual(area, Area["TOTAL_EUROPE"])

    def test_area_has_code_accepts_eic_code(self):
        self.assertTrue(Area.has_code("10Y1001A1001A876"))

    def test_be_15M_avg(self):
        with open(DATASET_DIR / "BE_15M_avg.xml") as f:
            data = f.read()

        self.maxDiff = None
        self.assertDictEqual(
            self.client.parse_price_document(data),
            {
                # part 1 - 15M resolution
                datetime.fromisoformat("2024-10-05T22:00:00Z"): 39.06,  # average
                datetime.fromisoformat("2024-10-05T23:00:00Z"): 44.22,  # average
                datetime.fromisoformat("2024-10-06T00:00:00Z"): 36.30,  # average
                datetime.fromisoformat("2024-10-06T01:00:00Z"): 36.30,  # extended
                datetime.fromisoformat("2024-10-06T02:00:00Z"): 36.30,  # extended
                # part 2 - 60M resolution
                datetime.fromisoformat("2024-10-06T03:00:00Z"): 64.98,
                datetime.fromisoformat("2024-10-06T04:00:00Z"): 64.98,  # extended
                datetime.fromisoformat("2024-10-06T05:00:00Z"): 57.86,
            },
        )

    def test_be_exact4(self):
        with open(DATASET_DIR / "BE_15M_exact4.xml") as f:
            data = f.read()

        self.maxDiff = None
        self.assertDictEqual(
            self.client.parse_price_document(data),
            {
                # part 1 - 15M resolution
                datetime.fromisoformat("2024-10-05T22:00:00Z"): 42.94,  # average
            },
        )


if __name__ == "__main__":
    unittest.main()
