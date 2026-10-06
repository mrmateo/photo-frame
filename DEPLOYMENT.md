# Deployment

## Raspberry Pi source deployment

Use a desktop session with Python 3.11 or newer. Install the runtime libraries and
copy this repository to `/opt/photo-frame` (including `assets`, `qml`, and `deploy`).
Create the virtual environment **on the Pi**; environments copied from another
machine are not portable.

```bash
sudo apt update
sudo apt install -y python3-venv libxcb-cursor0 libegl1 libopengl0 libxkbcommon-x11-0
```

As the user who owns the application checkout:

```bash
cd /opt/photo-frame
bash scripts/bootstrap.sh
cp config.example.json config.json
```

Edit the config with your credentials. Set `local_folder` to the writable service
cache rather than the application directory:

```json
"local_folder": "/var/lib/photo-frame/photos"
```

The service's `StateDirectory=photo-frame` makes systemd create `/var/lib/photo-frame`
and give ownership to the service user. To validate/run before the first service
start, create it explicitly (replace `pi` throughout if your username differs):

```bash
sudo install -d -o pi -g pi -m 0750 /var/lib/photo-frame
sudo chown root:pi /opt/photo-frame/config.json
sudo chmod 0640 /opt/photo-frame/config.json
sudo -u pi /opt/photo-frame/.venv/bin/python /opt/photo-frame/main.py --check-config --config /opt/photo-frame/config.json
```

## Install the service

The supplied profile runs in user `pi`'s X11 desktop with `DISPLAY=:0` and
`XAUTHORITY=/home/pi/.Xauthority`. Before installation, adjust the service's
`User`, `Group`, and `XAUTHORITY` if needed. A working graphical login/session
must exist; `graphical.target` alone does not establish desktop authentication.

```bash
sudo cp /opt/photo-frame/deploy/photo_frame.service /etc/systemd/system/
sudo chmod +x /opt/photo-frame/deploy/run_photo_frame.sh
sudo systemctl daemon-reload
sudo systemctl enable --now photo_frame.service
```

Optional environment overrides:

```bash
sudo cp /opt/photo-frame/deploy/photo_frame.env.example /etc/default/photo_frame
```

Set `CONFIG_PATH`, `PYTHON_BIN`, or display variables there. To relocate the whole
application, also update the unit's `WorkingDirectory` and `ExecStart`; `APP_DIR`
alone cannot relocate the launch script used by systemd.

For Wayland, use the active desktop user's `WAYLAND_DISPLAY`, `XDG_RUNTIME_DIR`,
and `QT_QPA_PLATFORM=wayland`. When no platform is explicitly set, the launcher
chooses Wayland from the session, then X11 from `DISPLAY`, then `eglfs`. The
checked-in service explicitly selects X11. UTF-8 locale defaults are supplied by
the launcher and environment template.

## Verify and troubleshoot

```bash
systemctl status photo_frame.service
journalctl -u photo_frame.service -f
bash /opt/photo-frame/deploy/collect_pi_diagnostics.sh | tee photo_frame_diag.txt
```

Application logs go to the journal without extra flags. The diagnostics script
reports session, service, Python, and Qt details without printing the config file.
For a checkout elsewhere, use
`APP_DIR=/your/checkout bash deploy/collect_pi_diagnostics.sh`.

For manual file logging, append `--log-file /writable/path/photo_frame.log` to the
launcher command. It also forwards flags such as `--demo-mode` and `--windowed`.
A missing/broken Python environment produces an actionable setup error.

Closing the app or sending SIGINT/SIGTERM requests cancellation of its workers.
Retries wake immediately; in-flight network calls use their request timeouts.
The service restarts failures, and does not restart a normal application exit.

The power command runs asynchronously with a ten-second timeout. The default
chooses `systemctl --no-ask-password poweroff`, then `shutdown -h now` when
systemctl is unavailable, then `sudo -n shutdown now`. Selection is based on
executable availability; it does not retry a denied command with another tool.
Configure `shutdown_command` and the service user's polkit/sudoers permissions
for your installation. Demo mode never executes it.

## Standalone packaging (optional)

Source deployment above does not require a standalone executable. To build one,
activate the environment so Qt's companion build tools are on `PATH`:

```bash
source .venv/bin/activate
pyside6-project build .
pyside6-deploy -c pysidedeploy.spec --dry-run
pyside6-deploy -c pysidedeploy.spec --mode standalone
```

The checked-in spec includes all three QML components. Output goes under `dist`;
build on the target platform. A packaged deployment needs its own launcher/unit
pointing at that executable, with an explicit config path and writable photo cache.

`--resources embedded` requires the generated Qt bundle and fails clearly if it
is missing. `--resources filesystem` always reads source files and is used by
`scripts/run_dev.sh`. The default `auto` prefers the bundle when available.
`rc_resources.py` and packaging output are generated artifacts and ignored by Git.
