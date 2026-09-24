# -*- coding: utf-8 -*-
"""Prepare a ROM locally and hand it to RetroPlayer."""
import datetime
import os
import traceback

import xbmc
import xbmcgui
import xbmcplugin

from . import bios, cache, cores, kodi
from .api import ApiError, AuthError, RommClient


def _human(n):
    n = float(n or 0)
    for unit in ('B', 'KB', 'MB', 'GB'):
        if n < 1024:
            return '{:.0f} {}'.format(n, unit) if unit == 'B' else '{:.1f} {}'.format(n, unit)
        n /= 1024
    return '{:.1f} TB'.format(n)


def release_date(rom):
    """RomM metadatum first_release_date is epoch milliseconds."""
    ms = (rom.get('metadatum') or {}).get('first_release_date')
    if not ms:
        return None
    try:
        return datetime.datetime.fromtimestamp(int(ms) / 1000, datetime.timezone.utc).date()
    except (TypeError, ValueError, OverflowError, OSError):
        return None


class Progress:
    def __init__(self, title):
        self.dialog = xbmcgui.DialogProgress()
        self.dialog.create(title)

    def files(self, done, total, index, count, name):
        if self.dialog.iscanceled():
            return False
        pct = min(100, int(done * 100 / total)) if total else 0
        line = '{}[CR]{}'.format(name, kodi.L(30609, _human(done), _human(total)) if total else _human(done))
        if count > 1:
            line = '{}/{}  {}'.format(index, count, line)
        self.dialog.update(pct, line)
        return True

    def bios(self, index, count, name):
        self.dialog.update(0, '{}: {} ({}/{})'.format(kodi.L(30613), name, index, count))

    def text(self, msg):
        self.dialog.update(0, msg)

    def close(self):
        self.dialog.close()


def fill_game_tag(li, rom, platform_name=None, game_client=None):
    tag = li.getGameInfoTag()
    tag.setTitle(rom.get('name') or rom.get('fs_name_no_tags') or rom.get('fs_name') or '')
    tag.setPlatform(platform_name or rom.get('platform_display_name') or rom.get('platform_slug') or '')
    meta = rom.get('metadatum') or {}
    if meta.get('genres'):
        tag.setGenres([str(g) for g in meta['genres']])
    if meta.get('companies'):
        tag.setDeveloper(', '.join(str(c) for c in meta['companies'][:3]))
    if rom.get('summary'):
        tag.setOverview(rom['summary'])
    released = release_date(rom)
    if released:
        tag.setYear(released.year)
    if game_client:
        tag.setGameClient(game_client)
    return tag


def prepare(rom, client, progress, want_play=True):
    """Download, extract, mirror BIOS. Returns (launch_path, game_client or None)."""
    slug = rom.get('platform_slug')
    installed = cores.installed_clients()
    candidates = cores.candidates(slug, installed)
    if want_play and not candidates:
        hint = (cores.mapped_cores(slug) or ['game.libretro.*'])[0]
        xbmcgui.Dialog().ok(kodi.L(30611, rom.get('platform_display_name') or slug), kodi.L(30612, hint))
        return None, None

    _dir, files = cache.ensure_rom(rom, client, progress.files)
    exts = cores.extensions(slug)
    files = cache.extract_if_needed(files, exts, progress.files)
    launch_path = cache.pick_launch_file(files, exts)
    if not launch_path:
        raise ApiError(kodi.L(30623))

    if want_play and kodi.setting_bool('sync_saves'):
        _pull_saves(rom, client, progress, launch_path, installed)

    if candidates and kodi.setting_bool('sync_bios'):
        try:
            bios.mirror(client, {'id': rom['platform_id'], 'slug': slug}, candidates, progress.bios)
        except (ApiError, OSError, ValueError) as e:
            kodi.log('BIOS mirror failed: {}'.format(e))
    cache.evict(keep_rom_id=rom['id'])

    pinned = candidates[0] if candidates and kodi.setting_bool('pin_core') else None
    # a user's explicit per-platform choice always pins
    if candidates and cores.user_choices().get(cores.canonical_slug(slug)) == candidates[0]:
        pinned = candidates[0]
    return launch_path, pinned


def _pull_saves(rom, client, progress, launch_path, installed):
    try:
        from . import device, saves
        saves.sync_rom(client, rom, device.ensure_device(client), 'pull', progress=progress.text,
                       launch_path=launch_path, installed=installed)
    except Exception as e:  # never block a launch on save sync
        kodi.log('save sync before launch failed: {}'.format(e), xbmc.LOGWARNING)


def resolve(handle, rom_id):
    client = RommClient()
    progress = None
    try:
        rom = client.rom(rom_id)
        progress = Progress(kodi.L(30608, rom.get('name') or ''))
        launch_path, game_client = prepare(rom, client, progress)
        progress.close()
        progress = None
        if not launch_path:
            xbmcplugin.setResolvedUrl(handle, False, xbmcgui.ListItem())
            return
        li = xbmcgui.ListItem(rom.get('name') or os.path.basename(launch_path), path=launch_path, offscreen=True)
        fill_game_tag(li, rom, game_client=game_client)
        if rom.get('path_cover_large'):
            li.setArt({'thumb': client.asset_url(rom['path_cover_large'])})
        kodi.log('launching {} with {}'.format(launch_path, game_client or 'Kodi default'))
        # needs Kodi with RetroPlayer playing the resolved (dyn) path, see patches in tv.kodi.Kodi
        xbmcplugin.setResolvedUrl(handle, True, li)
    except AuthError as e:
        _fail(handle, progress, str(e))
    except ApiError as e:
        if str(e) != 'cancelled':
            kodi.log('play failed: {}'.format(e))
            _fail(handle, progress, str(e), kodi.L(30610))
        else:
            _fail(handle, progress, None)
    except Exception as e:  # disk, archive or unexpected server data; never leave Kodi waiting
        kodi.log(traceback.format_exc(), xbmc.LOGERROR)
        _fail(handle, progress, str(e), kodi.L(30610))


def download_only(rom_id):
    client = RommClient()
    progress = None
    try:
        rom = client.rom(rom_id)
        progress = Progress(kodi.L(30608, rom.get('name') or ''))
        prepare(rom, client, progress, want_play=False)
        progress.close()
        kodi.notify(kodi.L(30624), rom.get('name'))
    except Exception as e:
        if progress:
            progress.close()
        if str(e) != 'cancelled':
            kodi.log(traceback.format_exc(), xbmc.LOGERROR)
            kodi.error(str(e), kodi.L(30610))


def _fail(handle, progress, message, heading=None):
    if progress:
        progress.close()
    if message:
        kodi.error(message, heading)
    xbmcplugin.setResolvedUrl(handle, False, xbmcgui.ListItem())
