# -*- coding: utf-8 -*-
"""Minimal RomM REST client built on urllib (no external dependencies)."""
import hashlib
import json
import mimetypes
import os
import platform as _platform
import socket
import ssl
import time
import uuid
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

import xbmc

from . import kodi

CLIENT = 'kodi'
MIN_SERVER = (5, 0, 0)
CHUNK = 1024 * 1024
TIMEOUT = 30

# scopes we ask for during pairing; assets/devices are for save sync later
SCOPES = ['me.read', 'platforms.read', 'roms.read', 'roms.user.read', 'roms.user.write',
          'collections.read', 'collections.write', 'firmware.read', 'assets.read', 'assets.write',
          'devices.read', 'devices.write']


class ApiError(Exception):
    def __init__(self, message, status=None, detail=None):
        super().__init__(message)
        self.status = status
        self.detail = detail


class AuthError(ApiError):
    pass


def parse_version(text):
    parts = []
    for p in str(text or '0').split('.')[:3]:
        digits = ''.join(ch for ch in p if ch.isdigit())
        parts.append(int(digits or 0))
    while len(parts) < 3:
        parts.append(0)
    return tuple(parts)


_monitor = None


def aborting():
    """True once Kodi is shutting down; every request checks it so no call outlives teardown."""
    global _monitor
    if _monitor is None:
        _monitor = xbmc.Monitor()
    return _monitor.abortRequested()


