from __future__ import annotations

import logging
import time
from dataclasses import dataclass

import requests

from .config import AppConfig

LOGGER = logging.getLogger(__name__)

FRIENDLY_WEATHER_NAMES = {
    'partlycloudy': 'Partly Cloudy',
    'mostlycloudy': 'Mostly Cloudy',
    'lightrain': 'Light Rain',
    'heavyrain': 'Heavy Rain',
    'thunderstorm': 'Thunderstorm',
    'lightsnow': 'Light Snow',
    'heavysnow': 'Heavy Snow',
    'rainandsnow': 'Rain and Snow',
}


@dataclass(slots=True)
class WeatherSnapshot:
    text: str
    condition: str | None = None


class WeatherService:
    def __init__(
        self,
        logger: logging.Logger | None = None,
        request_timeout_seconds: int = 8,
        request_retries: int = 3,
        retry_backoff_base_seconds: float = 1.5,
    ) -> None:
        self.logger = logger or LOGGER
        self.request_timeout_seconds = request_timeout_seconds
        self.request_retries = request_retries
        self.retry_backoff_base_seconds = retry_backoff_base_seconds

    def format_weather_condition(self, condition: str) -> str:
        if not condition:
            return 'Unknown'

        normalized = condition.lower().replace('-', '').replace('_', '')
        if normalized in FRIENDLY_WEATHER_NAMES:
            return FRIENDLY_WEATHER_NAMES[normalized]

        return condition.replace('_', ' ').replace('-', ' ').title()

    def fetch_weather(self, config: AppConfig) -> WeatherSnapshot:
        if not config.can_fetch_weather:
            return WeatherSnapshot(text='Weather unavailable', condition=None)

        last_error: Exception | None = None
        for attempt in range(self.request_retries):
            try:
                response = requests.get(
                    config.home_assistant_weather_url,
                    headers={'Authorization': f'Bearer {config.weather_api_key}'},
                    timeout=self.request_timeout_seconds,
                )
                response.raise_for_status()
                data = response.json()

                temperature = round(data['attributes']['temperature'])
                condition = str(data['state'])
                weather = self.format_weather_condition(condition)
                return WeatherSnapshot(text=f'{temperature} F  |  {weather}', condition=condition)
            except (requests.RequestException, ValueError, KeyError, TypeError) as error:
                last_error = error
                if attempt < self.request_retries - 1:
                    time.sleep(self.retry_backoff_base_seconds ** attempt)

        self.logger.error('Weather request failed: %s', last_error)
        return WeatherSnapshot(text='Weather unavailable', condition=None)
