# -*- coding: utf-8 -*-
"""Local download cache: <root>/<rom_id>/<files>, plus BIOS mirror under <root>/bios."""
import os
import re
import shutil
import time
import zipfile

import xbmcvfs

from . import kodi
from .cores import LAUNCH_PRIORITY

MARKER = '.romm.json'
ARCHIVE_EXTS = {'zip'}
SKIP_CATEGORIES = {'manual', 'walkthrough', 'patch', 'cheat', 'soundtrack', 'screenshot'}


def root():
    path = os.path.expanduser(xbmcvfs.translatePath(kodi.setting('cache_path').strip()))
    if '://' in path:                                    # network VFS: plain file I/O can't use it
        kodi.log('cache_path {} is not a local folder, using the add-on data folder'.format(path))
        path = ''
    if not path:
        path = os.path.join(kodi.PROFILE, 'cache')
    return kodi.ensure_dir(os.path.normpath(path))


def safe_join(base, *parts):
    """Join server-supplied names under base, refusing anything that escapes it."""
    base = os.path.normpath(base)
    path = os.path.normpath(os.path.join(base, *parts))
    if path != base and not path.startswith(base + os.sep):
        raise ValueError('unsafe path from server: {}'.format(os.path.join(*parts)))
    return path


def rom_dir(rom_id):
    return os.path.join(root(), str(int(rom_id)))


def marker_path(rom_id):
    return os.path.join(rom_dir(rom_id), MARKER)


def is_cached(rom_id):
    return os.path.exists(marker_path(rom_id))


def cached_ids():
    base = root()
    return set(int(n) for n in os.listdir(base) if n.isdigit() and os.path.exists(os.path.join(base, n, MARKER)))


def _ext(name):
    return os.path.splitext(name)[1].lstrip('.').lower()


def _game_files(rom):
    files = [f for f in (rom.get('files') or []) if (f.get('category') or 'game') not in SKIP_CATEGORIES]
    return files


def _relative_name(rom, rom_file):
    base = (rom.get('full_path') or '').rstrip('/') + '/'
    full = rom_file.get('full_path') or ''
    if base and full.startswith(base) and rom.get('has_multiple_files'):
        return full[len(base):]
    return rom_file['file_name']


def ensure_rom(rom, client, progress=None):
    """Download every game file of a ROM. Returns (directory, [local paths])."""
    rid = rom['id']
    directory = rom_dir(rid)
    marker = kodi.read_json(marker_path(rid))
    if marker and marker.get('fs_name') == rom.get('fs_name') and all(os.path.exists(p) for p in marker.get('files', [])):
        _touch(rid)
        return directory, marker['files']

    kodi.ensure_dir(directory)
    files = _game_files(rom)
    local = []
    if rom.get('has_multiple_files') and files:
        subdir = os.path.join(directory, rom.get('fs_name_no_ext') or rom.get('fs_name') or 'game')
        total = len(files)
        for i, f in enumerate(files, 1):
            dest = safe_join(subdir, _relative_name(rom, f).replace('/', os.sep))
            if not (os.path.exists(dest) and os.path.getsize(dest) == (f.get('file_size_bytes') or -1)):
                client.download(client.rom_file_url(f), dest, f.get('file_size_bytes'),
                                progress and (lambda d, t, i=i, n=f['file_name']: progress(d, t, i, total, n)))
            local.append(dest)
    else:
        name = rom.get('fs_name') or (files[0]['file_name'] if files else str(rid))
        dest = safe_join(directory, name)
        size = rom.get('fs_size_bytes')
        if not (os.path.exists(dest) and size and os.path.getsize(dest) == size):
            url = client.rom_file_url(files[0]) if len(files) == 1 else client.rom_content_url(rom)
            client.download(url, dest, size, progress and (lambda d, t: progress(d, t, 1, 1, name)))
        local.append(dest)

    kodi.write_json(marker_path(rid), {
        'rom_id': rid, 'fs_name': rom.get('fs_name'), 'name': rom.get('name'),
        'platform_slug': rom.get('platform_slug'), 'files': local, 'downloaded': int(time.time())})
    return directory, local


