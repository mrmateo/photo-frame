from __future__ import annotations

import json
import hashlib
import logging
import os
import tempfile
from concurrent.futures import CancelledError
from threading import Event
from dataclasses import asdict, dataclass
from io import BytesIO
from pathlib import Path
from typing import Callable
from urllib.parse import quote, urlencode

import requests
from PIL import Image, ImageOps
from pillow_heif import register_heif_opener
from requests.exceptions import RequestException

from photoframe import metadata

from .config import AppConfig
from .http_client import HttpClient
from .manifest import PhotoManifest, PhotoMetadata, SourceVersion

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
    failed: int = 0

    def to_dict(self) -> dict[str, int]:
        return asdict(self)


class PhotoSyncService:
    def __init__(
        self,
        logger: logging.Logger | None = None,
        request_timeout_seconds: int = 10,
        request_retries: int = 3,
        retry_backoff_base_seconds: float = 1.5,
        cancel_event: Event | None = None,
        client: HttpClient | None = None,
    ) -> None:
        self.logger = logger or LOGGER
        self.client = client or HttpClient(timeout=request_timeout_seconds, attempts=request_retries,
                                           backoff=retry_backoff_base_seconds, cancel_event=cancel_event)

    def close(self) -> None:
        self.client.close()

    def _notify(self, progress_callback: Callable[[str], None] | None, message: str) -> None:
        self.logger.info(message)
        if progress_callback is not None:
            progress_callback(message)

    @staticmethod
    def to_local_jpg_name(asset_id: str, source_version: SourceVersion | None = None) -> str:
        # Original filenames are not unique, even within a single album.
        suffix = ''
        if source_version is not None:
            signature = json.dumps(source_version, sort_keys=True).encode('utf-8')
            suffix = '-' + hashlib.sha256(signature).hexdigest()[:16]
        return f'asset-{quote(asset_id, safe="")}{suffix}.jpg'

    @staticmethod
    def convert_to_jpeg(image_bytes: bytes, output_path: Path) -> None:
        with Image.open(BytesIO(image_bytes)) as image:
            image.load()
            # Keep already-upright JPEGs lossless; normalize all other inputs.
            if image.format == 'JPEG' and image.getexif().get(274, 1) == 1:
                output_path.write_bytes(image_bytes)
            else:
                upright = ImageOps.exif_transpose(image)
                upright.convert('RGB').save(output_path, 'JPEG', quality=95)

    @staticmethod
    def _valid_cached_jpeg(path: Path) -> bool:
        try:
            with Image.open(path) as image:
                if image.format != 'JPEG' or image.getexif().get(274, 1) != 1:
                    return False
                image.load()
            return True
        except (OSError, ValueError):
            return False

    def _save_photo(self, image_bytes: bytes, output_path: Path) -> None:
        # A failed decode/write must never create a final, apparently cached file.
        descriptor, filename = tempfile.mkstemp(prefix='.photo-frame-', suffix='.tmp', dir=output_path.parent)
        os.close(descriptor)
        temp_path = Path(filename)
        try:
            self.convert_to_jpeg(image_bytes, temp_path)
            if not self._valid_cached_jpeg(temp_path):
                raise ValueError('Downloaded image did not produce a valid upright JPEG.')
            temp_path.replace(output_path)
        finally:
            temp_path.unlink(missing_ok=True)

    def _fetch_album_assets(self, config: AppConfig, headers: dict[str, str]) -> list[dict[str, object]]:
        """Finish and validate enumeration before permitting any stale cleanup."""
        assets: dict[str, dict[str, object]] = {}
        page = 1
        while True:
            response = self.client.request(
                'POST', retry=True,
                url=f'{config.immich_server_url.rstrip("/")}/api/search/metadata',
                headers=headers,
                json={'albumIds': [config.album_id], 'type': 'IMAGE', 'withExif': True, 'page': page},
            )
            payload = response.json()
            result = payload.get('assets') if isinstance(payload, dict) else None
            if not isinstance(result, dict) or not isinstance(result.get('items'), list) or 'nextPage' not in result:
                raise ValueError('Immich search response is missing assets.items or assets.nextPage.')
            for asset in result['items']:
                if (not isinstance(asset, dict)
                        or not isinstance(asset.get('id'), str) or not asset['id'].strip()
                        or not isinstance(asset.get('originalFileName'), str) or not asset['originalFileName'].strip()):
                    raise ValueError('Immich search returned an invalid asset; cleanup cancelled.')
                assets[asset['id']] = asset
            next_page = result['nextPage']
            if next_page is None:
                return list(assets.values())
            if isinstance(next_page, bool) or not isinstance(next_page, (str, int)):
                raise ValueError('Immich search returned an invalid nextPage.')
            try:
                next_page_number = int(next_page)
            except ValueError as error:
                raise ValueError('Immich search returned an invalid nextPage.') from error
            if next_page_number != page + 1:
                raise ValueError('Immich search returned a repeated or skipped page; cleanup cancelled.')
            page = next_page_number

    def fetch_faces_metadata(
        self,
        immich_server_url: str,
        asset_id: str,
        headers: dict[str, str],
    ) -> object:
        query_string = urlencode({'id': asset_id})
        try:
            response = self.client.request('GET', url=f'{immich_server_url}/api/faces?{query_string}', headers=headers)
        except requests.HTTPError as error:
            if error.response is not None and error.response.status_code in {401, 403}:
                raise PermissionError('API key does not have access to read face metadata.') from error
            raise
        return response.json()

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
        assets = self._fetch_album_assets(config, headers)
        photos_path.mkdir(parents=True, exist_ok=True)

        summary = SyncSummary(remote_assets=len(assets))
        # The search endpoint does not return an album name; omit it rather than invent one.
        cached_entries = PhotoManifest.load(photos_path, self.logger).preferred_entries()
        cached_by_id: dict[str, PhotoMetadata] = {}
        for name, entry in cached_entries.items():
            cached_id = entry.get('asset_id')
            if isinstance(cached_id, str):
                previous = cached_by_id.get(cached_id, {})
                if isinstance(entry.get('source_version'), dict) or not isinstance(previous.get('source_version'), dict):
                    cached_by_id[cached_id] = dict(entry, local_filename=name)
        # Preserve legacy metadata if migration/download fails. Never reuse legacy
        # pixels: filename collisions and discarded EXIF cannot be repaired locally.
        manifest_entries = dict(cached_entries)
        manifest_order: list[str] = []
        face_metadata_available = True

        expected_filenames = {
            self.to_local_jpg_name(asset['id'], metadata.source_version(asset)) for asset in assets
        }

        for asset in assets:
            self.client.check_cancelled()
            original_file_name = asset.get('originalFileName')
            asset_id = asset.get('id')
            source_version = metadata.source_version(asset)
            local_filename = self.to_local_jpg_name(asset_id, source_version)
            local_path = photos_path / local_filename
            manifest_order.append(local_filename)

            people = metadata.extract_people(asset)
            cached = cached_by_id.get(asset_id, {})
            cached_bounds = cached.get('face_bounds')
            same_source = cached.get('source_version') == source_version
            face_bounds = cached_bounds if same_source and isinstance(cached_bounds, dict) else None
            cached_people = cached.get('people')
            if isinstance(cached_people, list):
                people = metadata.extract_people_from_person_items(
                    [{'name': name} for name in people + cached_people]
                )

            if face_metadata_available:
                try:
                    faces = self.fetch_faces_metadata(
                        immich_server_url=immich_server_url,
                        asset_id=str(asset_id),
                        headers=headers,
                    )
                    face_items = faces.get('faces') if isinstance(faces, dict) else faces
                    if not isinstance(face_items, list) or not all(isinstance(face, dict) for face in face_items):
                        raise ValueError('Invalid face metadata response.')
                    fresh_bounds = metadata.extract_face_bounds(faces)
                    face_people = metadata.extract_people_from_faces(faces)
                    people = metadata.extract_people_from_person_items(
                        [{'name': name} for name in metadata.extract_people(asset) + face_people]
                    )
                    face_bounds = fresh_bounds
                except PermissionError as error:
                    face_metadata_available = False
                    self.logger.warning('Face metadata disabled: %s', error)
                except RequestException as error:
                    self.logger.warning(
                        'Face metadata request failed for %s: %s',
                        local_filename,
                        error,
                    )
                except (ValueError, TypeError) as error:
                    self.logger.warning(
                        'Could not parse face metadata for %s: %s',
                        local_filename,
                        error,
                    )

            entry = metadata.build_manifest_entry(
                asset=asset,
                local_filename=local_filename,
                album_name='',
                people=people,
                face_bounds=face_bounds,
            )
            entry['source_version'] = source_version

            if self._valid_cached_jpeg(local_path):
                manifest_entries[local_filename] = entry
                summary.skipped_existing += 1
                continue

            self._notify(progress_callback, f'Downloading {local_filename}...')
            # Face coordinates include Immich's crop/rotate/mirror edits.
            download_url = f'{immich_server_url}/api/assets/{asset_id}/original?edited=true'
            try:
                download_response = self.client.request(
                    'GET',
                    url=download_url,
                    headers=headers,
                )
                if Path(original_file_name).suffix.lower() not in JPEG_EXTENSIONS:
                    self._notify(progress_callback, f'Converting {original_file_name} to JPG...')
                self.client.check_cancelled()
                self._save_photo(download_response.content, local_path)
                if Path(original_file_name).suffix.lower() not in JPEG_EXTENSIONS:
                    summary.converted += 1
                summary.downloaded += 1
                manifest_entries[local_filename] = entry
            except CancelledError:
                raise
            except RequestException as error:
                self.logger.error('Download failed for %s: %s', local_filename, error)
                summary.failed += 1
            except Exception:
                self.logger.exception('Processing failed for %s', local_filename)
                summary.failed += 1

            if local_filename not in manifest_entries:
                # Keep old pixels paired with their old bounds if refresh fails.
                previous_filename = cached.get('local_filename')
                if isinstance(previous_filename, str) and previous_filename in cached_entries:
                    manifest_order[-1] = previous_filename

        self.client.check_cancelled()
        cleanup_allowed = not summary.failed
        if cleanup_allowed:
            manifest_entries = {name: entry for name, entry in manifest_entries.items() if name in expected_filenames}

        PhotoManifest(manifest_entries, manifest_order).save(photos_path)

        existing_files = {
            entry.name
            for entry in photos_path.iterdir()
            if entry.is_file() and entry.suffix.lower() in JPEG_EXTENSIONS
        }
        stale_filenames = existing_files - expected_filenames if cleanup_allowed else set()
        for filename in sorted(stale_filenames):
            self.client.check_cancelled()
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
