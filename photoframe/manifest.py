"""The on-disk photo catalog shared by synchronization and the slideshow."""
from __future__ import annotations

from dataclasses import dataclass, field
import json
import logging
from pathlib import Path
from typing import TypedDict, cast

MANIFEST_FILENAME = '.photo_frame_manifest.json'
MANIFEST_VERSION = 5
LOGGER = logging.getLogger(__name__)


class FaceBounds(TypedDict):
    left: float
    top: float
    right: float
    bottom: float
    image_width: float
    image_height: float
    count: int
    fit_only: bool


class SourceVersion(TypedDict):
    policy: str
    updated_at: str
    checksum: str
    is_edited: bool


class PhotoMetadata(TypedDict, total=False):
    asset_id: str
    original_filename: str
    local_filename: str
    taken_at: str
    location: str
    album: str
    people: list[str]
    face_bounds: FaceBounds | None
    is_favorite: bool
    source_version: SourceVersion


@dataclass
class PhotoManifest:
    photos: dict[str, PhotoMetadata] = field(default_factory=dict)
    photo_order: list[str] = field(default_factory=list)
    album: str = ''

    @classmethod
    def load(cls, photos_path: Path, logger: logging.Logger = LOGGER) -> 'PhotoManifest':
        path = photos_path / MANIFEST_FILENAME
        try:
            payload = json.loads(path.read_text(encoding='utf-8'))
            if not isinstance(payload, dict):
                raise ValueError('Manifest must be an object.')
            version = payload.get('version', 1)
            if type(version) is not int or not 1 <= version <= MANIFEST_VERSION:
                raise ValueError(f'Unsupported manifest version: {version}')
            photos = payload.get('photos', {})
            order = payload.get('photo_order', [])
            if not isinstance(photos, dict) or not isinstance(order, list):
                raise ValueError('Manifest photos/order must be an object/list.')
            entries = {name: cast(PhotoMetadata, entry) for name, entry in photos.items()
                       if isinstance(entry, dict) and Path(name).name == name}
            names = list(dict.fromkeys(name for name in order if isinstance(name, str) and name in entries))
            album = payload.get('album', '')
            return cls(entries, names, album if isinstance(album, str) else '')
        except FileNotFoundError:
            return cls()
        except (OSError, ValueError) as error:
            logger.warning('Could not read photo manifest %s: %s', path, error)
            return cls()

    def preferred_entries(self) -> dict[str, PhotoMetadata]:
        """Visit active revisions last so they win over retained older revisions."""
        entries = dict(self.photos)
        for name in self.photo_order:
            if name in entries:
                entries[name] = entries.pop(name)
        return entries

    def save(self, photos_path: Path) -> None:
        path = photos_path / MANIFEST_FILENAME
        temporary = path.with_suffix('.tmp')
        payload = {'version': MANIFEST_VERSION, 'album': self.album,
                   'photo_order': self.photo_order, 'photos': self.photos}
        try:
            temporary.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding='utf-8')
            temporary.replace(path)
        finally:
            temporary.unlink(missing_ok=True)
