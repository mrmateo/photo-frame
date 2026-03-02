from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
import logging
from pathlib import Path
import re
import shutil
import subprocess

from PySide6.QtCore import QObject, Property, QTimer, QUrl, Signal, Slot

from .config import AppConfig
from .photo_sync_service import PhotoSyncService
from .weather_service import WeatherService

LOGGER = logging.getLogger(__name__)
IMAGE_EXTENSIONS = {'.jpg', '.jpeg', '.png'}
SYNC_STATUS_CLEAR_MS = 10_000
CLOCK_MINUTE_INTERVAL_MS = 60_000

WEATHER_ICON_KEYS = {
    'sunny': 'sun',
    'clear': 'sun',
    'cloudy': 'cloud',
    'partlycloudy': 'partly_cloudy',
    'mostlycloudy': 'cloud',
    'overcast': 'cloud',
    'rain': 'rain',
    'lightrain': 'rain',
    'heavyrain': 'heavy_rain',
    'showers': 'rain',
    'drizzle': 'rain',
    'thunderstorm': 'storm',
    'thunder': 'storm',
    'snow': 'snow',
    'lightsnow': 'snow',
    'heavysnow': 'snow',
    'blizzard': 'snow',
    'fog': 'fog',
    'haze': 'fog',
    'windy': 'wind',
    'rainandsnow': 'mix',
}


