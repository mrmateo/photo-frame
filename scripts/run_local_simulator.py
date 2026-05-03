from __future__ import annotations

import argparse
import binascii
import json
from pathlib import Path
import subprocess
import struct
import sys
import zlib


REPO_ROOT = Path(__file__).resolve().parents[1]
SIMULATOR_DIR = REPO_ROOT / '.dev-simulator'
PHOTOS_DIR = SIMULATOR_DIR / 'photos'
CONFIG_PATH = SIMULATOR_DIR / 'config.json'
MANIFEST_PATH = PHOTOS_DIR / '.photo_frame_manifest.json'

SAMPLE_PHOTOS = [
    {
        'filename': 'sim-01-morning.png',
        'title': 'Morning Light',
        'subtitle': 'Kitchen table test image',
        'accent': (245, 183, 80),
        'background': (27, 50, 72),
        'taken_at': '2025-06-14T08:12:00Z',
        'location': 'Flagstaff, Arizona',
        'people': ['Avery', 'Sam'],
        'album': 'Local Simulator',
        'is_favorite': True,
    },
    {
        'filename': 'sim-02-desert.png',
        'title': 'Desert Drive',
        'subtitle': 'Wide crop and overlay check',
        'accent': (111, 192, 163),
        'background': (91, 48, 58),
        'taken_at': '2024-11-02T17:45:00Z',
        'location': 'Sedona, Arizona',
        'people': ['Jordan'],
        'album': 'Local Simulator',
        'is_favorite': False,
    },
    {
        'filename': 'sim-03-evening.png',
        'title': 'Evening Window',
        'subtitle': 'Portrait layout stress test',
        'accent': (132, 165, 255),
        'background': (24, 31, 55),
        'taken_at': '2023-12-28T19:30:00Z',
        'location': 'Phoenix, Arizona',
        'people': ['Taylor', 'Morgan', 'Casey', 'Riley', 'Quinn'],
        'album': 'Local Simulator',
        'is_favorite': False,
    },
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description='Create local simulator data and launch the photo frame in a desktop window.'
    )
    parser.add_argument(
        '--size',
        default='1280x720',
        help='Simulator window size, formatted WIDTHxHEIGHT. Use 720x1280 to test portrait.',
    )
    parser.add_argument(
        '--auto-exit-seconds',
        type=int,
        default=0,
        help='Close automatically after N seconds. Useful for smoke checks.',
    )
    parser.add_argument(
        '--reset',
        action='store_true',
        help='Regenerate simulator config, photos, and metadata.',
    )
    parser.add_argument(
        '--verbose',
        action='store_true',
        help='Enable app console logging.',
    )
    parser.add_argument(
        '--prepare-only',
        action='store_true',
        help='Create simulator data without launching the app.',
    )
    return parser.parse_args()


def reset_simulator_dir() -> None:
    if not SIMULATOR_DIR.exists():
        return

    for path in sorted(SIMULATOR_DIR.rglob('*'), reverse=True):
        if path.is_file():
            path.unlink()
        elif path.is_dir():
            path.rmdir()
    SIMULATOR_DIR.rmdir()


def interpolate(start: tuple[int, int, int], end: tuple[int, int, int], ratio: float) -> tuple[int, int, int]:
    return tuple(round(start[index] + (end[index] - start[index]) * ratio) for index in range(3))


