# -*- coding: utf-8 -*-
"""plugin:// router and directory listings."""
import json
import os
import traceback
from urllib.parse import parse_qsl, urlencode

import xbmc
import xbmcgui
import xbmcplugin

from . import auth, cache, cores, device, icons, kodi, launch, props
from .api import ApiError, AuthError, RommClient

BASE = 'plugin://{}/'.format(kodi.ADDON_ID)
HANDLE = -1
SORTS = [('name', 30305), ('first_release_date', 30306), ('average_rating', 30307),
         ('created_at', 30308), ('last_played', 30309)]


def url_for(action, **params):
    params['action'] = action
    return BASE + '?' + urlencode({k: v for k, v in params.items() if v is not None and v != ''})


def run_plugin(action, **params):
    return 'RunPlugin({})'.format(url_for(action, **params))


def end(succeeded=True, cache_to_disc=False):
    xbmcplugin.endOfDirectory(HANDLE, succeeded, cacheToDisc=cache_to_disc)


def folder(label, action, icon=None, art=None, context=None, **params):
    li = xbmcgui.ListItem(label, offscreen=True)
    art = dict(art or {})
    if icon:
        art.setdefault('icon', icon)
        art.setdefault('thumb', icon)
    if art:
        li.setArt(art)
    if context:
        li.addContextMenuItems(context)
    xbmcplugin.addDirectoryItem(HANDLE, url_for(action, **params), li, isFolder=True)


# ------------------------------------------------------------------ listings
def root():
    if not auth.is_paired():
        li = xbmcgui.ListItem(kodi.L(30005), offscreen=True)
        li.setArt({'icon': kodi.ICON})
        xbmcplugin.addDirectoryItem(HANDLE, url_for('pair'), li, isFolder=False)
        li = xbmcgui.ListItem(kodi.L(30007), offscreen=True)
        xbmcplugin.addDirectoryItem(HANDLE, url_for('settings'), li, isFolder=False)
        end()
        return
    folder(kodi.L(30000), 'platforms', kodi.ICON)
    folder(kodi.L(30001), 'collections', kodi.ICON)
    folder(kodi.L(30009), 'smart_collections', kodi.ICON)
    folder(kodi.L(30002), 'roms', kodi.ICON, last_played='true', order_by='last_played')
    folder(kodi.L(30003), 'roms', kodi.ICON, favorite='true')
    folder(kodi.L(30023), 'roms', kodi.ICON, statuses='backlogged')
    folder(kodi.L(30030), 'browse', kodi.ICON)
    folder(kodi.L(30004), 'search', kodi.ICON)
    li = xbmcgui.ListItem(kodi.L(30008), offscreen=True)
    li.setArt({'icon': kodi.ICON})
    xbmcplugin.addDirectoryItem(HANDLE, url_for('random'), li, isFolder=False)
    end()


def platforms(client):
    installed = cores.installed_clients()
    hide = kodi.setting_bool('hide_unsupported')
    items = sorted(client.platforms(), key=lambda p: (p.get('display_name') or p.get('name') or '').lower())
    for p in items:
        if not p.get('rom_count'):
            continue
        slug = p.get('slug') or p.get('fs_slug')
        supported = cores.is_supported(slug, installed)
        if hide and not supported:
            continue
        name = p.get('display_name') or p.get('name') or slug
        label = '{} ({})'.format(name, p['rom_count'])
        if not supported:
            label += ' ' + kodi.L(30014)
        context = [(kodi.L(30010), run_plugin('choose_core', slug=slug, name=name))]
        folder(label, 'roms', icons.platform_icon(client, p), context=context,
               platform_id=p['id'], slug=slug, name=name)
    xbmcplugin.addSortMethod(HANDLE, xbmcplugin.SORT_METHOD_NONE)
    end()


def collections(client, smart=False):
    items = client.smart_collections() if smart else client.collections()
    for c in sorted(items, key=lambda c: (c.get('name') or '').lower()):
        label = c.get('name') or str(c['id'])
        count = c.get('rom_count')
        if count is None and isinstance(c.get('rom_ids'), list):
            count = len(c['rom_ids'])
        if count is not None:
            label = '{} ({})'.format(label, count)
        covers = c.get('path_covers_large') or c.get('path_covers_small') or []
        icon = client.asset_url(c.get('path_cover_large') or c.get('path_cover_small') or c.get('url_cover')
                                or (covers[0] if covers else None))
        key = 'smart_collection_id' if smart else 'collection_id'
        folder(label, 'roms', icon, **{key: c['id'], 'name': c.get('name')})
    end()


def browse(client, kind=None):
    if not kind:
        for key, label in (('genres', 30031), ('regions', 30032), ('statuses', 30033)):
            folder(kodi.L(label), 'browse', kodi.ICON, kind=key)
    elif kind == 'statuses':
        for key, label in props.STATUSES[1:]:
            folder(kodi.L(label), 'roms', kodi.ICON, statuses=key, name=kodi.L(label))
    else:
        for value in sorted(client.rom_filters().get(kind) or [], key=str.lower):
            folder(value, 'roms', kodi.ICON, name=value, **{kind: value})
    end()


