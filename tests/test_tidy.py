import os
import re
import struct
import unittest

import support
import xbmcaddon
import xbmcplugin

from resources.lib import api, cache, icons, plugin
from resources.lib.api import RommClient


class Multipart(unittest.TestCase):
    def test_filename_cannot_inject_headers(self):
        body, _ctype = api._multipart({'saveFile': ('a"b\r\nX-Evil: 1.srm', b'D')})
        part = body.split(b'\r\n\r\n')[0].split(b'\r\n')
        self.assertEqual(part[1], b'Content-Disposition: form-data; name="saveFile"; filename="a%22b%0D%0AX-Evil: 1.srm"')
        self.assertEqual(len(part), 3)


class RunPluginActions(unittest.TestCase):
    def setUp(self):
        self.server = support.Server()
        self.settings = dict(xbmcaddon.SETTINGS)
        xbmcplugin.META.clear()

    def tearDown(self):
        self.server.close()
        xbmcaddon.SETTINGS.clear()
        xbmcaddon.SETTINGS.update(self.settings)

    def run_action(self, query):
        xbmcplugin.META.clear()
        plugin.run(['plugin://plugin.program.romm/', '1', query])
        return xbmcplugin.META.get('end')

    def test_unpaired_run_actions_end_no_directory(self):
        for action in ('details', 'favourite', 'sync_now'):
            with self.subTest(action=action):
                self.assertIsNone(self.run_action(f'?action={action}&rom_id=1'))

    def test_failed_run_action_ends_no_directory(self):
        xbmcaddon.SETTINGS.update({'server_url': self.server.url, 'token': 't'})
        self.server.reply = support.status(500)
        self.assertIsNone(self.run_action('?action=details&rom_id=1'))

    def test_failed_listing_still_ends_directory(self):
        xbmcaddon.SETTINGS.update({'server_url': self.server.url, 'token': 't'})
        self.server.reply = support.status(500)
        self.assertIs(self.run_action('?action=platforms'), False)


def ico(blob):
    return b'\x00\x00\x01\x00' + struct.pack('<H', 1) + b'\x00' * 8 + struct.pack('<II', len(blob), 22) + blob


class IconNegativeCache(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = support.Server()
        cls.client = RommClient(base_url=cls.server.url, token='t', timeout=0.5)

    @classmethod
    def tearDownClass(cls):
        cls.server.close()

    def fetches(self, slug, reply, times=3):
        self.server.reply = reply
        self.server.hits.clear()
        for _ in range(times):
            icon = icons.platform_icon(self.client, {'slug': slug, 'url_logo': '/logo.png'})
            self.assertEqual(icon, self.server.url + '/logo.png')
        return len(self.server.hits)

    def test_missing_icon_fetched_once(self):
        self.assertEqual(self.fetches('missing', support.status(404, b'Not Found')), 1)

    def test_bmp_only_icon_fetched_once(self):
        self.assertEqual(self.fetches('bmponly', support.ok(ico(b'BM' + b'\x00' * 20))), 1)

    def test_transient_failure_not_cached(self):
        self.assertEqual(self.fetches('flaky', support.status(500), times=2), 2)

    def test_png_icon_cached(self):
        self.server.reply = support.ok(ico(b'\x89PNG\r\n\x1a\n' + b'p' * 10))
        icon = icons.platform_icon(self.client, {'slug': 'good'})
        self.assertEqual(icon, os.path.join(cache.root(), 'icons', 'good.png'))
        self.assertEqual(os.path.getsize(icon), 18)


class ServiceDocstring(unittest.TestCase):
    def test_names_the_addon_xml_extension_point(self):
        root = os.path.dirname(support.HERE)
        with open(os.path.join(root, 'addon.xml'), encoding='utf-8') as f:
            point = re.search(r'<extension point="([^"]+)" library="service.py"', f.read()).group(1)
        with open(os.path.join(root, 'service.py'), encoding='utf-8') as f:
            doc = re.search(r'"""(.*?)"""', f.read(), re.DOTALL).group(1)
        self.assertEqual(re.findall(r'xbmc\.[\w.]*service', doc), [point])


if __name__ == '__main__':
    unittest.main()
