# -*- coding: utf-8 -*-
"""Game backdrops: a screenshot composed to fit the screen, see backdrop.py. A listing queues the ones it
lacks and shows the plain screenshot meanwhile; the service makes them and refreshes the list once."""
import hashlib
import os
import traceback

import xbmc

from . import backdrop, kodi
from .api import ApiError, RommClient

KEEP = 600                               # backdrops kept, about 300 MB; the least recently listed go
BATCH = 30                               # made before the list is refreshed: the top of a page fills in first
HANDHELD = {'gb', 'gbc', 'gba', 'nds', 'nintendo-dsi', '3ds', 'psp', 'psvita', 'neo-geo-pocket', 'neo-geo-pocket-color',
            'wonderswan', 'wonderswan-color', 'lynx', 'gamegear', 'virtualboy', 'pokemon-mini', 'n-gage'}   # square pixels
LISTING = 'plugin://{}/?'.format(kodi.ADDON_ID)


def folder():
    return kodi.profile_file('backdrops')


def queue_dir():
    return os.path.join(folder(), 'queue')


def look():
    """The screenshot's look behind a list: plain, scanlines or crt."""
    return kodi.setting('backdrop_look') or 'crt'


def screenshot(rom):
    return next(iter(rom.get('merged_screenshots') or []), None)


def aspect(rom):
    """A console's picture was 4:3 on a TV; a handheld's pixels were square."""
    return None if rom.get('platform_slug') in HANDHELD else 4 / 3


def name(shot):
    return hashlib.sha1('{}:{}'.format(look(), shot).encode()).hexdigest()[:20]   # another look: another file


def path(shot):
    return os.path.join(folder(), name(shot) + '.jpg')


# ---------------------------------------------------------------- listing
def art(client, rom):
    """The backdrop when made, else the plain screenshot; None without one."""
    shot = screenshot(rom)
    if not shot:
        return None
    made = path(shot)
    if os.path.exists(made):
        os.utime(made)                                  # listed again: kept longest
        return made
    return client.asset_url(shot)


def queue(roms):
    """Ask the service for the backdrops a listing lacks."""
    wanted = {screenshot(r): aspect(r) for r in roms if screenshot(r) and not os.path.exists(path(screenshot(r)))}
    if not wanted:
        return 0
    kodi.ensure_dir(queue_dir())
    for shot, ratio in wanted.items():
        request = os.path.join(queue_dir(), name(shot) + '.json')
        if not os.path.exists(request):
            kodi.write_json(request, {'shot': shot, 'aspect': ratio, 'look': look()})
    return len(wanted)


# ---------------------------------------------------------------- service
def serve(monitor):
    """On its own thread: make what listings have queued, a page at a time, and refresh the list showing it."""
    while not monitor.waitForAbort(1):
        try:
            made = work(monitor)
            if made:
                kodi.log('backdrops: made {}{}'.format(made, ', list refreshed' if refresh() else ''))
        except Exception:                               # never take the service down with it
            kodi.log('backdrops failed: {}'.format(traceback.format_exc()), xbmc.LOGWARNING)


def work(monitor, client=None):
    """Make a batch of queued backdrops; how many were made."""
    try:
        requests = sorted((n for n in os.listdir(queue_dir()) if n.endswith('.json')),
                          key=lambda n: os.path.getmtime(os.path.join(queue_dir(), n)))[:BATCH]   # as listed
    except OSError:
        return 0
    made = 0
    for request in requests:
        if monitor.abortRequested():
            break
        file = os.path.join(queue_dir(), request)
        wanted = kodi.read_json(file) or {}
        client = client or RommClient(timeout=4)
        if wanted.get('shot') and make(client, wanted['shot'], wanted.get('aspect'), wanted.get('look')):
            made += 1
        try:
            os.remove(file)                             # done, or not worth another go until listed again
        except OSError:
            pass
    if made:
        tidy()
    return made


def make(client, shot, ratio, style):
    """Compose and keep one backdrop; False when it could not be."""
    dest = os.path.join(folder(), hashlib.sha1('{}:{}'.format(style, shot).encode()).hexdigest()[:20] + '.jpg')
    try:
        data = client.asset(shot)
        composed = backdrop.compose(data, pixel=True, aspect=ratio, look=style)
        if composed is data:                            # no PIL: nothing to keep
            return False
        with open(dest + '.tmp', 'wb') as f:
            f.write(composed)
        os.replace(dest + '.tmp', dest)
        return True
    except (ApiError, OSError, ValueError) as e:        # PIL raises OSError for unreadable pictures
        kodi.debug('backdrop for {}: {}'.format(shot, e))
        return False


def refresh():
    """Redraw a game list on screen, so it picks up the backdrops just made; the position is kept."""
    if not xbmc.getInfoLabel('Container.FolderPath').startswith(LISTING):
        return False
    xbmc.executebuiltin('Container.Refresh')
    return True


def tidy():
    files = sorted((os.path.join(folder(), n) for n in os.listdir(folder()) if n.endswith('.jpg')), key=os.path.getmtime)
    for old in files[:-KEEP]:
        os.remove(old)