def rom_item(client, rom, installed, choices, cached_ids, favourite_ids=None, sortable=True):
    name = rom.get('name') or rom.get('fs_name_no_tags') or rom.get('fs_name')
    li = xbmcgui.ListItem(name, offscreen=True)
    launch.fill_game_tag(li, rom)
    art = {}
    cover = client.asset_url(rom.get('path_cover_large') or rom.get('url_cover'))
    if cover:
        art.update(thumb=cover, poster=cover, icon=cover)
    shots = rom.get('merged_screenshots') or []
    if shots:
        art['fanart'] = client.asset_url(shots[0])
    if art:
        li.setArt(art)
    cached = rom['id'] in cached_ids
    if cached:
        li.setLabel2(kodi.L(30624))
    li.setProperty('IsPlayable', 'true')
    li.setProperty('romm.rom_id', str(rom['id']))
    if rom.get('regions'):
        li.setProperty('romm.regions', ', '.join(rom['regions']))
    slug = rom.get('platform_slug')
    context = [(kodi.L(30012), run_plugin('details', rom_id=rom['id']))]
    if shots:
        context.append((kodi.L(30034), 'SlideShow({})'.format(url_for('screenshots', rom_id=rom['id']))))
    if not cached:
        context.append((kodi.L(30015), run_plugin('download', rom_id=rom['id'])))
    else:
        context.append((kodi.L(30011), run_plugin('remove_cache', rom_id=rom['id'])))
    if slug and cores.is_supported(slug, installed, choices):
        context.append((kodi.L(30010), run_plugin('choose_core', slug=slug,
                                                  name=rom.get('platform_display_name') or slug)))
    context += props.context_items(rom, favourite_ids, run_plugin)
    if sortable:
        context.append((kodi.L(30016), run_plugin('sort_by')))
    li.addContextMenuItems(context)
    xbmcplugin.addDirectoryItem(HANDLE, url_for('play', rom_id=rom['id']), li, isFolder=False)


def roms(client, params):
    offset = int(params.get('offset') or 0)
    limit = kodi.setting_int('page_size') or 100
    filters = {k: params[k] for k in ('platform_id', 'collection_id', 'smart_collection_id',
                                      'search_term', 'favorite', 'last_played', 'statuses', 'genres',
                                      'regions') if params.get(k)}
    if 'platform_id' in filters:
        filters['platform_ids'] = filters.pop('platform_id')
    filters['order_by'] = params.get('order_by') or kodi.setting('sort_by') or 'name'
    filters['order_dir'] = 'asc' if filters['order_by'] == 'name' else 'desc'
    items, total = client.roms(offset=offset, limit=limit, **filters)
    installed = cores.installed_clients()
    choices = cores.user_choices()
    cached_ids = cache.cached_ids()
    favourite_ids = props.favourite_ids(client)
    xbmcplugin.setContent(HANDLE, 'games')
    if params.get('name'):
        xbmcplugin.setPluginCategory(HANDLE, params['name'])
    for rom in items:
        rom_item(client, rom, installed, choices, cached_ids, favourite_ids, not params.get('order_by'))
    if offset + limit < (total or 0):
        nxt = {k: v for k, v in params.items() if k != 'action'}
        nxt['offset'] = offset + limit
        folder('{} ({}/{})'.format(kodi.L(30006), min(offset + limit, total), total), 'roms', **nxt)
    if not items:
        kodi.notify(kodi.L(30625))
    xbmcplugin.addSortMethod(HANDLE, xbmcplugin.SORT_METHOD_NONE)
    xbmcplugin.addSortMethod(HANDLE, xbmcplugin.SORT_METHOD_LABEL_IGNORE_THE)
    end()


def choose_sort():
    keys = [k for k, _ in SORTS]
    current = kodi.setting('sort_by') or 'name'
    pick = xbmcgui.Dialog().select(kodi.L(30304), [kodi.L(label) for _, label in SORTS],
                                   preselect=keys.index(current) if current in keys else 0)
    if pick >= 0:
        kodi.set_setting('sort_by', keys[pick])
        xbmc.executebuiltin('Container.Refresh')


def search(client):
    term = xbmcgui.Dialog().input(kodi.L(30004))
    end(False)
    if term:
        # the failed search node isn't in history, so Back from the results returns to root
        xbmc.executebuiltin('Container.Update({})'.format(url_for('roms', search_term=term, name=term)))


def random_game(client):
    rom = client.random_rom()
    if rom:
        xbmc.executebuiltin('PlayMedia({})'.format(url_for('play', rom_id=rom['id'])))


