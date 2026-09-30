import os
import unittest

import support

from resources.lib import bios
from resources.lib.api import RommClient


class Client(RommClient):
    def __init__(self, server, firmware):
        super().__init__(base_url=server.url, token='t', timeout=1)
        self.fw = firmware

    def firmware(self, platform_id):
        return self.fw


class UnknownSize(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = support.Server()
        cls.system_dir = bios.system_dir
        cls.root = support.scratch('system')
        bios.system_dir = lambda core_id: os.path.join(cls.root, core_id)

    @classmethod
    def tearDownClass(cls):
        bios.system_dir = cls.system_dir
        cls.server.close()

    def test_download_without_size_or_part(self):
        self.server.reply = support.ok(b'B' * 50)
        dest = os.path.join(support.scratch('nosize'), 'bios.bin')
        Client(self.server, []).download(self.server.url + '/fw', dest, -1)
        self.assertEqual(os.path.getsize(dest), 50)

    def test_mirror_firmware_without_size(self):
        self.server.reply = support.ok(b'B' * 50)
        self.server.hits.clear()
        client = Client(self.server, [{'id': 1, 'file_name': 'bios.bin'}])
        self.assertEqual(bios.mirror(client, {'id': 3, 'slug': 'nosize'}, ['core.a']), 1)
        self.assertEqual(os.path.getsize(os.path.join(self.root, 'core.a', 'bios.bin')), 50)
        self.assertEqual(bios.mirror(client, {'id': 3, 'slug': 'nosize'}, ['core.a']), 0)
        self.assertEqual(len(self.server.hits), 1)                # staged copy reused


if __name__ == '__main__':
    unittest.main()
