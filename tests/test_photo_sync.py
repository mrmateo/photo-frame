from io import BytesIO
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from PIL import Image, ImageDraw, ImageOps
import requests

from photoframe.config import AppConfig
from photoframe.photo_sync_service import MANIFEST_FILENAME, PhotoSyncService


def image_bytes(color='red', size=(120, 90), orientation=1, format='JPEG'):
    image = Image.new('RGB', size, color)
    ImageDraw.Draw(image).rectangle((0, 0, size[0] // 3, size[1] // 3), fill='blue')
    exif = Image.Exif()
    exif[274] = orientation
    output = BytesIO()
    image.save(output, format=format, exif=exif)
    return output.getvalue()


def response(payload=None, content=None):
    result = requests.Response()
    result.status_code = 200
    result._content = json.dumps(payload).encode() if payload is not None else content
    result.request = requests.Request('POST', 'https://example.invalid', json={}).prepare()
    return result


def asset(asset_id, filename='photo.jpg'):
    return {'id': asset_id, 'originalFileName': filename, 'type': 'IMAGE'}


def face(x=100):
    return {'imageWidth': 1000, 'imageHeight': 1000, 'boundingBoxX1': x,
            'boundingBoxY1': 100, 'boundingBoxX2': x + 100, 'boundingBoxY2': 200,
            'person': {'name': 'Alex'}}


def page(items, next_page=None):
    return response({'assets': {'items': items, 'nextPage': next_page}})


class PhotoSyncTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name)
        self.config = AppConfig(immich_server_url='https://example.invalid/', api_key='test', album_id='album')
        self.service = PhotoSyncService(logger=Mock())
        self.service.get_with_retries = Mock(return_value=response(content=image_bytes()))
        self.service.fetch_faces_metadata = Mock(return_value=[face()])
        self.post = self.enterContext(patch('photoframe.photo_sync_service.requests.post'))
        self.post.return_value = page([asset('a')])

    def sync(self):
        return self.service.sync_photos(self.config, self.path)

    def local(self, asset_id, source=None):
        version = self.service._source_version(source or asset(asset_id))
        return self.path / self.service.to_local_jpg_name(asset_id, version)

    def manifest(self):
        return json.loads((self.path / MANIFEST_FILENAME).read_text())

    def seed_cache(self, filename=None):
        filename = filename or self.local('a').name
        (self.path / filename).write_bytes(image_bytes())
        entry = {'asset_id': 'a', 'local_filename': filename, 'people': ['Alex'],
                 'face_bounds': self.service._extract_face_bounds([face()])}
        if filename == self.local('a').name:
            entry['source_version'] = self.service._source_version(asset('a'))
        (self.path / MANIFEST_FILENAME).write_text(json.dumps({'version': 3, 'photos': {filename: entry}}))
        return entry

    def test_json_request_and_complete_pagination_before_cleanup(self):
        self.local('b').write_bytes(image_bytes())
        self.post.side_effect = [page([asset('a')], '2'), page([asset('b')])]
        summary = self.sync()
        self.assertEqual(summary.remote_assets, 2)
        self.assertEqual(summary.deleted, 0)
        self.assertTrue(self.local('b').exists())
        requests_sent = [call.kwargs['json'] for call in self.post.call_args_list]
        self.assertEqual([body['page'] for body in requests_sent], [1, 2])
        self.assertEqual(requests_sent[0]['albumIds'], ['album'])
        self.assertEqual(requests_sent[0]['type'], 'IMAGE')
        self.assertTrue(requests_sent[0]['withExif'])
        self.assertEqual(self.manifest()['photo_order'], [self.local('a').name, self.local('b').name])

    def test_bad_or_incomplete_enumeration_never_changes_cache(self):
        self.seed_cache()
        old_manifest = (self.path / MANIFEST_FILENAME).read_bytes()
        bad_pages = [response({}), response({'assets': {'items': []}}),
                     response({'assets': {'items': {}, 'nextPage': None}}),
                     page([{}]), page([], '1'), page([], '4'), page([], True), page([], 'bad')]
        for bad_page in bad_pages:
            with self.subTest(payload=bad_page.content):
                self.post.side_effect = [page([asset('b')], '2'), bad_page]
                with self.assertRaises(ValueError):
                    self.sync()
                self.assertEqual((self.path / MANIFEST_FILENAME).read_bytes(), old_manifest)
                self.assertTrue(self.local('a').exists())
                self.service.get_with_retries.assert_not_called()
        self.post.side_effect = [page([asset('b')], '2'), requests.Timeout('offline')]
        with self.assertRaises(requests.Timeout):
            self.sync()
        self.assertEqual((self.path / MANIFEST_FILENAME).read_bytes(), old_manifest)

    def test_empty_completed_album_cleans_stale_files(self):
        self.seed_cache()
        self.post.return_value = page([])
        self.assertEqual(self.sync().deleted, 1)
        self.assertFalse(self.local('a').exists())
        self.assertEqual(self.manifest()['photos'], {})

    def test_duplicate_original_names_keep_pixels_and_faces_separate(self):
        self.post.return_value = page([asset('a', 'IMG_0001.jpg'), asset('b', 'IMG_0001.png')])
        self.service.get_with_retries.side_effect = [response(content=image_bytes('red')),
                                                   response(content=image_bytes('green', format='PNG'))]
        self.service.fetch_faces_metadata.side_effect = [[face(100)], [face(800)]]
        summary = self.sync()
        self.assertEqual(summary.downloaded, 2)
        entries = self.manifest()['photos']
        self.assertEqual(entries[self.local('a').name]['face_bounds']['left'], .1)
        self.assertEqual(entries[self.local('b').name]['face_bounds']['left'], .8)
        with Image.open(self.local('a')) as a, Image.open(self.local('b')) as b:
            self.assertGreater(a.getpixel((100, 70))[0], 200)
            self.assertGreater(b.getpixel((100, 70))[1], 100)
        self.assertNotIn('/', self.service.to_local_jpg_name('../outside'))

    def test_legacy_cache_is_replaced_from_original_with_orientation(self):
        self.seed_cache('photo.jpg')
        self.service.get_with_retries.return_value = response(content=image_bytes(orientation=6))
        summary = self.sync()
        self.assertEqual(summary.downloaded, 1)
        self.assertFalse((self.path / 'photo.jpg').exists())
        with Image.open(self.local('a')) as image:
            self.assertEqual(image.size, (90, 120))
            self.assertEqual(image.getexif().get(274, 1), 1)
        self.assertEqual(self.manifest()['version'], 5)

    def test_failed_migration_preserves_legacy_photos_and_metadata(self):
        old = self.seed_cache('photo.jpg')
        self.service.get_with_retries.side_effect = requests.Timeout('offline')
        self.assertEqual(self.sync().failed, 1)
        self.assertTrue((self.path / 'photo.jpg').exists())
        self.assertEqual(self.manifest()['photos']['photo.jpg'], old)
        self.assertFalse(self.local('a').exists())
        self.service.get_with_retries.side_effect = None
        self.sync()
        self.assertTrue(self.local('a').exists())
        self.assertFalse((self.path / 'photo.jpg').exists())

    def test_partial_migration_prefers_metadata_from_asset_id_cache(self):
        old = self.seed_cache('photo.jpg')
        self.local('a').write_bytes(image_bytes())
        newer = dict(old, local_filename=self.local('a').name,
                     source_version=self.service._source_version(asset('a')),
                     face_bounds=self.service._extract_face_bounds([face(800)]))
        # Legacy filenames sort after asset filenames in the on-disk manifest.
        (self.path / MANIFEST_FILENAME).write_text(json.dumps({
            'photos': {self.local('a').name: newer, 'photo.jpg': old}
        }))
        self.service.fetch_faces_metadata.side_effect = requests.Timeout('offline')
        self.sync()
        self.assertEqual(self.manifest()['photos'][self.local('a').name]['face_bounds']['left'], .8)

    def test_face_failures_preserve_cached_bounds_and_people(self):
        for failure in [requests.Timeout('offline'), PermissionError('forbidden'), ValueError('bad JSON')]:
            with self.subTest(failure=failure):
                old = self.seed_cache()
                self.service.fetch_faces_metadata.side_effect = failure
                self.sync()
                entry = self.manifest()['photos'][self.local('a').name]
                self.assertEqual(entry['face_bounds'], old['face_bounds'])
                self.assertEqual(entry['people'], ['Alex'])

    def test_malformed_faces_preserve_cache_but_successful_empty_clears_it(self):
        for payload in [{}, [dict(face(), imageWidth=0)], [None]]:
            with self.subTest(payload=payload):
                old = self.seed_cache()
                self.service.fetch_faces_metadata.return_value = payload
                self.sync()
                self.assertEqual(self.manifest()['photos'][self.local('a').name]['face_bounds'], old['face_bounds'])
        self.service.fetch_faces_metadata.return_value = []
        self.sync()
        entry = self.manifest()['photos'][self.local('a').name]
        self.assertIsNone(entry['face_bounds'])
        self.assertEqual(entry['people'], [])

    def test_permission_failure_preserves_remaining_assets_without_more_face_calls(self):
        self.seed_cache()
        manifest = self.manifest()
        manifest['photos'][self.local('b').name] = dict(manifest['photos'][self.local('a').name], asset_id='b')
        (self.path / MANIFEST_FILENAME).write_text(json.dumps(manifest))
        self.post.return_value = page([asset('a'), asset('b')])
        self.service.fetch_faces_metadata.side_effect = PermissionError('forbidden')
        self.sync()
        self.service.fetch_faces_metadata.assert_called_once()
        self.assertEqual(self.manifest()['photos'][self.local('b').name]['face_bounds']['left'], .1)

    def test_atomic_write_failure_leaves_no_final_file_and_is_retried(self):
        def fail_write(data, path):
            path.write_bytes(b'partial')
            raise OSError('disk full')
        with patch.object(self.service, 'convert_to_jpeg', side_effect=fail_write):
            self.assertEqual(self.sync().failed, 1)
        self.assertFalse(self.local('a').exists())
        self.assertEqual(list(self.path.glob('.photo-frame-*.tmp')), [])
        self.assertEqual(self.sync().downloaded, 1)
        self.assertTrue(self.service._valid_cached_jpeg(self.local('a')))

    def test_failed_replacement_leaves_existing_file_untouched(self):
        self.seed_cache()
        original = self.local('a').read_bytes()
        with patch.object(Path, 'replace', side_effect=OSError('replace failed')):
            with self.assertRaises(OSError):
                self.service._save_photo(image_bytes('green'), self.local('a'))
        self.assertEqual(self.local('a').read_bytes(), original)
        self.assertEqual(list(self.path.glob('.photo-frame-*.tmp')), [])

    def test_corrupt_cache_is_downloaded_again(self):
        self.local('a').write_bytes(b'jpe')
        self.assertEqual(self.sync().downloaded, 1)
        self.assertTrue(self.service._valid_cached_jpeg(self.local('a')))
        self.assertEqual(self.sync().skipped_existing, 1)
        self.assertEqual(self.service.get_with_retries.call_count, 1)

    def test_invalid_download_does_not_become_cached(self):
        self.service.get_with_retries.return_value = response(content=b'not an image')
        self.assertEqual(self.sync().failed, 1)
        self.assertFalse(self.local('a').exists())
        self.assertEqual(list(self.path.glob('.photo-frame-*.tmp')), [])

    def test_all_exif_rotations_and_mirrors_are_normalized(self):
        for format in ['JPEG', 'PNG']:
            for orientation in range(1, 9):
                with self.subTest(format=format, orientation=orientation):
                    data = image_bytes(orientation=orientation, format=format)
                    self.service._save_photo(data, self.local('a'))
                    with Image.open(BytesIO(data)) as source, Image.open(self.local('a')) as actual:
                        expected = ImageOps.exif_transpose(source).convert('RGB')
                        self.assertEqual(actual.size, expected.size)
                        self.assertEqual(actual.getexif().get(274, 1), 1)
                        for x, y in [(10, 10), (actual.width - 10, 10), (10, actual.height - 10),
                                     (actual.width - 10, actual.height - 10)]:
                            self.assertLess(max(abs(a - b) for a, b in zip(actual.getpixel((x, y)), expected.getpixel((x, y)))), 15)

    def test_heic_decode_produces_valid_jpeg(self):
        data = image_bytes(format='HEIF')
        self.service._save_photo(data, self.local('a'))
        self.assertTrue(self.service._valid_cached_jpeg(self.local('a')))

    def test_face_bounds_validation_and_mixed_source_scales(self):
        bounds = self.service._extract_face_bounds({'faces': [face(), dict(face(1600), imageWidth=2000,
                  imageHeight=2000, boundingBoxX2=1800, boundingBoxY1=200, boundingBoxY2=400)]})
        self.assertEqual((bounds['left'], bounds['right'], bounds['count']), (.1, .9, 2))
        for field, value in [('imageWidth', 0), ('imageHeight', float('nan')), ('boundingBoxX1', True),
                             ('imageWidth', 10**1000), ('boundingBoxX2', 50)]:
            with self.subTest(field=field), self.assertRaises(ValueError):
                self.service._extract_face_bounds([dict(face(), **{field: value})])

    def test_edited_download_matches_face_coordinate_frame(self):
        edited = dict(asset('a'), isEdited=True, updatedAt='v1')
        self.post.return_value = page([edited])
        original = image_bytes('red')
        edited_image = image_bytes('green', size=(90, 120))
        self.service.get_with_retries.side_effect = lambda url, **kwargs: response(
            content=edited_image if url.endswith('?edited=true') else original
        )
        self.sync()
        with Image.open(self.local('a', edited)) as image:
            self.assertEqual(image.size, (90, 120))
            self.assertGreater(image.getpixel((80, 100))[1], 100)

    def test_changed_edit_revision_downloads_new_pixels_before_publishing_bounds(self):
        old_asset = dict(asset('a'), isEdited=True, updatedAt='v1')
        self.post.return_value = page([old_asset])
        self.sync()
        old_path = self.local('a', old_asset)
        old_bytes = old_path.read_bytes()
        old_manifest = (self.path / MANIFEST_FILENAME).read_bytes()
        edited = dict(old_asset, updatedAt='v2')
        self.post.return_value = page([edited])
        self.service.fetch_faces_metadata.return_value = [face(800)]

        def during_download(**kwargs):
            self.assertEqual(old_path.read_bytes(), old_bytes)
            self.assertEqual((self.path / MANIFEST_FILENAME).read_bytes(), old_manifest)
            return response(content=image_bytes('green'))

        self.service.get_with_retries.side_effect = during_download
        summary = self.sync()
        self.assertEqual(summary.downloaded, 1)
        new_path = self.local('a', edited)
        self.assertNotEqual(old_path, new_path)
        self.assertEqual(self.manifest()['photo_order'], [new_path.name])
        self.assertEqual(self.manifest()['photos'][new_path.name]['face_bounds']['left'], .8)
        self.assertFalse(old_path.exists())
        self.assertEqual(self.sync().skipped_existing, 1)

    def test_failed_edit_refresh_retains_old_pixels_and_old_bounds(self):
        self.seed_cache()
        old_manifest = self.manifest()
        old_bytes = self.local('a').read_bytes()
        edited = dict(asset('a'), isEdited=True, updatedAt='v2')
        self.post.return_value = page([edited])
        self.service.fetch_faces_metadata.return_value = [face(800)]
        self.service.get_with_retries.side_effect = requests.Timeout('offline')
        self.assertEqual(self.sync().failed, 1)
        self.assertEqual(self.local('a').read_bytes(), old_bytes)
        self.assertEqual(self.manifest()['photos'], old_manifest['photos'])
        self.assertEqual(self.manifest()['photo_order'], [self.local('a').name])
        self.assertFalse(self.local('a', edited).exists())

    def test_face_failure_does_not_reuse_bounds_from_an_older_edit(self):
        self.seed_cache()
        edited = dict(asset('a'), isEdited=True, updatedAt='v2')
        self.post.return_value = page([edited])
        self.service.fetch_faces_metadata.side_effect = requests.Timeout('offline')
        self.sync()
        self.assertIsNone(self.manifest()['photos'][self.local('a', edited).name]['face_bounds'])

    def test_face_bounds_intersect_edited_image_without_rejecting_other_faces(self):
        self.service.fetch_faces_metadata.return_value = [face(800), dict(face(-20), boundingBoxX2=100)]
        self.sync()
        result = self.manifest()['photos'][self.local('a').name]['face_bounds']
        self.assertEqual((result['left'], result['right'], result['count']), (0, .9, 2))

    def test_faces_cropped_entirely_out_are_ignored_and_clear_cached_bounds(self):
        self.seed_cache()
        self.service.fetch_faces_metadata.return_value = [face(-200)]
        self.sync()
        self.assertIsNone(self.manifest()['photos'][self.local('a').name]['face_bounds'])

    def test_inconsistent_face_coordinate_frames_require_whole_image(self):
        result = self.service._extract_face_bounds([face(), dict(face(800), imageHeight=2000)])
        self.assertTrue(result['fit_only'])

    def test_same_aspect_ratio_at_different_scales_can_still_crop(self):
        result = self.service._extract_face_bounds([face(), dict(face(1600), imageWidth=2000,
                 imageHeight=2000, boundingBoxX2=1800, boundingBoxY1=200, boundingBoxY2=400)])
        self.assertFalse(result['fit_only'])

    def test_unedited_and_replaced_assets_have_distinct_cache_revisions(self):
        original = dict(asset('a'), isEdited=True, updatedAt='v1', checksum='original')
        undo = dict(original, isEdited=False, updatedAt='v2')
        replaced = dict(undo, checksum='replacement')
        self.assertEqual(len({self.local('a', item) for item in (original, undo, replaced)}), 3)

    def test_partial_sync_uses_active_revision_metadata_on_next_face_failure(self):
        previous = dict(asset('a'), updatedAt='v1')
        current = dict(previous, updatedAt='v2')
        self.post.return_value = page([previous])
        self.sync()
        self.post.return_value = page([current, asset('b')])
        self.service.fetch_faces_metadata.side_effect = [[face(800)], [face()]]
        self.service.get_with_retries.side_effect = [response(content=image_bytes('green')), requests.Timeout('offline')]
        self.assertEqual(self.sync().failed, 1)
        self.assertTrue(self.local('a', previous).exists())
        self.assertTrue(self.local('a', current).exists())
        self.service.fetch_faces_metadata.side_effect = requests.Timeout('offline')
        self.service.get_with_retries.side_effect = requests.Timeout('offline')
        self.sync()
        self.assertEqual(self.manifest()['photos'][self.local('a', current).name]['face_bounds']['left'], .8)


if __name__ == '__main__':
    unittest.main()
