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

    def test_console_screenshot_stretched_to_four_by_three(self):
        from PIL import Image
        out = Image.open(io.BytesIO(backdrop.compose(picture(256, 224), pixel=True, aspect=4 / 3)))
        self.assertEqual(out.size, backdrop.CANVAS)
        x, y = (1920 - 1195) // 2, (1080 - 896) // 2                        # 4x tall, 4:3 wide
        self.assertTrue(close(out.getpixel((x + 12, y + 12)), (20, 220, 20)))
        self.assertTrue(close(out.getpixel((x + 1195 - 12, y + 896 - 12)), (200, 60, 60)))
        self.assertLess(max(out.getpixel((x - 12, 540))), 120)                 # the blurred copy beside it
        row = [out.getpixel((x + i, y + 12)) for i in range(0, 1195)]
        self.assertTrue(close(row[597 - 12], (20, 220, 20)) and close(row[597 + 12], (200, 60, 60)))   # the edge, mid-way
        tall = Image.open(io.BytesIO(backdrop.compose(picture(224, 256), pixel=True, aspect=4 / 3)))
        self.assertTrue(close(tall.getpixel(((1920 - 896) // 2 + 12, 28 + 12)), (20, 220, 20)))      # upright: 4x, not widened

    def test_big_screenshot_shrinks_to_fit(self):
        from PIL import Image
        out = Image.open(io.BytesIO(backdrop.compose(picture(4000, 3000), pixel=True)))
        self.assertEqual(out.size, backdrop.CANVAS)
        self.assertTrue(close(out.getpixel((240 + 5, 5)), (20, 220, 20)))        # 1440 by 1080, centred

    def test_a_screen_sized_screenshot_is_left_alone(self):
        data = picture(1920, 1080)
        self.assertIs(backdrop.compose(data, pixel=True), data)
        self.assertIsNot(backdrop.compose(picture(640, 360), pixel=True), picture(640, 360))   # small: scaled up sharp

    def test_crt_look_darkens_the_line_between_rows(self):
        from PIL import Image
        plain = Image.open(io.BytesIO(backdrop.compose(picture(320, 240), pixel=True)))
        crt = Image.open(io.BytesIO(backdrop.compose(picture(320, 240), pixel=True, look='crt')))
        lines = Image.open(io.BytesIO(backdrop.compose(picture(320, 240), pixel=True, look='scanlines')))
        self.assertEqual(crt.size, backdrop.CANVAS)
        x, y = (1920 - 1280) // 2 + 400, (1080 - 960) // 2 + 600                # inside the red half, 4 px rows
        for out in (crt, lines):
            body = sum(out.getpixel((x + i, y + 1))[0] for i in range(12)) / 12
            foot = sum(out.getpixel((x + i, y + 3))[0] for i in range(12)) / 12
            self.assertLess(foot, body * 0.8)                                  # the last of each row's 4 lines is dark
        self.assertGreater(abs(crt.getpixel((x, y + 1))[1] - crt.getpixel((x + 1, y + 1))[1]), 10)   # phosphor stripes
        self.assertLess(abs(lines.getpixel((x, y + 1))[1] - lines.getpixel((x + 1, y + 1))[1]), 4)  # none on scanlines
        self.assertEqual(plain.getpixel((x, y + 3)), plain.getpixel((x, y + 1)))
        self.assertEqual(backdrop.compose(picture(320, 240), pixel=True, look='nonsense'),
                         backdrop.compose(picture(320, 240), pixel=True))                 # unknown: plain

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
        return picture(256, 224)

    def asset_url(self, path):
        return 'https://romm' + path


@unittest.skipUnless(PIL, 'needs PIL')
class Fanart(unittest.TestCase):
    def setUp(self):
        shutil.rmtree(kodi.profile_file('backdrops'), ignore_errors=True)
        self.addCleanup(shutil.rmtree, kodi.profile_file('backdrops'), True)

    def rom(self, n):
        return {'id': n, 'name': 'Game {}'.format(n), 'platform_slug': 'snes',
                'merged_screenshots': ['/assets/romm/resources/roms/1/{}/screenshots/0.jpg'.format(n)]}

    def test_made_once_and_kept(self):
        client = Shots()
        plugin.make_backdrops(client, [self.rom(1), self.rom(1)])
        path = plugin.fanart(client, self.rom(1))
        self.assertTrue(path.startswith(kodi.profile_file('backdrops')) and os.path.exists(path))
        self.assertFalse(os.path.exists(path + '.tmp'))
        self.assertEqual(plugin.fanart(client, self.rom(1)), path)
        self.assertEqual(len(client.fetched), 1)
        self.assertIsNone(plugin.fanart(client, {'id': 2}))

    def test_a_listing_makes_a_pageful_at_once(self):
        client = Shots()
        roms = [self.rom(n) for n in range(5)]
        with mock.patch.object(plugin, 'BACKDROPS', 3):
            plugin.make_backdrops(client, roms)
        made = [plugin.fanart(client, r) for r in roms]
        self.assertEqual(sum(1 for p in made if p.startswith('https://romm')), 2)   # beyond the cap: plain for now
        self.assertEqual(len(client.fetched), 3)
        plugin.make_backdrops(client, roms)                                     # the next visit does the rest
        self.assertEqual(len(client.fetched), 5)
        self.assertTrue(all(plugin.fanart(client, r).endswith('.jpg') for r in roms))

    def test_consoles_stretch_and_handhelds_keep_their_pixels(self):
        from PIL import Image
        client = Shots()
        self.enterContext(mock.patch.object(plugin, 'look', lambda: 'plain'))
        gb = dict(self.rom(2), platform_slug='gb')
        plugin.make_backdrops(client, [self.rom(1), gb])
        snes = Image.open(plugin.fanart(client, self.rom(1)))
        self.assertTrue(close(snes.getpixel((362 + 12, 92 + 12)), (20, 220, 20)))      # 4:3: 1195 wide
        self.assertLess(max(snes.getpixel((362 - 12, 540))), 120)                       # the blurred copy beside it
        hand = Image.open(plugin.fanart(client, gb))
        self.assertTrue(close(hand.getpixel((448 + 12, 92 + 12)), (20, 220, 20)))      # 4x: 1024 wide, as drawn
        self.assertLess(max(hand.getpixel((448 - 12, 540))), 120)

    def test_each_look_has_its_own_file(self):
        client = Shots()
        with mock.patch.object(plugin, 'look', lambda: 'crt'):
            plugin.make_backdrops(client, [self.rom(1)])
            crt = plugin.fanart(client, self.rom(1))
        with mock.patch.object(plugin, 'look', lambda: 'plain'):
            self.assertTrue(plugin.fanart(client, self.rom(1)).startswith('https://romm'))   # not made for this look yet
            plugin.make_backdrops(client, [self.rom(1)])
            plain = plugin.fanart(client, self.rom(1))
        self.assertNotEqual(crt, plain)
        self.assertEqual(len(client.fetched), 2)

    def test_server_down_shows_the_plain_screenshot(self):
        client = Shots(fail=True)
        plugin.make_backdrops(client, [self.rom(1)])
        self.assertTrue(plugin.fanart(client, self.rom(1)).startswith('https://romm'))
        self.assertFalse(os.path.exists(kodi.profile_file('backdrops')))

    def test_least_recently_listed_go_first(self):
        client = Shots()
        with mock.patch.object(plugin, 'KEEP', 2):
            plugin.make_backdrops(client, [self.rom(1)])
            first = plugin.fanart(client, self.rom(1))
            os.utime(first, (1, 1))
            plugin.make_backdrops(client, [self.rom(2), self.rom(3)])
        self.assertFalse(os.path.exists(first))
        self.assertEqual(len(os.listdir(kodi.profile_file('backdrops'))), 2)


if __name__ == '__main__':
    unittest.main()
