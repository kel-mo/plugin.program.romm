import io
import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

import support
import xbmc
import xbmcaddon
import xbmcplugin

from resources.lib import kodi, plugin, tiles
from resources.lib.api import RommClient

try:
    import PIL                                          # in Kodi's flatpak Python, not always on the host
except ImportError:
    PIL = None

DAY = '2026-10-02'


def game(rom_id, shot=True, cover=True):
    base = '/assets/romm/resources/roms/1/{}/'.format(rom_id)
    return {'id': rom_id, 'name': 'Game {}'.format(rom_id),
            'merged_screenshots': [base + 'screenshots/0.jpg'] if shot else [],
            'path_cover_large': base + 'cover/big.png?ts=2026-09-07 09:54:39' if cover else ''}


class Library:
    """Just enough of RommClient: the whole library, favourites, recently played and backlog."""

    def __init__(self, games=(), favourites=(), played=(), backlog=()):
        self.lists = {'all': list(games), 'favourites': list(favourites), 'played': list(played),
                      'backlog': list(backlog)}
        self.fetched = []

    def roms(self, offset=0, limit=100, **filters):
        kind = ('favourites' if 'collection_id' in filters else 'played' if filters.get('last_played')
                else 'backlog' if filters.get('statuses') else 'all')
        items = self.lists[kind]
        return items[offset:offset + limit], len(items)

    def favourites(self):
        return {'id': 1, 'is_favorite': True} if self.lists['favourites'] else None

    def asset(self, path):
        self.fetched.append(path)
        return b'picture'


