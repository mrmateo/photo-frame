import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
os.environ.setdefault('QT_QUICK_BACKEND', 'software')

from concurrent.futures import CancelledError
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import Mock, patch

from PySide6.QtGui import QGuiApplication
from PySide6.QtCore import QProcess
from PySide6.QtTest import QTest

from photoframe.config import AppConfig
from photoframe.controller import PhotoFrameController
from photoframe.photo_sync_service import PhotoSyncService
from photoframe.manifest import MANIFEST_FILENAME

ROOT = Path(__file__).resolve().parents[1]


class LifecycleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QGuiApplication.instance() or QGuiApplication([])

    def setUp(self):
        self.directory = self.enterContext(tempfile.TemporaryDirectory())
        self.config = AppConfig(local_folder=self.directory, immich_server_url='https://example.invalid',
                                api_key='test', album_id='album')
        self.controller = PhotoFrameController(self.config, str(ROOT / 'assets/weather'))

    def tearDown(self):
        self.controller.stop()
        self.controller.executor.shutdown(wait=True, cancel_futures=True)
        if self.controller._shutdown_process.state() != QProcess.ProcessState.NotRunning:
            self.controller._shutdown_process.waitForFinished(1000)
        self.controller.deleteLater()
        QTest.qWait(10)

    def test_stop_interrupts_retry_wait_and_does_not_publish_completion(self):
        attempted = threading.Event()
        def offline(*args, **kwargs):
            import requests
            attempted.set()
            raise requests.Timeout('offline')
        self.controller.photo_sync_service.client.session.request = Mock(side_effect=offline)
        finished = []
        self.controller.syncFinishedSignal.connect(lambda *args: finished.append(args))
        self.controller.syncNow()
        self.assertTrue(attempted.wait(2))
        started = time.monotonic()
        self.controller.stop()
        self.controller.executor.shutdown(wait=True)
        self.assertLess(time.monotonic() - started, .5)
        QTest.qWait(20)
        self.assertEqual(finished, [])
        self.assertEqual(self.controller.photo_sync_service.client.session.request.call_count, 1)
        self.assertFalse((Path(self.directory) / MANIFEST_FILENAME).exists())
        # Late UI actions cannot submit new work to a stopped executor.
        self.controller.syncNow()
        self.controller.refreshWeather()
        self.controller.start()
        self.assertFalse(self.controller._image_timer.isActive())

    def test_cancelled_sync_does_not_publish_manifest_or_delete_cache(self):
        service = PhotoSyncService()
        self.addCleanup(service.close)
        existing = Path(self.directory) / 'existing.jpg'
        existing.write_bytes(b'keep me')
        old_manifest = {'photos': {'existing.jpg': {'asset_id': 'old'}}, 'photo_order': ['existing.jpg']}
        manifest = Path(self.directory) / MANIFEST_FILENAME
        manifest.write_text(json.dumps(old_manifest))
        def enumerate_then_cancel(*args):
            service.client.cancel_event.set()
            return []
        with patch.object(service, '_fetch_album_assets', side_effect=enumerate_then_cancel):
            with self.assertRaises(CancelledError):
                service.sync_photos(self.config, Path(self.directory))
        self.assertEqual(json.loads(manifest.read_text()), old_manifest)
        self.assertEqual(existing.read_bytes(), b'keep me')

    def test_power_command_is_asynchronous_and_times_out(self):
        self.config.shutdown_command = (sys.executable, '-c', 'import time; time.sleep(30)')
        with patch('photoframe.controller.SHUTDOWN_TIMEOUT_MS', 100):
            started = time.monotonic()
            self.controller.shutdownNow()
            self.assertLess(time.monotonic() - started, .2)
            deadline = time.monotonic() + 3
            while self.controller._shutdown_process.state() != QProcess.ProcessState.NotRunning and time.monotonic() < deadline:
                QTest.qWait(20)
        self.assertEqual(self.controller._shutdown_process.state(), QProcess.ProcessState.NotRunning)
        self.assertIn('Failed to power off', self.controller.syncStatus)

    def test_failed_command_start_is_reported(self):
        self.config.shutdown_command = (str(Path(self.directory) / 'does-not-exist'),)
        self.controller.shutdownNow()
        QTest.qWait(50)
        self.assertIn('Failed to power off', self.controller.syncStatus)
        self.assertFalse(self.controller._shutdown_timer.isActive())

    def test_demo_never_starts_power_command(self):
        self.controller.demo_mode = True
        with patch.object(self.controller, '_resolve_shutdown_command') as resolve:
            self.controller.shutdownNow()
        resolve.assert_not_called()


class ProcessExitTests(unittest.TestCase):
    def test_cancelled_worker_does_not_hold_process_open(self):
        script = '''
from PySide6.QtCore import QCoreApplication
from photoframe.config import AppConfig
from photoframe.controller import PhotoFrameController
import requests, threading
app = QCoreApplication([])
controller = PhotoFrameController(AppConfig(immich_server_url='https://example.invalid', api_key='test', album_id='a'), 'assets/weather')
attempted = threading.Event()
def request(*args, **kwargs):
    attempted.set()
    raise requests.Timeout('offline')
controller.photo_sync_service.client.session.request = request
controller.syncNow()
assert attempted.wait(2)
controller.stop()
print('stopped', flush=True)
'''
        with subprocess.Popen([sys.executable, '-c', script], cwd=ROOT, stdout=subprocess.PIPE,
                              stderr=subprocess.PIPE, text=True) as process:
            try:
                stdout, stderr = process.communicate(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.communicate()
                self.fail('Cancelled worker kept the process alive.')
        self.assertEqual(process.returncode, 0, stderr)
        self.assertEqual(stdout.strip(), 'stopped')
