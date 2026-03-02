# Deployment Guide (PySide6 + Qt Quick)

This guide follows Qt for Python deployment recommendations (`pyside6-rcc`, `pyside6-deploy`, Qt Resource System).

## 1) Prepare project
From repo root:

```bash
python3 -m venv venv
venv/bin/python -m pip install -r requirements.txt
venv/bin/pyside6-rcc resources.qrc -o rc_resources.py
```

That build step generates `rc_resources.py` from `resources.qrc`, allowing `qrc:/` loading of QML and assets.
This project intentionally stays on PySide6 6.8.x for Raspberry Pi compatibility.

## 2) Local smoke test

```bash
QT_QPA_PLATFORM=offscreen venv/bin/python main.py --demo-mode --auto-exit-seconds 3 --verbose
```

## 3) Initialize deploy spec
Run once from repo root:

```bash
venv/bin/pyside6-deploy main.py --init
```

Use the checked-in `pysidedeploy.spec` as a starting point.

## 4) Dry run and build package

```bash
venv/bin/pyside6-deploy -c pysidedeploy.spec --dry-run
venv/bin/pyside6-deploy -c pysidedeploy.spec --mode standalone
```

Output is placed under `dist`.

## 5) Raspberry Pi install layout
Recommended layout:

```text
/opt/photo-frame/
  main.py
  photoframe/
  qml/
  config.json
  deploy/run_photo_frame.sh
  venv/
```

## 6) Raspberry Pi runtime dependencies
Install required runtime libraries for Qt xcb plugin:

```bash
sudo apt update
sudo apt install -y libxcb-cursor0
```

If your system locale is non-UTF-8, set UTF-8 locale values in `/etc/default/photo_frame`
(the provided env template already uses `LANG=C.UTF-8` and `LC_ALL=C.UTF-8`).

## 7) Systemd service

```bash
sudo cp /opt/photo-frame/deploy/photo_frame.service /etc/systemd/system/
sudo chmod +x /opt/photo-frame/deploy/run_photo_frame.sh
sudo systemctl daemon-reload
sudo systemctl enable --now photo_frame.service
sudo systemctl status photo_frame.service
```

If you need overrides, install the optional env file:

```bash
sudo cp /opt/photo-frame/deploy/photo_frame.env.example /etc/default/photo_frame
```

Default checked-in profile is X11 for user `pi`:
- `User=pi`, `Group=pi`
- `DISPLAY=:0`
- `XAUTHORITY=/home/pi/.Xauthority`
- `QT_QPA_PLATFORM=xcb`
- `QSG_RENDER_LOOP=basic`
- `QSG_RHI_BACKEND=opengl`

`APP_DIR` and `CONFIG_PATH` default in `deploy/run_photo_frame.sh`, so `/etc/default/photo_frame` is only needed for overrides.
Use `/etc/default/photo_frame` to override environment variables without editing the unit file.
If your username is not `pi`, update `User`/`Group` in the unit and the `XAUTHORITY` path.

When `QT_QPA_PLATFORM` is unset (for example, direct manual runs), launcher auto-detect order is:
1. Existing `QT_QPA_PLATFORM` value
2. Wayland session (`WAYLAND_DISPLAY` or `XDG_SESSION_TYPE=wayland`) -> `wayland`
3. X11 session (`DISPLAY` set) -> `xcb`
4. Fallback -> `eglfs`

### X11 notes
- Defaults are already set for X11 in the service file.
- Verify `XAUTHORITY` path matches your desktop user.

### Wayland notes
- Ensure service runs as the desktop user in the active session.
- Set `QT_QPA_PLATFORM=wayland` in `/etc/default/photo_frame`.

## 8) Verify and troubleshoot

```bash
systemctl status photo_frame.service
journalctl -u photo_frame.service -f
```

## 9) Shutdown behavior
By default, shutdown command fallback order is:
1. `systemctl poweroff`
2. `shutdown -h now`
3. `sudo shutdown now`

For deterministic behavior, set `shutdown_command` in config:

```json
"shutdown_command": ["systemctl", "poweroff"]
```

If privileges are insufficient, configure polkit/sudoers for your deployment user.
