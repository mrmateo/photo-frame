"""Normalize Immich responses independently of HTTP, disk storage, and Qt."""
from __future__ import annotations

from .cropping import finite_number, same_aspect_ratio
from .manifest import FaceBounds, PhotoMetadata, SourceVersion


def source_version(asset: dict[str, object]) -> SourceVersion:
    # Pixel filenames change with server edits/replacements, so a slideshow
    # cannot apply an old manifest's bounds to newly replaced image bytes.
    return {
        'policy': 'edited-v1',
        'updated_at': first_text_value(asset.get('updatedAt')),
        'checksum': first_text_value(asset.get('checksum')),
        'is_edited': asset.get('isEdited') is True,
    }


def first_text_value(*values: object) -> str:
    for value in values:
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ''


def extract_people(asset: dict[str, object]) -> list[str]:
    people = asset.get('people')
    if not isinstance(people, list):
        return []

    return extract_people_from_person_items(people)


def extract_people_from_person_items(items: list[object]) -> list[str]:
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


def extract_people_from_faces(faces: object) -> list[str]:
    items = face_items(faces)
    if not items:
        return []

    people: list[object] = []
    for face in items:
        person = face.get('person')
        if isinstance(person, dict):
            people.append(person)

    return extract_people_from_person_items(people)


def face_items(faces: object) -> list[dict[str, object]]:
    if isinstance(faces, dict):
        faces = faces.get('faces')
    if not isinstance(faces, list):
        return []
    return [face for face in faces if isinstance(face, dict)]


def positive_number(value: object) -> float | None:
    number = finite_number(value)
    return number if number is not None and number > 0 else None


def extract_face_bounds(faces: object) -> FaceBounds | None:
    """Union visible face portions; reject malformed coordinate responses."""
    valid_faces: list[tuple[float, float, float, float, float, float]] = []
    for face in face_items(faces):
        image_width = positive_number(face.get('imageWidth'))
        image_height = positive_number(face.get('imageHeight'))
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


def extract_location(exif_info: dict[str, object]) -> str:
    parts = [
        first_text_value(exif_info.get('city')),
        first_text_value(exif_info.get('state')),
        first_text_value(exif_info.get('country')),
    ]
    return ', '.join(part for part in parts if part)


def build_manifest_entry(
    asset: dict[str, object],
    local_filename: str,
    album_name: str,
    people: list[str] | None = None,
    face_bounds: FaceBounds | None = None,
) -> PhotoMetadata:
    exif_info = asset.get('exifInfo')
    exif = exif_info if isinstance(exif_info, dict) else {}

    return {
        'asset_id': first_text_value(asset.get('id')),
        'original_filename': first_text_value(asset.get('originalFileName')),
        'local_filename': local_filename,
        'taken_at': first_text_value(
            asset.get('localDateTime'),
            exif.get('dateTimeOriginal'),
            asset.get('fileCreatedAt'),
            asset.get('createdAt'),
        ),
        'location': extract_location(exif),
        'album': album_name,
        'people': people if people is not None else extract_people(asset),
        'face_bounds': face_bounds,
        'is_favorite': bool(asset.get('isFavorite')),
    }
