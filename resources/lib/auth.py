# -*- coding: utf-8 -*-
"""Pairing flows: RFC 8628 style device code, or an 8-digit client token code."""
import time

import xbmcgui

from . import kodi
from .api import ApiError, RommClient, MIN_SERVER


def _store(client, payload):
    token = payload.get('access_token') or payload.get('raw_token')
    if not token:
        raise ApiError('no token in response: {}'.format(payload))
    kodi.set_setting('token', token)
    kodi.set_setting('device_id', payload.get('device_id') or '')
    client.token = token
    try:
        me = client.me()
        kodi.set_setting('username', me.get('username', ''))
    except ApiError:
        kodi.set_setting('username', '')
    kodi.notify(kodi.L(30604, client.base_url))


def _check_server(client):
    version = client.server_version()
    if version < MIN_SERVER:
        raise ApiError(kodi.L(30621, '.'.join(map(str, version))))


def pair_device_code():
    client = RommClient()
    if not client.base_url:
        kodi.error(kodi.L(30601))
        kodi.ADDON.openSettings()
        return False
    try:
        _check_server(client)
        init = client.device_auth_init()
    except ApiError as e:
        kodi.log('device auth init failed: {}'.format(e))
        kodi.error(str(e), kodi.L(30605))
        return False

    verify = init.get('verification_path_complete') or init.get('verification_path') or '/pair/device'
    if verify.startswith('/'):
        verify = client.base_url + verify
    code = init.get('user_code', '')
    interval = max(int(init.get('interval') or 5), 2)
    deadline = time.time() + int(init.get('expires_in') or 600)

    dialog = xbmcgui.DialogProgress()
    dialog.create(kodi.L(30005), '{}[CR][B]{}[/B][CR]{}'.format(kodi.L(30602, verify), code, kodi.L(30603)))
    try:
        while time.time() < deadline:
            if dialog.iscanceled():
                return False
            remaining = deadline - time.time()
            dialog.update(int(100 * remaining / max(int(init.get('expires_in') or 600), 1)))
            try:
                result = client.device_auth_poll(init['device_code'])
            except ApiError as e:
                kodi.log('device auth poll failed: {}'.format(e))
                kodi.error(str(e), kodi.L(30605))
                return False
            if result == 'pending':
                pass
            elif result == 'slow_down':
                interval += 5
            elif result == 'denied':
                kodi.error(kodi.L(30622), kodi.L(30605))
                return False
            elif isinstance(result, dict):
                _store(client, result)
                return True
            for _ in range(interval * 4):
                if dialog.iscanceled():
                    return False
                time.sleep(0.25)
    finally:
        dialog.close()
    kodi.error(kodi.L(30622), kodi.L(30605))
    return False


def pair_with_code():
    client = RommClient()
    if not client.base_url:
        kodi.error(kodi.L(30601))
        kodi.ADDON.openSettings()
        return False
    code = xbmcgui.Dialog().input(kodi.L(30606), type=xbmcgui.INPUT_NUMERIC)
    if not code:
        return False
    try:
        _check_server(client)
        _store(client, client.exchange_pair_code(code))
        return True
    except ApiError as e:
        kodi.log('pair code exchange failed: {}'.format(e))
        kodi.error(kodi.L(30622) if e.status in (400, 404, 410) else str(e), kodi.L(30605))
        return False


def sign_out():
    for key in ('token', 'device_id', 'username'):
        kodi.set_setting(key, '')
    kodi.notify(kodi.L(30607))


def is_paired():
    return bool(kodi.setting('server_url') and kodi.setting('token'))
