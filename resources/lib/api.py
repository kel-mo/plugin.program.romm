# -*- coding: utf-8 -*-
"""Minimal RomM REST client built on urllib (no external dependencies)."""
import json
import os
import platform as _platform
import socket
import ssl
import time
import uuid
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

from . import kodi

CLIENT = 'kodi'
MIN_SERVER = (5, 0, 0)
CHUNK = 1024 * 1024
TIMEOUT = 30

# scopes we ask for during pairing; assets/devices are for save sync later
SCOPES = ['me.read', 'platforms.read', 'roms.read', 'roms.user.read', 'roms.user.write',
          'collections.read', 'firmware.read', 'assets.read', 'assets.write',
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


class RommClient:
    def __init__(self, base_url=None, token=None):
        self.base_url = (base_url or kodi.setting('server_url')).strip().rstrip('/')
        self.token = token if token is not None else kodi.setting('token')
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

    def request(self, method, path, params=None, body=None, auth=True, raw=False, timeout=TIMEOUT):
        if not self.base_url:
            raise ApiError(kodi.L(30601))
        url = self.url(path, **(params or {}))
        data = None
        extra = {}
        if body is not None:
            data = json.dumps(body).encode('utf-8')
            extra['Content-Type'] = 'application/json'
        req = Request(url, data=data, headers=self.headers(auth, extra), method=method)
        kodi.debug('{} {}'.format(method, url))
        try:
            resp = urlopen(req, timeout=timeout, context=self.ssl_ctx)
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
        return json.loads(payload.decode('utf-8'))

    def get(self, path, **params):
        return self.request('GET', path, params=params)

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
            if e.status in (400, 404, 410) and detail in ('access_denied', 'expired_token') or e.status in (404, 410):
                return 'denied'
            raise

    def exchange_pair_code(self, code):
        return self.post('/api/client-tokens/exchange', {'code': code.strip()}, auth=False)

    # ---------------------------------------------------------------- library
    def platforms(self):
        return self.get('/api/platforms') or []

    def platform(self, platform_id):
        return self.get('/api/platforms/{}'.format(int(platform_id)))

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

    def firmware(self, platform_id):
        return self.get('/api/firmware', platform_id=int(platform_id)) or []

    def update_rom_user(self, rom_id, **props):
        return self.request('PUT', '/api/roms/{}/props'.format(int(rom_id)), body=props)

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
        kodi.ensure_dir(os.path.dirname(dest))
        part = dest + '.part'
        done = os.path.getsize(part) if os.path.exists(part) else 0
        extra = {'Range': 'bytes={}-'.format(done)} if done else {}
        req = Request(url, headers=self.headers(True, extra))
        try:
            resp = urlopen(req, timeout=TIMEOUT, context=self.ssl_ctx)
        except HTTPError as e:
            if e.code == 416 and done:          # server says we already have it all
                os.replace(part, dest)
                return dest
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
                if progress and now - last > 0.25:
                    last = now
                    if progress(done, total) is False:
                        resp.close()
                        raise ApiError('cancelled')
        resp.close()
        os.replace(part, dest)
        return dest
