from __future__ import annotations

import json
from dataclasses import dataclass, fields
from pathlib import Path
import shlex
from urllib.parse import urlsplit

MIN_IMAGE_CYCLE_SECONDS = 3
MIN_HOURLY_INTERVAL_SECONDS = 60
# QTimer accepts a signed 32-bit interval in milliseconds.
MAX_INTERVAL_SECONDS = 2_147_483


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
        photos_path = Path(self.local_folder).expanduser()
        return (photos_path if photos_path.is_absolute() else self.config_dir / photos_path).resolve()

    @classmethod
    def from_file(cls, config_path: Path) -> 'AppConfig':
        try:
            payload = json.loads(config_path.read_text(encoding='utf-8'))
        except (OSError, ValueError) as error:
            raise ValueError(f'Cannot read config {config_path}: {error}') from error
        if not isinstance(payload, dict):
            raise ValueError('Config must be a JSON object.')
        allowed = {field.name for field in fields(cls)} - {'config_dir'}
        unknown = payload.keys() - allowed
        if unknown:
            raise ValueError(f'Unknown config setting(s): {", ".join(sorted(unknown))}')

        config = cls(config_dir=config_path.resolve().parent)
        for name, value in payload.items():
            if name == 'shutdown_command':
                if value is not None:
                    if isinstance(value, str):
                        try:
                            value = shlex.split(value)
                        except ValueError as error:
                            raise ValueError(f'shutdown_command: {error}') from error
                    if (not isinstance(value, list) or not value
                            or not all(isinstance(part, str) and part.strip() for part in value)):
                        raise ValueError('shutdown_command must be a nonempty command array, command string, or null.')
                    value = tuple(value)
            elif name in {'image_cycle_seconds', 'hourly_interval_seconds'}:
                minimum = MIN_IMAGE_CYCLE_SECONDS if name == 'image_cycle_seconds' else MIN_HOURLY_INTERVAL_SECONDS
                if type(value) is not int or not minimum <= value <= MAX_INTERVAL_SECONDS:
                    raise ValueError(f'{name} must be an integer between {minimum} and {MAX_INTERVAL_SECONDS}.')
            else:
                if not isinstance(value, str):
                    raise ValueError(f'{name} must be a string.')
                value = value.strip()
                if name == 'local_folder' and not value:
                    raise ValueError('local_folder must not be empty.')
                if name.endswith('_url') and value:
                    try:
                        url = urlsplit(value)
                        valid = url.scheme in {'http', 'https'} and bool(url.hostname)
                        url.port  # Validate a supplied port as well.
                    except ValueError:
                        valid = False
                    if not valid:
                        raise ValueError(f'{name} must be an absolute http:// or https:// URL.')
            setattr(config, name, value)

        for group in (('immich_server_url', 'api_key', 'album_id'),
                      ('home_assistant_weather_url', 'weather_api_key')):
            if any(getattr(config, name) for name in group):
                missing = [name for name in group if not getattr(config, name)]
                if missing:
                    raise ValueError(f'Incomplete integration configuration; missing: {", ".join(missing)}')
        return config

    @classmethod
    def demo(cls, config_dir: Path) -> 'AppConfig':
        return cls(config_dir=config_dir)