class Tiles(unittest.TestCase):
    def setUp(self):
        self.settings = dict(xbmcaddon.SETTINGS)
        xbmcaddon.SETTINGS['tiles'] = 'true'
        shutil.rmtree(tiles.tile_dir(), ignore_errors=True)
        self.addCleanup(shutil.rmtree, tiles.tile_dir(), True)

    def tearDown(self):
        xbmcaddon.SETTINGS.clear()
        xbmcaddon.SETTINGS.update(self.settings)

    def test_screenshot_before_box_art(self):
        self.assertTrue(tiles.picture(game(1)).endswith('screenshots/0.jpg'))
        self.assertTrue(tiles.picture(game(1, shot=False)).startswith('/assets/romm/resources/roms/1/1/cover/'))
        self.assertIsNone(tiles.picture(game(1, shot=False, cover=False)))
        self.assertIsNone(tiles.picture({'id': 1, 'merged_screenshots': ['https://images.igdb.com/x.jpg']}))

    def test_favourites_prefer_a_favourite(self):
        lib = Library(games=[game(i) for i in range(1, 30)], favourites=[game(100), game(101)])
        self.assertIn(tiles.pick(lib, 'favourites', DAY)['id'], (100, 101))

    def test_favourites_fall_back_to_any_game(self):
        lib = Library(games=[game(1, shot=False, cover=False), game(2)], favourites=[game(100, shot=False, cover=False)])
        self.assertEqual(tiles.pick(lib, 'favourites', DAY)['id'], 2)

    def test_last_played_shows_the_last_game_with_a_picture(self):
        lib = Library(games=[game(1)], played=[game(7, shot=False, cover=False), game(8, shot=False), game(9)])
        self.assertEqual(tiles.pick(lib, 'last_played', DAY)['id'], 8)

    def test_same_game_all_day(self):
        lib = Library(favourites=[game(i) for i in range(1, 30)])
        self.assertEqual(tiles.pick(lib, 'favourites', DAY), tiles.pick(lib, 'favourites', DAY))

    def test_skips_games_already_shown(self):
        lib = Library(games=[game(1), game(2)])
        self.assertEqual(tiles.pick(lib, 'platforms', DAY, skip={1})['id'], 2)
        self.assertIn(tiles.pick(lib, 'platforms', DAY, skip={1, 2})['id'], (1, 2))   # all shown: share one

    def test_offline_gives_no_game(self):
        server = support.Server()
        self.addCleanup(server.close)
        self.assertIsNone(tiles.pick(RommClient(server.url, 't', timeout=2), 'favourites', DAY))

    def test_without_pil_the_picture_is_used(self):
        dest = os.path.join(kodi.ensure_dir(tiles.tile_dir()), 'x.jpg')
        with mock.patch.dict(sys.modules, {'PIL': None}):
            tiles.render(b'picture', 'ROMs', dest)
        with open(dest, 'rb') as f:
            self.assertEqual(f.read(), b'picture')
        self.assertFalse(os.path.exists(dest + '.tmp'))

    @unittest.skipUnless(PIL, 'needs PIL')
    def test_tile_is_square_dark_and_labelled(self):
        from PIL import Image
        shot = io.BytesIO()
        Image.new('RGB', (256, 224), (200, 200, 200)).save(shot, 'PNG')
        dest = os.path.join(kodi.ensure_dir(tiles.tile_dir()), 'x.jpg')
        with mock.patch.object(tiles, 'font_file', lambda: (None, False)):
            tiles.render(shot.getvalue(), 'ROMs', dest)
        im = Image.open(dest).convert('L')
        self.assertEqual(im.size, (tiles.SIZE, tiles.SIZE))
        self.assertEqual(im.crop((128, 216, 384, 296)).getextrema()[1], 255)    # white text in the middle
        self.assertLess(im.crop((0, 0, 64, 64)).getextrema()[1], 160)          # darkened picture at the corner
        row = [im.getpixel((x, tiles.SIZE // 2)) for x in range(tiles.SIZE)]
        first = next(x for x, v in enumerate(row) if v > 240)
        with mock.patch.object(tiles, 'font_file', lambda: (None, False)), mock.patch.object(tiles, 'SHADOW', 0):
            tiles.render(shot.getvalue(), 'ROMs', dest)
        plain = Image.open(dest).convert('L')
        halo = sum(im.getpixel((x, tiles.SIZE // 2)) for x in range(first - 12, first))
        self.assertLess(halo, sum(plain.getpixel((x, tiles.SIZE // 2)) for x in range(first - 12, first)) * 0.6)

    @unittest.skipUnless(PIL, 'needs PIL')
    def test_one_text_size_fits_the_longest_name(self):
        from PIL import Image, ImageDraw
        draw = ImageDraw.Draw(Image.new('L', (1, 1)))
        with mock.patch.object(tiles, 'font_file', lambda: (None, False)):
            size = tiles.text_size(['Search', 'Smart collections'])
            self.assertEqual(size, tiles.text_size(['collections']))           # wraps rather than shrinks
            face, stroke = tiles.font(size)
            self.assertEqual(tiles.lines(draw, 'Smart collections', face, stroke), 'Smart\ncollections')
            self.assertEqual(tiles.lines(draw, 'Search', face, stroke), 'Search')
            self.assertLess(tiles.text_size(['Search', 'Supercalifragilistic']), tiles.text_size(['Search']))

    @unittest.skipUnless(PIL, 'needs PIL')
    def test_halo_sits_on_wrapped_lines(self):
        from PIL import Image, ImageDraw
        with mock.patch.object(tiles, 'font_file', lambda: (None, False)):
            size = tiles.text_size(['Collections', 'Smart collections'])
            face, stroke = tiles.font(size)
        mask = Image.new('L', (tiles.SIZE, tiles.SIZE))
        draw = ImageDraw.Draw(mask)
        text = tiles.lines(draw, 'Smart collections', face, stroke)
        self.assertIn('\n', text)
        draw.text((60, 100), text, font=face, fill=255, stroke_width=stroke, align='center')
        glyphs = mask.getbbox()
        halo = tiles.halo((60, 100), text, face, stroke, size).point(lambda v: 255 if v > 40 else 0).getbbox()
        top, bottom = glyphs[1] - halo[1], halo[3] - glyphs[3]
        self.assertLessEqual(abs(top - bottom), 3)           # as far past the last line as the first

    def test_a_refresh_past_midnight_keeps_its_day(self):
        lib = Library(games=[game(i) for i in range(1, 30)])
        with mock.patch.object(tiles, 'render', lambda data, label, dest, size: open(dest, 'wb').close()), \
                mock.patch.object(kodi, 'jsonrpc', lambda *a, **k: {}), \
                mock.patch.object(tiles, 'drawing', lambda day=None: (day or 'tomorrow') + ' v'):
            tiles.refresh(lib, xbmc.Monitor())
        with open(tiles.stamp()) as f:
            self.assertEqual(f.read(), tiles.date.today().isoformat() + ' v')

    def test_skin_bold_font_first(self):
        skin = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, skin)
        os.makedirs(os.path.join(skin, 'xml'))
        os.makedirs(os.path.join(skin, 'fonts'))
        with open(os.path.join(skin, 'xml', 'Font.xml'), 'w') as f:
            f.write('<fonts><fontset id="Default"><font><name>font13</name><filename>Sans-Regular.ttf</filename></font>'
                    '<font><name>font_bold</name><filename>Sans-Bold.ttf</filename></font></fontset></fonts>')
        for name in ('Sans-Regular.ttf', 'Sans-Bold.ttf'):
            open(os.path.join(skin, 'fonts', name), 'w').close()
        where = lambda p: p.replace('special://skin', skin)
        with mock.patch.object(tiles.xbmcvfs, 'translatePath', where):
            self.assertEqual(tiles.font_file(), (os.path.join(skin, 'fonts', 'Sans-Bold.ttf'), True))
            os.remove(os.path.join(skin, 'fonts', 'Sans-Bold.ttf'))
            self.assertEqual(tiles.font_file(), (os.path.join(skin, 'fonts', 'Sans-Regular.ttf'), False))

    def test_refresh_draws_each_tile_once_a_day(self):
        calls = []

        def rpc(method, **params):
            calls.append(method)
            return {'textures': [{'textureid': 7}]} if method == 'Textures.GetTextures' else {}
        lib = Library(games=[game(i) for i in range(4, 30)], played=[game(3)], favourites=[game(3)])
        with mock.patch.object(tiles, 'render', lambda data, label, dest, size: open(dest, 'wb').close()), \
                mock.patch.object(kodi, 'jsonrpc', rpc):
            self.assertTrue(tiles.due())
            self.assertEqual(tiles.refresh(lib, xbmc.Monitor()), len(tiles.FOLDERS))
            self.assertFalse(tiles.due())
        for key in tiles.FOLDERS:
            self.assertEqual(len(tiles.drawn(key)), 1, key)
        self.assertEqual(len(set(lib.fetched)), len(tiles.FOLDERS))             # a different game on each
        self.assertIn('/3/', lib.fetched[list(tiles.FOLDERS).index('last_played')])   # folders pick first
        self.assertEqual(calls, ['Textures.GetTextures', 'Textures.RemoveTexture'])

    def test_waits_for_the_names(self):
        lib = Library(games=[game(i) for i in range(1, 30)])
        real = kodi.L
        with mock.patch.object(kodi, 'L', lambda i, *a: '' if i == 30023 else real(i, *a)), \
                mock.patch.object(tiles, 'render', lambda *a: self.fail('drew without a name')):
            self.assertEqual(tiles.refresh(lib, xbmc.Monitor()), 0)
        self.assertEqual(lib.fetched, [])
        self.assertTrue(tiles.due())

    def test_update_redraws_the_same_day(self):
        kodi.ensure_dir(tiles.tile_dir())
        with open(tiles.stamp(), 'w') as f:
            f.write(tiles.drawing())
        self.assertFalse(tiles.due())
        with mock.patch.object(kodi, 'ADDON_VERSION', '9.9.9'):
            self.assertTrue(tiles.due())
        with open(tiles.stamp(), 'w') as f:
            f.write(tiles.date.today().isoformat())                       # as 0.2.6 wrote it
        self.assertTrue(tiles.due())

    def test_off_draws_nothing(self):
        xbmcaddon.SETTINGS['tiles'] = 'false'
        self.assertFalse(tiles.due())

    def draw(self, *names):
        kodi.ensure_dir(tiles.tile_dir())
        for name in names:
            open(os.path.join(tiles.tile_dir(), name), 'w').close()
        return [os.path.join(tiles.tile_dir(), n) for n in names]

    def test_newest_drawing_wins(self):
        old, new = self.draw('platforms-100.jpg', 'platforms-200.jpg')
        self.assertEqual(tiles.current('platforms'), new)
        self.assertIsNone(tiles.current('search'))

    def test_old_drawings_go(self):
        gone, newest, other, stray = self.draw('search-100.jpg', 'search-200.jpg', 'platforms-100.jpg', 'romm-100.jpg')
        with mock.patch.object(kodi, 'jsonrpc', lambda *a, **k: {}):
            tiles.tidy()
        self.assertEqual([os.path.exists(p) for p in (gone, newest, other, stray)], [False, True, True, False])

    def test_menu_shows_tiles(self):
        tile, = self.draw('last_played-100.jpg')
        xbmcaddon.SETTINGS.update({'server_url': 'http://romm', 'token': 't'})
        del xbmcplugin.ITEMS[:]
        plugin.root()
        art = {li.label: li.art.get('thumb') for url, li, _ in xbmcplugin.ITEMS}
        self.assertEqual(sorted(art), sorted(kodi.L(i) for i in tiles.FOLDERS.values()))   # every menu entry has its own tile
        self.assertEqual(art[kodi.L(30002)], tile)
        self.assertEqual(art[kodi.L(30000)], kodi.ICON)                    # no tile drawn yet
        xbmcaddon.SETTINGS['tiles'] = 'false'
        self.assertEqual(tiles.art('last_played'), kodi.ICON)


    def test_favourites_pointed_back_at_the_icon(self):
        tile = os.path.join(tiles.tile_dir(), 'search-100.jpg')
        favs = [{'type': 'window', 'title': 'Films', 'window': 'videos', 'windowparameter': 'videodb://movies/', 'thumbnail': ''},
                {'type': 'window', 'title': 'RomM', 'window': 'programs', 'windowparameter': 'plugin://plugin.program.romm', 'thumbnail': tile},
                {'type': 'script', 'title': 'Mine', 'path': 'script.mine', 'thumbnail': '/my/own.png'},
                {'type': 'window', 'title': 'Folder', 'window': 'programs', 'windowparameter': 'plugin://plugin.program.romm/?action=x',
                 'thumbnail': tile}]
        calls = []

        def rpc(method, **params):                            # as Kodi: adding a favourite that exists removes it
            calls.append(method)
            if method == 'Favourites.GetFavourites':
                return {'favourites': [dict(f) for f in favs]}
            same = lambda f: all(f.get(k) == params.get(k) for k in ('type', 'window', 'windowparameter', 'path'))
            found = next((f for f in favs if same(f)), None)
            favs.remove(found) if found else favs.append(dict(params, thumbnail=params.get('thumbnail', '')))
            return 'OK'
        with mock.patch.object(kodi, 'jsonrpc', rpc):
            self.assertEqual(tiles.repair_favourites(xbmc.Monitor()), 2)
        self.assertEqual([f['title'] for f in favs], ['Films', 'RomM', 'Mine', 'Folder'])      # in place
        self.assertEqual([f['thumbnail'] for f in favs], ['', kodi.ICON, '/my/own.png', kodi.ICON])
        self.assertEqual(calls.count('Favourites.AddFavourite'), 6)                           # from the first on
        with mock.patch.object(kodi, 'jsonrpc', rpc):
            self.assertEqual(tiles.repair_favourites(xbmc.Monitor()), 0)                                   # nothing left to fix
        self.assertEqual(calls.count('Favourites.AddFavourite'), 6)
        favs.append({'type': 'unknown', 'title': 'Odd', 'thumbnail': ''})
        favs[1]['thumbnail'] = tile
        with mock.patch.object(kodi, 'jsonrpc', rpc):
            self.assertEqual(tiles.repair_favourites(xbmc.Monitor()), 0)                                   # can't keep the order
        self.assertEqual(favs[1]['thumbnail'], tile)


if __name__ == '__main__':
    unittest.main()
