from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
import shlex

MIN_IMAGE_CYCLE_SECONDS = 3
MIN_HOURLY_INTERVAL_SECONDS = 60


def _coerce_positive_int(value: object, fallback: int, minimum: int) -> int:
    if not isinstance(value, (int, float, str)):
        return fallback

    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return fallback
    return max(parsed, minimum)


def _coerce_shutdown_command(value: object) -> tuple[str, ...] | None:
    if value is None:
        return None

    if isinstance(value, str):
        parts = tuple(part for part in shlex.split(value.strip()) if part)
        return parts or None

    if isinstance(value, list):
        parts = tuple(str(part).strip() for part in value if str(part).strip())
        return parts or None

    return None


@dataclass(slots=True)
class AppConfig:
    immich_server_url: str = ''
    api_key: str = ''
    album_id: str = ''
    local_folder: str = 'photos'
    home_assistant_weather_url: str = ''
    weather_api_key: str = ''
    image_cycle_seconds: int = 15
    hourly_interval_seconds: int = 3600
    shutdown_command: tuple[str, ...] | None = None
    config_dir: Path = Path('.')

    @property
    def can_sync(self) -> bool:
        return bool(self.immich_server_url and self.api_key and self.album_id and self.local_folder)

    @property
    def can_fetch_weather(self) -> bool:
        return bool(self.weather_api_key and self.home_assistant_weather_url)

    def resolve_photos_path(self) -> Path:
        photos_path = Path(self.local_folder)
        if photos_path.is_absolute():
            return photos_path
        return (self.config_dir / photos_path).resolve()

    @classmethod
    def from_file(cls, config_path: Path) -> 'AppConfig':
        with config_path.open(encoding='utf-8') as config_file:
            payload = json.load(config_file)

        return cls(
            immich_server_url=payload.get('immich_server_url', '').strip(),
            api_key=payload.get('api_key', '').strip(),
            album_id=payload.get('album_id', '').strip(),
            local_folder=payload.get('local_folder', 'photos').strip(),
            home_assistant_weather_url=payload.get('home_assistant_weather_url', '').strip(),
            weather_api_key=payload.get('weather_api_key', '').strip(),
            image_cycle_seconds=_coerce_positive_int(
                payload.get('image_cycle_seconds', 15),
                fallback=15,
                minimum=MIN_IMAGE_CYCLE_SECONDS,
            ),
            hourly_interval_seconds=_coerce_positive_int(
                payload.get('hourly_interval_seconds', 3600),
                fallback=3600,
                minimum=MIN_HOURLY_INTERVAL_SECONDS,
            ),
            shutdown_command=_coerce_shutdown_command(payload.get('shutdown_command')),
            config_dir=config_path.resolve().parent,
        )

    @classmethod
    def demo(cls, config_dir: Path) -> 'AppConfig':
        return cls(config_dir=config_dir)
