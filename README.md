# PySide6 + Qt Quick Photo Frame (Deployment-Ready Starter)

This implementation is structured around Qt/PySide deployment guidance:
- Qt Quick UI + Python backend separation,
- bundled QML/assets via Qt Resource System (`resources.qrc`),
- standard app/config/log paths (`QStandardPaths`),
- deployment flow with `pyside6-project` and `pyside6-deploy`.

## Included behavior
- Full-screen slideshow with edge tap navigation in the order returned by Immich's album search.
- Face-aware portrait cropping using Immich's detected face bounds, with a
  centered-crop fallback when face metadata is unavailable. If the detected faces
  cannot all fit in the viewport crop, the whole photo is shown with letterboxing.
  EXIF rotation and mirrored orientations are applied before cropping.
  Immich's edited image is requested so in-app crops, rotations, and flips match
  its face coordinates. Inconsistent coordinate dimensions also use the whole-photo fallback.
- Top-center tap photo metadata overlay with date, location, album,
  favorite state, filename, and tagged people when available.
- Crossfade transitions that wait for the next photo to load, with responsive info panel layout.
- Immich photo sync service (download, convert, metadata manifest, stale cleanup).
- Home Assistant weather polling service with retries.
- Hourly sync/weather timers and per-second clock updates.
- Manual sync + shutdown buttons.

## Key files
- `main.py`: app bootstrap, CLI parsing, config discovery, logging.
- `photoframe/controller.py`: Qt-facing state controller.
- `photoframe/photo_sync_service.py`: Immich sync backend.
- `photoframe/weather_service.py`: Home Assistant weather backend.
- `qml/Main.qml`: Qt Quick UI.
- `resources.qrc`: bundled QML/weather assets.
- `pyproject.toml`: `pyside6-project` source manifest.

## Config
1. Copy `config.example.json` to `config.json`.
2. Update keys/URLs.

Optional:
- `shutdown_command`: command array used by shutdown button.
  - Example: `["systemctl", "poweroff"]`

Recommended Immich API key permissions:
- `album.read`: read the configured album and its asset list.
- `asset.read`: search for the photos in the configured album.
- `asset.download`: download each original image.
- `face.read`: optional but recommended for smart cropping and tagged people.
  The app uses `GET /api/faces?id=<asset_id>` to keep detected faces inside the
  portrait crop and falls back to a centered crop when face data is unavailable.

Config lookup order at runtime:
1. `--config <path>`
2. `PHOTO_FRAME_CONFIG` env var
3. `QStandardPaths.AppConfigLocation/config.json`
4. `config.json`

## Development run
From repo root:

1. Install deps:
   - `venv/bin/python -m pip install -r requirements.txt`
2. Build Qt resources:
   - `venv/bin/pyside6-project build .`
3. Run:
   - `venv/bin/python main.py --config config.json`

Demo mode (no network/poweroff):
- `QT_QPA_PLATFORM=offscreen venv/bin/python main.py --demo-mode --auto-exit-seconds 5`

Windowed simulator preview:
- `venv/bin/python main.py --config .dev-simulator/config.json --demo-mode --windowed --window-size 800x1280`

Regression tests (including offscreen QML rendering and HEIC conversion):
- `QT_QPA_PLATFORM=offscreen QT_QUICK_BACKEND=software venv/bin/python -m unittest discover -s tests -v`

## Deployable package (pyside6-deploy)
From repo root:

1. Initialize spec once:
   - `venv/bin/pyside6-deploy main.py --init`
2. Edit `pysidedeploy.spec` values (`title`, `input_file`, `project_dir`, `qml_files`, `exec_directory`).
3. Dry run:
   - `venv/bin/pyside6-deploy -c pysidedeploy.spec --dry-run`
4. Build standalone package:
   - `venv/bin/pyside6-deploy -c pysidedeploy.spec --mode standalone`

