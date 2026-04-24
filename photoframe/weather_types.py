from __future__ import annotations

from dataclasses import dataclass


WEATHER_ICON_EXTENSION = '.svg'
UNKNOWN_WEATHER_ICON_KEY = 'unknown'


@dataclass(frozen=True, slots=True)
class WeatherConditionType:
    icon_key: str
    label: str | None = None


WEATHER_CONDITION_TYPES: dict[str, WeatherConditionType] = {
    'sunny': WeatherConditionType(icon_key='sun'),
    'clear': WeatherConditionType(icon_key='sun'),
    'clearnight': WeatherConditionType(icon_key='sun', label='Clear Night'),
    'cloudy': WeatherConditionType(icon_key='cloud'),
    'partlycloudy': WeatherConditionType(icon_key='partly_cloudy', label='Partly Cloudy'),
    'mostlycloudy': WeatherConditionType(icon_key='cloud', label='Mostly Cloudy'),
    'overcast': WeatherConditionType(icon_key='cloud'),
    'rain': WeatherConditionType(icon_key='rain'),
    'rainy': WeatherConditionType(icon_key='rain'),
    'lightrain': WeatherConditionType(icon_key='rain', label='Light Rain'),
    'heavyrain': WeatherConditionType(icon_key='heavy_rain', label='Heavy Rain'),
    'pouring': WeatherConditionType(icon_key='heavy_rain'),
    'showers': WeatherConditionType(icon_key='rain'),
    'drizzle': WeatherConditionType(icon_key='rain'),
    'thunderstorm': WeatherConditionType(icon_key='storm'),
    'thunderstorms': WeatherConditionType(icon_key='storm', label='Thunderstorms'),
    'thunder': WeatherConditionType(icon_key='storm'),
    'lightning': WeatherConditionType(icon_key='storm'),
    'lightningrainy': WeatherConditionType(icon_key='storm', label='Lightning and Rain'),
    'snow': WeatherConditionType(icon_key='snow'),
    'snowy': WeatherConditionType(icon_key='snow'),
    'lightsnow': WeatherConditionType(icon_key='snow', label='Light Snow'),
    'heavysnow': WeatherConditionType(icon_key='snow', label='Heavy Snow'),
    'blizzard': WeatherConditionType(icon_key='snow'),
    'rainandsnow': WeatherConditionType(icon_key='mix', label='Rain and Snow'),
    'snowyrainy': WeatherConditionType(icon_key='mix', label='Snow and Rain'),
    'sleet': WeatherConditionType(icon_key='mix'),
    'hail': WeatherConditionType(icon_key='mix'),
    'fog': WeatherConditionType(icon_key='fog'),
    'foggy': WeatherConditionType(icon_key='fog'),
    'haze': WeatherConditionType(icon_key='fog'),
    'mist': WeatherConditionType(icon_key='fog'),
    'windy': WeatherConditionType(icon_key='wind'),
    'windyvariant': WeatherConditionType(icon_key='wind', label='Windy'),
    'wind': WeatherConditionType(icon_key='wind'),
}


def normalize_weather_condition(condition: str | None) -> str:
    if not condition:
        return ''
    return condition.lower().replace('-', '').replace('_', '').replace(' ', '')


def format_weather_condition(condition: str | None) -> str:
    if not condition:
        return 'Unknown'

    normalized = normalize_weather_condition(condition)
    condition_type = WEATHER_CONDITION_TYPES.get(normalized)
    if condition_type and condition_type.label:
        return condition_type.label

    return condition.replace('_', ' ').replace('-', ' ').title()


def weather_icon_key(condition: str | None) -> str:
    normalized = normalize_weather_condition(condition)

    if normalized in WEATHER_CONDITION_TYPES:
        return WEATHER_CONDITION_TYPES[normalized].icon_key

    sorted_condition_types = sorted(WEATHER_CONDITION_TYPES.items(), key=lambda item: len(item[0]), reverse=True)
    for key, condition_type in sorted_condition_types:
        if key in normalized:
            return condition_type.icon_key

    return UNKNOWN_WEATHER_ICON_KEY
