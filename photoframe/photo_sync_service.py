from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import Callable

import requests
from PIL import Image
from pillow_heif import register_heif_opener
from requests.exceptions import RequestException

from .config import AppConfig

register_heif_opener()

LOGGER = logging.getLogger(__name__)
JPEG_EXTENSIONS = {'.jpg', '.jpeg'}
MANIFEST_FILENAME = '.photo_frame_manifest.json'


@dataclass
class SyncSummary:
    remote_assets: int = 0
    downloaded: int = 0
    converted: int = 0
    deleted: int = 0
    skipped_existing: int = 0
    skipped_invalid: int = 0
    failed: int = 0

    def to_dict(self) -> dict[str, int]:
        return {
            'remote_assets': self.remote_assets,
            'downloaded': self.downloaded,
            'converted': self.converted,
            'deleted': self.deleted,
            'skipped_existing': self.skipped_existing,
            'skipped_invalid': self.skipped_invalid,
            'failed': self.failed,
        }


class PhotoSyncService:
    def __init__(
        self,
        logger: logging.Logger | None = None,
        request_timeout_seconds: int = 10,
        request_retries: int = 3,
        retry_backoff_base_seconds: float = 1.5,
    ) -> None:
        self.logger = logger or LOGGER
        self.request_timeout_seconds = request_timeout_seconds
        self.request_retries = request_retries
        self.retry_backoff_base_seconds = retry_backoff_base_seconds

    def _notify(self, progress_callback: Callable[[str], None] | None, message: str) -> None:
        self.logger.info(message)
        if progress_callback is not None:
            progress_callback(message)

    @staticmethod
    def to_local_jpg_name(original_file_name: str) -> str:
        return f'{Path(original_file_name).stem}.jpg'

    @staticmethod
    def _first_text_value(*values: object) -> str:
        for value in values:
            if isinstance(value, str) and value.strip():
                return value.strip()
        return ''

    @staticmethod
    def _extract_people(asset: dict[str, object]) -> list[str]:
        people = asset.get('people')
        if not isinstance(people, list):
            return []

        names: list[str] = []
        seen_names: set[str] = set()
        for person in people:
            if not isinstance(person, dict) or person.get('isHidden') is True:
                continue

            raw_name = person.get('name')
            if not isinstance(raw_name, str):
                continue

            name = raw_name.strip()
            name_key = name.casefold()
            if name and name_key not in seen_names:
                names.append(name)
                seen_names.add(name_key)
        return names

    @staticmethod
    def _extract_location(exif_info: dict[str, object]) -> str:
        parts = [
            PhotoSyncService._first_text_value(exif_info.get('city')),
            PhotoSyncService._first_text_value(exif_info.get('state')),
            PhotoSyncService._first_text_value(exif_info.get('country')),
        ]
        return ', '.join(part for part in parts if part)

    @classmethod
    def _build_manifest_entry(
        cls,
        asset: dict[str, object],
        local_filename: str,
        album_name: str,
    ) -> dict[str, object]:
        exif_info = asset.get('exifInfo')
        exif = exif_info if isinstance(exif_info, dict) else {}

        return {
            'asset_id': cls._first_text_value(asset.get('id')),
            'original_filename': cls._first_text_value(asset.get('originalFileName')),
            'local_filename': local_filename,
            'taken_at': cls._first_text_value(
                asset.get('localDateTime'),
                exif.get('dateTimeOriginal'),
                asset.get('fileCreatedAt'),
                asset.get('createdAt'),
            ),
            'location': cls._extract_location(exif),
            'album': album_name,
            'people': cls._extract_people(asset),
            'is_favorite': bool(asset.get('isFavorite')),
        }

    def _write_manifest(
        self,
        photos_path: Path,
        album: dict[str, object],
        entries: dict[str, dict[str, object]],
    ) -> None:
        manifest_path = photos_path / MANIFEST_FILENAME
        temp_path = manifest_path.with_suffix('.tmp')
        album_name = self._first_text_value(album.get('albumName'), album.get('name'))
        payload = {
            'version': 1,
            'album': album_name,
            'photos': entries,
        }

        temp_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding='utf-8')
        temp_path.replace(manifest_path)

    @staticmethod
    def convert_to_jpeg(image_bytes: bytes, output_path: Path) -> None:
        with Image.open(BytesIO(image_bytes)) as image:
            if image.mode != 'RGB':
                image = image.convert('RGB')
            image.save(output_path, 'JPEG', quality=95)

    def get_with_retries(
        self,
        url: str,
        headers: dict[str, str],
        timeout: int,
        retries: int | None = None,
    ) -> requests.Response:
        retry_count = self.request_retries if retries is None else retries
        last_error: RequestException | None = None

        for attempt in range(retry_count):
            try:
                return requests.get(url, headers=headers, timeout=timeout)
            except RequestException as error:
                last_error = error
                if attempt < retry_count - 1:
                    time.sleep(self.retry_backoff_base_seconds ** attempt)

        if last_error is not None:
            raise last_error
        raise RequestException('GET request failed without exception details')

    def sync_photos(
        self,
        config: AppConfig,
        photos_path: Path,
        progress_callback: Callable[[str], None] | None = None,
    ) -> SyncSummary:
        if not config.can_sync:
            raise ValueError('Missing required sync configuration values.')

        immich_server_url = config.immich_server_url.rstrip('/')
        headers = {
            'x-api-key': config.api_key,
            'Content-Type': 'application/json',
        }

        self._notify(progress_callback, 'Connecting to Immich...')
        response = self.get_with_retries(
            url=f'{immich_server_url}/api/albums/{config.album_id}',
            headers=headers,
            timeout=self.request_timeout_seconds,
        )
        response.raise_for_status()

        album = response.json()
        if not isinstance(album, dict):
            raise ValueError('Immich album response was not a JSON object.')

        raw_assets = album.get('assets', [])
        assets = [asset for asset in raw_assets if isinstance(asset, dict)] if isinstance(raw_assets, list) else []
        photos_path.mkdir(parents=True, exist_ok=True)

        summary = SyncSummary(remote_assets=len(assets))
        album_name = self._first_text_value(album.get('albumName'), album.get('name'))
        manifest_entries: dict[str, dict[str, object]] = {}

        expected_filenames = {
            self.to_local_jpg_name(original_file_name)
            for asset in assets
            if isinstance(original_file_name := asset.get('originalFileName'), str)
            and original_file_name.strip()
        }

        for asset in assets:
            original_file_name = asset.get('originalFileName')
            asset_id = asset.get('id')

            if not isinstance(original_file_name, str) or not original_file_name.strip() or not asset_id:
                self.logger.warning('Skipping invalid asset: %s', repr(asset))
                summary.skipped_invalid += 1
                continue

            local_filename = self.to_local_jpg_name(original_file_name)
            local_path = photos_path / local_filename
            manifest_entries[local_filename] = self._build_manifest_entry(
                asset=asset,
                local_filename=local_filename,
                album_name=album_name,
            )

            if local_path.exists():
                summary.skipped_existing += 1
                continue

            self._notify(progress_callback, f'Downloading {local_filename}...')
            download_url = f'{immich_server_url}/api/assets/{asset_id}/original'

            try:
                download_response = self.get_with_retries(
                    url=download_url,
                    headers=headers,
                    timeout=self.request_timeout_seconds,
                )
                download_response.raise_for_status()

                file_ext = Path(original_file_name).suffix.lower()
                if file_ext in JPEG_EXTENSIONS:
                    local_path.write_bytes(download_response.content)
                else:
                    self._notify(progress_callback, f'Converting {original_file_name} to JPG...')
                    self.convert_to_jpeg(download_response.content, local_path)
                    summary.converted += 1

                summary.downloaded += 1
            except RequestException as error:
                self.logger.error('Download failed for %s: %s', local_filename, error)
                summary.failed += 1
            except Exception:
                self.logger.exception('Processing failed for %s', local_filename)
                summary.failed += 1

        self._write_manifest(photos_path=photos_path, album=album, entries=manifest_entries)

        existing_files = {
            entry.name
            for entry in photos_path.iterdir()
            if entry.is_file() and entry.suffix.lower() in JPEG_EXTENSIONS
        }
        for filename in sorted(existing_files - expected_filenames):
            file_path = photos_path / filename
            try:
                file_path.unlink()
                summary.deleted += 1
                self._notify(progress_callback, f'Removed {filename}')
            except OSError as error:
                self.logger.error('Delete failed for %s: %s', filename, error)
                summary.failed += 1

        self.logger.info('Sync complete: %s', summary.to_dict())
        return summary