def generate_photo(sample: dict[str, object], output_path: Path, size: tuple[int, int] = (1600, 1000)) -> None:
    width, height = size
    background = sample['background']
    accent = sample['accent']
    assert isinstance(background, tuple)
    assert isinstance(accent, tuple)

    pixels = bytearray(width * height * 3)

    def set_pixel(x: int, y: int, color: tuple[int, int, int]) -> None:
        if 0 <= x < width and 0 <= y < height:
            offset = (y * width + x) * 3
            pixels[offset : offset + 3] = bytes(color)

    for y in range(height):
        ratio = y / max(1, height - 1)
        color = interpolate(background, accent, ratio * 0.42)
        for x in range(width):
            vignette = abs((x / width) - 0.5) * 0.26
            set_pixel(x, y, interpolate(color, (0, 0, 0), vignette))

    def fill_rect(left: float, top: float, right: float, bottom: float, color: tuple[int, int, int]) -> None:
        for y in range(round(top), round(bottom)):
            for x in range(round(left), round(right)):
                set_pixel(x, y, color)

    def fill_ellipse(left: float, top: float, right: float, bottom: float, color: tuple[int, int, int]) -> None:
        center_x = (left + right) / 2
        center_y = (top + bottom) / 2
        radius_x = max(1, (right - left) / 2)
        radius_y = max(1, (bottom - top) / 2)
        for y in range(max(0, round(top)), min(height, round(bottom))):
            for x in range(max(0, round(left)), min(width, round(right))):
                if ((x - center_x) / radius_x) ** 2 + ((y - center_y) / radius_y) ** 2 <= 1:
                    set_pixel(x, y, color)

    def draw_line(start: tuple[float, float], end: tuple[float, float], color: tuple[int, int, int], thickness: int) -> None:
        x1, y1 = start
        x2, y2 = end
        steps = max(abs(round(x2 - x1)), abs(round(y2 - y1)), 1)
        radius = max(1, thickness // 2)
        for step in range(steps + 1):
            ratio = step / steps
            x = round(x1 + (x2 - x1) * ratio)
            y = round(y1 + (y2 - y1) * ratio)
            fill_ellipse(x - radius, y - radius, x + radius, y + radius, color)

    fill_rect(0, height * 0.62, width, height, interpolate(background, (0, 0, 0), 0.28))
    fill_ellipse(width * 0.62, -height * 0.18, width * 1.08, height * 0.56, accent)
    fill_rect(width * 0.08, height * 0.16, width * 0.16, height * 0.84, (235, 243, 247))
    fill_rect(width * 0.18, height * 0.16, width * 0.26, height * 0.84, (192, 218, 229))
    draw_line((width * 0.08, height * 0.70), (width * 0.42, height * 0.52), (255, 255, 255), 8)
    draw_line((width * 0.42, height * 0.52), (width * 0.70, height * 0.76), (255, 255, 255), 8)
    fill_rect(width * 0.09, height * 0.74, width * 0.45, height * 0.80, (248, 251, 255))
    fill_rect(width * 0.09, height * 0.82, width * 0.34, height * 0.85, (214, 226, 235))

    rows = []
    row_width = width * 3
    for y in range(height):
        row = pixels[y * row_width : (y + 1) * row_width]
        rows.append(b'\x00' + bytes(row))
    raw_payload = b''.join(rows)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(build_png(width, height, raw_payload))


def png_chunk(name: bytes, payload: bytes) -> bytes:
    return (
        struct.pack('>I', len(payload))
        + name
        + payload
        + struct.pack('>I', binascii.crc32(name + payload) & 0xFFFFFFFF)
    )


def build_png(width: int, height: int, raw_payload: bytes) -> bytes:
    signature = b'\x89PNG\r\n\x1a\n'
    header = struct.pack('>IIBBBBB', width, height, 8, 2, 0, 0, 0)
    return (
        signature
        + png_chunk(b'IHDR', header)
        + png_chunk(b'IDAT', zlib.compress(raw_payload, level=6))
        + png_chunk(b'IEND', b'')
    )


def write_config() -> None:
    SIMULATOR_DIR.mkdir(parents=True, exist_ok=True)
    payload = {
        'local_folder': 'photos',
        'image_cycle_seconds': 5,
        'hourly_interval_seconds': 3600,
        'immich_server_url': '',
        'api_key': '',
        'album_id': '',
        'home_assistant_weather_url': '',
        'weather_api_key': '',
    }
    CONFIG_PATH.write_text(json.dumps(payload, indent=2) + '\n', encoding='utf-8')


def write_sample_photos() -> None:
    PHOTOS_DIR.mkdir(parents=True, exist_ok=True)
    manifest: dict[str, object] = {'photos': {}}
    photos = manifest['photos']
    assert isinstance(photos, dict)

    for sample in SAMPLE_PHOTOS:
        filename = str(sample['filename'])
        output_path = PHOTOS_DIR / filename
        generate_photo(sample, output_path)
        photos[filename] = {
            'taken_at': sample['taken_at'],
            'location': sample['location'],
            'people': sample['people'],
            'album': sample['album'],
            'is_favorite': sample['is_favorite'],
            'original_filename': filename,
        }

    MANIFEST_PATH.write_text(json.dumps(manifest, indent=2) + '\n', encoding='utf-8')


def ensure_simulator_data(reset: bool) -> None:
    if reset:
        reset_simulator_dir()

    if CONFIG_PATH.exists() and MANIFEST_PATH.exists() and any(PHOTOS_DIR.glob('*.png')):
        return

    write_config()
    write_sample_photos()


def launch_app(args: argparse.Namespace) -> int:
    command = [
        sys.executable,
        str(REPO_ROOT / 'main.py'),
        '--config',
        str(CONFIG_PATH),
        '--demo-mode',
        '--windowed',
        '--size',
        args.size,
    ]
    if args.auto_exit_seconds > 0:
        command.extend(['--auto-exit-seconds', str(args.auto_exit_seconds)])
    if args.verbose:
        command.append('--verbose')

    return subprocess.run(command, cwd=REPO_ROOT, check=False).returncode


def main() -> int:
    args = parse_args()
    ensure_simulator_data(reset=args.reset)
    if args.prepare_only:
        print(f'Prepared simulator data in {SIMULATOR_DIR}')
        return 0
    return launch_app(args)


if __name__ == '__main__':
    raise SystemExit(main())
