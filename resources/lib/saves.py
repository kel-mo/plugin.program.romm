# -*- coding: utf-8 -*-
"""In-game save sync with RomM (slot "autosave"); Kodi save states are never synced."""
import os
import shutil
from datetime import datetime, timezone

import xbmcvfs

from . import cache, cores, kodi
from .api import ApiError, AuthError, md5_file

SLOT = 'autosave'
EXTS = ('srm', 'sav', 'rtc', 'eep', 'fla', 'mpk', 'sra', 'dsv', 'mcr', 'mcd', 'brm', 'nv')
SIDE_EXTS = {'rtc'}                                   # companions of the SRAM file, one save per slot
TABLE_FILE = kodi.data_file('core_saves.json')
STATE_FILE = kodi.profile_file('saves_state.json')
KODI_EXT = '.sav'

_table = None


def core_entry(core_id):
    global _table
    if _table is None:
        _table = kodi.read_json(TABLE_FILE, {}) or {}
    return _table.get(core_id)


def savestates_dir():
    # ProfileManager::GetSavestatesFolder: profile folder when it has its own databases, else master
    for special in ('special://profile/Savestates/', 'special://masterprofile/Savestates/'):
        path = xbmcvfs.translatePath(special)
        if os.path.isdir(path):
            return path
    return xbmcvfs.translatePath('special://profile/Savestates/')


def kodi_dir():
    return os.path.join(savestates_dir(), 'InGameSaves')


def core_dir(core_id):
    # game.libretro: <addon profile>/save (LibretroResources.cpp)
    return xbmcvfs.translatePath('special://profile/addon_data/{}/save/'.format(core_id))


def _exts(core_id):
    ext = (core_entry(core_id) or {}).get('ext')
    return ((ext,) if ext and ext not in EXTS else ()) + EXTS


def _iso(ts):
    return datetime.fromtimestamp(ts, timezone.utc).isoformat()


def _ts(text):
    if not text:
        return None
    try:
        dt = datetime.fromisoformat(str(text).replace('Z', '+00:00'))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.timestamp()


def launch_file(rom):
    marker = cache.marker(rom['id']) or {}
    files = marker.get('files') or []
    return cache.pick_launch_file(files, cores.extensions(rom.get('platform_slug'))) if files else None


def local_files(launch_path, core_ids):
    """Existing save files for a launch file: [(path, upload name)], Kodi's own first."""
    name = os.path.basename(launch_path)
    stem = os.path.splitext(name)[0]
    out = []
    path = os.path.join(kodi_dir(), name + KODI_EXT)
    if os.path.isfile(path):
        out.append((path, stem + '.srm'))              # raw SRAM, same bytes as RetroArch .srm
    for core_id in core_ids:
        if (core_entry(core_id) or {}).get('multi'):
            kodi.debug('saves: {} keeps folder saves, skipped'.format(core_id))
            continue
        base = core_dir(core_id)
        for ext in _exts(core_id):
            path = os.path.join(base, stem + '.' + ext)
            if os.path.isdir(path):
                kodi.log('saves: skipping folder save {}'.format(path))
            elif os.path.isfile(path) and ext not in SIDE_EXTS:
                out.append((path, os.path.basename(path)))
    return out


def target(launch_path, core_ids):
    """Where a download goes when this device has no save file yet, or None."""
    name = os.path.basename(launch_path)
    stem = os.path.splitext(name)[0]
    for core_id in core_ids:
        entry = core_entry(core_id)
        if entry is None:
            base = core_dir(core_id)
            found = [e for e in _exts(core_id) if os.path.isfile(os.path.join(base, stem + '.' + e))]
            entry = {'mode': 'core', 'ext': found[0]} if found else {'mode': 'kodi'}
        if entry.get('multi') or entry.get('mode') == 'none':
            continue
        if entry.get('mode') == 'core':
            return os.path.join(core_dir(core_id), stem + '.' + (entry.get('ext') or 'srm'))
        return os.path.join(kodi_dir(), name + KODI_EXT)
    return None


def _state():
    return kodi.read_json(STATE_FILE, {}) or {}


def _held(rom_id, save_id=None, clear=False):
    """Slot version this run opened, so repeated pushes rewrite it instead of adding versions."""
    state = _state()
    key = str(rom_id)
    if clear or save_id:
        if save_id:
            state[key] = save_id
        else:
            state.pop(key, None)
        kodi.write_json(STATE_FILE, state)
    return state.get(key)


def _upload(client, rom, path, name, slot, device_id, session_id, overwrite=False, op=None):
    with open(path, 'rb') as f:
        data = f.read()
    if not data:
        kodi.log('saves: not uploading empty {}'.format(path))
        return False
    rid = rom['id']
    if slot is None:
        client.upload_save(rid, name, data, None, None, device_id, session_id)
        return True
    held = _held(rid)
    if held and op and op.get('save_id') == held:
        try:
            client.update_save(held, name, data, device_id)
            return True
        except AuthError:
            raise
        except ApiError as e:
            if e.status != 404:
                raise
    # emulator omitted so the web player finds the same save
    saved = client.upload_save(rid, name, data, slot, None, device_id, session_id,
                               overwrite=overwrite, autocleanup=True) or {}
    if saved.get('id'):
        _held(rid, saved['id'])
    return True


def _archive(client, rom, path, name, device_id, session_id):
    """Preserve a losing local copy as an archival (null slot) save unless RomM already has it."""
    if not os.path.isfile(path) or not os.path.getsize(path):
        return
    digest = md5_file(path)
    if any(s.get('content_hash') == digest for s in client.saves(rom_id=rom['id'])):
        return
    stem, ext = os.path.splitext(name)
    stamp = datetime.now(timezone.utc).strftime('%Y-%m-%d %H-%M-%S')
    _upload(client, rom, path, '{} [{}]{}'.format(stem, stamp, ext), None, device_id, session_id)


