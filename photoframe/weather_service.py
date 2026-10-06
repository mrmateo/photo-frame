from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from threading import Event

import requests

from .config import AppConfig
from .http_client import HttpClient
from .weather_types import format_weather_condition

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class WeatherSnapshot:
    temperature_text: str = ''
    condition_text: str = 'Weather unavailable'
    condition: str | None = None


class WeatherService:
    def __init__(self, logger: logging.Logger | None = None, request_timeout_seconds: int = 8,
                 request_retries: int = 3, retry_backoff_base_seconds: float = 1.5,
                 cancel_event: Event | None = None, client: HttpClient | None = None) -> None:
        self.logger = logger or LOGGER
        self.client = client or HttpClient(timeout=request_timeout_seconds, attempts=request_retries,
                                           backoff=retry_backoff_base_seconds, cancel_event=cancel_event)

    def close(self) -> None:
        self.client.close()

    def fetch_weather(self, config: AppConfig) -> WeatherSnapshot:
        if not config.can_fetch_weather:
            return WeatherSnapshot()
        try:
            response = self.client.request('GET', config.home_assistant_weather_url,
                                           headers={'Authorization': f'Bearer {config.weather_api_key}'})
            data = response.json()
            temperature = data['attributes']['temperature']
            condition = data['state']
            if (isinstance(temperature, bool) or not isinstance(temperature, (int, float))
                    or not math.isfinite(temperature) or not isinstance(condition, str)):
                raise ValueError('Weather must contain a finite temperature and a text condition.')
            return WeatherSnapshot(temperature_text=f'{round(temperature)}°',
                                   condition_text=format_weather_condition(condition), condition=condition)
        except (requests.RequestException, ValueError, KeyError, TypeError, OverflowError) as error:
            self.logger.error('Weather request failed: %s', error)
            return WeatherSnapshot()
