# -*- coding: utf-8 -*-
"""Map RomM platform slugs to Kodi game.libretro.* add-ons."""
import xbmcgui

from . import kodi

TABLE_FILE = kodi.data_file('platform_cores.json')
USER_FILE = kodi.profile_file('platform_cores_user.json')

# preferred launch file types, best first
LAUNCH_PRIORITY = ['m3u', 'cue', 'chd', 'gdi', 'pbp', 'ccd', 'toc', 'rvz', 'wbfs', 'gcz', 'ciso', 'iso',
                   'img', 'bin', 'mdf', 'cdi', 'nrg', 'exe', 'elf', 'dol', 'wad', 'nds', 'gba', 'gbc', 'gb',
                   'sfc', 'smc', 'nes', 'fds', 'z64', 'n64', 'v64', 'md', 'gen', 'smd', 'sms', 'gg', 'pce',
                   'sgx', 'ws', 'wsc', 'ngp', 'ngc', 'vb', 'lnx', 'a26', 'a52', 'a78', 'j64', 'jag', 'rom',
                   'col', 'int', 'vec', 'o2', 'dsk', 'adf', 'st', 'msa', 'd64', 't64', 'tap', 'prg', 'zip',
                   '7z', 'conf', 'bat', 'com', 'pak']

_table = None


def table():
    global _table
    if _table is None:
        _table = kodi.read_json(TABLE_FILE, {}) or {}
        _table.setdefault('platforms', {})
        _table.setdefault('aliases', {})
    return _table


def canonical_slug(slug):
    slug = (slug or '').lower()
    return table()['aliases'].get(slug, slug)


def platform_entry(slug):
    return table()['platforms'].get(canonical_slug(slug))


def mapped_cores(slug):
    entry = platform_entry(slug)
    return list(entry.get('cores', [])) if entry else []


def extensions(slug):
    """Known playable extensions for a platform, or None when unknown."""
    entry = platform_entry(slug)
    exts = entry.get('extensions') if entry else None
    return set(e.lower().lstrip('.') for e in exts) if exts else None


def installed_clients():
    result = kodi.jsonrpc('Addons.GetAddons', type='kodi.gameclient', enabled=True) or {}
    return set(a['addonid'] for a in result.get('addons', []) or [])


def user_choices():
    return kodi.read_json(USER_FILE, {}) or {}


def set_user_choice(slug, core_id):
    choices = user_choices()
    slug = canonical_slug(slug)
    if core_id:
        choices[slug] = core_id
    else:
        choices.pop(slug, None)
    kodi.write_json(USER_FILE, choices)


def reset_user_choices():
    kodi.write_json(USER_FILE, {})


def candidates(slug, installed=None, choices=None):
    """Installed cores for a platform, best first. User choice wins."""
    installed = installed_clients() if installed is None else installed
    cores = [c for c in mapped_cores(slug) if c in installed]
    choice = (user_choices() if choices is None else choices).get(canonical_slug(slug))
    if choice and choice in installed:
        cores = [choice] + [c for c in cores if c != choice]
    return cores


def is_supported(slug, installed=None, choices=None):
    return bool(candidates(slug, installed, choices))


def core_label(core_id):
    result = kodi.jsonrpc('Addons.GetAddonDetails', addonid=core_id, properties=['name']) or {}
    return (result.get('addon') or {}).get('name') or core_id


def choose_for_platform(slug, platform_name=''):
    installed = installed_clients()
    cores = [c for c in mapped_cores(slug) if c in installed]
    if not cores:
        kodi.error(kodi.L(30611, platform_name or slug))
        return
    labels = [kodi.L(30013)] + [core_label(c) for c in cores]
    current = user_choices().get(canonical_slug(slug))
    preselect = cores.index(current) + 1 if current in cores else 0
    idx = xbmcgui.Dialog().select('{}: {}'.format(kodi.L(30010), platform_name or slug), labels, preselect=preselect)
    if idx < 0:
        return
    set_user_choice(slug, cores[idx - 1] if idx > 0 else None)
