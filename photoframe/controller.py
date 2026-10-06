from __future__ import annotations

from concurrent.futures import CancelledError, ThreadPoolExecutor
from datetime import datetime
import logging
from pathlib import Path
import re
import shutil
from threading import Event

from PySide6.QtCore import QObject, Property, QProcess, QTimer, QUrl, Signal, Slot

from .config import AppConfig
from .presentation import crop_info_for_image, format_photo_details
from .manifest import PhotoManifest, PhotoMetadata
from .photo_sync_service import PhotoSyncService
from .weather_service import WeatherService, WeatherSnapshot
from .weather_types import UNKNOWN_WEATHER_ICON_KEY, WEATHER_ICON_EXTENSION, weather_icon_key

LOGGER = logging.getLogger(__name__)
IMAGE_EXTENSIONS = {'.jpg', '.jpeg', '.png'}
SYNC_STATUS_CLEAR_MS = 10_000
SHUTDOWN_TIMEOUT_MS = 10_000
DEMO_WEATHER = WeatherSnapshot(temperature_text='88°', condition_text='Partly Cloudy', condition='partlycloudy')


class PhotoFrameController(QObject):
    currentImageChanged = Signal()
    hasImagesChanged = Signal()
    clockTextChanged = Signal()
    dateTextChanged = Signal()
    weatherChanged = Signal()
    weatherIconChanged = Signal()
    syncStatusChanged = Signal()
    syncInProgressChanged = Signal()
    currentPhotoDetailsChanged = Signal()
    currentCropInfoChanged = Signal()

    syncProgressSignal = Signal(str)
    syncFinishedSignal = Signal(object, str)
    weatherFinishedSignal = Signal(object)

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

        self._stopping = Event()
        self.photo_sync_service = PhotoSyncService(cancel_event=self._stopping)
        self.weather_service = WeatherService(cancel_event=self._stopping)
        self.executor = ThreadPoolExecutor(max_workers=2)

        self.photos_path = self.config.resolve_photos_path()

        self._images: list[Path] = []
        self._index = 0

        self._current_image = ''
        self._has_images = False
        self._clock_text = ''
        self._date_text = ''
        self._weather = WeatherSnapshot(condition_text='Weather loading...')
        self._weather_icon = self._resolve_weather_icon(None)
        self._sync_status = ''
        self._current_photo_details = ''
        self._current_crop_info: dict[str, object] = {}

        self._sync_in_progress = False
        self._weather_in_progress = False
        self._photo_metadata: dict[str, PhotoMetadata] = {}
        self._photo_order: list[str] = []

        self._image_timer = QTimer(self)
        self._image_timer.timeout.connect(self._advance_image_timer)

        self._clock_timer = QTimer(self)
        self._clock_timer.timeout.connect(self._update_clock)

        self._weather_timer = QTimer(self)
        self._weather_timer.timeout.connect(self.refreshWeather)

        self._sync_timer = QTimer(self)
        self._sync_timer.timeout.connect(self.syncNow)

        self._status_clear_timer = QTimer(self)
        self._status_clear_timer.setSingleShot(True)
        self._status_clear_timer.timeout.connect(self._clear_sync_status)

        self._shutdown_process = QProcess(self)
        self._shutdown_process.finished.connect(self._on_shutdown_finished)
        self._shutdown_process.errorOccurred.connect(self._on_shutdown_error)
        self._shutdown_timer = QTimer(self)
        self._shutdown_timer.setSingleShot(True)
        self._shutdown_timer.timeout.connect(self._on_shutdown_timeout)

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

    @Property('QVariantMap', notify=weatherChanged)
    def weather(self) -> dict[str, str]:
        return {'temperatureText': self._weather.temperature_text, 'conditionText': self._weather.condition_text}

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

    @Property(str, notify=currentPhotoDetailsChanged)
    def currentPhotoDetails(self) -> str:
        return self._current_photo_details

    @Property('QVariantMap', notify=currentCropInfoChanged)
    def currentCropInfo(self) -> dict[str, object]:
        return self._current_crop_info

    @Slot()
    def start(self) -> None:
        if self._stopping.is_set():
            return
        self.photos_path.mkdir(parents=True, exist_ok=True)
        self._reload_images(preserve_current=False)
        self._update_clock()

        self._image_timer.start(self._image_cycle_interval_ms())
        self._clock_timer.start(1000)
        hourly_interval_ms = self._hourly_interval_ms()
        self._weather_timer.start(hourly_interval_ms)
        self._sync_timer.start(hourly_interval_ms)

        if self.demo_mode:
            self._set_weather(DEMO_WEATHER)
            self._set_sync_status('Demo mode: network calls disabled.', auto_clear_ms=SYNC_STATUS_CLEAR_MS)
            return

        self.refreshWeather()
        self.syncNow()

    @Slot()
    def stop(self) -> None:
        self._stopping.set()
        self._shutdown_timer.stop()
        if self._shutdown_process.state() != QProcess.ProcessState.NotRunning:
            self._shutdown_process.kill()
        if not self._sync_in_progress:
            self.photo_sync_service.close()
        if not self._weather_in_progress:
            self.weather_service.close()
        for timer in (self._image_timer, self._clock_timer, self._weather_timer, self._sync_timer, self._status_clear_timer):
            timer.stop()
        self.executor.shutdown(wait=False, cancel_futures=True)

    def _set_current_image(self, image_path: Path | None) -> None:
        image_url = ''
        if image_path:
            url = QUrl.fromLocalFile(str(image_path))
            try:
                # Reload even if sync repaired the file currently on screen.
                url.setQuery(f'v={image_path.stat().st_mtime_ns}')
            except OSError:
                pass
            image_url = url.toString()
        image_changed = self._current_image != image_url
        # Crop listeners must see the new URL so they cannot apply the next
        # photo's bounds to the image still fading out.
        self._current_image = image_url
        self._set_current_crop_info(crop_info_for_image(image_path, self._photo_metadata))
        if image_changed:
            self.currentImageChanged.emit()
        self._set_current_photo_details(format_photo_details(image_path, self._photo_metadata))

    def _set_current_crop_info(self, value: dict[str, object]) -> None:
        if self._current_crop_info != value:
            self._current_crop_info = value
            self.currentCropInfoChanged.emit()

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

    def _set_weather(self, value: WeatherSnapshot) -> None:
        if self._weather != value:
            self._weather = value
            self.weatherChanged.emit()
        self._set_weather_icon(self._resolve_weather_icon(value.condition))

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

    def _set_current_photo_details(self, value: str) -> None:
        if self._current_photo_details != value:
            self._current_photo_details = value
            self.currentPhotoDetailsChanged.emit()

    def _clear_sync_status(self) -> None:
        self._set_sync_status('', auto_clear_ms=None)

    @Slot(str)
    def _on_sync_progress(self, message: str) -> None:
        if self._stopping.is_set():
            return
        self._set_sync_status(message, auto_clear_ms=None)

    def _reload_images(self, preserve_current: bool = True) -> None:
        self._reload_photo_metadata()

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
        images = self._order_images_by_manifest(images)
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

    def _reload_photo_metadata(self) -> None:
        manifest = PhotoManifest.load(self.photos_path)
        self._photo_metadata = manifest.photos
        self._photo_order = manifest.photo_order

    def _order_images_by_manifest(self, images: list[Path]) -> list[Path]:
        if not self._photo_order:
            return images

        images_by_name = {path.name: path for path in images}
        ordered_images: list[Path] = []
        seen_names: set[str] = set()
        seen_assets: set[str] = set()

        def asset_id(path: Path) -> str:
            metadata = self._photo_metadata.get(path.name)
            value = metadata.get('asset_id') if isinstance(metadata, dict) else None
            return value if isinstance(value, str) else ''

        for filename in self._photo_order:
            image_path = images_by_name.get(filename)
            if image_path is None or filename in seen_names:
                continue
            ordered_images.append(image_path)
            seen_names.add(filename)
            if identity := asset_id(image_path):
                seen_assets.add(identity)

        # Older revisions retained after a partial sync must not be shown again
        # when a current revision of the same asset is already in the manifest.
        ordered_images.extend(path for path in images if path.name not in seen_names and asset_id(path) not in seen_assets)
        return ordered_images

    def _update_clock(self) -> None:
        now = datetime.now()
        self._set_clock_text(now.strftime('%I:%M %p'))
        self._set_date_text(now.strftime('%A, %b %d'))

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
        if self._stopping.is_set():
            return
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
        result, error_text = {}, ''
        try:
            result = self.photo_sync_service.sync_photos(
                config=self.config, photos_path=self.photos_path,
                progress_callback=self.syncProgressSignal.emit,
            ).to_dict()
        except CancelledError:
            return
        except Exception as error:
            LOGGER.exception('Sync worker failed')
            error_text = str(error)
        finally:
            self.photo_sync_service.close()
        if not self._stopping.is_set():
            self.syncFinishedSignal.emit(result, error_text)

    @Slot(object, str)
    def _on_sync_finished(self, summary: object, error_text: str) -> None:
        if self._stopping.is_set():
            return
        self._set_sync_in_progress(False)

        if error_text:
            self._set_sync_status('Sync failed. Please check configuration/logs.', auto_clear_ms=SYNC_STATUS_CLEAR_MS)
            return

        self._reload_images(preserve_current=True)
        summary_dict = summary if isinstance(summary, dict) else {}
        self._set_sync_status(self._format_sync_summary(summary_dict), auto_clear_ms=SYNC_STATUS_CLEAR_MS)

    @Slot()
    def refreshWeather(self) -> None:
        if self._stopping.is_set():
            return
        if self.demo_mode:
            self._set_weather(DEMO_WEATHER)
            return

        if self._weather_in_progress:
            return

        if not self.config.can_fetch_weather:
            self._set_weather(WeatherSnapshot())
            return

        self._weather_in_progress = True
        self.executor.submit(self._weather_worker)

    def _weather_worker(self) -> None:
        try:
            snapshot = self.weather_service.fetch_weather(self.config)
        except CancelledError:
            return
        except Exception:
            LOGGER.exception('Weather worker failed')
            snapshot = WeatherSnapshot()
        finally:
            self.weather_service.close()
        if not self._stopping.is_set():
            self.weatherFinishedSignal.emit(snapshot)

    @Slot(object)
    def _on_weather_finished(self, snapshot: WeatherSnapshot) -> None:
        if self._stopping.is_set():
            return
        self._weather_in_progress = False
        self._set_weather(snapshot)

    @Slot()
    def shutdownNow(self) -> None:
        if self._stopping.is_set() or self._shutdown_process.state() != QProcess.ProcessState.NotRunning:
            return
        if self.demo_mode:
            self._set_sync_status('Demo mode: shutdown skipped.', auto_clear_ms=3000)
            return
        command = self._resolve_shutdown_command()
        self._shutdown_timer.start(SHUTDOWN_TIMEOUT_MS)
        self._shutdown_process.start(command[0], command[1:])

    def _shutdown_failed(self, reason: str) -> None:
        self._shutdown_timer.stop()
        LOGGER.error('Power off failed: %s', reason)
        if not self._stopping.is_set():
            self._set_sync_status('Failed to power off. Check shutdown_command and service logs.',
                                  auto_clear_ms=SYNC_STATUS_CLEAR_MS)

    def _on_shutdown_finished(self, exit_code: int, exit_status: QProcess.ExitStatus) -> None:
        self._shutdown_timer.stop()
        if exit_code != 0 or exit_status != QProcess.ExitStatus.NormalExit:
            self._shutdown_failed(f'command exited with status {exit_code}')

    def _on_shutdown_error(self, error: QProcess.ProcessError) -> None:
        self._shutdown_failed(self._shutdown_process.errorString())

    def _on_shutdown_timeout(self) -> None:
        self._shutdown_process.kill()
        self._shutdown_failed('command timed out')

    def _resolve_shutdown_command(self) -> list[str]:
        if self.config.shutdown_command:
            return list(self.config.shutdown_command)

        if shutil.which('systemctl'):
            return ['systemctl', '--no-ask-password', 'poweroff']

        if shutil.which('shutdown'):
            return ['shutdown', '-h', 'now']

        return ['sudo', '-n', 'shutdown', 'now']

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

    def _resolve_weather_icon(self, condition: str | None) -> str:
        icon_key = weather_icon_key(condition)
        icon_filename = f'{icon_key}{WEATHER_ICON_EXTENSION}'

        if self.weather_icon_base_url.startswith('qrc:/'):
            return f'{self.weather_icon_base_url}/{icon_filename}'

        icon_path = Path(self.weather_icon_base_url) / icon_filename
        if icon_path.exists():
            return QUrl.fromLocalFile(str(icon_path)).toString()

        unknown_path = Path(self.weather_icon_base_url) / f'{UNKNOWN_WEATHER_ICON_KEY}{WEATHER_ICON_EXTENSION}'
        if unknown_path.exists():
            return QUrl.fromLocalFile(str(unknown_path)).toString()
        return ''
