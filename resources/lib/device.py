# -*- coding: utf-8 -*-
"""Device identity: the RomM device_id this Kodi reports and syncs as."""
import os

import xbmc

from . import kodi
from .api import ApiError

STATE = 'device.json'


def ensure_device(client):
    """Return the device_id, registering with POST /api/devices if none is stored.

    The device-code pairing flow already stores one (token bound to a Device); the
    pair-code flow does not. Persist under setting 'device_id'.
    """
    device_id = kodi.setting('device_id')
    if not device_id:
        device_id = client.register_device()
        kodi.set_setting('device_id', device_id)
        kodi.notify(kodi.L(30724, client.device_name()))
    path = kodi.profile_file(STATE)
    state = kodi.read_json(path) or {}
    if state.get('device_id') != device_id or state.get('version') != kodi.ADDON_VERSION:
        try:
            client.update_device(device_id)
            kodi.write_json(path, {'device_id': device_id, 'version': kodi.ADDON_VERSION})
        except ApiError as e:
            if e.status == 404:
                raise
            kodi.log('device update failed: {}'.format(e), xbmc.LOGWARNING)
    return device_id


def forget_device():
    """Called when the server answers 404 for our device_id; next ensure_device re-registers."""
    kodi.set_setting('device_id', '')
    try:
        os.remove(kodi.profile_file(STATE))
    except OSError:
        pass


def with_device(client, fn):
    """fn(device_id) -> result; on 404 re-register once and retry."""
    try:
        return fn(ensure_device(client))
    except ApiError as e:
        if e.status != 404:
            raise
        kodi.log('device {} unknown to server, registering again'.format(kodi.setting('device_id')))
        forget_device()
        return fn(ensure_device(client))
