import os
import struct
import unittest
from unittest import mock

import support

from resources.lib import bios, cache, icons
from resources.lib.api import RommClient

EVIL = '../../evil'                  # escapes the cache, stays in the test dir


class Recorder(RommClient):
    def __init__(self, server=None, firmware=None):
        super().__init__(base_url=server.url if server else 'http://127.0.0.1:9', token='t', timeout=1)
        self.fw = firmware or []
        self.dests = []

    def firmware(self, platform_id):
        return self.fw

    def download(self, url, dest, expected_size=None, progress=None):
        self.dests.append(dest)


def ico(png):
    return b'\x00\x00\x01\x00' + struct.pack('<H', 1) + b'\x00' * 8 + struct.pack('<II', len(png), 22) + png


class Traversal(unittest.TestCase):
    def test_rom_subdir(self):
        client = Recorder()
        rom = {'id': 8, 'fs_name': 'x', 'fs_name_no_ext': EVIL, 'has_multiple_files': True,
               'files': [{'id': 1, 'file_name': 'f.bin', 'file_size_bytes': 1}]}
        with self.assertRaises(ValueError):
            cache.ensure_rom(rom, client)
        self.assertEqual(client.dests, [])

    def test_bios_staging(self):
        client = Recorder(firmware=[{'id': 1, 'file_name': 'bios.bin', 'file_size_bytes': 5}])
        system = support.scratch('system-paths')
        with mock.patch.object(bios, 'system_dir', lambda core_id: system), self.assertRaises(ValueError):
            bios.mirror(client, {'id': 3, 'slug': EVIL}, ['core.a'])
        self.assertEqual(client.dests, [])

    def test_icon_file(self):
        server = support.Server()
        self.addCleanup(server.close)
        server.reply = support.ok(ico(b'\x89PNG\r\n\x1a\n' + b'p' * 10))
        with self.assertRaises(ValueError):
            icons.platform_icon(Recorder(server), {'slug': EVIL})
        self.assertFalse(os.path.exists(os.path.normpath(os.path.join(cache.root(), 'icons', EVIL + '.png'))))


if __name__ == '__main__':
    unittest.main()