class RommClient:
    def __init__(self, base_url=None, token=None, timeout=TIMEOUT):
        self.base_url = (base_url or kodi.setting('server_url')).strip().rstrip('/')
        self.token = token if token is not None else kodi.setting('token')
        self.timeout = timeout
        self.ssl_ctx = ssl.create_default_context()

    # ------------------------------------------------------------------ core
    def url(self, path, **params):
        clean = {k: v for k, v in params.items() if v is not None and v != ''}
        query = urlencode(clean, doseq=True)
        return '{}{}{}'.format(self.base_url, path, '?' + query if query else '')

    def headers(self, auth=True, extra=None):
        h = {'Accept': 'application/json',
             'User-Agent': '{}/{}'.format(kodi.ADDON_ID, kodi.ADDON_VERSION)}
        if auth and self.token:
            h['Authorization'] = 'Bearer ' + self.token
        if extra:
            h.update(extra)
        return h

    def request(self, method, path, params=None, body=None, auth=True, timeout=None, raw=False,
                files=None):
        """files: {field: (filename, bytes)} sends multipart/form-data instead of JSON."""
        if not self.base_url:
            raise ApiError(kodi.L(30601))
        if aborting():
            raise ApiError('cancelled')
        url = self.url(path, **(params or {}))
        data = None
        extra = {}
        if files:
            data, ctype = _multipart(files)
            extra['Content-Type'] = ctype
        elif body is not None:
            data = json.dumps(body).encode('utf-8')
            extra['Content-Type'] = 'application/json'
        req = Request(url, data=data, headers=self.headers(auth, extra), method=method)
        kodi.debug('{} {}'.format(method, url))
        try:
            resp = urlopen(req, timeout=timeout or self.timeout, context=self.ssl_ctx)
        except HTTPError as e:
            detail = None
            try:
                detail = json.loads(e.read().decode('utf-8', 'replace')).get('detail')
            except (ValueError, AttributeError):
                pass
            if e.code in (401, 403):
                raise AuthError(kodi.L(30615), e.code, detail)
            raise ApiError('HTTP {} for {}: {}'.format(e.code, path, detail or e.reason), e.code, detail)
        except (URLError, socket.timeout, OSError) as e:
            raise ApiError('{}: {}'.format(kodi.L(30614), e))
        if raw:
            return resp
        payload = resp.read()
        resp.close()
        if not payload:
            return None
        try:
            return json.loads(payload.decode('utf-8'))
        except ValueError:
            raise ApiError('{}: non-JSON response for {}'.format(kodi.L(30614), path))

    def get(self, path, **params):
        return self.request('GET', path, params=params)

    def delete(self, path, body=None, **params):
        return self.request('DELETE', path, params=params, body=body)

    def put(self, path, body=None, **params):
        return self.request('PUT', path, params=params, body=body if body is not None else {})

    def post(self, path, body=None, auth=True, **params):
        return self.request('POST', path, params=params, body=body if body is not None else {}, auth=auth)

    # ---------------------------------------------------------------- server
    def heartbeat(self):
        return self.request('GET', '/api/heartbeat', auth=False)

    def server_version(self):
        return parse_version(self.heartbeat().get('SYSTEM', {}).get('VERSION'))

    def me(self):
        return self.get('/api/users/me')

    # ------------------------------------------------------------- device auth
    @staticmethod
    def client_device_identifier():
        cdi = kodi.setting('client_device_identifier')
        if not cdi:
            cdi = uuid.uuid4().hex
            kodi.set_setting('client_device_identifier', cdi)
        return cdi

    def device_name(self):
        return 'Kodi on {}'.format(socket.gethostname() or _platform.node() or 'unknown')

    def device_auth_init(self):
        body = {'client_device_identifier': self.client_device_identifier(),
                'name': self.device_name(),
                'client': CLIENT,
                'platform': _platform.system().lower() or 'linux',
                'client_version': kodi.ADDON_VERSION,
                'requested_scopes': SCOPES}
        return self.post('/api/auth/device/init', body, auth=False)

    def device_auth_poll(self, device_code):
        """Returns the token payload, or one of pending / slow_down / denied."""
        try:
            return self.post('/api/auth/device/token', {'device_code': device_code}, auth=False)
        except ApiError as e:
            detail = str(e.detail or '')
            if e.status == 400 and detail in ('authorization_pending', 'slow_down'):
                return 'slow_down' if detail == 'slow_down' else 'pending'
            if (e.status == 400 and detail in ('access_denied', 'expired_token')) or e.status in (404, 410):
                return 'denied'
            raise

    def exchange_pair_code(self, code):
        return self.post('/api/client-tokens/exchange', {'code': code.strip()}, auth=False)

    # ---------------------------------------------------------------- library
    def platforms(self):
        return self.get('/api/platforms') or []

    def roms(self, offset=0, limit=100, **filters):
        params = dict(offset=offset, limit=limit, with_char_index='false',
                      with_filter_values='false', with_rom_id_index='false',
                      order_by='name', order_dir='asc')
        params.update(filters)
        page = self.get('/api/roms', **params) or {}
        return page.get('items', []), page.get('total', 0)

    def rom(self, rom_id):
        return self.get('/api/roms/{}'.format(int(rom_id)))

    def random_rom(self, **filters):
        return self.get('/api/roms/random', **filters)

    def collections(self):
        return self.get('/api/collections') or []

    def smart_collections(self):
        return self.get('/api/collections/smart') or []

    def favourites(self, create=False):
        """The user's favourites collection; RomM's web UI creates it lazily as "Favorites"."""
        user = kodi.setting('username')
        for c in self.collections():             # other users' public collections are listed too
            if c.get('is_favorite') and (c.get('owner_username') == user if user else not c.get('is_public')):
                return c
        if create:
            return self.request('POST', '/api/collections', params=dict(is_favorite='true'),
                                files={'name': (None, b'Favorites')})
        return None

    def add_to_collection(self, collection_id, rom_ids):
        return self.post('/api/collections/{}/roms'.format(int(collection_id)), {'rom_ids': list(rom_ids)})

    def remove_from_collection(self, collection_id, rom_ids):
        return self.delete('/api/collections/{}/roms'.format(int(collection_id)), {'rom_ids': list(rom_ids)})

    def update_rom_props(self, rom_id, **props):
        """props: RomUserData fields (status, backlogged, hidden, now_playing, rating, ...)."""
        return self.put('/api/roms/{}/props'.format(int(rom_id)), props)

    def firmware(self, platform_id):
        return self.get('/api/firmware', platform_id=int(platform_id)) or []

    # --------------------------------------------------------------- devices
    def device_payload(self):
        return {'name': self.device_name(), 'platform': _platform.system().lower() or 'linux',
                'client': CLIENT, 'client_version': kodi.ADDON_VERSION,
                'hostname': socket.gethostname() or None, 'sync_mode': 'api'}

    def register_device(self):
        """POST /api/devices; returns the device_id (existing device reused by fingerprint)."""
        payload = dict(self.device_payload(), allow_existing=True)
        return self.post('/api/devices', payload)['device_id']

    def update_device(self, device_id):
        return self.put('/api/devices/{}'.format(device_id), self.device_payload())

    def heartbeat_playing(self, rom_id, device_id):
        """Tell RomM this device is playing rom_id; server TTL is ~90 s, call every ~30 s."""
        return self.post('/api/activity/heartbeat', {'rom_id': int(rom_id), 'device_id': device_id})

    def heartbeat_clear(self, device_id):
        return self.delete('/api/activity/heartbeat', device_id=device_id)

    def ingest_play_sessions(self, device_id, sessions):
        """sessions: [{rom_id, save_slot, start_time (ISO 8601 UTC), end_time, duration_ms}], max 100."""
        return self.post('/api/play-sessions', {'device_id': device_id, 'sessions': sessions})

    # ------------------------------------------------------------ save sync
    def negotiate_sync(self, device_id, saves, rom_ids=None):
        """saves: [{rom_id, file_name, slot, emulator, content_hash, updated_at, file_size_bytes}]."""
        body = {'device_id': device_id, 'saves': saves}
        if rom_ids:
            body['rom_ids'] = [int(r) for r in rom_ids]
        return self.post('/api/sync/negotiate', body)

    def complete_sync(self, session_id, completed=0, failed=0, play_sessions=None):
        body = {'operations_completed': completed, 'operations_failed': failed}
        if play_sessions:
            body['play_sessions'] = play_sessions
        return self.post('/api/sync/sessions/{}/complete'.format(int(session_id)), body)

    def saves(self, rom_id=None, rom_ids=None, device_id=None, slot=None):
        return self.get('/api/saves', rom_id=rom_id, rom_ids=rom_ids, device_id=device_id, slot=slot) or []

    def upload_save(self, rom_id, file_name, data, slot=None, emulator=None, device_id=None, session_id=None,
                    overwrite=False, autocleanup=False):
        """overwrite replaces a newer server copy instead of a 409; autocleanup trims old slot versions."""
        return self.request('POST', '/api/saves',
                            params=dict(rom_id=int(rom_id), slot=slot, emulator=emulator,
                                        device_id=device_id, session_id=session_id,
                                        overwrite='true' if overwrite else None,
                                        autocleanup='true' if autocleanup else None),
                            files={'saveFile': (file_name, data)})

    def update_save(self, save_id, file_name, data, device_id=None):
        return self.request('PUT', '/api/saves/{}'.format(int(save_id)), params=dict(device_id=device_id),
                            files={'saveFile': (file_name, data)})

    def download_save(self, save_id, device_id=None, session_id=None):
        """Returns the save bytes."""
        resp = self.request('GET', '/api/saves/{}/content'.format(int(save_id)),
                            params=dict(device_id=device_id, session_id=session_id), raw=True)
        data = resp.read()
        resp.close()
        return data

    def confirm_save_downloaded(self, save_id, device_id):
        return self.post('/api/saves/{}/downloaded'.format(int(save_id)), {'device_id': device_id})

    # --------------------------------------------------------------- content
    def rom_content_url(self, rom, file_ids=None):
        name = rom.get('fs_name') or str(rom['id'])
        return self.url('/api/roms/{}/content/{}'.format(rom['id'], quote(name)),
                        file_ids=','.join(str(i) for i in file_ids) if file_ids else None)

    def rom_file_url(self, rom_file):
        return self.url('/api/roms/{}/files/content/{}'.format(rom_file['id'], quote(rom_file['file_name'])))

    def firmware_url(self, fw):
        return self.url('/api/firmware/{}/content/{}'.format(fw['id'], quote(fw['file_name'])))

    def asset_url(self, path):
        """Covers/logos: RomM returns either absolute URLs or resource paths."""
        if not path:
            return ''
        path = quote(path, safe='/:?=&%+,@')       # cover paths carry "?ts=<date with spaces>"
        if path.startswith('http://') or path.startswith('https://'):
            return path
        if path.startswith('/'):
            return self.base_url + path
        return '{}/assets/romm/resources/{}'.format(self.base_url, path)

    def download(self, url, dest, expected_size=None, progress=None):
        """Stream url to dest with resume support. progress(done, total) -> False cancels."""
        if aborting():
            raise ApiError('cancelled')
        kodi.ensure_dir(os.path.dirname(dest))
        part = dest + '.part'
        done = os.path.getsize(part) if os.path.exists(part) else 0
        if expected_size and done > expected_size:       # stale partial from a changed file
            os.remove(part)
            done = 0
        extra = {'Range': 'bytes={}-'.format(done)} if done else {}
        req = Request(url, headers=self.headers(True, extra))
        try:
            resp = urlopen(req, timeout=self.timeout, context=self.ssl_ctx)
        except HTTPError as e:
            if e.code == 416 and done and (not expected_size or done == expected_size):
                os.replace(part, dest)          # server says we already have it all
                return dest
            if e.code == 416:
                os.remove(part)
                raise ApiError('stale partial download removed, retry', e.code)
            if e.code in (401, 403):
                raise AuthError(kodi.L(30615), e.code)
            raise ApiError('HTTP {} downloading {}'.format(e.code, url), e.code)
        except (URLError, socket.timeout, OSError) as e:
            raise ApiError('{}: {}'.format(kodi.L(30614), e))
        if resp.status != 206 and done:
            done = 0                             # server ignored Range: start over
        total = expected_size
        length = resp.headers.get('Content-Length')
        if length and length.isdigit():
            total = int(length) + done
        mode = 'ab' if done else 'wb'
        last = 0
        with open(part, mode) as f:
            while True:
                chunk = resp.read(CHUNK)
                if not chunk:
                    break
                f.write(chunk)
                done += len(chunk)
                now = time.time()
                if now - last > 0.25:
                    last = now
                    if aborting() or (progress and progress(done, total) is False):
                        resp.close()
                        raise ApiError('cancelled')
        resp.close()
        os.replace(part, dest)
        return dest


def md5_file(path):
    h = hashlib.md5()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(CHUNK), b''):
            h.update(chunk)
    return h.hexdigest()


def _multipart(files):
    boundary = '----romm-kodi-' + uuid.uuid4().hex
    body = bytearray()
    for field, (filename, data) in files.items():
        if filename is None:                     # plain form field
            body += ('--{}\r\nContent-Disposition: form-data; name="{}"\r\n\r\n'
                     .format(boundary, field)).encode('utf-8')
            body += data + b'\r\n'
            continue
        ctype = mimetypes.guess_type(filename)[0] or 'application/octet-stream'
        body += ('--{}\r\nContent-Disposition: form-data; name="{}"; filename="{}"\r\n'
                 'Content-Type: {}\r\n\r\n'.format(boundary, field, filename, ctype)).encode('utf-8')
        body += data
        body += b'\r\n'
    body += '--{}--\r\n'.format(boundary).encode('utf-8')
    return bytes(body), 'multipart/form-data; boundary=' + boundary