def extract_if_needed(local_files, supported_exts, progress=None):
    """Unpack a single zip when no candidate core reads archives directly."""
    if len(local_files) != 1 or _ext(local_files[0]) not in ARCHIVE_EXTS:
        return local_files
    if supported_exts and 'zip' in supported_exts:
        return local_files
    archive = local_files[0]
    target = os.path.splitext(archive)[0]
    if os.path.isdir(target) and os.listdir(target):
        return _walk(target)
    if progress:
        progress(0, 1, 1, 1, os.path.basename(archive))
    with zipfile.ZipFile(archive) as z:
        for member in z.infolist():
            # guard against path traversal
            dest = os.path.normpath(os.path.join(target, member.filename))
            if not dest.startswith(os.path.normpath(target) + os.sep) and dest != os.path.normpath(target):
                continue
            z.extract(member, target)
    extracted = _walk(target)
    if extracted:
        os.remove(archive)
        marker = kodi.read_json(os.path.join(os.path.dirname(archive), MARKER))
        if marker:
            marker['files'] = extracted
            kodi.write_json(os.path.join(os.path.dirname(archive), MARKER), marker)
    return extracted or local_files


def _walk(directory):
    out = []
    for base, _dirs, names in os.walk(directory):
        out.extend(os.path.join(base, n) for n in names if not n.startswith('.'))
    return sorted(out)


def pick_launch_file(local_files, supported_exts=None):
    """Choose the file to hand to RetroPlayer, writing an .m3u for multi-disc sets."""
    if not local_files:
        return None
    if len(local_files) == 1:
        return local_files[0]
    by_ext = {}
    for f in local_files:
        by_ext.setdefault(_ext(f), []).append(f)
    if by_ext.get('m3u'):
        return sorted(by_ext['m3u'])[0]
    discs = by_ext.get('cue') or by_ext.get('chd') or by_ext.get('gdi') or by_ext.get('pbp') or []
    if len(discs) > 1:
        return write_m3u(discs)
    for ext in LAUNCH_PRIORITY:
        if by_ext.get(ext) and (not supported_exts or ext in supported_exts):
            return sorted(by_ext[ext])[0]
    if supported_exts:
        for f in local_files:
            if _ext(f) in supported_exts:
                return f
    return max(local_files, key=os.path.getsize)


def _natural(name):
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r'(\d+)', name)]


def write_m3u(discs):
    discs = sorted(discs, key=_natural)
    directory = os.path.dirname(discs[0])
    prefix = os.path.commonprefix([os.path.splitext(os.path.basename(d))[0] for d in discs])
    base = re.sub(r'[\s(\[\-_]*(disc|disk|cd|side)?[\s(\[\-_]*$', '', prefix, flags=re.I) or 'game'
    path = os.path.join(directory, base + '.m3u')
    with open(path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(os.path.relpath(d, directory) for d in discs) + '\n')
    return path


def _touch(rom_id):
    try:
        os.utime(marker_path(rom_id), None)
    except OSError:
        pass


def dir_size(path):
    total = 0
    for base, _dirs, names in os.walk(path):
        for n in names:
            try:
                total += os.path.getsize(os.path.join(base, n))
            except OSError:
                pass
    return total


def entries():
    out = []
    for name in os.listdir(root()):
        if not name.isdigit():
            continue
        marker = os.path.join(root(), name, MARKER)
        if os.path.exists(marker):
            out.append((os.path.getmtime(marker), int(name)))
    return sorted(out)


def remove(rom_id):
    shutil.rmtree(rom_dir(rom_id), ignore_errors=True)


def evict(keep_rom_id=None):
    limit = kodi.setting_int('cache_limit_gb') * 1024 ** 3
    if limit <= 0:
        return
    size = dir_size(root())
    for _mtime, rid in entries():
        if size <= limit:
            break
        if rid == keep_rom_id:
            continue
        size -= dir_size(rom_dir(rid))
        kodi.log('evicting rom {} from cache'.format(rid))
        remove(rid)


def clear():
    for name in os.listdir(root()):
        path = os.path.join(root(), name)
        if os.path.isdir(path):
            shutil.rmtree(path, ignore_errors=True)
        else:
            os.remove(path)
