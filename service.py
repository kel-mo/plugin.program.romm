# -*- coding: utf-8 -*-
"""Background service: tracks RetroPlayer playback of cached games for play sessions and
save sync. Registered in addon.xml as xbmc.python.service."""
import traceback
from collections import deque

import xbmc

from resources.lib import auth, cache, device, kodi
from resources.lib.api import ApiError, RommClient
from resources.lib.sessions import PlayTracker


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
    client = RommClient()
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


def run():
    monitor = xbmc.Monitor()
    player = GamePlayer()
    tracker = PlayTracker()
    kodi.log('service started')
    while not monitor.waitForAbort(1):
        try:
            step(player, tracker)
        except Exception:
            kodi.log(traceback.format_exc(), xbmc.LOGERROR)
    try:
        if auth.is_paired() and tracker.rom_id is not None:
            tracker.stop()                          # queues the session, clears heartbeat, flushes
        elif auth.is_paired():
            tracker.flush()
    except Exception:
        kodi.log(traceback.format_exc(), xbmc.LOGERROR)


if __name__ == '__main__':
    run()
