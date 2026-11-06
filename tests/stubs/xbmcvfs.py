"""Kodi stub: local paths, and archive:// reading <archive>.contents/ as the archive's files."""
import os
from urllib.parse import unquote


def _local(p):
    if not p.startswith('archive://'):
        return p
    host, _, rel = p[len('archive://'):].partition('/')
    return os.path.join(unquote(host) + '.contents', rel)


def translatePath(p): return p
def exists(p): return os.path.exists(p)
def mkdirs(p): os.makedirs(p, exist_ok=True); return True
def listdir(p):
    d = _local(p)
    names = sorted(os.listdir(d)) if os.path.isdir(d) else []
    return ([n for n in names if os.path.isdir(os.path.join(d, n))],
            [n for n in names if os.path.isfile(os.path.join(d, n))])


class File:
    def __init__(self, p, mode=None): self._f = open(_local(p), 'rb')
    def size(self): return os.fstat(self._f.fileno()).st_size
    def readBytes(self, n=-1): return bytearray(self._f.read(n if n > 0 else -1))
    def close(self): self._f.close()
