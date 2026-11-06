import os
import unittest
import zipfile

import support

from resources.lib import cache
from resources.lib.api import ApiError


class Extract(unittest.TestCase):
    def setUp(self):
        self.dir = support.scratch('extract')
        self.archive = os.path.join(self.dir, 'game.zip')
        with zipfile.ZipFile(self.archive, 'w') as z:
            z.writestr('a.bin', b'a' * 10)
            z.writestr('b.bin', b'b' * 10)

    def sizes(self, files):
        return [(os.path.basename(p), os.path.getsize(p)) for p in files]

    def test_interrupted_extract_is_redone(self):
        os.makedirs(os.path.join(self.dir, 'game'))
        with open(os.path.join(self.dir, 'game', 'a.bin'), 'wb') as f:
            f.write(b'a')                                         # partial first member
        out = cache.extract_if_needed([self.archive], {'bin'})
        self.assertEqual(self.sizes(out), [('a.bin', 10), ('b.bin', 10)])
        self.assertFalse(os.path.exists(self.archive))

    def test_completed_extract_is_reused(self):
        out = cache.extract_if_needed([self.archive], {'bin'})
        self.assertEqual(self.sizes(out), [('a.bin', 10), ('b.bin', 10)])
        self.assertEqual(cache.extract_if_needed([self.archive], {'bin'}), out)


    def zip_of(self, name, members):
        path = os.path.join(self.dir, name)
        with zipfile.ZipFile(path, 'w') as z:
            for m in members:
                z.writestr(m, b'x' * 10)
        return path

    def test_zipped_disc_is_unpacked_although_the_cores_read_zips(self):
        archive = self.zip_of('disc.zip', ['disc.cue', 'disc (Track 1).bin'])
        out = cache.extract_if_needed([archive], {'cue', 'chd', 'zip'})
        self.assertEqual(self.sizes(out), [('disc (Track 1).bin', 10), ('disc.cue', 10)])
        self.assertFalse(os.path.exists(archive))

    def test_arcade_zip_is_kept(self):
        archive = self.zip_of('stv.zip', ['epr-20091.ic8', 'mpr-20092.ic1'])
        self.assertEqual(cache.extract_if_needed([archive], {'cue', 'chd', 'zip'}), [archive])
        self.assertTrue(os.path.exists(archive))

    def test_dos_zip_with_a_cd_image_is_kept(self):
        archive = self.zip_of('dos.zip', ['GAME.EXE', 'cd/game.cue', 'cd/game.bin'])
        dos = {'bat', 'chd', 'com', 'cue', 'exe', 'iso', 'zip'}
        self.assertEqual(cache.extract_if_needed([archive], dos, keep_archives=True), [archive])
        self.assertTrue(os.path.exists(archive))


class ExtractThroughKodi(unittest.TestCase):
    """.7z goes through Kodi's vfs.libarchive; the stub serves <archive>.contents/."""

    def setUp(self):
        self.dir = support.scratch('extract7z')
        self.archive = os.path.join(self.dir, 'game.7z')
        open(self.archive, 'wb').close()

    def add(self, name, size):
        path = os.path.join(self.archive + '.contents', name)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'wb') as f:
            f.write(b'x' * size)

    def test_7z_is_unpacked_with_its_folders(self):
        self.add('Game (Europe)/Game (Europe).cue', 10)
        self.add('Game (Europe)/Game (Europe) (Track 1).bin', cache.CHUNK + 5)
        self.add('readme.txt', 3)
        seen = []
        out = cache.extract_if_needed([self.archive], {'cue', 'chd'},
                                      lambda done, total, i, n, name: seen.append((i, n, done, total)))
        rel = sorted(os.path.relpath(p, os.path.join(self.dir, 'game')) for p in out)
        self.assertEqual(rel, ['Game (Europe)/Game (Europe) (Track 1).bin', 'Game (Europe)/Game (Europe).cue',
                               'readme.txt'])
        self.assertEqual(os.path.getsize(os.path.join(self.dir, 'game', rel[0])), cache.CHUNK + 5)
        self.assertFalse(os.path.exists(self.archive))
        self.assertIn((2, 3, cache.CHUNK, cache.CHUNK + 5), seen)

    def test_cancel_leaves_nothing_marked_unpacked(self):
        self.add('game.iso', cache.CHUNK + 1)
        with self.assertRaises(ApiError):
            cache.extract_if_needed([self.archive], {'iso'}, lambda *a: False)
        self.assertTrue(os.path.exists(self.archive))
        self.assertFalse(os.path.exists(os.path.join(self.dir, 'game', cache.EXTRACTED)))

    def test_arcade_7z_is_kept(self):
        self.add('rom.ic1', 3)
        self.assertEqual(cache.extract_if_needed([self.archive], {'7z', 'zip'}), [self.archive])
        os.remove(os.path.join(self.archive + '.contents', 'rom.ic1'))
        self.assertEqual(cache.extract_if_needed([self.archive], {'7z', 'zip'}), [self.archive])  # no libarchive

    def test_member_kodi_cannot_read_keeps_the_archive(self):
        self.add('game.iso', 0)                           # what Kodi gives for a member it can't open
        with self.assertRaises(ApiError):
            cache.extract_if_needed([self.archive], {'iso'})
        self.assertTrue(os.path.exists(self.archive))
        self.assertFalse(os.path.exists(os.path.join(self.dir, 'game', cache.EXTRACTED)))

    def test_unreadable_7z_says_so(self):
        with self.assertRaises(ApiError) as e:
            cache.extract_if_needed([self.archive], {'iso'})
        self.assertIn('vfs.libarchive', str(e.exception))
        self.assertTrue(os.path.exists(self.archive))


if __name__ == '__main__':
    unittest.main()