def _download(client, op, dest, device_id, session_id):
    data = client.download_save(op['save_id'], device_id, session_id)
    if not data:
        kodi.log('saves: server copy of {} is empty, not written'.format(op.get('file_name')))
        return False
    kodi.ensure_dir(os.path.dirname(dest))
    if os.path.isfile(dest):
        shutil.copy2(dest, dest + '.bak')
    tmp = dest + '.part'
    with open(tmp, 'wb') as f:
        f.write(data)
    os.replace(tmp, dest)
    ts = _ts(op.get('server_updated_at'))
    if ts:
        os.utime(dest, (ts, ts))
    client.confirm_save_downloaded(op['save_id'], device_id)
    return True


def _server_wins(op, local_path):
    policy = kodi.setting('conflict_policy') or 'newest'
    if policy == 'server':
        return True
    if policy == 'kodi':
        return False
    server_ts = _ts(op.get('server_updated_at'))
    return server_ts is None or os.path.getmtime(local_path) <= server_ts


def sync_rom(client, rom, device_id, direction, progress=None, *, launch_path=None, installed=None):
    """Negotiate and apply save operations for one ROM.

    rom: DetailedRomSchema dict (needs id, fs_name, platform_slug).
    direction: 'pull' before launch (apply downloads only) or 'push' after playback
    (uploads, downloads and conflicts).
    Returns (uploaded, downloaded) counts. Raises ApiError on server failure.
    """
    rid = rom['id']
    launch_path = launch_path or launch_file(rom)
    if not launch_path:
        kodi.debug('saves: rom {} is not cached, nothing to sync'.format(rid))
        return 0, 0
    title = rom.get('name') or rom.get('fs_name') or str(rid)
    if progress:
        progress('{}: {}'.format(kodi.L(30720), title))
    core_ids = cores.candidates(rom.get('platform_slug'), installed)
    found = local_files(launch_path, core_ids)
    usable = [(p, n) for p, n in found if os.path.getsize(p)]
    local = max(usable, key=lambda f: os.path.getmtime(f[0])) if usable else None
    if len(usable) > 1:
        kodi.log('saves: several saves for {}, using newest {}'.format(title, local[0]))
    entries = []
    if local:
        entries.append({'rom_id': rid, 'file_name': local[1], 'slot': SLOT, 'content_hash': md5_file(local[0]),
                        'updated_at': _iso(os.path.getmtime(local[0])),
                        'file_size_bytes': os.path.getsize(local[0])})
    if direction == 'pull':
        _held(rid, clear=True)                         # new run, new slot version
    result = client.negotiate_sync(device_id, entries, [rid]) or {}
    session_id = result.get('session_id')
    dest = local[0] if local else (found[0][0] if found else target(launch_path, core_ids))
    name = local[1] if local else os.path.splitext(os.path.basename(launch_path))[0] + '.srm'
    uploaded = downloaded = done = failed = 0
    for op in result.get('operations') or []:
        if op.get('rom_id') != rid or op.get('slot') != SLOT:
            continue
        action = op.get('action')
        try:
            if action == 'upload' and local and direction == 'push':
                if _upload(client, rom, local[0], name, SLOT, device_id, session_id, op=op):
                    uploaded += 1
            elif action == 'download' and op.get('save_id'):
                if not dest:
                    kodi.log('saves: no save location for {} with {}'.format(title, core_ids or 'no core'))
                    continue
                if local:
                    _archive(client, rom, local[0], name, device_id, session_id)
                if _download(client, op, dest, device_id, session_id):
                    downloaded += 1
            elif action == 'conflict' and local and op.get('save_id'):
                if _server_wins(op, local[0]):
                    _archive(client, rom, local[0], name, device_id, session_id)
                    if _download(client, op, dest, device_id, session_id):
                        downloaded += 1
                    kodi.notify(kodi.L(30723, title, 'RomM'))
                elif direction == 'push':
                    # RomM keeps the older slot version, so the server copy survives
                    if _upload(client, rom, local[0], name, SLOT, device_id, session_id, overwrite=True):
                        uploaded += 1
                    kodi.notify(kodi.L(30723, title, 'Kodi'))
                else:
                    kodi.log('saves: conflict for {}, keeping local copy until playback ends'.format(title))
                    continue
            else:
                continue
            done += 1
        except AuthError:
            raise
        except (ApiError, OSError) as e:
            failed += 1
            kodi.log('saves: {} failed for {}: {}'.format(action, title, e))
    if session_id:
        client.complete_sync(session_id, done, failed)
    kodi.log('saves: {} {}: {} uploaded, {} downloaded, {} failed'.format(direction, title, uploaded,
                                                                          downloaded, failed))
    return uploaded, downloaded


def sync_all(client, device_id, progress=None):
    """Negotiate every cached ROM, one at a time (settings button "Sync saves now")."""
    installed = cores.installed_clients()
    uploaded = downloaded = 0
    for rid in sorted(cache.cached_ids()):
        marker = cache.marker(rid) or {}
        rom = {'id': rid, 'name': marker.get('name'), 'fs_name': marker.get('fs_name'),
               'platform_slug': marker.get('platform_slug')}
        try:
            up, down = sync_rom(client, rom, device_id, 'push', progress, installed=installed)
        except AuthError:
            raise
        except (ApiError, OSError) as e:
            kodi.log('saves: sync failed for rom {}: {}'.format(rid, e))
            continue
        uploaded += up
        downloaded += down
    return uploaded, downloaded
