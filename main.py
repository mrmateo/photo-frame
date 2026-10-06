from __future__ import annotations

import argparse
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import signal
import sys

from PySide6.QtCore import QCoreApplication, QStandardPaths, QTimer, Qt, QUrl

from photoframe import __version__
from photoframe.config import AppConfig, MAX_INTERVAL_SECONDS

APP_DIR = Path(__file__).resolve().parent
DEFAULT_LOCAL_CONFIG_PATH = APP_DIR / 'config.json'
DEFAULT_ENV_CONFIG_KEY = 'PHOTO_FRAME_CONFIG'
RESOURCE_QML_URL = QUrl('qrc:/qml/Main.qml')
RESOURCE_WEATHER_ICON_BASE = 'qrc:/assets/weather'


def configure_logging(verbose: bool = False, log_file: Path | None = None) -> None:
    # stderr works for terminal runs and systemd's journal without extra flags.
    logging.basicConfig(level=logging.DEBUG if verbose else logging.INFO,
                        format='%(asctime)s %(levelname)s %(name)s %(message)s',
                        handlers=[logging.StreamHandler()], force=True)
    if log_file is not None:
        try:
            log_file = log_file.expanduser()
            log_file.parent.mkdir(parents=True, exist_ok=True)
            handler = RotatingFileHandler(log_file, maxBytes=2 * 1024 * 1024, backupCount=4, encoding='utf-8')
            handler.setFormatter(logging.getLogger().handlers[0].formatter)
            logging.getLogger().addHandler(handler)
        except OSError as error:
            logging.getLogger(__name__).warning('Cannot open optional log file %s: %s', log_file, error)


def parse_auto_exit_seconds(raw_value: str) -> int:
    try:
        value = int(raw_value)
    except ValueError as error:
        raise argparse.ArgumentTypeError('--auto-exit-seconds must be an integer') from error
    if not 0 <= value <= MAX_INTERVAL_SECONDS:
        raise argparse.ArgumentTypeError(f'--auto-exit-seconds must be between 0 and {MAX_INTERVAL_SECONDS}')
    return value


def parse_window_size(raw_value: str) -> tuple[int, int]:
    try:
        width, height = map(int, raw_value.strip().lower().replace('×', 'x').split('x'))
    except ValueError as error:
        raise argparse.ArgumentTypeError('--window-size must use WIDTHxHEIGHT, for example 800x1280') from error
    if not (320 <= width <= 16_384 and 320 <= height <= 16_384):
        raise argparse.ArgumentTypeError('--window-size dimensions must be between 320 and 16384')
    return width, height


def resolve_config_path(explicit_path: str | None, demo_mode: bool) -> Path | None:
    selected = explicit_path or os.environ.get(DEFAULT_ENV_CONFIG_KEY, '').strip()
    if selected:
        candidate = Path(selected).expanduser().resolve()
        if not candidate.is_file():
            raise ValueError(f'Config file not found at {candidate}')
        return candidate
    standard_path = Path(QStandardPaths.writableLocation(QStandardPaths.AppConfigLocation)) / 'config.json'
    for candidate in (standard_path, DEFAULT_LOCAL_CONFIG_PATH):
        if candidate.is_file():
            return candidate
    if demo_mode:
        return None
    raise ValueError(f'No config found. Use --config PATH or {DEFAULT_ENV_CONFIG_KEY}, or create {standard_path}.')


def check_photos_directory(config: AppConfig) -> Path:
    photos_path = config.resolve_photos_path()
    existing = photos_path
    while not existing.exists() and existing != existing.parent:
        existing = existing.parent
    if not existing.is_dir() or not os.access(existing, os.R_OK | os.W_OK | os.X_OK):
        raise ValueError(f'Photo directory is not writable by this user: {photos_path}')
    return photos_path


