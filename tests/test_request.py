import unittest

import support

from resources.lib import icons, props
from resources.lib.api import ApiError, RommClient


class BodyErrors(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = support.Server()
        cls.client = RommClient(base_url=cls.server.url, token='t', timeout=0.5)

    @classmethod
    def tearDownClass(cls):
        cls.server.close()

    def test_body_timeout(self):
        self.server.reply = support.stall()
        with self.assertRaises(ApiError):
            self.client.get('/api/x')

    def test_short_body(self):
        self.server.reply = support.short(1000, 100)
        with self.assertRaises(ApiError):
            self.client.get('/api/x')

    def test_download_save_body_timeout(self):
        self.server.reply = support.stall()
        with self.assertRaises(ApiError):
            self.client.download_save(1)

    def test_download_save_returns_bytes(self):
        self.server.reply = support.ok(b'SAVE')
        self.assertEqual(self.client.download_save(1), b'SAVE')

    def test_icon_body_timeout_falls_back(self):
        self.server.reply = support.stall()
        icon = icons.platform_icon(self.client, {'slug': 'stall', 'url_logo': '/logo.png'})
        self.assertEqual(icon, self.server.url + '/logo.png')

    def test_favourites_body_timeout(self):
        self.server.reply = support.stall()
        self.assertIsNone(props.favourite_ids(self.client))

    def test_json_body(self):
        self.server.reply = support.ok(b'{"a": 1}')
        self.assertEqual(self.client.get('/api/x'), {'a': 1})


if __name__ == '__main__':
    unittest.main()
