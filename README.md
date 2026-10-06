# Photo Frame

A PySide6 + Qt Quick slideshow for an Immich album, with face-aware cropping,
Home Assistant weather, photo details, and touch controls.

## Quick start

Requires Python 3.11 or newer. From the repository root:

```bash
bash scripts/bootstrap.sh
cp config.example.json config.json
# Edit config.json with your server URLs, album ID, and API keys.
.venv/bin/python main.py --check-config --config config.json
bash scripts/run_dev.sh --config config.json
```

`bootstrap.sh` creates `.venv`, installs the exact versions in `requirements.txt`,
checks dependencies, and builds Qt resources with the correct executable search path.
Set `PYTHON_BIN` if your default Python is older than 3.11:

```bash
PYTHON_BIN=python3.13 bash scripts/bootstrap.sh
```

Set `VENV_DIR` on the scripts to use another environment. If an existing environment
is broken (for example after removing its Python installation), the bootstrap
reports it without deleting it. Move that directory aside or choose a new `VENV_DIR`.

The development launcher opens a window and always loads QML/assets from the
filesystem, so edits are visible on the next run even if an older resource bundle exists.
For fullscreen operation, use `.venv/bin/python main.py --config config.json`.

## Configuration

Settings are described by `config.example.json`:

- `immich_server_url`, `api_key`, `album_id`: configure all three, or leave all empty to disable sync.
- `home_assistant_weather_url`, `weather_api_key`: configure both, or leave both empty to disable weather.
- `local_folder`: a dedicated photo cache directory, relative to the config file or absolute; `~` expands to the current user's home.
- `image_cycle_seconds`: integer from 3 through 2147483; default 15.
- `hourly_interval_seconds`: sync/weather polling interval, integer from 60 through 2147483; default 3600.
- `shutdown_command`: optional command array or shell-like argument string. No shell is executed. Example: `["systemctl", "--no-ask-password", "poweroff"]`.

Unknown settings, invalid types, malformed URLs, and incomplete integrations are
reported with the setting name. `--check-config` validates settings and directory
access without opening a display or contacting either server. Run it as the same
user who will run the frame; it does not create directories.

Configuration lookup order:

1. `--config PATH`
2. `PHOTO_FRAME_CONFIG`
3. `QStandardPaths.AppConfigLocation/config.json`
4. `config.json` beside `main.py`

Recommended Immich key permissions are `asset.read` for album search,
`asset.download` for image downloads, and optional `face.read` for cropping and
people. The search API does not supply an album name, so new syncs omit that
caption instead of labeling every album "Picture Frame".

For an offline collection, a config containing only `{"local_folder": "photos"}` is enough.
The directory supports JPEG and PNG images. Enabling Immich sync makes it a managed
cache: a completed sync removes JPEGs outside the selected album, including older
filename-based copies. Use a dedicated directory.

## Controls and behavior

- Tap the left/right edges to navigate; automatic slides follow Immich search order.
- Tap the top center for date, location, favorite state, filename, and tagged people.
- Tap the middle to reveal controls. Hold power for 1.1 seconds to shut down.
- Crossfades wait for the next image to decode and keep the previous photo on load failure.
- Cropping keeps detected faces visible. A group that cannot fit, or inconsistent
  coordinate dimensions, causes the whole image to be shown with letterboxing.
- EXIF rotation/mirroring is normalized; edited Immich images are downloaded to
  match face coordinates. Missing face metadata falls back to a centered crop.

Demo mode disables network and power commands:

```bash
bash scripts/run_dev.sh --demo-mode --window-size 800x1280
QT_QPA_PLATFORM=offscreen QT_QUICK_BACKEND=software .venv/bin/python main.py --demo-mode --auto-exit-seconds 3
```

Logs go to stderr by default, including the systemd journal. `--verbose` enables
debug logging. `--log-file /path/photo_frame.log` additionally enables rotating
file logs; failure to open that optional file does not prevent startup.

## Tests and dependency updates

```bash
bash scripts/check.sh
```

This builds resources, checks shell syntax, and runs all tests, including offscreen
QML rendering, HEIC conversion, config/launcher failures, retries, cancellation,
power-command timeouts, and demo startup with both resource modes. CI runs the same
command on Python 3.11 and 3.13.

`pyproject.toml` declares direct dependencies. `requirements.txt` is the generated
lock containing exact runtime versions. To deliberately update them:

```bash
.venv/bin/python scripts/update_lock.py
bash scripts/bootstrap.sh
bash scripts/check.sh
```

The update script resolves dependencies in a temporary clean environment. Review
and commit the resulting lockfile after testing. Application version lives in
`photoframe/__init__.py`; packaging and `--version` read it from there.

## Code layout

- `main.py`: CLI, config discovery, logging, resource selection, and app lifecycle.
- `photoframe/controller.py`: Qt properties, timers, navigation, and worker coordination.
- `photoframe/http_client.py`: per-service sessions, transient retries, and cancellation.
- `photoframe/photo_sync_service.py`: album enumeration, downloads, and safe cache cleanup.
- `photoframe/metadata.py`: normalization of Immich responses.
- `photoframe/manifest.py`: typed metadata definitions and shared atomic manifest storage.
- `photoframe/presentation.py`: photo details and crop validation independent of Qt.
- `qml/Slideshow.qml`: image loading, crop geometry, and two-buffer crossfades.
- `qml/InfoPanel.qml`: metadata, clock/weather, and action controls.
- `qml/Main.qml`: window, gestures, and overlay visibility.

## Cache recovery

`.photo_frame_manifest.json` stores metadata and slideshow order beside the photos.
Files use `asset-<id>-<revision>.jpg` names to avoid collisions and keep old face
coordinates paired with old image pixels during refreshes. Server revision changes
refresh the image, including some metadata-only changes.

Downloads and the manifest are published atomically. Corrupt JPEGs are downloaded
again. Failed downloads preserve existing photos; legacy filename caches migrate
on successful sync. Face request failures preserve bounds for the same revision;
a successful empty response clears them. Stale cleanup requires completely
validated pagination and successful downloads. Cancellation prevents further
requests, interrupts retry waits, and stops before manifest publication or further
cleanup when observed; a request already in progress may need its timeout to expire.

## Raspberry Pi and packaged builds

See [DEPLOYMENT.md](DEPLOYMENT.md) for installation, writable cache setup, systemd,
standalone packaging, and diagnostics.
