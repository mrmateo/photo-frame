from __future__ import annotations

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
        assets = album.get('assets', [])
        photos_path.mkdir(parents=True, exist_ok=True)

        summary = SyncSummary(remote_assets=len(assets))

        expected_filenames = {
            self.to_local_jpg_name(asset['originalFileName'])
            for asset in assets
            if 'originalFileName' in asset
        }

        for asset in assets:
            original_file_name = asset.get('originalFileName')
            asset_id = asset.get('id')

            if not original_file_name or not asset_id:
                self.logger.warning('Skipping invalid asset: %s', repr(asset))
                summary.skipped_invalid += 1
                continue

            local_filename = self.to_local_jpg_name(original_file_name)
            local_path = photos_path / local_filename

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

        existing_files = {entry.name for entry in photos_path.iterdir() if entry.is_file()}
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