## Raspberry Pi systemd template
- Service template: `deploy/photo_frame.service`
- Launcher script: `deploy/run_photo_frame.sh`
- Optional env overrides template: `deploy/photo_frame.env.example`

Typical install flow:
1. Copy app folder to `/opt/photo-frame`.
2. Install runtime dependency for xcb plugin:
   - `sudo apt update && sudo apt install -y libxcb-cursor0`
3. Make script executable:
   - `chmod +x /opt/photo-frame/deploy/run_photo_frame.sh`
4. Install unit:
   - `sudo cp /opt/photo-frame/deploy/photo_frame.service /etc/systemd/system/`
5. Optional: install env overrides file:
   - `sudo cp /opt/photo-frame/deploy/photo_frame.env.example /etc/default/photo_frame`
6. Enable/start:
   - `sudo systemctl daemon-reload`
   - `sudo systemctl enable --now photo_frame.service`

The service defaults to an X11 profile for `pi`:
- `User=pi`, `Group=pi`
- `DISPLAY=:0`
- `XAUTHORITY=/home/pi/.Xauthority`
- `QT_QPA_PLATFORM=xcb`

`APP_DIR` and `CONFIG_PATH` default in `deploy/run_photo_frame.sh`, so `/etc/default/photo_frame` is only needed for overrides.
If your username differs, update `User`/`Group` in `photo_frame.service` and `XAUTHORITY` in the service or `/etc/default/photo_frame`.
If your system locale is non-UTF-8, set `LANG=C.UTF-8` and `LC_ALL=C.UTF-8` in `/etc/default/photo_frame`.

When `QT_QPA_PLATFORM` is unset (manual runs), launcher fallback is:
- Wayland session -> `QT_QPA_PLATFORM=wayland`
- X11 session -> `QT_QPA_PLATFORM=xcb`
- No desktop session -> `QT_QPA_PLATFORM=eglfs`

Override by setting `QT_QPA_PLATFORM` in `/etc/default/photo_frame`.

## Notes
- If `rc_resources.py` is missing, app falls back to filesystem QML/assets and logs a warning.
- Logs are written to `QStandardPaths.AppDataLocation/logs/photo_frame.log`.
- Synced photo metadata and search-result order are stored beside the downloaded photos in `.photo_frame_manifest.json`.
- Photos are cached as `asset-<asset_id>-<revision>.jpg` so repeated camera filenames stay distinct.
  Revision filenames keep an older slideshow's face bounds paired with its older
  pixels while sync fetches updated photos. Changes to Immich's `updatedAt`, checksum,
  or edit state refresh the image; this can also refresh it after metadata-only changes.
  The first successful sync after upgrading downloads fresh images to replace
  older filename-based caches and repair any previously lost orientation data.
  If any download fails, existing photos are retained and migration retries on the next sync.
- Downloads are decoded and saved atomically. Corrupt cached JPEGs are downloaded again.
- Face metadata request failures retain the last known bounds and people for the
  same asset and image revision; a successful empty face response clears those cached values.
  Face boxes partly outside an edited image are clipped to its visible area;
  faces entirely outside it do not affect cropping.
- Stale cleanup runs only after every search-results page has been validated and
  all required photo downloads have succeeded. It removes local `.jpg`/`.jpeg`
  files outside the completed album cache, including obsolete filename-based copies.

## Collect Raspberry Pi diagnostics
To collect environment details for deployment tuning:

- `bash /opt/photo-frame/deploy/collect_pi_diagnostics.sh | tee photo_frame_diag.txt`

If you are running from this repository instead of `/opt`, use:

- `bash deploy/collect_pi_diagnostics.sh | tee photo_frame_diag.txt`

Optional overrides if needed:

- `APP_DIR=/your/app/path`
- `PYTHON_BIN=/your/python/path`
- `APP_SERVICE=photo_frame.service`

The script reports system/session/service/Qt runtime details and does not print `config.json` secrets.
