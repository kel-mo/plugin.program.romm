import os
import unittest

import support

from resources.lib import cache
from resources.lib.api import ApiError, RommClient


class ShortRead(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = support.Server()
        cls.client = RommClient(base_url=cls.server.url, token='t', timeout=1)

    @classmethod
    def tearDownClass(cls):
        cls.server.close()

    def test_short_read_raises_and_keeps_part(self):
        self.server.reply = support.short(1000, 100)
        dest = os.path.join(support.scratch('short'), 'game.zip')
        with self.assertRaises(ApiError):
            self.client.download(self.server.url + '/x', dest, 1000)
        self.assertFalse(os.path.exists(dest))
        self.assertEqual(os.path.getsize(dest + '.part'), 100)   # kept for resume

    def test_body_timeout_raises_api_error(self):
        self.server.reply = support.stall(1000)
        dest = os.path.join(support.scratch('stall'), 'game.zip')
        with self.assertRaises(ApiError):
            self.client.download(self.server.url + '/x', dest, 1000)
        self.assertFalse(os.path.exists(dest))

    def test_full_read_completes(self):
        self.server.reply = support.ok(b'x' * 1000)
        dest = os.path.join(support.scratch('full'), 'game.zip')
        self.client.download(self.server.url + '/x', dest, 1000)
        self.assertEqual(os.path.getsize(dest), 1000)
        self.assertFalse(os.path.exists(dest + '.part'))

    def test_ensure_rom_records_no_truncated_rom(self):
        self.server.reply = support.short(1000, 100)
        rom = {'id': 7, 'fs_name': 'g.zip', 'fs_size_bytes': 1000, 'files': [{'id': 1, 'file_name': 'g.zip'}]}
        with self.assertRaises(ApiError):
            cache.ensure_rom(rom, self.client)
        self.assertFalse(cache.is_cached(7))


if __name__ == '__main__':
    unittest.main()
