# -*- coding: utf-8 -*-
"""Mirror RomM firmware into each candidate core's libretro system directory."""
import os
import shutil

import xbmcvfs

from . import cache, kodi


BIOS_TABLE = kodi.data_file('core_bios.json')
_table = None


def core_entry(core_id):
    global _table
    if _table is None:
        _table = kodi.read_json(BIOS_TABLE, {}) or {}
    return _table.get(core_id) or {}


def target_name(core_id, file_name):
    """Relative path inside system/ for a firmware file, honouring per-core layouts."""
    entry = core_entry(core_id)
    subdir = (entry.get('subdir') or '').replace('/', os.sep)
    for declared in list(entry.get('required') or []) + list(entry.get('optional') or []):
        if os.path.basename(declared).lower() == file_name.lower():
            declared = declared.replace('/', os.sep)
            return declared if os.sep in declared else os.path.join(subdir, declared)
    return os.path.join(subdir, file_name)


def system_dir(core_id):
    # game.libretro uses <profile>/resources/system when the profile resources dir is non-empty
    path = xbmcvfs.translatePath('special://profile/addon_data/{}/resources/system/'.format(core_id))
    return kodi.ensure_dir(path)


def mirror(client, platform, core_ids, progress=None):
    """Download platform firmware once, then copy into every core's system dir."""
    if not core_ids:
        return 0
    firmware = client.firmware(platform['id'])
    if not firmware:
        return 0
    staging = os.path.join(cache.root(), 'bios', platform.get('slug') or str(platform['id']))
    copied = 0
    for i, fw in enumerate(firmware, 1):
        if fw.get('missing_from_fs'):
            continue
        src = os.path.join(staging, fw['file_name'])
        size = fw.get('file_size_bytes') or -1
        if not (os.path.exists(src) and os.path.getsize(src) == size):
            if progress:
                progress(i, len(firmware), fw['file_name'])
            client.download(client.firmware_url(fw), src, size)
        for core_id in core_ids:
            dest = os.path.join(system_dir(core_id), target_name(core_id, fw['file_name']))
            if os.path.exists(dest) and os.path.getsize(dest) == os.path.getsize(src):
                continue
            kodi.ensure_dir(os.path.dirname(dest))
            shutil.copy2(src, dest)
            copied += 1
    return copied
