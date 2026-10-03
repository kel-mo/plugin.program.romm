import io
import os
import shutil
import sys
import unittest
from unittest import mock

import support  # noqa: F401  (test paths)

from resources.lib import backdrop, kodi, plugin
from resources.lib.api import ApiError

try:
    import PIL                                          # in Kodi's flatpak Python, not always on the host
except ImportError:
    PIL = None


def picture(w, h):
    from PIL import Image
    im = Image.new('RGB', (w, h), (200, 60, 60))
    im.paste((20, 220, 20), (0, 0, w // 2, h // 2))                     # a sharp corner to find again
    out = io.BytesIO()
    im.save(out, 'PNG')
    return out.getvalue()


def close(a, b):
    """Pixels equal but for JPEG rounding."""
    return max(abs(x - y) for x, y in zip(a, b)) <= 3


@unittest.skipUnless(PIL, 'needs PIL')
class Compose(unittest.TestCase):
    def test_screenshot_scaled_by_whole_numbers_onto_the_screen(self):
        from PIL import Image
        out = Image.open(io.BytesIO(backdrop.compose(picture(320, 240), pixel=True)))
        self.assertEqual(out.size, backdrop.CANVAS)
        x, y = (1920 - 1280) // 2, (1080 - 960) // 2                        # 4x: 1280 by 960, centred
        self.assertTrue(close(out.getpixel((x + 2, y + 2)), (20, 220, 20)))
        self.assertTrue(close(out.getpixel((x + 636, y + 476)), (20, 220, 20)))   # the last green pixel's block
        self.assertTrue(close(out.getpixel((x + 644, y + 484)), (200, 60, 60)))   # the next one, no smoothing between
        edge = out.crop((0, 0, 300, 1080)).convert('L')
        self.assertLess(sum(edge.tobytes()) / (300 * 1080), 100)              # the copy beside it is dimmed
        self.assertGreater(edge.getextrema()[0], 0)

    def test_big_screenshot_shrinks_to_fit(self):
        from PIL import Image
        out = Image.open(io.BytesIO(backdrop.compose(picture(4000, 3000), pixel=True)))
        self.assertEqual(out.size, backdrop.CANVAS)
        self.assertTrue(close(out.getpixel((240 + 5, 5)), (20, 220, 20)))        # 1440 by 1080, centred

    def test_a_screen_sized_screenshot_is_left_alone(self):
        data = picture(1920, 1080)
        self.assertIs(backdrop.compose(data, pixel=True), data)
        self.assertIsNot(backdrop.compose(picture(640, 360), pixel=True), picture(640, 360))   # small: scaled up sharp

    def test_tall_photo_sits_whole_on_a_blurred_copy(self):
        from PIL import Image
        out = Image.open(io.BytesIO(backdrop.compose(picture(600, 900))))
        self.assertEqual(out.size, (1600, 900))                                # 16:9 at the photo's own height
        self.assertTrue(close(out.getpixel((500 + 10, 10)), (20, 220, 20)))

    def test_without_pil_the_picture_is_used(self):
        data = picture(320, 240)
        with mock.patch.dict(sys.modules, {'PIL': None}):
            self.assertIs(backdrop.compose(data, pixel=True), data)


class Shots:
    def __init__(self, fail=False):
        self.fetched, self.fail = [], fail

    def asset(self, path):
        self.fetched.append(path)
        if self.fail:
            raise ApiError('down')
        return picture(320, 240)

    def asset_url(self, path):
        return 'https://romm' + path


@unittest.skipUnless(PIL, 'needs PIL')
class Fanart(unittest.TestCase):
    def setUp(self):
        shutil.rmtree(kodi.profile_file('backdrops'), ignore_errors=True)
        self.addCleanup(shutil.rmtree, kodi.profile_file('backdrops'), True)
        plugin._budget = plugin.BACKDROPS

    def rom(self, n):
        return {'id': n, 'name': 'Game {}'.format(n), 'merged_screenshots': ['/assets/romm/resources/roms/1/{}/screenshots/0.jpg'.format(n)]}

    def test_made_once_and_kept(self):
        client = Shots()
        path = plugin.fanart(client, self.rom(1))
        self.assertTrue(path.startswith(kodi.profile_file('backdrops')) and os.path.exists(path))
        self.assertFalse(os.path.exists(path + '.tmp'))
        self.assertEqual(plugin.fanart(client, self.rom(1)), path)
        self.assertEqual(len(client.fetched), 1)
        self.assertIsNone(plugin.fanart(client, {'id': 2}))

    def test_a_listing_makes_a_few_and_leaves_the_rest_plain(self):
        client = Shots()
        made = [plugin.fanart(client, self.rom(n)) for n in range(plugin.BACKDROPS + 3)]
        self.assertEqual(sum(1 for p in made if p.startswith('https://romm')), 3)
        self.assertEqual(len(client.fetched), plugin.BACKDROPS)
        plugin._budget = plugin.BACKDROPS                                      # the next listing
        self.assertTrue(plugin.fanart(client, self.rom(plugin.BACKDROPS + 1)).endswith('.jpg'))

    def test_server_down_shows_the_plain_screenshot(self):
        self.assertTrue(plugin.fanart(Shots(fail=True), self.rom(1)).startswith('https://romm'))
        self.assertFalse(os.path.exists(kodi.profile_file('backdrops')))

    def test_least_recently_listed_go_first(self):
        client = Shots()
        with mock.patch.object(plugin, 'KEEP', 2):
            first = plugin.fanart(client, self.rom(1))
            os.utime(first, (1, 1))
            plugin.fanart(client, self.rom(2))
            plugin.fanart(client, self.rom(3))
        self.assertFalse(os.path.exists(first))
        self.assertEqual(len(os.listdir(kodi.profile_file('backdrops'))), 2)


if __name__ == '__main__':
    unittest.main()