class PhotoFrameController(QObject):
    currentImageChanged = Signal()
    hasImagesChanged = Signal()
    clockTextChanged = Signal()
    dateTextChanged = Signal()
    weatherTextChanged = Signal()
    weatherIconChanged = Signal()
    syncStatusChanged = Signal()
    syncInProgressChanged = Signal()

    syncProgressSignal = Signal(str)
    syncFinishedSignal = Signal(object, str)
    weatherFinishedSignal = Signal(str, str)

    def __init__(
        self,
        config: AppConfig,
        weather_icon_base_url: str,
        demo_mode: bool = False,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self.config = config
        self.demo_mode = demo_mode
        self.weather_icon_base_url = weather_icon_base_url.rstrip('/')

        self.photo_sync_service = PhotoSyncService()
        self.weather_service = WeatherService()
        self.executor = ThreadPoolExecutor(max_workers=2)

        self.photos_path = self.config.resolve_photos_path()

        self._images: list[Path] = []
        self._index = 0

        self._current_image = ''
        self._has_images = False
        self._clock_text = ''
        self._date_text = ''
        self._weather_text = 'Weather loading...'
        self._weather_icon = self._resolve_weather_icon(None)
        self._sync_status = ''

        self._sync_in_progress = False
        self._weather_in_progress = False

        self._image_timer = QTimer(self)
        self._image_timer.timeout.connect(self._advance_image_timer)

        self._clock_timer = QTimer(self)
        self._clock_timer.timeout.connect(self._on_clock_timer)

        self._weather_timer = QTimer(self)
        self._weather_timer.timeout.connect(self.refreshWeather)

        self._sync_timer = QTimer(self)
        self._sync_timer.timeout.connect(self.syncNow)

        self._status_clear_timer = QTimer(self)
        self._status_clear_timer.setSingleShot(True)
        self._status_clear_timer.timeout.connect(self._clear_sync_status)

        self.syncProgressSignal.connect(self._on_sync_progress)
        self.syncFinishedSignal.connect(self._on_sync_finished)
        self.weatherFinishedSignal.connect(self._on_weather_finished)

    @staticmethod
    def natural_sort_key(name: str) -> list[object]:
        parts = re.split(r'(\d+)', name.lower())
        return [int(part) if part.isdigit() else part for part in parts]

    @Property(str, notify=currentImageChanged)
    def currentImage(self) -> str:
        return self._current_image

    @Property(bool, notify=hasImagesChanged)
    def hasImages(self) -> bool:
        return self._has_images

    @Property(str, notify=clockTextChanged)
    def clockText(self) -> str:
        return self._clock_text

    @Property(str, notify=dateTextChanged)
    def dateText(self) -> str:
        return self._date_text

    @Property(str, notify=weatherTextChanged)
    def weatherText(self) -> str:
        return self._weather_text

    @Property(str, notify=weatherIconChanged)
    def weatherIcon(self) -> str:
        return self._weather_icon

    @Property(str, notify=syncStatusChanged)
    def syncStatus(self) -> str:
        return self._sync_status

    @Property(bool, notify=syncInProgressChanged)
    def syncEnabled(self) -> bool:
        return not self._sync_in_progress

    @Property(bool, notify=syncInProgressChanged)
    def syncInProgress(self) -> bool:
        return self._sync_in_progress

    @Slot()
    def start(self) -> None:
        self.photos_path.mkdir(parents=True, exist_ok=True)
        self._reload_images(preserve_current=False)
        self._update_clock()

        self._image_timer.start(self._image_cycle_interval_ms())
        self._start_clock_timer()
        hourly_interval_ms = self._hourly_interval_ms()
        self._weather_timer.start(hourly_interval_ms)
        self._sync_timer.start(hourly_interval_ms)

        if self.demo_mode:
            self._set_weather_text('Demo mode weather')
            self._set_sync_status('Demo mode: network calls disabled.', auto_clear_ms=SYNC_STATUS_CLEAR_MS)
            return

        self.refreshWeather()
        self.syncNow()

    @Slot()
    def stop(self) -> None:
        for timer in (self._image_timer, self._clock_timer, self._weather_timer, self._sync_timer, self._status_clear_timer):
            timer.stop()
        self.executor.shutdown(wait=False, cancel_futures=True)

    def _set_current_image(self, image_path: Path | None) -> None:
        image_url = QUrl.fromLocalFile(str(image_path)).toString() if image_path else ''
        if self._current_image != image_url:
            self._current_image = image_url
            self.currentImageChanged.emit()

    def _set_has_images(self, has_images: bool) -> None:
        if self._has_images != has_images:
            self._has_images = has_images
            self.hasImagesChanged.emit()

    def _set_clock_text(self, value: str) -> None:
        if self._clock_text != value:
            self._clock_text = value
            self.clockTextChanged.emit()

    def _set_date_text(self, value: str) -> None:
        if self._date_text != value:
            self._date_text = value
            self.dateTextChanged.emit()

    def _set_weather_text(self, value: str) -> None:
        if self._weather_text != value:
            self._weather_text = value
            self.weatherTextChanged.emit()

    def _set_weather_icon(self, value: str) -> None:
        if self._weather_icon != value:
            self._weather_icon = value
            self.weatherIconChanged.emit()

    def _set_sync_in_progress(self, in_progress: bool) -> None:
        if self._sync_in_progress != in_progress:
            self._sync_in_progress = in_progress
            self.syncInProgressChanged.emit()

    def _set_sync_status(self, value: str, auto_clear_ms: int | None = None) -> None:
        if self._sync_status != value:
            self._sync_status = value
            self.syncStatusChanged.emit()

        self._status_clear_timer.stop()
        if auto_clear_ms is not None and value:
            self._status_clear_timer.start(auto_clear_ms)

    def _clear_sync_status(self) -> None:
        self._set_sync_status('', auto_clear_ms=None)

    @Slot(str)
    def _on_sync_progress(self, message: str) -> None:
        self._set_sync_status(message, auto_clear_ms=None)

    def _reload_images(self, preserve_current: bool = True) -> None:
        previous_path = None
        if preserve_current and self._images and self._current_image:
            previous_path = self._images[self._index]

        if not self.photos_path.exists():
            self._images = []
            self._set_has_images(False)
            self._index = 0
            self._set_current_image(None)
            return

        images = [
            path
            for path in sorted(self.photos_path.iterdir(), key=lambda entry: self.natural_sort_key(entry.name))
            if path.is_file() and path.suffix.lower() in IMAGE_EXTENSIONS
        ]
        self._images = images
        self._set_has_images(bool(images))

        if not images:
            self._index = 0
            self._set_current_image(None)
            return

        if previous_path and previous_path in images:
            self._index = images.index(previous_path)
        else:
            self._index = min(self._index, len(images) - 1)

        self._set_current_image(images[self._index])

    def _update_clock(self) -> None:
        now = datetime.now()
        self._set_clock_text(now.strftime('%I:%M %p'))
        self._set_date_text(now.strftime('%A, %b %d'))

    def _start_clock_timer(self) -> None:
        now = datetime.now()
        milliseconds_until_next_minute = (
            ((59 - now.second) * 1000)
            + (1000 - (now.microsecond // 1000))
        )
        self._clock_timer.start(max(1_000, milliseconds_until_next_minute))

    def _on_clock_timer(self) -> None:
        self._update_clock()
        self._clock_timer.start(CLOCK_MINUTE_INTERVAL_MS)

    def _image_cycle_interval_ms(self) -> int:
        return max(1, self.config.image_cycle_seconds) * 1000

    def _hourly_interval_ms(self) -> int:
        return max(60, self.config.hourly_interval_seconds) * 1000

    def _reset_image_timer(self) -> None:
        if self._image_timer.isActive():
            self._image_timer.start(self._image_cycle_interval_ms())

    def _advance_image_timer(self) -> None:
        self._advance_image(delta=1, manual=False)

    def _advance_image(self, delta: int, manual: bool) -> None:
        if not self._images:
            return

        if manual:
            self._reset_image_timer()

        self._index = (self._index + delta) % len(self._images)
        self._set_current_image(self._images[self._index])

    @Slot()
    def nextImage(self) -> None:
        self._advance_image(delta=1, manual=True)

    @Slot()
    def previousImage(self) -> None:
        self._advance_image(delta=-1, manual=True)

    @Slot()
    def syncNow(self) -> None:
        if self.demo_mode:
            self._set_sync_status('Demo mode: sync skipped.', auto_clear_ms=SYNC_STATUS_CLEAR_MS)
            return

        if self.syncInProgress:
            self._set_sync_status('Sync already in progress...', auto_clear_ms=3000)
            return

        if not self.config.can_sync:
            self._set_sync_status('Sync skipped: config incomplete.', auto_clear_ms=SYNC_STATUS_CLEAR_MS)
            return

        self._set_sync_in_progress(True)
        self._set_sync_status('Syncing photos...')
        self.executor.submit(self._sync_worker)

    def _sync_worker(self) -> None:
        try:
            summary = self.photo_sync_service.sync_photos(
                config=self.config,
                photos_path=self.photos_path,
                progress_callback=self.syncProgressSignal.emit,
            )
            self.syncFinishedSignal.emit(summary.to_dict(), '')
        except Exception as error:
            LOGGER.exception('Sync worker failed')
            self.syncFinishedSignal.emit({}, str(error))

    @Slot(object, str)
    def _on_sync_finished(self, summary: object, error_text: str) -> None:
        self._set_sync_in_progress(False)

        if error_text:
            self._set_sync_status('Sync failed. Please check configuration/logs.', auto_clear_ms=SYNC_STATUS_CLEAR_MS)
            return

        self._reload_images(preserve_current=True)
        summary_dict = summary if isinstance(summary, dict) else {}
        self._set_sync_status(self._format_sync_summary(summary_dict), auto_clear_ms=SYNC_STATUS_CLEAR_MS)

    @Slot()
    def refreshWeather(self) -> None:
        if self.demo_mode:
            self._set_weather_text('Demo mode weather')
            self._set_weather_icon(self._resolve_weather_icon('sunny'))
            return

        if self._weather_in_progress:
            return

        if not self.config.can_fetch_weather:
            self._set_weather_text('Weather unavailable')
            self._set_weather_icon(self._resolve_weather_icon(None))
            return

        self._weather_in_progress = True
        self.executor.submit(self._weather_worker)

    def _weather_worker(self) -> None:
        try:
            snapshot = self.weather_service.fetch_weather(self.config)
            self.weatherFinishedSignal.emit(snapshot.text, snapshot.condition or '')
        except Exception:
            LOGGER.exception('Weather worker failed')
            self.weatherFinishedSignal.emit('Weather unavailable', '')

    @Slot(str, str)
    def _on_weather_finished(self, weather_text: str, condition: str) -> None:
        self._weather_in_progress = False
        self._set_weather_text(weather_text)
        self._set_weather_icon(self._resolve_weather_icon(condition))

    @Slot()
    def shutdownNow(self) -> None:
        if self.demo_mode:
            self._set_sync_status('Demo mode: shutdown skipped.', auto_clear_ms=3000)
            return

        command = self._resolve_shutdown_command()
        try:
            subprocess.run(command, check=True)
        except (subprocess.CalledProcessError, FileNotFoundError) as error:
            LOGGER.error('Power off failed: %s', error)
            self._set_sync_status(
                'Failed to power off. Set shutdown_command in config if needed.',
                auto_clear_ms=SYNC_STATUS_CLEAR_MS,
            )

    def _resolve_shutdown_command(self) -> list[str]:
        if self.config.shutdown_command:
            return list(self.config.shutdown_command)

        if shutil.which('systemctl'):
            return ['systemctl', 'poweroff']

        if shutil.which('shutdown'):
            return ['shutdown', '-h', 'now']

        return ['sudo', 'shutdown', 'now']

    @staticmethod
    def _format_sync_summary(summary: dict[str, int]) -> str:
        if not summary:
            return 'Sync complete.'

        changes: list[str] = []
        if summary.get('downloaded', 0):
            changes.append(f"{summary['downloaded']} added")
        if summary.get('deleted', 0):
            changes.append(f"{summary['deleted']} removed")
        if summary.get('converted', 0):
            changes.append(f"{summary['converted']} converted")
        if summary.get('failed', 0):
            changes.append(f"{summary['failed']} failed")

        if not changes:
            return 'Sync complete: no changes.'
        return f"Sync complete: {', '.join(changes)}."

    def _resolve_weather_icon_key(self, condition: str | None) -> str:
        condition_lower = condition.lower() if condition else ''

        if condition_lower in WEATHER_ICON_KEYS:
            return WEATHER_ICON_KEYS[condition_lower]

        for key, icon_key in WEATHER_ICON_KEYS.items():
            if key in condition_lower:
                return icon_key

        return 'unknown'

    def _resolve_weather_icon(self, condition: str | None) -> str:
        icon_key = self._resolve_weather_icon_key(condition)

        if self.weather_icon_base_url.startswith('qrc:/'):
            return f'{self.weather_icon_base_url}/{icon_key}.png'

        icon_path = Path(self.weather_icon_base_url) / f'{icon_key}.png'
        if icon_path.exists():
            return QUrl.fromLocalFile(str(icon_path)).toString()

        unknown_path = Path(self.weather_icon_base_url) / 'unknown.png'
        if unknown_path.exists():
            return QUrl.fromLocalFile(str(unknown_path)).toString()
        return ''
