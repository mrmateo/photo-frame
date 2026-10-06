import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]


class StartupTests(unittest.TestCase):
    def test_demo_starts_and_exits_with_each_resource_mode(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            photos = folder / 'photos'
            photos.mkdir()
            Image.new('RGB', (120, 90), 'teal').save(photos / 'demo.jpg')
            config = folder / 'config.json'
            config.write_text(json.dumps({'local_folder': 'photos'}))
            # Build the bundle into the temporary directory; never import a stale working-tree bundle.
            build = subprocess.run([str(Path(sys.executable).parent / 'pyside6-rcc'),
                                    str(ROOT / 'resources.qrc'), '-o', str(folder / 'rc_resources.py')],
                                   text=True, capture_output=True, timeout=30)
            self.assertEqual(build.returncode, 0, build.stderr)
            env = dict(os.environ, QT_QPA_PLATFORM='offscreen', QT_QUICK_BACKEND='software',
                       QT_QUICK_CONTROLS_STYLE='Basic')
            script = f'import sys; sys.path[:0] = [{str(folder)!r}, {str(ROOT)!r}]; import main; raise SystemExit(main.main())'
            for mode in ('filesystem', 'embedded'):
                with self.subTest(mode=mode):
                    result = subprocess.run([sys.executable, '-c', script, '--config', str(config), '--demo-mode',
                                             '--windowed', '--resources', mode, '--auto-exit-seconds', '1'],
                                            cwd=folder, env=env, text=True, capture_output=True, timeout=15)
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertIn(f'Using {mode} resources', result.stderr)
                    self.assertNotIn('ReferenceError', result.stderr)
                    self.assertNotIn('TypeError', result.stderr)
                    self.assertNotIn('failed to load', result.stderr)
