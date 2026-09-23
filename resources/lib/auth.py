# -*- coding: utf-8 -*-
"""Pairing flows: RFC 8628 style device code, or an 8-digit client token code."""
import time

import xbmc
import xbmcgui

from . import kodi, pairdialog, qr
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


def _client_or_prompt():
    """Settings buttons run before the dialog saves, so ask for the URL if it is still empty."""
    client = RommClient()
    if not client.base_url:
        url = xbmcgui.Dialog().input(kodi.L(30101), 'https://', type=xbmcgui.INPUT_ALPHANUM)
        url = (url or '').strip().rstrip('/')
        if not url or url == 'https:':
            kodi.error(kodi.L(30601))
            return None
        if not url.startswith(('http://', 'https://')):
            url = 'https://' + url
        kodi.set_setting('server_url', url)
        client = RommClient(base_url=url)
    return client


def _poll_loop(client, init, is_cancelled, on_tick):
    """Poll the token endpoint until approved, denied, expired or cancelled."""
    interval = max(int(init.get('interval') or 5), 2)
    expires_in = int(init.get('expires_in') or 600)
    deadline = time.time() + expires_in
    monitor = xbmc.Monitor()
    while time.time() < deadline:
        if is_cancelled() or monitor.abortRequested():
            return None
        on_tick(deadline - time.time())
        result = client.device_auth_poll(init['device_code'])
        if result == 'slow_down':
            interval += 5
        elif result == 'denied':
            return 'denied'
        elif isinstance(result, dict):
            return result
        for _ in range(interval * 4):
            # waitForAbort also pumps Kodi callbacks such as the dialog's onAction
            if is_cancelled() or monitor.waitForAbort(0.25):
                return None
    return 'denied'


def pair_device_code():
    client = _client_or_prompt()
    if not client:
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
    short_url = verify.split('?')[0]
    code = init.get('user_code', '')
    expires_in = int(init.get('expires_in') or 600)

    kodi.ensure_dir(kodi.PROFILE)
    qr_png = qr.make(verify, kodi.profile_file('pair-qr.png'))
    window = None
    dialog = None
    if qr_png:
        background = qr.solid(kodi.profile_file('pair-bg.png'), (0x1e, 0x1e, 0x2e))
        window = pairdialog.PairDialog(qr_png, background, short_url, code, expires_in)
        window.show()
        is_cancelled, on_tick = (lambda: window.cancelled), window.tick
    else:
        dialog = xbmcgui.DialogProgress()
        dialog.create(kodi.L(30005), '{}[CR][B]{}[/B][CR]{}'.format(kodi.L(30602, short_url), code, kodi.L(30603)))
        is_cancelled = dialog.iscanceled
        on_tick = lambda remaining: dialog.update(int(100 * remaining / expires_in))

    try:
        result = _poll_loop(client, init, is_cancelled, on_tick)
    except ApiError as e:
        kodi.log('device auth poll failed: {}'.format(e))
        result = e
    finally:
        if window:
            window.close()
            del window
        if dialog:
            dialog.close()

    if isinstance(result, dict):
        _store(client, result)
        return True
    if result is None:
        return False
    kodi.error(str(result) if isinstance(result, ApiError) else kodi.L(30622), kodi.L(30605))
    return False


def pair_with_code():
    client = _client_or_prompt()
    if not client:
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
