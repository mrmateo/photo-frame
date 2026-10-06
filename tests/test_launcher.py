import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(shutil.which('bash'), 'Requires bash')
class LauncherTests(unittest.TestCase):
    def setUp(self):
        self.directory = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.python = self.directory / 'fake-python'
        self.python.write_text('#!/usr/bin/env bash\nprintf "%s\\n" "$QT_QPA_PLATFORM" "$@"\n')
        self.python.chmod(0o755)
        self.env = dict(os.environ, PYTHON_BIN=str(self.python), APP_DIR=str(ROOT), CONFIG_PATH='/tmp/test-config.json')
        for name in ('QT_QPA_PLATFORM', 'WAYLAND_DISPLAY', 'XDG_SESSION_TYPE', 'DISPLAY'):
            self.env.pop(name, None)

    def launch(self, library_present=True):
        # More than a pipe buffer of output reproduces the old grep -q/SIGPIPE failure.
        listing = "printf 'libxcb-cursor.so.0\\n';" if library_present else ''
        script = '''ldconfig() { %s for ((i=0; i<20000; i++)); do printf 'other-library.so\\n'; done; }
export -f ldconfig
bash deploy/run_photo_frame.sh --demo-mode --auto-exit-seconds 1
''' % listing
        return subprocess.run(['bash', '-c', script], cwd=ROOT, env=self.env, text=True,
                              capture_output=True, timeout=10)

    def test_present_library_and_forwarded_arguments(self):
        self.env['QT_QPA_PLATFORM'] = 'xcb'
        result = self.launch()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('--demo-mode\n--auto-exit-seconds\n1', result.stdout)
        self.assertIn('/tmp/test-config.json', result.stdout)

    def test_missing_library_has_actionable_error(self):
        self.env['QT_QPA_PLATFORM'] = 'xcb'
        result = self.launch(library_present=False)
        self.assertEqual(result.returncode, 1)
        self.assertIn('libxcb-cursor0', result.stderr)

    def test_platform_detection_and_override(self):
        for environment, platform in [({}, 'eglfs'), ({'DISPLAY': ':0'}, 'xcb'),
                                      ({'WAYLAND_DISPLAY': 'wayland-0'}, 'wayland'),
                                      ({'QT_QPA_PLATFORM': 'offscreen', 'DISPLAY': ':0'}, 'offscreen')]:
            with self.subTest(environment=environment):
                original = self.env.copy()
                self.env.update(environment)
                result = self.launch()
                self.env = original
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stdout.splitlines()[0], platform)

    def test_missing_python_reports_setup_command(self):
        self.env['PYTHON_BIN'] = str(self.directory / 'missing')
        result = self.launch()
        self.assertEqual(result.returncode, 1)
        self.assertIn('scripts/bootstrap.sh', result.stderr)
