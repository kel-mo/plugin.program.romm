# -*- coding: utf-8 -*-
"""Background service: tracks RetroPlayer playback of cached games for play sessions and
save sync, and draws the tiles each day. Registered in addon.xml as xbmc.service."""
import threading
import traceback
from collections import deque

import xbmc

from resources.lib import auth, cache, device, fanart, kodi, tiles
from resources.lib.api import ApiError, RommClient
from resources.lib.sessions import SERVICE_TIMEOUT, PlayTracker

TILE_START = 30                          # seconds after start before drawing tiles, so Kodi settles first
TILE_CHECK = 60                          # seconds between checks for a new day or the setting turned on
TILE_RETRY = 900                         # seconds to wait after the server gave no pictures


class GamePlayer(xbmc.Player):
    """Callbacks run on Kodi's thread: only queue events, the main loop does the I/O."""

    def __init__(self):
        super().__init__()
        self.events = deque()

    def _started(self):
        try:
            if not self.isPlayingGame():
                return
            try:
                path = self.getPlayingFile()
            except Exception:                       # RuntimeError when nothing plays any more
                return
            rom_id = cache.rom_id_for_path(path)
            if rom_id is not None:
                self.events.append(('start', rom_id))
        except Exception:
            kodi.log(traceback.format_exc(), xbmc.LOGERROR)

    def _stopped(self):
        self.events.append(('stop', None))

    def onAVStarted(self):
        self._started()

    def onPlayBackStarted(self):
        self._started()

    def onPlayBackStopped(self):
        self._stopped()

    def onPlayBackEnded(self):
        self._stopped()

    def onPlayBackError(self):
        self._stopped()


def push_saves(rom_id):
    from resources.lib import saves
    client = RommClient(timeout=SERVICE_TIMEOUT)
    try:
        rom = client.rom(rom_id)
        uploaded, downloaded = device.with_device(
            client, lambda device_id: saves.sync_rom(client, rom=rom, device_id=device_id, direction='push'))
    except ApiError as e:
        kodi.log('save sync for rom {} failed: {}'.format(rom_id, e), xbmc.LOGWARNING)
        kodi.error(kodi.L(30722))
        return
    except Exception:
        kodi.log('save sync for rom {} failed: {}'.format(rom_id, traceback.format_exc()), xbmc.LOGERROR)
        return
    if uploaded + downloaded:
        kodi.notify(kodi.L(30721, uploaded, downloaded), time=2500)


def step(player, tracker):
    if not auth.is_paired():
        player.events.clear()
        return
    if not player.events and tracker.rom_id is not None and not player.isPlayingGame():
        player.events.append(('stop', None))        # missed callback
    while player.events:
        event, rom_id = player.events.popleft()
        if event == 'start':
            tracker.start(rom_id)
            continue
        played = tracker.rom_id
        tracker.stop()
        if played is not None and kodi.setting_bool('sync_saves'):
            push_saves(played)
    tracker.tick()


def draw_tiles():
    """On its own thread, so slow fetches never hold up play tracking or save sync."""
    monitor = xbmc.Monitor()
    wait = TILE_START
    while not monitor.waitForAbort(wait):
        wait = TILE_CHECK
        url, token = kodi.fresh_setting('server_url'), kodi.fresh_setting('token')
        if url and token and tiles.due():
            try:
                if not tiles.refresh(RommClient(url, token, timeout=SERVICE_TIMEOUT), monitor):
                    wait = TILE_RETRY
            except Exception:                       # never take the service down with it
                kodi.log('tiles failed: {}'.format(traceback.format_exc()), xbmc.LOGWARNING)
                wait = TILE_RETRY


def run():
    monitor = xbmc.Monitor()
    player = GamePlayer()
    tracker = PlayTracker()
    drawer = threading.Thread(target=draw_tiles, daemon=True)
    drawer.start()
    maker = threading.Thread(target=fanart.serve, args=(monitor,), daemon=True)
    maker.start()
    kodi.log('service started')
    while not monitor.waitForAbort(1):
        try:
            step(player, tracker)
        except Exception:
            kodi.log(traceback.format_exc(), xbmc.LOGERROR)
    # Kodi is shutting down: no network from here on, only queue the open session to disk.
    # Pending uploads flush after the next game; the server-side heartbeat expires by itself.
    try:
        tracker.stop(network=False)
    except Exception:
        kodi.log(traceback.format_exc(), xbmc.LOGERROR)
    drawer.join(SERVICE_TIMEOUT)
    maker.join(SERVICE_TIMEOUT)


if __name__ == '__main__':
    run()
