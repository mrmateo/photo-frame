import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from photoframe.config import AppConfig, MAX_INTERVAL_SECONDS
from photoframe import __version__

ROOT = Path(__file__).resolve().parents[1]


class ConfigTests(unittest.TestCase):
    def setUp(self):
        self.directory = self.enterContext(tempfile.TemporaryDirectory())
        self.config_path = Path(self.directory) / 'config.json'

    def load(self, payload):
        self.config_path.write_text(json.dumps(payload))
        return AppConfig.from_file(self.config_path)

    def test_defaults_and_relative_photo_directory(self):
        config = self.load({})
        self.assertEqual(config.resolve_photos_path(), Path(self.directory).resolve() / 'photos')
        self.assertFalse(config.can_sync)
        self.assertFalse(config.can_fetch_weather)

    def test_invalid_values_report_setting_names(self):
        cases = [([], 'object'), ({'api_key': None}, 'api_key'), ({'api_key': 123}, 'api_key'),
                 ({'image_cyle_seconds': 15}, 'image_cyle_seconds'), ({'local_folder': ''}, 'local_folder'),
                 ({'image_cycle_seconds': True}, 'image_cycle_seconds'), ({'image_cycle_seconds': 2}, 'image_cycle_seconds'),
                 ({'image_cycle_seconds': 3.5}, 'image_cycle_seconds'), ({'hourly_interval_seconds': 59}, 'hourly_interval_seconds'),
                 ({'hourly_interval_seconds': MAX_INTERVAL_SECONDS + 1}, 'hourly_interval_seconds'),
                 ({'immich_server_url': 'immich.local'}, 'immich_server_url'),
                 ({'shutdown_command': [None]}, 'shutdown_command'), ({'shutdown_command': []}, 'shutdown_command'),
                 ({'shutdown_command': '"unterminated'}, 'shutdown_command'), ({'config_dir': '/tmp'}, 'config_dir')]
        for payload, message in cases:
            with self.subTest(payload=payload), self.assertRaisesRegex(ValueError, message):
                self.load(payload)

    def test_incomplete_integration_names_missing_fields_without_secrets(self):
        with self.assertRaises(ValueError) as error:
            self.load({'api_key': 'do-not-print-me'})
        self.assertIn('album_id', str(error.exception))
        self.assertNotIn('do-not-print-me', str(error.exception))

    def test_valid_settings_and_command_strings(self):
        config = self.load({'immich_server_url': ' https://immich.local/ ', 'api_key': 'test', 'album_id': 'a',
                            'home_assistant_weather_url': 'http://ha.local/api/states/weather.home', 'weather_api_key': 'test',
                            'shutdown_command': 'systemctl --no-ask-password poweroff', 'image_cycle_seconds': 3})
        self.assertTrue(config.can_sync)
        self.assertTrue(config.can_fetch_weather)
        self.assertEqual(config.shutdown_command, ('systemctl', '--no-ask-password', 'poweroff'))

    def run_cli(self, *args):
        # A nonexistent Qt plugin proves help/config checks do not initialize the GUI.
        env = dict(os.environ, QT_QPA_PLATFORM='not-a-real-platform', PHOTO_FRAME_CONFIG='')
        return subprocess.run([sys.executable, str(ROOT / 'main.py'), *args], env=env,
                              text=True, capture_output=True, timeout=10)

    def test_check_config_is_headless_and_does_not_create_photo_directory(self):
        self.load({})
        result = self.run_cli('--check-config', '--config', str(self.config_path))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('Configuration valid', result.stdout)
        self.assertFalse((Path(self.directory) / 'photos').exists())

    def test_bad_config_and_unusable_photo_directory_exit_cleanly(self):
        for payload in [[], {'local_folder': str(self.config_path)}]:
            self.config_path.write_text(json.dumps(payload))
            result = self.run_cli('--check-config', '--config', str(self.config_path))
            self.assertEqual(result.returncode, 1)
            self.assertNotIn('Traceback', result.stderr)

    def test_optional_log_failure_keeps_console_logging(self):
        self.load({})
        result = self.run_cli('--check-config', '--config', str(self.config_path),
                              '--log-file', str(self.config_path / 'invalid.log'))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('Cannot open optional log file', result.stderr)

    def test_help_version_and_argument_errors_are_headless(self):
        self.assertEqual(self.run_cli('--version').stdout.strip(), __version__)
        self.assertEqual(self.run_cli('--help').returncode, 0)
        for args in [('--window-size', 'bad'), ('--window-size', '10x10'), ('--auto-exit-seconds', '-1')]:
            result = self.run_cli(*args)
            self.assertEqual(result.returncode, 2)
            self.assertNotIn('Traceback', result.stderr)
