from __future__ import annotations

import json
import hashlib
import logging
import os
import tempfile
import time
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import Callable
from urllib.parse import quote, urlencode

import requests
from PIL import Image, ImageOps
from pillow_heif import register_heif_opener
from requests.exceptions import RequestException

from .config import AppConfig
from .cropping import finite_number, same_aspect_ratio

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
    def to_local_jpg_name(asset_id: str, source_version: dict[str, object] | None = None) -> str:
        # Original filenames are not unique, even within a single album.
        suffix = ''
        if source_version is not None:
            signature = json.dumps(source_version, sort_keys=True).encode('utf-8')
            suffix = '-' + hashlib.sha256(signature).hexdigest()[:16]
        return f'asset-{quote(asset_id, safe="")}{suffix}.jpg'

    @classmethod
    def _source_version(cls, asset: dict[str, object]) -> dict[str, object]:
        # Pixel filenames change with server edits/replacements, so a slideshow
        # cannot apply an old manifest's bounds to newly replaced image bytes.
        return {
            'policy': 'edited-v1',
            'updated_at': cls._first_text_value(asset.get('updatedAt')),
            'checksum': cls._first_text_value(asset.get('checksum')),
            'is_edited': asset.get('isEdited') is True,
        }

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

        return PhotoSyncService._extract_people_from_person_items(people)

    @staticmethod
    def _extract_people_from_person_items(items: list[object]) -> list[str]:
        names: list[str] = []
        seen_names: set[str] = set()
        for person in items:
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
    def _extract_people_from_faces(faces: object) -> list[str]:
        face_items = PhotoSyncService._face_items(faces)
        if not face_items:
            return []

        people: list[object] = []
        for face in face_items:
            person = face.get('person')
            if isinstance(person, dict):
                people.append(person)

        return PhotoSyncService._extract_people_from_person_items(people)

    @staticmethod
    def _face_items(faces: object) -> list[dict[str, object]]:
        if isinstance(faces, dict):
            faces = faces.get('faces')
        if not isinstance(faces, list):
            return []
        return [face for face in faces if isinstance(face, dict)]

    @staticmethod
    def _number(value: object, *, allow_zero: bool = False) -> float | None:
        number = finite_number(value)
        if number is None:
            return None
        minimum_is_valid = number >= 0 if allow_zero else number > 0
        return number if minimum_is_valid else None

    @classmethod
    def _extract_face_bounds(cls, faces: object) -> dict[str, object] | None:
        """Union visible face portions; reject malformed coordinate responses."""
        valid_faces: list[tuple[float, float, float, float, float, float]] = []
        for face in cls._face_items(faces):
            image_width = cls._number(face.get('imageWidth'))
            image_height = cls._number(face.get('imageHeight'))
            x1 = finite_number(face.get('boundingBoxX1'))
            y1 = finite_number(face.get('boundingBoxY1'))
            x2 = finite_number(face.get('boundingBoxX2'))
            y2 = finite_number(face.get('boundingBoxY2'))

            if None in (image_width, image_height, x1, y1, x2, y2):
                raise ValueError('Invalid face dimensions or coordinates.')
            assert image_width is not None and image_height is not None
            assert x1 is not None and y1 is not None and x2 is not None and y2 is not None
            if x2 <= x1 or y2 <= y1:
                raise ValueError('Inverted or empty face bounding box.')
            # Immich transforms boxes after edits without clipping them. A
            # partially visible face is valid; a fully removed one is irrelevant.
            x1, y1 = max(0.0, x1), max(0.0, y1)
            x2, y2 = min(image_width, x2), min(image_height, y2)
            if x2 <= x1 or y2 <= y1:
                continue
            valid_faces.append((x1, y1, x2, y2, image_width, image_height))

        if not valid_faces:
            return None

        # Detection and manual boxes may use different resolutions. Normalize
        # each separately; incompatible aspect ratios require showing all pixels.
        normalized = [
            (x1 / width, y1 / height, x2 / width, y2 / height)
            for x1, y1, x2, y2, width, height in valid_faces
        ]
        return {
            'left': min(face[0] for face in normalized),
            'top': min(face[1] for face in normalized),
            'right': max(face[2] for face in normalized),
            'bottom': max(face[3] for face in normalized),
            'count': len(normalized),
            'image_width': valid_faces[0][4],
            'image_height': valid_faces[0][5],
            'fit_only': any(
                not same_aspect_ratio(width, height, valid_faces[0][4], valid_faces[0][5])
                for _, _, _, _, width, height in valid_faces
            ),
        }

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
        people: list[str] | None = None,
        face_bounds: dict[str, object] | None = None,
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
            'people': people if people is not None else cls._extract_people(asset),
            'face_bounds': face_bounds,
            'is_favorite': bool(asset.get('isFavorite')),
        }

    def _write_manifest(
        self,
        photos_path: Path,
        album: dict[str, object],
        entries: dict[str, dict[str, object]],
        photo_order: list[str],
    ) -> None:
        manifest_path = photos_path / MANIFEST_FILENAME
        temp_path = manifest_path.with_suffix('.tmp')
        album_name = self._first_text_value(album.get('albumName'), album.get('name'))
        payload = {
            'version': 5,
            'album': album_name,
            'photo_order': photo_order,
            'photos': entries,
        }

        temp_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding='utf-8')
        temp_path.replace(manifest_path)

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

    def _read_cached_entries(self, photos_path: Path) -> dict[str, dict[str, object]]:
        try:
            payload = json.loads((photos_path / MANIFEST_FILENAME).read_text(encoding='utf-8'))
            photos = payload.get('photos') if isinstance(payload, dict) else None
            if isinstance(photos, dict):
                entries = {name: entry for name, entry in photos.items() if isinstance(entry, dict)}
                order = payload.get('photo_order')
                # Put actively displayed revisions last so they take precedence
                # over retained older revisions after an incomplete sync.
                if isinstance(order, list):
                    for name in order:
                        if isinstance(name, str) and name in entries:
                            entries[name] = entries.pop(name)
                return entries
        except FileNotFoundError:
            pass
        except (OSError, ValueError) as error:
            self.logger.warning('Could not read cached photo metadata: %s', error)
        return {}

    def _fetch_album_assets(self, config: AppConfig, headers: dict[str, str]) -> list[dict[str, object]]:
        """Finish and validate enumeration before permitting any stale cleanup."""
        assets: dict[str, dict[str, object]] = {}
        page = 1
        while True:
            response = requests.post(
                url=f'{config.immich_server_url.rstrip("/")}/api/search/metadata',
                headers=headers,
                json={'albumIds': [config.album_id], 'type': 'IMAGE', 'withExif': True, 'page': page},
                timeout=self.request_timeout_seconds,
            )
            response.raise_for_status()
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

    def fetch_face_people(
        self,
        immich_server_url: str,
        asset_id: str,
        headers: dict[str, str],
    ) -> list[str]:
        faces = self.fetch_faces_metadata(
            immich_server_url=immich_server_url,
            asset_id=asset_id,
            headers=headers,
        )
        return self._extract_people_from_faces(faces)

    def fetch_faces_metadata(
        self,
        immich_server_url: str,
        asset_id: str,
        headers: dict[str, str],
    ) -> object:
        query_string = urlencode({'id': asset_id})
        response = self.get_with_retries(
            url=f'{immich_server_url}/api/faces?{query_string}',
            headers=headers,
            timeout=self.request_timeout_seconds,
        )
        if response.status_code in {401, 403}:
            raise PermissionError('API key does not have access to read face metadata.')

        response.raise_for_status()
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
        album_name = 'Picture Frame'
        cached_entries = self._read_cached_entries(photos_path)
        cached_by_id: dict[str, dict[str, object]] = {}
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
            self.to_local_jpg_name(asset['id'], self._source_version(asset)) for asset in assets
        }

        for asset in assets:
            original_file_name = asset.get('originalFileName')
            asset_id = asset.get('id')

            if not isinstance(original_file_name, str) or not original_file_name.strip() or not asset_id:
                self.logger.warning('Skipping invalid asset: %s', repr(asset))
                summary.skipped_invalid += 1
                continue

            source_version = self._source_version(asset)
            local_filename = self.to_local_jpg_name(asset_id, source_version)
            local_path = photos_path / local_filename
            manifest_order.append(local_filename)

            people = self._extract_people(asset)
            cached = cached_by_id.get(asset_id, {})
            cached_bounds = cached.get('face_bounds')
            same_source = cached.get('source_version') == source_version
            face_bounds = cached_bounds if same_source and isinstance(cached_bounds, dict) else None
            cached_people = cached.get('people')
            if isinstance(cached_people, list):
                people = self._extract_people_from_person_items(
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
                    fresh_bounds = self._extract_face_bounds(faces)
                    face_people = self._extract_people_from_faces(faces)
                    people = self._extract_people_from_person_items(
                        [{'name': name} for name in self._extract_people(asset) + face_people]
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

            entry = self._build_manifest_entry(
                asset=asset,
                local_filename=local_filename,
                album_name=album_name,
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
                download_response = self.get_with_retries(
                    url=download_url,
                    headers=headers,
                    timeout=self.request_timeout_seconds,
                )
                download_response.raise_for_status()

                if Path(original_file_name).suffix.lower() not in JPEG_EXTENSIONS:
                    self._notify(progress_callback, f'Converting {original_file_name} to JPG...')
                self._save_photo(download_response.content, local_path)
                if Path(original_file_name).suffix.lower() not in JPEG_EXTENSIONS:
                    summary.converted += 1

                summary.downloaded += 1
                manifest_entries[local_filename] = entry
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

        cleanup_allowed = not summary.failed and not summary.skipped_invalid
        if cleanup_allowed:
            manifest_entries = {name: entry for name, entry in manifest_entries.items() if name in expected_filenames}

        self._write_manifest(
            photos_path=photos_path,
            album={'albumName': album_name},
            entries=manifest_entries,
            photo_order=manifest_order,
        )

        existing_files = {
            entry.name
            for entry in photos_path.iterdir()
            if entry.is_file() and entry.suffix.lower() in JPEG_EXTENSIONS
        }
        stale_filenames = existing_files - expected_filenames if cleanup_allowed else set()
        for filename in sorted(stale_filenames):
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
