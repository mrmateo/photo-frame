from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import sys

from PySide6.QtCore import QCommandLineOption, QCommandLineParser, QCoreApplication, QStandardPaths, QTimer, Qt, QUrl
from PySide6.QtGui import QGuiApplication
from PySide6.QtQml import QQmlApplicationEngine

from photoframe.config import AppConfig
from photoframe.controller import PhotoFrameController

APP_DIR = Path(__file__).resolve().parent
DEFAULT_LOCAL_CONFIG_PATH = APP_DIR / 'config.json'
DEFAULT_ENV_CONFIG_KEY = 'PHOTO_FRAME_CONFIG'
RESOURCE_QML_URL = QUrl('qrc:/qml/Main.qml')
RESOURCE_WEATHER_ICON_BASE = 'qrc:/assets/weather'


def configure_logging(verbose: bool) -> None:
    app_data_dir = Path(QStandardPaths.writableLocation(QStandardPaths.AppDataLocation))
    log_dir = app_data_dir / 'logs'
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / 'photo_frame.log'

    handlers: list[logging.Handler] = [
        RotatingFileHandler(
            log_path,
            maxBytes=2 * 1024 * 1024,
            backupCount=4,
            encoding='utf-8',
        )
    ]
    if verbose:
        handlers.append(logging.StreamHandler())

    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s %(levelname)s %(name)s %(message)s',
        handlers=handlers,
        force=True,
    )


def parse_auto_exit_seconds(raw_value: str) -> int:
    try:
        return max(0, int(raw_value or 0))
    except ValueError as error:
        raise ValueError('--auto-exit-seconds must be an integer value') from error


def resolve_config_path(explicit_path: str, demo_mode: bool) -> Path | None:
    if explicit_path:
        candidate = Path(explicit_path).expanduser().resolve()
        if not candidate.exists():
            raise FileNotFoundError(f'Config file not found at {candidate}')
        return candidate

    env_path = os.environ.get(DEFAULT_ENV_CONFIG_KEY, '').strip()
    if env_path:
        candidate = Path(env_path).expanduser().resolve()
        if candidate.exists():
            return candidate
        raise FileNotFoundError(
            f'Config file set in {DEFAULT_ENV_CONFIG_KEY} does not exist: {candidate}'
        )

    standard_config_dir = Path(QStandardPaths.writableLocation(QStandardPaths.AppConfigLocation))
    standard_config_path = standard_config_dir / 'config.json'
    if standard_config_path.exists():
        return standard_config_path

    if DEFAULT_LOCAL_CONFIG_PATH.exists():
        return DEFAULT_LOCAL_CONFIG_PATH

    if demo_mode:
        return None

    raise FileNotFoundError(
        'No config.json found. Checked: --config path, PHOTO_FRAME_CONFIG, '
        f'{standard_config_path}, and {DEFAULT_LOCAL_CONFIG_PATH}.'
    )


def load_qml_resources() -> bool:
    try:
        import rc_resources  # type: ignore  # noqa: F401
    except ImportError:
        return False
    return True


def build_parser() -> tuple[QCommandLineParser, dict[str, QCommandLineOption]]:
    parser = QCommandLineParser()
    parser.setApplicationDescription('Digital photo frame app (PySide6 + Qt Quick)')
    parser.addHelpOption()
    parser.addVersionOption()

    config_option = QCommandLineOption(
        ['c', 'config'],
        'Path to JSON config file.',
        'path',
    )
    demo_mode_option = QCommandLineOption(
        ['demo-mode'],
        'Skip network calls and power commands for UI-only demos.',
    )
    auto_exit_option = QCommandLineOption(
        ['auto-exit-seconds'],
        'Auto-close after N seconds (useful for smoke tests).',
        'seconds',
        '0',
    )
    verbose_option = QCommandLineOption(['verbose'], 'Enable console logging.')

    parser.addOption(config_option)
    parser.addOption(demo_mode_option)
    parser.addOption(auto_exit_option)
    parser.addOption(verbose_option)

    return parser, {
        'config': config_option,
        'demo': demo_mode_option,
        'auto_exit': auto_exit_option,
        'verbose': verbose_option,
    }


def main() -> int:
    QCoreApplication.setOrganizationName('DigitalPhotoFrame')
    QCoreApplication.setApplicationName('PhotoFrame')
    QCoreApplication.setApplicationVersion('0.2.0')
    QGuiApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )

    app = QGuiApplication(sys.argv)

    parser, options = build_parser()
    parser.process(app)

    verbose = parser.isSet(options['verbose'])
    configure_logging(verbose=verbose)
    logger = logging.getLogger(__name__)

    demo_mode = parser.isSet(options['demo'])

    try:
        auto_exit_seconds = parse_auto_exit_seconds(parser.value(options['auto_exit']))
        config_path = resolve_config_path(parser.value(options['config']), demo_mode=demo_mode)
        config = AppConfig.demo(APP_DIR) if config_path is None else AppConfig.from_file(config_path)
    except (ValueError, FileNotFoundError) as error:
        parser.showMessageAndExit(QCommandLineParser.MessageType.Error, str(error), 1)
        return 1

    use_qrc = load_qml_resources()
    if use_qrc:
        qml_url = RESOURCE_QML_URL
        weather_icon_base = RESOURCE_WEATHER_ICON_BASE
        logger.info('Using embedded Qt resource bundle for QML and assets.')
    else:
        qml_path = APP_DIR / 'qml' / 'Main.qml'
        if not qml_path.exists():
            logger.error('Main QML file not found at %s', qml_path)
            return 1

        qml_url = QUrl.fromLocalFile(str(qml_path))
        weather_icon_base = str(APP_DIR / 'assets' / 'weather')
        logger.warning(
            'Running without embedded resources (rc_resources.py missing). '
            'Use pyside6-project build for deployable builds.'
        )

    logger.info('Photos directory resolved to: %s', config.resolve_photos_path())
    if config_path is not None:
        logger.info('Loaded config: %s', config_path)
    else:
        logger.info('Running with demo config.')

    engine = QQmlApplicationEngine()
    engine.objectCreationFailed.connect(
        lambda _url: QCoreApplication.exit(1),
        Qt.ConnectionType.QueuedConnection,
    )

    controller = PhotoFrameController(
        config=config,
        weather_icon_base_url=weather_icon_base,
        demo_mode=demo_mode,
    )
    engine.setInitialProperties({'backend': controller})
    engine.load(qml_url)

    if not engine.rootObjects():
        logger.error('QML engine failed to create root object from %s', qml_url.toString())
        return 1

    app.aboutToQuit.connect(controller.stop)
    QTimer.singleShot(0, controller.start)

    if auto_exit_seconds > 0:
        logger.info('Auto exit in %s seconds', auto_exit_seconds)
        QTimer.singleShot(auto_exit_seconds * 1000, app.quit)

    return app.exec()


if __name__ == '__main__':
    raise SystemExit(main())
