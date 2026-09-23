# -*- coding: utf-8 -*-
"""Platform icons: RomM's own /assets/platforms/<slug>.ico, unpacked to PNG for Kodi."""
import os
import struct

from . import cache, kodi
from .api import ApiError

PNG_MAGIC = b'\x89PNG\r\n\x1a\n'


def _png_from_ico(data):
    """Return the largest PNG entry of an ICO, or None when entries are BMP."""
    if len(data) < 6 or data[:4] != b'\x00\x00\x01\x00':
        return None
    count = struct.unpack('<H', data[4:6])[0]
    best = None
    for i in range(count):
        entry = data[6 + i * 16:6 + (i + 1) * 16]
        if len(entry) < 16:
            break
        size, offset = struct.unpack('<II', entry[8:16])
        blob = data[offset:offset + size]
        if blob[:8] == PNG_MAGIC and (best is None or size > len(best)):
            best = blob
    return best


def platform_icon(client, platform):
    """Local PNG path for a platform, downloading RomM's icon once; else the metadata logo URL."""
    slug = platform.get('slug') or platform.get('fs_slug')
    fallback = client.asset_url(platform.get('url_logo'))
    if not slug:
        return fallback
    icon_dir = os.path.join(cache.root(), 'icons')
    png = os.path.join(icon_dir, slug + '.png')
    if os.path.exists(png):
        return png
    try:
        resp = client.request('GET', '/assets/platforms/{}.ico'.format(slug), auth=False, raw=True)
        data = resp.read()
        resp.close()
    except ApiError as e:
        kodi.debug('no platform icon for {}: {}'.format(slug, e))
        return fallback
    blob = _png_from_ico(data)
    if not blob:
        return fallback
    kodi.ensure_dir(icon_dir)
    with open(png, 'wb') as f:
        f.write(blob)
    return png
