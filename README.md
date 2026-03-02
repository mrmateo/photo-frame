# PySide6 + Qt Quick Photo Frame (Deployment-Ready Starter)

This implementation is structured around Qt/PySide deployment guidance:
- Qt Quick UI + Python backend separation,
- bundled QML/assets via Qt Resource System (`resources.qrc`),
- standard app/config/log paths (`QStandardPaths`),
- deployment flow with `pyside6-rcc` and `pyside6-deploy`.

## Included behavior
- Full-screen slideshow with edge tap navigation.
- Fade transitions and responsive info panel layout.
- Immich photo sync service (download, convert, stale cleanup).
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
- `pyproject.toml`: project metadata and Python dependency manifest.

## Config
1. Copy `config.example.json` to `config.json`.
2. Update keys/URLs.

Optional:
- `shutdown_command`: command array used by shutdown button.
  - Example: `["systemctl", "poweroff"]`

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
   - `venv/bin/pyside6-rcc resources.qrc -o rc_resources.py`
3. Run:
   - `venv/bin/python main.py --config config.json`

This project intentionally stays on PySide6 6.8.x for Raspberry Pi compatibility.

Demo mode (no network/poweroff):
- `QT_QPA_PLATFORM=offscreen venv/bin/python main.py --demo-mode --auto-exit-seconds 5`

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
