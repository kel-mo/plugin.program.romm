import os
import threading
import unittest

import support

from resources.lib import kodi


class ConcurrentWriters(unittest.TestCase):
    def test_two_writers_one_file(self):
        directory = support.scratch('state')
        path = os.path.join(directory, 'saves_state.json')
        errors = []

        def writer(n):
            for i in range(300):
                try:
                    kodi.write_json(path, {'writer': n, 'i': i, 'pad': 'x' * 2000})
                except OSError as e:
                    errors.append(e)

        threads = [threading.Thread(target=writer, args=(n,)) for n in range(2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(errors, [])
        self.assertEqual(kodi.read_json(path)['i'], 299)
        self.assertEqual(os.listdir(directory), ['saves_state.json'])


if __name__ == '__main__':
    unittest.main()
