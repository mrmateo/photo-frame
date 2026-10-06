"""Pure photo presentation helpers, independent of Qt and background workers."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from PIL import Image

from .cropping import finite_number, same_aspect_ratio
from .manifest import PhotoMetadata


def crop_info_for_image(image_path: Path | None, photos: dict[str, PhotoMetadata]) -> dict[str, object]:
    if image_path is None:
        return {}
    metadata = photos.get(image_path.name)
    if not isinstance(metadata, dict):
        return {}
    bounds = metadata.get('face_bounds')
    if not isinstance(bounds, dict):
        return {}

    required_keys = ('left', 'top', 'right', 'bottom', 'image_width', 'image_height')
    values = {key: finite_number(bounds.get(key)) for key in required_keys}
    if any(value is None for value in values.values()):
        return {}
    if not (0 <= values['left'] < values['right'] <= 1
            and 0 <= values['top'] < values['bottom'] <= 1
            and values['image_width'] > 0 and values['image_height'] > 0):
        return {}
    try:
        with Image.open(image_path) as image:
            width, height = image.size
            if image.getexif().get(274, 1) in (5, 6, 7, 8):
                width, height = height, width
    except (OSError, ValueError):
        return {}
    # Render with the actual upright aspect ratio, not rounded ML preview
    # dimensions. If coordinate frames disagree, preserve the whole photo.
    values['fit_only'] = bounds.get('fit_only') is True or not same_aspect_ratio(
        width, height, values['image_width'], values['image_height']
    )
    values['image_width'], values['image_height'] = float(width), float(height)
    return values


def metadata_text(value: object) -> str:
    return value.strip() if isinstance(value, str) else ''


def format_people(people: object) -> str:
    if not isinstance(people, list):
        return ''

    names = [name.strip() for name in people if isinstance(name, str) and name.strip()]
    if not names:
        return ''

    visible_names = names[:4]
    suffix = f' +{len(names) - 4}' if len(names) > 4 else ''
    return f"With: {', '.join(visible_names)}{suffix}"


def format_taken_at(raw_value: object) -> str:
    if not isinstance(raw_value, str) or not raw_value.strip():
        return ''

    normalized = raw_value.strip().replace('Z', '+00:00')
    try:
        taken_at = datetime.fromisoformat(normalized)
    except ValueError:
        return raw_value.strip()

    return taken_at.strftime('%B %d, %Y').replace(' 0', ' ')


def format_photo_details(image_path: Path | None, photos: dict[str, PhotoMetadata]) -> str:
    if image_path is None:
        return ''

    metadata = photos.get(image_path.name)
    if not isinstance(metadata, dict):
        return image_path.name

    lines = [
        format_taken_at(metadata.get('taken_at')),
        metadata_text(metadata.get('location')),
        format_people(metadata.get('people')),
    ]

    album = metadata_text(metadata.get('album'))
    if album:
        lines.append(f'Album: {album}')

    if metadata.get('is_favorite') is True:
        lines.append('Favorite')

    original_filename = metadata_text(metadata.get('original_filename'))
    if original_filename and original_filename != image_path.name:
        lines.append(original_filename)

    visible_lines = [line for line in lines if line]
    return '\n'.join(visible_lines) if visible_lines else image_path.name
