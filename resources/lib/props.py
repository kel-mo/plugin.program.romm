# -*- coding: utf-8 -*-
"""Per-user RomM game properties: favourite, backlog, play status, hidden."""
import xbmc
import xbmcgui

from . import kodi
from .api import ApiError, AuthError

STATUSES = [(None, 30024), ('incomplete', 30025), ('finished', 30026), ('completed_100', 30027),
            ('retired', 30028), ('never_playing', 30029)]


def context_items(rom, favourite_ids, run_plugin):
    """Context menu entries for a listed ROM; favourite_ids is None when unknown."""
    rom_id = rom['id']
    user = rom.get('rom_user') or {}
    items = []
    if favourite_ids is not None:
        fav = rom_id in favourite_ids
        items.append((kodi.L(30018 if fav else 30017),
                      run_plugin('favourite', rom_id=rom_id, add='0' if fav else '1')))
    backlogged = bool(user.get('backlogged'))
    items.append((kodi.L(30020 if backlogged else 30019),
                  run_plugin('backlog', rom_id=rom_id, add='0' if backlogged else '1')))
    items.append((kodi.L(30021), run_plugin('status', rom_id=rom_id, current=user.get('status'))))
    items.append((kodi.L(30022), run_plugin('hide', rom_id=rom_id, name=rom.get('name'))))
    return items


def favourite_ids(client):
    try:
        fav = client.favourites()
    except ApiError as e:
        kodi.log('favourites lookup failed: {}'.format(e), xbmc.LOGWARNING)
        return None
    return set(fav.get('rom_ids') or []) if fav else set()


def _apply(change, message):
    try:
        change()
    except AuthError:
        kodi.error(kodi.L(30631))
        return
    except ApiError as e:
        kodi.log('update failed: {}'.format(e), xbmc.LOGWARNING)
        kodi.error(str(e))
        return
    kodi.notify(kodi.L(message))
    xbmc.executebuiltin('Container.Refresh')


def favourite(client, rom_id, add):
    def change():
        fav = client.favourites(create=add)
        if add:
            client.add_to_collection(fav['id'], [int(rom_id)])
        elif fav:
            client.remove_from_collection(fav['id'], [int(rom_id)])
    _apply(change, 30629 if add else 30630)


def backlog(client, rom_id, add):
    _apply(lambda: client.update_rom_props(rom_id, backlogged=add), 30633)


def status(client, rom_id, current=None):
    keys = [k for k, _ in STATUSES]
    pick = xbmcgui.Dialog().select(kodi.L(30021), [kodi.L(label) for _, label in STATUSES],
                                   preselect=keys.index(current) if current in keys else 0)
    if pick >= 0 and keys[pick] != current:
        _apply(lambda: client.update_rom_props(rom_id, status=keys[pick]), 30633)


def hide(client, rom_id, name=None):
    if xbmcgui.Dialog().yesno(kodi.ADDON_NAME, kodi.L(30632, name or rom_id)):
        _apply(lambda: client.update_rom_props(rom_id, hidden=True), 30633)
