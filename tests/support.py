"""Test setup: Kodi stubs on sys.path, an isolated profile/cache and a local HTTP server."""
import atexit
import os
import shutil
import socket
import sys
import tempfile
import threading

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [os.path.join(HERE, 'stubs'), os.path.dirname(HERE)]

import xbmcaddon

TMP = tempfile.mkdtemp(prefix='romm-tests-')
atexit.register(shutil.rmtree, TMP, True)
xbmcaddon.PROFILE = os.path.join(TMP, 'profile')
xbmcaddon.SETTINGS.clear()                   # never the real server or token
xbmcaddon.SETTINGS.update({'sort_by': 'name', 'cache_path': os.path.join(TMP, 'cache')})


def scratch(name):
    path = os.path.join(TMP, name)
    shutil.rmtree(path, ignore_errors=True)
    os.makedirs(path)
    return path


def head(status, length, extra=b''):
    return b'HTTP/1.1 %s\r\nContent-Length: %d\r\nConnection: close\r\n%s\r\n' % (status, length, extra)


def ok(body):
    return lambda conn: conn.sendall(head(b'200 OK', len(body)) + body)


def status(code, reason=b'Error'):
    return lambda conn: conn.sendall(head(b'%d %s' % (code, reason), 2) + b'{}')


def short(promised, sent):
    """Promise a body of promised bytes, send only sent, then close."""
    return lambda conn: conn.sendall(head(b'200 OK', promised) + b'x' * sent)


def stall(promised=100):
    """Send the headers and one byte, then go quiet until the client gives up."""
    def reply(conn):
        conn.sendall(head(b'200 OK', promised) + b'{')
        conn.settimeout(5)
        try:
            conn.recv(1)
        except OSError:
            pass
    return reply


class Server:
    """One reply callable per request, set in .reply; request paths land in .hits."""

    def __init__(self):
        self.sock = socket.socket()
        self.sock.bind(('127.0.0.1', 0))
        self.sock.listen(20)
        self.url = f'http://127.0.0.1:{self.sock.getsockname()[1]}'
        self.reply = status(500)
        self.hits = []
        threading.Thread(target=self._serve, daemon=True).start()

    def _serve(self):
        while True:
            try:
                conn, _ = self.sock.accept()
            except OSError:
                return
            threading.Thread(target=self._handle, args=(conn,), daemon=True).start()

    def _handle(self, conn):
        with conn:
            request = conn.recv(65536).decode('latin-1')
            self.hits.append(request.split(' ')[1] if ' ' in request else '')
            self.reply(conn)

    def close(self):
        self.sock.close()