def load_qml_resources() -> bool:
    try:
        import rc_resources  # type: ignore  # noqa: F401
    except ImportError:
        return False
    return True


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description='Digital photo frame (PySide6 + Qt Quick)')
    parser.add_argument('--version', action='version', version=__version__)
    parser.add_argument('-c', '--config', help='Path to JSON configuration.')
    parser.add_argument('--check-config', action='store_true', help='Validate configuration and photo-directory access without a display or network calls.')
    parser.add_argument('--demo-mode', action='store_true', help='Skip network calls and power commands.')
    parser.add_argument('--auto-exit-seconds', type=parse_auto_exit_seconds, default=0)
    parser.add_argument('--windowed', action='store_true')
    parser.add_argument('--window-size', type=parse_window_size, default=(1280, 720), metavar='WIDTHxHEIGHT')
    parser.add_argument('--resources', choices=('auto', 'filesystem', 'embedded'), default='auto',
                        help='Use filesystem for development; embedded requires a resource build.')
    parser.add_argument('--log-file', type=Path, help='Also write rotating logs to this file.')
    parser.add_argument('--verbose', action='store_true', help='Enable debug logging.')
    return parser


def main() -> int:
    args = build_parser().parse_args()
    QCoreApplication.setOrganizationName('DigitalPhotoFrame')
    QCoreApplication.setApplicationName('PhotoFrame')
    QCoreApplication.setApplicationVersion(__version__)
    configure_logging(verbose=args.verbose, log_file=args.log_file)
    logger = logging.getLogger(__name__)
    try:
        config_path = resolve_config_path(args.config, demo_mode=args.demo_mode)
        config = AppConfig.demo(APP_DIR) if config_path is None else AppConfig.from_file(config_path)
        photos_path = check_photos_directory(config)
        if args.check_config:
            print(f'Configuration valid: {config_path or "demo defaults"}\nPhotos: {photos_path}')
            print(f'Photo sync: {"configured" if config.can_sync else "disabled"}; '
                  f'weather: {"configured" if config.can_fetch_weather else "disabled"}')
            return 0
        photos_path.mkdir(parents=True, exist_ok=True)
    except (OSError, ValueError) as error:
        logger.error('%s', error)
        return 1

    use_qrc = args.resources != 'filesystem' and load_qml_resources()
    if args.resources == 'embedded' and not use_qrc:
        logger.error('Embedded resources are missing. Run scripts/bootstrap.sh or pyside6-project build .')
        return 1
    qml_url = RESOURCE_QML_URL if use_qrc else QUrl.fromLocalFile(str(APP_DIR / 'qml/Main.qml'))
    weather_base = RESOURCE_WEATHER_ICON_BASE if use_qrc else str(APP_DIR / 'assets/weather')
    logger.info('Using %s resources; photos: %s', 'embedded' if use_qrc else 'filesystem', photos_path)

    # Configuration/help commands above never initialize a GUI platform plugin.
    from PySide6.QtGui import QCursor, QGuiApplication
    from PySide6.QtQml import QQmlApplicationEngine
    from photoframe.controller import PhotoFrameController

    QGuiApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    app = QGuiApplication([sys.argv[0]])
    if not args.windowed:
        app.setOverrideCursor(QCursor(Qt.CursorShape.BlankCursor))
    engine = QQmlApplicationEngine()
    controller = PhotoFrameController(config, weather_base, demo_mode=args.demo_mode)
    engine.objectCreationFailed.connect(lambda _url: app.exit(1), Qt.ConnectionType.QueuedConnection)
    engine.setInitialProperties({'backend': controller, 'startFullScreen': not args.windowed,
                                 'initialWindowWidth': args.window_size[0], 'initialWindowHeight': args.window_size[1]})
    engine.load(qml_url)
    if not engine.rootObjects():
        controller.stop()
        logger.error('QML engine failed to load %s', qml_url.toString())
        return 1

    app.aboutToQuit.connect(controller.stop)
    if not args.windowed:
        app.aboutToQuit.connect(QGuiApplication.restoreOverrideCursor)
    previous_handlers = {sig: signal.signal(sig, lambda *_: app.quit()) for sig in (signal.SIGINT, signal.SIGTERM)}
    QTimer.singleShot(0, controller.start)
    if args.auto_exit_seconds:
        QTimer.singleShot(args.auto_exit_seconds * 1000, app.quit)
    try:
        return app.exec()
    finally:
        controller.stop()
        # Tear down QML bindings while their Python backend is still alive.
        del engine
        for sig, handler in previous_handlers.items():
            signal.signal(sig, handler)


if __name__ == '__main__':
    raise SystemExit(main())
