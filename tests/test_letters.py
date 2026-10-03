import unittest
from unittest import mock

import support  # noqa: F401  (test paths)
import xbmcaddon
import xbmcplugin

from resources.lib import plugin


class Library:
    """Just enough of RommClient for a list by name: 1087 games, and where each initial starts."""

    def __init__(self, total=1087):
        self.total = total
        self.calls = []

    def roms(self, offset=0, limit=100, **filters):
        self.calls.append(('roms', offset, limit, filters))
        return [{'id': n, 'name': 'Game {}'.format(n), 'platform_slug': 'snes'} for n in range(offset, min(offset + limit, self.total))], self.total

    def letters(self, **filters):
        self.calls.append(('letters', filters))
        return {'0': 0, 'a': 4, 'b': 53, 's': 739, 't': 910, 'z': 1081}, self.total

    def favourites(self):
        return None

    def asset_url(self, path):
        return ''


def listed():
    return [(url, li.label, getattr(li, 'label2', '')) for url, li, _ in xbmcplugin.ITEMS]


class Letters(unittest.TestCase):
    def setUp(self):
        self.settings = dict(xbmcaddon.SETTINGS)
        xbmcaddon.SETTINGS.update({'server_url': 'http://romm', 'token': 't', 'page_size': '100'})
        self.addCleanup(lambda: (xbmcaddon.SETTINGS.clear(), xbmcaddon.SETTINGS.update(self.settings)))
        self.quiet = mock.patch.object(plugin.fanart, 'queue', lambda roms: 0)
        self.quiet.start()
        self.addCleanup(self.quiet.stop)
        del xbmcplugin.ITEMS[:]

    def test_a_long_list_by_name_offers_a_jump(self):
        plugin.roms(Library(), {'action': 'roms', 'regions': 'USA', 'name': 'USA'})
        url, label, _ = listed()[0]
        self.assertEqual(label, 'Jump to letter')
        self.assertIn('action=letters', url)
        self.assertIn('regions=USA', url)
        self.assertNotIn('offset', url)
        self.assertEqual(len(listed()), 1 + 100 + 1)                              # the jump, a page, next

    def test_a_short_or_otherwise_sorted_list_does_not(self):
        plugin.roms(Library(total=40), {'action': 'roms', 'regions': 'USA'})
        self.assertNotIn('Jump to letter', [label for _, label, _ in listed()])
        del xbmcplugin.ITEMS[:]
        plugin.roms(Library(), {'action': 'roms', 'regions': 'USA', 'order_by': 'last_played'})
        self.assertNotIn('Jump to letter', [label for _, label, _ in listed()])

    def test_each_letter_opens_the_page_that_starts_there(self):
        lib = Library()
        plugin.letters(lib, {'action': 'letters', 'regions': 'USA', 'name': 'USA'})
        self.assertEqual(lib.calls, [('letters', {'regions': 'USA'})])
        rows = listed()
        self.assertEqual([label for _, label, _ in rows], ['0-9', 'A', 'B', 'S', 'T', 'Z'])
        self.assertEqual([n for _, _, n in rows], ['4', '49', '686', '171', '171', '6'])   # games under each
        t = next(url for url, label, _ in rows if label == 'T')
        self.assertIn('action=roms', t)
        self.assertIn('offset=910', t)
        self.assertIn('regions=USA', t)
        self.assertNotIn('action=letters', t)


if __name__ == '__main__':
    unittest.main()
