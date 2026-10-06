import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from photoframe.manifest import MANIFEST_FILENAME, PhotoManifest


class ManifestTests(unittest.TestCase):
    def setUp(self):
        self.directory = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.path = self.directory / MANIFEST_FILENAME

    def test_roundtrip_and_active_revision_precedence(self):
        manifest = PhotoManifest({'new.jpg': {'asset_id': 'a'}, 'old.jpg': {'asset_id': 'a'}}, ['new.jpg'])
        manifest.save(self.directory)
        loaded = PhotoManifest.load(self.directory)
        self.assertEqual(loaded, manifest)
        self.assertEqual(list(loaded.preferred_entries()), ['old.jpg', 'new.jpg'])

    def test_invalid_manifests_have_consistent_empty_fallback(self):
        for payload in [[], {'version': 999}, {'photos': []}, {'photo_order': {}}]:
            with self.subTest(payload=payload):
                self.path.write_text(json.dumps(payload))
                logger = Mock()
                self.assertEqual(PhotoManifest.load(self.directory, logger), PhotoManifest())
                logger.warning.assert_called_once()

    def test_legacy_manifests_and_invalid_entries(self):
        self.path.write_text(json.dumps({'photos': {'old.jpg': {'asset_id': 'a'}, '../outside.jpg': {}, 'bad.jpg': 123},
                                         'photo_order': ['old.jpg', 'old.jpg', None, 'missing.jpg']}))
        loaded = PhotoManifest.load(self.directory)
        self.assertEqual(loaded.photo_order, ['old.jpg'])
        self.assertEqual(loaded.photos, {'old.jpg': {'asset_id': 'a'}})

    def test_failed_publish_keeps_previous_manifest_and_removes_temporary(self):
        self.path.write_text('previous')
        with patch.object(Path, 'replace', side_effect=OSError('disk full')):
            with self.assertRaises(OSError):
                PhotoManifest().save(self.directory)
        self.assertEqual(self.path.read_text(), 'previous')
        self.assertFalse(self.path.with_suffix('.tmp').exists())
