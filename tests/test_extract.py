import os
import unittest
import zipfile

import support

from resources.lib import cache


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


if __name__ == '__main__':
    unittest.main()
