import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
os.environ.setdefault('QT_QUICK_BACKEND', 'software')

from pathlib import Path
import json
import random
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from PIL import Image, ImageDraw
import requests
from PySide6.QtCore import QObject, QUrl
from PySide6.QtGui import QGuiApplication, QImage
from PySide6.QtQml import QQmlApplicationEngine, QJSEngine, QQmlExpression
from PySide6.QtQuick import QQuickImageProvider, QQuickWindow
from PySide6.QtTest import QTest

from photoframe.config import AppConfig
from photoframe.controller import PhotoFrameController

ROOT = Path(__file__).resolve().parents[1]


def bounds(left=.8, right=.9, top=.3, bottom=.5, width=1440, height=1080):
    return {'left': left, 'right': right, 'top': top, 'bottom': bottom,
            'image_width': width, 'image_height': height}


class CroppingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QGuiApplication.instance() or QGuiApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name)
        self.backend = PhotoFrameController(AppConfig(local_folder=str(self.path)), str(ROOT / 'assets/weather'), demo_mode=True)
        self.backend._set_has_images(True)
        self.engine = QQmlApplicationEngine()
        self.engine.setInitialProperties({'backend': self.backend, 'startFullScreen': False,
                                          'initialWindowWidth': 400, 'initialWindowHeight': 640})
        self.engine.load(QUrl.fromLocalFile(str(ROOT / 'qml/Main.qml')))
        self.assertTrue(self.engine.rootObjects())
        self.window = self.engine.rootObjects()[0]
        self.assertIsNotNone(self.photo)

    @property
    def photo(self):
        # Crossfades alternate image buffers; inspect the currently displayed one.
        return self.window.findChild(QObject, 'photo')

    def tearDown(self):
        self.backend.stop()
        self.window.close()
        self.engine.deleteLater()
        self.backend.deleteLater()
        QTest.qWait(20)
        self.temp.cleanup()

    def wait_for(self, predicate, timeout=4):
        deadline = time.monotonic() + timeout
        while not predicate() and time.monotonic() < deadline:
            QTest.qWait(20)
        self.assertTrue(predicate(), 'QML did not settle before timeout')

    def ready(self):
        # status is the QQuickImage enum (Ready == 1).
        return self.enum_value('status') == 1 and self.photo.property('opacity') >= .999

    def enum_value(self, name):
        expression = QQmlExpression(self.engine.contextForObject(self.photo), self.photo, f'Number({name})')
        value, _ = expression.evaluate()
        self.assertFalse(expression.hasError())
        return value

    def make_image(self, name='photo.jpg', size=(1200, 900), rectangles=((.8, .3, .9, .5),), orientation=1):
        image = Image.new('RGB', size, 'white')
        draw = ImageDraw.Draw(image)
        for left, top, right, bottom in rectangles:
            draw.rectangle((int(left * size[0]), int(top * size[1]), int(right * size[0]), int(bottom * size[1])), fill='red')
        exif = Image.Exif()
        exif[274] = orientation
        path = self.path / name
        image.save(path, exif=exif, quality=95)
        return path

    def display(self, path, crop_bounds):
        self.backend._photo_metadata[path.name] = {'face_bounds': crop_bounds}
        self.backend._set_current_image(path)
        self.wait_for(lambda: self.window.property('displayedImage') == self.backend.currentImage and self.ready())
        QTest.qWait(40)

    def red_pixels(self):
        shot = self.window.grabWindow()
        self.assertFalse(shot.isNull())
        # Ignore the bottom info overlays; fixtures put faces in the upper half.
        pixels = []
        for y in range(0, int(shot.height() * .6), 2):
            for x in range(0, shot.width(), 2):
                color = shot.pixelColor(x, y)
                if color.red() > 180 and color.green() < 80 and color.blue() < 80:
                    pixels.append((x / shot.width(), y / shot.height()))
        return pixels

    def test_single_face_and_small_source_are_visible(self):
        for size in [(1200, 900), (120, 90)]:
            with self.subTest(size=size):
                self.display(self.make_image(name=f'{size[0]}.jpg', size=size), bounds())
                self.assertGreater(len(self.red_pixels()), 100)
                self.assertLess(self.photo.property('x'), 0)

    def test_raw_exif_rotations_and_mirrors_crop_upright(self):
        # Store the inverse transform of an upright fixture, retaining EXIF.
        upright = Image.new('RGB', (1200, 900), 'white')
        ImageDraw.Draw(upright).rectangle((960, 270, 1080, 450), fill='red')
        inverse = {2: Image.Transpose.FLIP_LEFT_RIGHT, 3: Image.Transpose.ROTATE_180,
                   4: Image.Transpose.FLIP_TOP_BOTTOM, 5: Image.Transpose.TRANSPOSE,
                   6: Image.Transpose.ROTATE_90, 7: Image.Transpose.TRANSVERSE,
                   8: Image.Transpose.ROTATE_270}
        for orientation in range(2, 9):
            with self.subTest(orientation=orientation):
                source = upright.transpose(inverse[orientation])
                exif = Image.Exif()
                exif[274] = orientation
                path = self.path / f'orientation-{orientation}.jpg'
                source.save(path, exif=exif, quality=95)
                self.display(path, bounds())
                pixels = self.red_pixels()
                self.assertGreater(len(pixels), 100)
                self.assertTrue(all(.55 < x < .85 for x, y in pixels))

    def test_wide_group_fits_entire_image_and_keeps_both_faces(self):
        path = self.make_image(rectangles=((.05, .3, .15, .5), (.85, .3, .95, .5)))
        self.display(path, bounds(left=.05, right=.95))
        pixels = self.red_pixels()
        self.assertTrue(any(x < .2 for x, y in pixels))
        self.assertTrue(any(x > .8 for x, y in pixels))
        self.assertEqual(self.photo.property('x'), 0)
        self.assertEqual(self.photo.property('width'), self.window.width())
        self.assertEqual(self.enum_value('fillMode'), 1)  # PreserveAspectFit

    def test_tall_group_in_landscape_fits_entire_image(self):
        self.window.setWidth(640)
        self.window.setHeight(400)
        path = self.make_image(size=(900, 1200), rectangles=((.3, .05, .5, .15), (.3, .85, .5, .95)))
        self.display(path, bounds(left=.3, right=.5, top=.05, bottom=.95, width=900, height=1200))
        self.assertEqual(self.photo.property('y'), 0)
        self.assertEqual(self.enum_value('fillMode'), 1)
        self.assertEqual(self.photo.property('height'), self.window.height())

    def test_missing_metadata_uses_centered_crop(self):
        path = self.make_image(rectangles=((.45, .3, .55, .5),))
        self.display(path, None)
        self.assertGreater(len(self.red_pixels()), 100)
        self.assertEqual(self.photo.property('x'), 0)
        self.assertEqual(self.enum_value('fillMode'), 2)  # PreserveAspectCrop

    def test_mismatched_metadata_aspect_ratio_fits_instead_of_hiding_face(self):
        path = self.make_image(size=(1600, 900), rectangles=((.90, .3, .98, .5),))
        self.display(path, bounds(left=.90, right=.98, width=1000, height=1000))
        self.assertEqual(self.enum_value('fillMode'), 1)
        self.assertTrue(any(x > .9 for x, y in self.red_pixels()))

    def test_preview_rounding_uses_actual_image_dimensions(self):
        path = self.make_image(size=(1201, 900))
        self.display(path, bounds(width=1440, height=1079))
        actual = self.window.property('displayedCropInfo')
        self.assertAlmostEqual(actual['image_width'] / actual['image_height'], 1201 / 900)
        self.assertEqual(self.enum_value('fillMode'), 2)

    def test_mixed_face_coordinate_frames_fit_even_if_first_frame_matches_image(self):
        path = self.make_image(rectangles=((.05, .3, .15, .5),))
        self.display(path, dict(bounds(left=.8, right=.9), fit_only=True))
        self.assertEqual(self.enum_value('fillMode'), 1)
        self.assertTrue(any(x < .2 for x, y in self.red_pixels()))

    def test_complete_face_rectangles_stay_inside_rendered_viewport_at_edges(self):
        cases = [
            ((1201, 900), (400, 640), (0, .2, .1, .4)),
            ((1201, 900), (400, 640), (.9, .2, 1, .4)),
            ((900, 1201), (640, 400), (.2, 0, .4, .1)),
            ((900, 1201), (640, 400), (.2, .9, .4, 1)),
            ((1280, 900), (400, 640), (.21875, .2, .658203125, .4)),
            ((1200, 900), (400, 640), (0, 0, 1, 1)),
        ]
        for index, (size, viewport, rect) in enumerate(cases):
            with self.subTest(size=size, viewport=viewport, rect=rect):
                self.window.setWidth(viewport[0])
                self.window.setHeight(viewport[1])
                path = self.make_image(f'edge-{index}.jpg', size=size, rectangles=(rect,))
                self.display(path, {
                    'left': rect[0], 'top': rect[1], 'right': rect[2], 'bottom': rect[3],
                    'image_width': size[0], 'image_height': size[1],
                })
                painted_width = self.photo.property('paintedWidth')
                painted_height = self.photo.property('paintedHeight')
                x = self.photo.property('x') + (self.photo.property('width') - painted_width) / 2
                y = self.photo.property('y') + (self.photo.property('height') - painted_height) / 2
                # Account only for subpixel resampling, not a partially visible face.
                self.assertGreaterEqual(x + rect[0] * painted_width, -1)
                self.assertLessEqual(x + rect[2] * painted_width, viewport[0] + 1)
                self.assertGreaterEqual(y + rect[1] * painted_height, -1)
                self.assertLessEqual(y + rect[3] * painted_height, viewport[1] + 1)

    def test_manifest_prefers_current_revision_without_duplicate_slides(self):
        old = self.path / 'old.jpg'
        current = self.path / 'current.jpg'
        unrelated = self.path / 'other.jpg'
        self.backend._photo_order = [current.name]
        self.backend._photo_metadata = {
            old.name: {'asset_id': 'same'}, current.name: {'asset_id': 'same'}
        }
        self.assertEqual(self.backend._order_images_by_manifest([old, current, unrelated]), [current, unrelated])
        # If the new file is unavailable, keep the previous revision usable.
        self.assertEqual(self.backend._order_images_by_manifest([old, unrelated]), [old, unrelated])

    def test_edited_face_coordinates_survive_complete_sync_and_qml_render(self):
        original_bytes = self.make_image('original.jpg', rectangles=((.1, .3, .2, .5),)).read_bytes()
        edited_bytes = self.make_image('edited.jpg').read_bytes()
        cache = self.path / 'cache'
        self.backend.photos_path = cache
        self.backend.config.immich_server_url = 'https://example.invalid'
        self.backend.config.album_id = 'test-album'
        self.backend.config.api_key = 'test'
        face = {'imageWidth': 1440, 'imageHeight': 1080, 'boundingBoxX1': 1152,
                'boundingBoxX2': 1296, 'boundingBoxY1': 324, 'boundingBoxY2': 540}
        remote_asset = {'id': 'test-asset', 'originalFileName': 'photo.jpg', 'type': 'IMAGE',
                        'isEdited': True, 'updatedAt': 'v1'}

        def http_response(payload=None, content=None):
            response = requests.Response()
            response.status_code = 200
            response._content = json.dumps(payload).encode() if payload is not None else content
            return response

        def get(url, **kwargs):
            if '/api/faces?' in url:
                return http_response([face])
            return http_response(content=edited_bytes if url.endswith('?edited=true') else original_bytes)

        with patch('photoframe.photo_sync_service.requests.get', side_effect=get), patch(
            'photoframe.photo_sync_service.requests.post',
            return_value=http_response({'assets': {'items': [remote_asset], 'nextPage': None}}),
        ):
            summary = self.backend.photo_sync_service.sync_photos(self.backend.config, cache)
        self.assertEqual(summary.downloaded, 1)
        self.backend._on_sync_finished(summary.to_dict(), '')
        self.wait_for(lambda: self.window.property('displayedImage') == self.backend.currentImage and self.ready())
        QTest.qWait(40)
        self.assertEqual(self.enum_value('fillMode'), 2)
        pixels = self.red_pixels()
        self.assertGreater(len(pixels), 100)
        self.assertTrue(all(.55 < x < .85 for x, y in pixels))

    def test_metadata_refresh_updates_current_photo_without_navigation(self):
        path = self.make_image()
        self.display(path, None)
        self.assertEqual(self.window.property('displayedCropInfo'), {})
        self.assertEqual(len(self.red_pixels()), 0)
        self.backend._photo_metadata[path.name] = {'face_bounds': bounds()}
        self.backend._set_current_image(path)
        self.wait_for(lambda: self.window.property('displayedCropInfo') == self.backend.currentCropInfo and self.ready())
        QTest.qWait(40)
        self.assertGreater(len(self.red_pixels()), 100)

    def test_next_photo_metadata_does_not_change_outgoing_crop(self):
        path = self.make_image()
        self.display(path, bounds())
        before = self.window.property('displayedCropInfo')
        next_path = self.make_image('next.jpg', rectangles=((.1, .3, .2, .5),))
        self.backend._photo_metadata[next_path.name] = {'face_bounds': bounds(left=.1, right=.2)}
        self.backend._set_current_image(next_path)
        self.assertEqual(self.window.property('displayedCropInfo'), before)
        self.wait_for(lambda: self.window.property('displayedImage') == self.backend.currentImage and self.ready())
        self.assertEqual(self.window.property('displayedCropInfo')['left'], .1)

    def solid_image(self, name, color):
        path = self.path / name
        Image.new('RGB', (400, 640), color).save(path)
        return path

    def test_crossfade_blends_without_dimming_or_changing_outgoing_crop(self):
        first = self.solid_image('first.png', 'red')
        self.display(first, None)
        outgoing = self.photo
        self.backend._set_current_image(self.solid_image('next.png', 'blue'))
        self.wait_for(lambda: self.window.property('photoTransitionRunning'))
        QTest.qWait(430)
        self.assertIs(self.photo, outgoing)
        self.assertEqual(outgoing.parent().property('opacity'), 1)
        color = self.window.grabWindow().pixelColor(200, 100)
        self.assertGreater(color.red(), 40)
        self.assertGreater(color.blue(), 40)
        self.assertGreaterEqual(color.red() + color.blue(), 250)
        self.wait_for(lambda: self.window.property('displayedImage') == self.backend.currentImage)
        self.assertGreater(self.window.grabWindow().pixelColor(200, 100).blue(), 250)
        self.assertEqual(outgoing.property('source').toString(), '')

    def test_slow_load_keeps_current_photo_visible_until_ready(self):
        requested = threading.Event()
        release = threading.Event()

        class DelayedImageProvider(QQuickImageProvider):
            def __init__(self):
                super().__init__(QQuickImageProvider.ImageType.Image)

            def requestImage(self, identifier, size, requested_size):
                requested.set()
                release.wait(timeout=5)
                image = QImage(400, 640, QImage.Format.Format_RGB32)
                image.fill('blue')
                size.setWidth(image.width())
                size.setHeight(image.height())
                return image

        self.engine.addImageProvider('delayed', DelayedImageProvider())
        self.display(self.solid_image('first.png', 'red'), None)
        first_url = self.backend.currentImage
        try:
            self.backend._current_image = 'image://delayed/next'
            self.backend.currentImageChanged.emit()
            self.wait_for(requested.is_set)
            QTest.qWait(1000)
            self.assertFalse(self.window.property('photoTransitionRunning'))
            self.assertEqual(self.window.property('displayedImage'), first_url)
            self.assertGreater(self.window.grabWindow().pixelColor(200, 100).red(), 250)
        finally:
            release.set()
        self.wait_for(lambda: self.window.property('photoTransitionRunning'))
        self.wait_for(lambda: self.window.property('displayedImage') == self.backend.currentImage)

    def test_failed_image_keeps_previous_photo_and_next_request_recovers(self):
        self.display(self.solid_image('first.png', 'red'), None)
        first_url = self.backend.currentImage
        self.backend._set_current_image(self.path / 'missing.png')
        QTest.qWait(1100)
        self.assertEqual(self.window.property('displayedImage'), first_url)
        self.assertFalse(self.window.property('photoTransitionRunning'))
        self.assertGreater(self.window.grabWindow().pixelColor(200, 100).red(), 250)
        self.display(self.solid_image('valid.png', 'blue'), None)

    def test_rapid_navigation_finishes_dissolve_then_shows_latest_request(self):
        self.display(self.solid_image('first.png', 'red'), None)
        second = self.solid_image('second.png', 'blue')
        third = self.solid_image('third.png', 'green')
        latest = self.solid_image('latest.png', 'yellow')
        self.backend._set_current_image(second)
        self.wait_for(lambda: self.window.property('photoTransitionRunning'))
        incoming = self.window.findChild(QObject, 'incomingPhoto')
        second_url = incoming.property('source')
        self.backend._set_current_image(third)
        self.backend._set_current_image(latest)
        self.assertEqual(incoming.property('source'), second_url)
        self.wait_for(lambda: self.window.property('displayedImage') == self.backend.currentImage)
        self.assertFalse(self.window.property('photoTransitionRunning'))
        color = self.window.grabWindow().pixelColor(200, 100)
        self.assertGreater(color.red(), 250)
        self.assertGreater(color.green(), 250)

    def test_fitted_photo_crossfade_clears_outgoing_photo_from_letterbox(self):
        self.display(self.solid_image('first.png', 'red'), None)
        fitted = self.path / 'fitted.png'
        Image.new('RGB', (1200, 900), 'blue').save(fitted)
        self.display(fitted, bounds(left=.05, right=.95, width=1200, height=900))
        self.assertEqual(self.enum_value('fillMode'), 1)
        color = self.window.grabWindow().pixelColor(200, 100)
        self.assertLess(max(color.red(), color.green(), color.blue()), 5)

    def test_removing_all_photos_cancels_crossfade(self):
        self.display(self.solid_image('first.png', 'red'), None)
        self.backend._set_current_image(self.solid_image('next.png', 'blue'))
        self.wait_for(lambda: self.window.property('photoTransitionRunning'))
        self.backend._set_current_image(None)
        self.assertFalse(self.window.property('photoTransitionRunning'))
        self.assertEqual(self.window.property('displayedImage'), '')
        QTest.qWait(1000)
        self.assertEqual(self.window.property('displayedImage'), '')

    def test_repaired_current_file_is_reloaded(self):
        path = self.make_image(rectangles=())
        self.display(path, bounds())
        old_url = self.backend.currentImage
        self.assertEqual(len(self.red_pixels()), 0)
        self.make_image()
        self.backend._set_current_image(path)
        self.assertNotEqual(self.backend.currentImage, old_url)
        self.wait_for(lambda: self.window.property('displayedImage') == self.backend.currentImage and self.ready())
        QTest.qWait(40)
        self.assertGreater(len(self.red_pixels()), 100)

    def test_resize_recomputes_group_fallback(self):
        path = self.make_image(rectangles=((.05, .3, .15, .5), (.85, .3, .95, .5)))
        self.display(path, bounds(left=.05, right=.95))
        self.assertEqual(self.enum_value('fillMode'), 1)
        self.window.setWidth(640)
        self.window.setHeight(480)
        QTest.qWait(40)
        self.assertEqual(self.enum_value('fillMode'), 2)

    def test_invalid_cached_bounds_fall_back_safely(self):
        path = self.path / 'invalid.jpg'
        for key, value in [('image_width', 0), ('left', -.1), ('right', 1.1), ('top', float('nan')),
                           ('bottom', float('inf')), ('image_height', True), ('right', .1),
                           ('image_width', 10**1000)]:
            with self.subTest(key=key):
                self.backend._photo_metadata[path.name] = {'face_bounds': dict(bounds(), **{key: value})}
                self.assertEqual(self.backend._crop_info_for_image(path), {})

    def test_crop_axis_preserves_all_faces_when_they_fit(self):
        # Execute the production QML's JS, not a Python reimplementation.
        source = (ROOT / 'qml/Main.qml').read_text()
        engine = QJSEngine()
        functions = source[source.index('    function clamp('):source.index('    function showWholeImage(')]
        result = engine.evaluate(functions + '\nvar root = {clamp: clamp}; cropAxis;')
        self.assertFalse(result.isError())
        rng = random.Random(1)
        for _ in range(10000):
            start, end = sorted((rng.random(), rng.random()))
            length = rng.random()
            offset = result.call([start, end, length]).toNumber()
            self.assertGreaterEqual(offset, -1e-10)
            self.assertLessEqual(offset + length, 1 + 1e-10)
            if end - start <= length:
                self.assertLessEqual(offset, start + 1e-10)
                self.assertGreaterEqual(offset + length, end - 1e-10)


if __name__ == '__main__':
    unittest.main()
