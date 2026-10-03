import io
import os
import shutil
import sys
import unittest
from unittest import mock

import support  # noqa: F401  (test paths)
import xbmc

from resources.lib import backdrop, fanart
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
        shutil.rmtree(fanart.folder(), ignore_errors=True)
        self.addCleanup(shutil.rmtree, fanart.folder(), True)
        del xbmc.BUILTINS[:]
        xbmc.INFOLABELS.clear()

    def rom(self, n, slug='snes'):
        return {'id': n, 'name': 'Game {}'.format(n), 'platform_slug': slug,
                'merged_screenshots': ['/assets/romm/resources/roms/1/{}/screenshots/0.jpg'.format(n)]}

    def test_listing_queues_and_the_service_makes(self):
        client = Shots()
        roms = [self.rom(1), self.rom(2), {'id': 3}]
        self.assertEqual(fanart.queue(roms), 2)
        self.assertEqual(fanart.queue(roms), 2)                                   # queued once
        self.assertEqual(len(os.listdir(fanart.queue_dir())), 2)
        self.assertTrue(fanart.art(client, self.rom(1)).startswith('https://romm'))   # plain meanwhile
        self.assertIsNone(fanart.art(client, {'id': 3}))
        self.assertEqual(fanart.work(xbmc.Monitor(), client), 2)
        self.assertEqual(os.listdir(fanart.queue_dir()), [])
        made = fanart.art(client, self.rom(1))
        self.assertTrue(made.startswith(fanart.folder()) and os.path.exists(made))
        self.assertFalse(os.path.exists(made + '.tmp'))
        self.assertEqual(fanart.queue(roms), 0)                                   # nothing left to ask for
        self.assertEqual(fanart.work(xbmc.Monitor(), client), 0)
        self.assertEqual(len(client.fetched), 2)

    def test_a_game_list_on_screen_is_refreshed(self):
        client = Shots()
        fanart.queue([self.rom(1)])
        xbmc.INFOLABELS['Container.FolderPath'] = 'plugin://plugin.program.romm/?action=roms&platform_id=8'
        with mock.patch.object(fanart, 'RommClient', lambda timeout: client):
            fanart.serve(type('Once', (), {'waits': iter([False, True]),
                                            'waitForAbort': lambda s, t: next(s.waits), 'abortRequested': lambda s: False})())
        self.assertEqual(xbmc.BUILTINS, ['Container.Refresh'])
        xbmc.INFOLABELS['Container.FolderPath'] = 'plugin://plugin.video.other/'
        fanart.refresh()
        self.assertEqual(xbmc.BUILTINS, ['Container.Refresh'])                    # someone else's list: left alone

    def test_consoles_stretch_and_handhelds_keep_their_pixels(self):
        from PIL import Image
        client = Shots()
        with mock.patch.object(fanart, 'look', lambda: 'plain'):
            gb = self.rom(2, 'gb')
            fanart.queue([self.rom(1), gb])
            fanart.work(xbmc.Monitor(), client)
            snes = Image.open(fanart.art(client, self.rom(1)))
            hand = Image.open(fanart.art(client, gb))
        self.assertTrue(close(snes.getpixel((362 + 12, 92 + 12)), (20, 220, 20)))      # 4:3: 1195 wide
        self.assertLess(max(snes.getpixel((362 - 12, 540))), 120)                       # the blurred copy beside it
        self.assertTrue(close(hand.getpixel((448 + 12, 92 + 12)), (20, 220, 20)))      # 4x: 1024 wide, as drawn
        self.assertLess(max(hand.getpixel((448 - 12, 540))), 120)

    def test_each_look_has_its_own_file(self):
        client = Shots()
        with mock.patch.object(fanart, 'look', lambda: 'crt'):
            fanart.queue([self.rom(1)])
            fanart.work(xbmc.Monitor(), client)
            crt = fanart.art(client, self.rom(1))
        with mock.patch.object(fanart, 'look', lambda: 'plain'):
            self.assertTrue(fanart.art(client, self.rom(1)).startswith('https://romm'))   # not made for this look yet
            fanart.queue([self.rom(1)])
            fanart.work(xbmc.Monitor(), client)
            plain = fanart.art(client, self.rom(1))
        self.assertNotEqual(crt, plain)
        self.assertEqual(len(client.fetched), 2)

    def test_server_down_leaves_the_plain_screenshot(self):
        client = Shots(fail=True)
        fanart.queue([self.rom(1)])
        self.assertEqual(fanart.work(xbmc.Monitor(), client), 0)
        self.assertEqual(os.listdir(fanart.queue_dir()), [])                      # asked again by the next listing
        self.assertTrue(fanart.art(client, self.rom(1)).startswith('https://romm'))
        self.assertEqual(fanart.queue([self.rom(1)]), 1)

    def test_least_recently_listed_go_first(self):
        client = Shots()
        with mock.patch.object(fanart, 'KEEP', 2):
            fanart.queue([self.rom(1)])
            fanart.work(xbmc.Monitor(), client)
            first = fanart.art(client, self.rom(1))
            os.utime(first, (1, 1))
            fanart.queue([self.rom(2), self.rom(3)])
            fanart.work(xbmc.Monitor(), client)
        self.assertFalse(os.path.exists(first))
        self.assertEqual(len([n for n in os.listdir(fanart.folder()) if n.endswith('.jpg')]), 2)


if __name__ == '__main__':
    unittest.main()
