from concurrent.futures import CancelledError
import json
import threading
import unittest
from unittest.mock import Mock

import requests

from photoframe.config import AppConfig
from photoframe.http_client import HttpClient
from photoframe.weather_service import WeatherService, WeatherSnapshot


def response(status=200, payload=None):
    result = requests.Response()
    result.status_code = status
    result.url = 'https://example.invalid'
    result._content = json.dumps(payload).encode()
    result._content_consumed = True
    return result


class HttpTests(unittest.TestCase):
    def setUp(self):
        self.session = Mock(spec=requests.Session)
        self.cancel = Mock(spec=threading.Event)
        self.cancel.is_set.return_value = False
        self.cancel.wait.return_value = False
        self.client = HttpClient(session=self.session, cancel_event=self.cancel)

    def test_transient_failures_retry_with_bounded_attempts_and_timeout(self):
        for failure in [requests.Timeout(), requests.ConnectionError(), response(503), response(429)]:
            with self.subTest(failure=failure):
                self.session.request.reset_mock()
                self.session.request.side_effect = [failure, response(payload={'ok': True})]
                self.assertEqual(self.client.request('GET', 'https://example.invalid').json(), {'ok': True})
                self.assertEqual(self.session.request.call_count, 2)
                self.assertEqual(self.session.request.call_args.kwargs['timeout'], 10)
        self.session.request.side_effect = requests.Timeout('offline')
        self.session.request.reset_mock()
        with self.assertRaises(requests.Timeout):
            self.client.request('GET', 'https://example.invalid')
        self.assertEqual(self.session.request.call_count, 3)

    def test_authentication_and_other_permanent_errors_are_not_retried(self):
        for status in (400, 401, 403, 404):
            with self.subTest(status=status):
                self.session.request.reset_mock()
                self.session.request.return_value = response(status)
                with self.assertRaises(requests.HTTPError):
                    self.client.request('GET', 'https://example.invalid')
                self.session.request.assert_called_once()
                self.cancel.wait.assert_not_called()

    def test_only_explicitly_read_only_posts_are_retried(self):
        self.session.request.side_effect = requests.Timeout()
        with self.assertRaises(requests.Timeout):
            self.client.request('POST', 'https://example.invalid')
        self.session.request.assert_called_once()
        self.session.request.reset_mock()
        with self.assertRaises(requests.Timeout):
            self.client.request('POST', 'https://example.invalid', retry=True)
        self.assertEqual(self.session.request.call_count, 3)

    def test_cancel_before_request_or_during_backoff(self):
        self.cancel.is_set.return_value = True
        with self.assertRaises(CancelledError):
            self.client.request('GET', 'https://example.invalid')
        self.session.request.assert_not_called()
        self.cancel.is_set.side_effect = [False, True]
        self.cancel.wait.return_value = True
        self.session.request.side_effect = requests.Timeout()
        with self.assertRaises(CancelledError):
            self.client.request('GET', 'https://example.invalid')
        self.session.request.assert_called_once()

    def test_services_own_separate_sessions(self):
        first, second = HttpClient(), HttpClient()
        self.addCleanup(first.close)
        self.addCleanup(second.close)
        self.assertIsNot(first.session, second.session)


class WeatherTests(unittest.TestCase):
    def setUp(self):
        self.client = Mock(spec=HttpClient)
        self.service = WeatherService(client=self.client, logger=Mock())
        self.config = AppConfig(home_assistant_weather_url='https://example.invalid', weather_api_key='test')

    def test_valid_weather_is_formatted(self):
        self.client.request.return_value = response(payload={'attributes': {'temperature': 71.6}, 'state': 'partlycloudy'})
        self.assertEqual(self.service.fetch_weather(self.config), WeatherSnapshot('72°', 'Partly Cloudy', 'partlycloudy'))

    def test_bad_weather_is_unavailable_without_repeating_parsing_requests(self):
        for payload in [None, {}, {'attributes': {'temperature': None}, 'state': 'sunny'},
                        {'attributes': {'temperature': float('inf')}, 'state': 'sunny'},
                        {'attributes': {'temperature': 72}, 'state': []}]:
            with self.subTest(payload=payload):
                self.client.request.reset_mock()
                self.client.request.return_value = response(payload=payload)
                self.assertEqual(self.service.fetch_weather(self.config), WeatherSnapshot())
                self.client.request.assert_called_once()

    def test_cancellation_propagates(self):
        self.client.request.side_effect = CancelledError()
        with self.assertRaises(CancelledError):
            self.service.fetch_weather(self.config)