def details(client, rom_id):
    rom = client.rom(rom_id)
    lines = [rom.get('name') or '', rom.get('platform_display_name') or rom.get('platform_slug') or '', '']
    meta = rom.get('metadatum') or {}
    released = launch.release_date(rom)
    if released:
        lines.append(released.isoformat())
    if meta.get('genres'):
        lines.append(', '.join(map(str, meta['genres'])))
    if meta.get('companies'):
        lines.append(', '.join(map(str, meta['companies'])))
    if meta.get('player_count'):
        lines.append(kodi.L(30634, meta['player_count']))
    if meta.get('average_rating'):
        lines.append(kodi.L(30635, float(meta['average_rating'])))
    if rom.get('regions'):
        lines.append(', '.join(rom['regions']))
    lines.append('{} ({})'.format(rom.get('fs_name'), launch._human(rom.get('fs_size_bytes'))))
    if rom.get('summary'):
        lines += ['', rom['summary']]
    xbmcgui.Dialog().textviewer(kodi.L(30012), '\n'.join(lines))


def screenshots(client, rom_id):
    rom = client.rom(rom_id)
    xbmcplugin.setContent(HANDLE, 'images')
    for shot in rom.get('merged_screenshots') or []:
        url = client.asset_url(shot)
        li = xbmcgui.ListItem(os.path.basename(shot), path=url, offscreen=True)
        li.setArt({'thumb': url})
        xbmcplugin.addDirectoryItem(HANDLE, url, li, isFolder=False)
    end()


def sync_now(client):
    from . import saves
    progress = xbmcgui.DialogProgress()
    progress.create(kodi.L(30720))
    try:
        uploaded, downloaded = device.with_device(
            client, lambda device_id: saves.sync_all(client, device_id, lambda msg: progress.update(0, msg)))
    except (NotImplementedError, ApiError) as e:
        kodi.log('save sync failed: {}'.format(e), xbmc.LOGWARNING)
        kodi.error(kodi.L(30722))
        return
    finally:
        progress.close()
    kodi.notify(kodi.L(30721, uploaded, downloaded))


# --------------------------------------------------------------------- main
def run(argv):
    global HANDLE
    HANDLE = int(argv[1])
    params = dict(parse_qsl(argv[2].lstrip('?')))
    action = params.get('action', 'root')
    kodi.debug('action={} params={}'.format(action, json.dumps(params)))

    # actions that need no server
    if action == 'root':
        return root()
    if action == 'pair':
        return auth.pair_device_code()
    if action == 'pair_code':
        return auth.pair_with_code()
    if action == 'signout':
        auth.sign_out()
        return xbmc.executebuiltin('Container.Refresh')
    if action == 'settings':
        return kodi.ADDON.openSettings()
    if action == 'choose_core':
        cores.choose_for_platform(params.get('slug'), params.get('name'))
        return xbmc.executebuiltin('Container.Refresh')
    if action == 'sort_by':
        return choose_sort()
    if action == 'reset_cores':
        cores.reset_user_choices()
        return kodi.notify(kodi.L(30619))
    if action == 'clear_cache':
        if xbmcgui.Dialog().yesno(kodi.ADDON_NAME, kodi.L(30616)):
            cache.clear()
            kodi.notify(kodi.L(30617))
        return
    if action == 'remove_cache':
        cache.remove(params['rom_id'])
        kodi.notify(kodi.L(30618))
        return xbmc.executebuiltin('Container.Refresh')

    if not auth.is_paired():
        if action == 'play':
            xbmcplugin.setResolvedUrl(HANDLE, False, xbmcgui.ListItem())
        kodi.error(kodi.L(30600))
        return end(False)

    if action == 'play':
        return launch.resolve(HANDLE, params['rom_id'])
    if action == 'download':
        return launch.download_only(params['rom_id'])

    try:
        dispatch(action, params)
    except AuthError as e:
        kodi.error(str(e))
        end(False)
    except ApiError as e:
        kodi.log('request failed: {}'.format(e), xbmc.LOGERROR)
        kodi.error(str(e))
        end(False)
    except Exception as e:  # keep Kodi from waiting on a listing that never ends
        kodi.log(traceback.format_exc(), xbmc.LOGERROR)
        kodi.error(str(e))
        end(False)


def dispatch(action, params):
    client = RommClient()
    if action == 'platforms':
        platforms(client)
    elif action == 'collections':
        collections(client)
    elif action == 'smart_collections':
        collections(client, smart=True)
    elif action == 'roms':
        roms(client, params)
    elif action == 'browse':
        browse(client, params.get('kind'))
    elif action == 'search':
        search(client)
    elif action == 'random':
        random_game(client)
    elif action == 'details':
        details(client, params['rom_id'])
    elif action == 'screenshots':
        screenshots(client, params['rom_id'])
    elif action == 'sync_now':
        sync_now(client)
    elif action == 'favourite':
        props.favourite(client, params['rom_id'], params.get('add') == '1')
    elif action == 'backlog':
        props.backlog(client, params['rom_id'], params.get('add') == '1')
    elif action == 'status':
        props.status(client, params['rom_id'], params.get('current'))
    elif action == 'hide':
        props.hide(client, params['rom_id'], params.get('name'))
    else:
        kodi.log('unknown action {}'.format(action), xbmc.LOGWARNING)
        end(False)
