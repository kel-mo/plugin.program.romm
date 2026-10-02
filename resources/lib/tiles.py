# -*- coding: utf-8 -*-
"""Menu and favourites tiles: a darkened game screenshot with the add-on's or a folder's name over it, drawn daily."""
import html
import io
import os
import random
import re
import time
import xml.etree.ElementTree as ET
from datetime import date
from urllib.parse import parse_qsl, quote
from xml.sax.saxutils import escape

import xbmcvfs

from . import kodi
from .api import ApiError

SIZE = 512                               # square, as Estuary shows favourites
DIM = 0.5                                # picture brightness behind the name
SHADOW = 200                             # darkness of the halo round the name, of 255
ROOT = 'romm'                            # the add-on's own tile
FOLDERS = {'platforms': (30000, {'action': 'platforms'}), 'collections': (30001, {'action': 'collections'}),
           'smart_collections': (30009, {'action': 'smart_collections'}),
           'last_played': (30002, {'action': 'roms', 'last_played': 'true', 'order_by': 'last_played'}),
           'favourites': (30003, {'action': 'roms', 'favorite': 'true'}),
           'backlog': (30023, {'action': 'roms', 'statuses': 'backlogged'}),
           'browse': (30030, {'action': 'browse'}), 'search': (30004, {'action': 'search'}),
           'random': (30008, {'action': 'random'})}    # label, and the menu's plugin:// query
FONT_DIRS = ('special://skin/fonts', 'special://home/media/Fonts', 'special://xbmc/media/Fonts')


def tile_dir():
    return os.path.join(kodi.PROFILE, 'tiles')


def drawn(key):
    """Every drawing of a tile, oldest first; each has its own name, as Kodi keeps showing a file it has loaded."""
    try:
        names = os.listdir(tile_dir())
    except OSError:
        return []
    return sorted(os.path.join(tile_dir(), n) for n in names if re.fullmatch(re.escape(key) + r'-\d+\.jpg', n))


def current(key):
    found = drawn(key)
    return found[-1] if found else None


def art(key):
    """The tile when there is one, else the add-on icon."""
    tile = current(key)
    return tile if tile and kodi.setting_bool('tiles') else kodi.ICON


# ------------------------------------------------------------------- games
def picture(rom):
    """A screenshot, else the box art: its path on the server, or None."""
    paths = (rom.get('merged_screenshots') or []) + [rom.get('path_cover_large')]
    return next((p for p in paths if p and p.startswith('/')), None)


def favourites(client):
    fav = client.favourites()
    return client.roms(limit=50, collection_id=fav['id'])[0] if fav else []


def anything(client):
    """Games from a random place in the library."""
    total = client.roms(limit=1)[1]
    return client.roms(offset=random.randrange(max(total - 50, 0) + 1), limit=50)[0] if total else []


def last_played(client):
    """The game played last that has a picture."""
    found = client.roms(limit=10, last_played='true', order_by='last_played', order_dir='desc')[0]
    return next(([r] for r in found if picture(r)), [])


def backlog(client):
    return client.roms(limit=50, statuses='backlogged')[0]


SOURCES = {ROOT: (favourites, anything), 'favourites': (favourites, anything), 'last_played': (last_played, anything),
           'backlog': (backlog, anything)}                  # the rest: anything


def pick(client, key, day, skip=()):
    """A game for the tile from the first source with one no other tile shows, else a shared one;
    the same one all day where it can."""
    rnd = random.Random('{}:{}'.format(day, key))
    spare = None
    for source in SOURCES.get(key, (anything,)):
        try:
            found = sorted((r for r in source(client) if picture(r)), key=lambda r: r['id'])
        except ApiError as e:
            kodi.debug('tile {}: {} failed: {}'.format(key, source.__name__, e))
            continue
        fresh = [r for r in found if r['id'] not in skip]
        if fresh:
            return rnd.choice(fresh)
        spare = spare or found
    return rnd.choice(spare) if spare else None


# ----------------------------------------------------------------- drawing
def font_file():
    """The current skin's font, bold if it ships one: (path or None, bold)."""
    skin = xbmcvfs.translatePath('special://skin/')
    fonts = []
    for sub in sorted(os.listdir(skin)) if os.path.isdir(skin) else []:
        try:
            sets = ET.parse(os.path.join(skin, sub, 'Font.xml')).getroot().findall('fontset')
        except (ET.ParseError, OSError):
            continue
        chosen = next((s for s in sets if s.get('id', '').lower() == 'default'), sets[0] if sets else None)
        if chosen is not None:
            fonts = [(f.findtext('name') or '', f.findtext('filename') or '') for f in chosen.iter('font')]
            break
    files = [fn for _, fn in fonts if fn]
    tries = [(fn, True) for fn in files if re.search('bold|black|heavy', fn, re.I)]
    tries += [(fn, False) for name, fn in fonts if name == 'font13' and fn] + [(fn, False) for fn in files]
    for fn, bold in tries + [('arial.ttf', False)]:
        for d in FONT_DIRS:
            found = os.path.join(xbmcvfs.translatePath(d), fn)
            if os.path.isfile(found):
                return found, bold
    return None, False


def font(size):
    """The skin's font at this size, and the stroke that thickens a regular one."""
    from PIL import ImageFont
    file, bold = font_file()
    return (ImageFont.truetype(file, size) if file else ImageFont.load_default(size)), (0 if bold else max(1, size // 24))


def text_size(labels):
    """One size for every tile, so the names match: the largest at which the longest fits 80 % of the width."""
    try:
        from PIL import Image, ImageDraw
    except ImportError:
        return SIZE // 5
    draw = ImageDraw.Draw(Image.new('L', (1, 1)))
    size = SIZE // 5
    while size > 12:
        face, stroke = font(size)
        widest = max(draw.textbbox((0, 0), label, font=face, stroke_width=stroke)[2] for label in labels)
        if widest <= SIZE * 0.8:
            break
        size = int(size * 0.9)
    return size


def render(data, label, dest, size=SIZE // 5):
    """A square crop, darkened, with the label centred; the plain picture when Kodi's Python lacks PIL."""
    tmp = dest + '.tmp'
    try:
        from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageOps
    except ImportError:
        with open(tmp, 'wb') as f:
            f.write(data)
        os.replace(tmp, dest)
        return
    im = ImageOps.exif_transpose(Image.open(io.BytesIO(data))).convert('RGB')
    im = ImageEnhance.Brightness(ImageOps.fit(im, (SIZE, SIZE), Image.LANCZOS)).enhance(DIM)
    draw = ImageDraw.Draw(im)
    face, stroke = font(size)
    left, top, right, bottom = draw.textbbox((0, 0), label, font=face, stroke_width=stroke)
    xy = ((SIZE - (right - left)) / 2 - left, (SIZE - (bottom - top)) / 2 - top)
    shadow = Image.new('L', im.size)                        # a soft dark halo, so bright pictures stay readable
    ImageDraw.Draw(shadow).text(xy, label, font=face, fill=SHADOW, stroke_width=stroke + size // 12, stroke_fill=SHADOW)
    im.paste((0, 0, 0), mask=shadow.filter(ImageFilter.GaussianBlur(size / 6)))
    draw.text(xy, label, font=face, fill=(255, 255, 255), stroke_width=stroke, stroke_fill=(255, 255, 255))
    im.save(tmp, 'JPEG', quality=88)
    os.replace(tmp, dest)


# ------------------------------------------------------------------- refresh
def stamp():
    return os.path.join(tile_dir(), 'drawn')


def drawing():
    """What the stamp records: the day, and the version, so an update redraws at once."""
    return '{} {}'.format(date.today().isoformat(), kodi.ADDON_VERSION)


def due():
    """Tiles on and not yet drawn today by this version."""
    if kodi.fresh_setting('tiles') != 'true':
        return False
    try:
        with open(stamp()) as f:
            return f.read().strip() != drawing()
    except OSError:
        return True


def refresh(client, monitor):
    """Draw every tile anew and drop old drawings; how many were drawn."""
    kodi.ensure_dir(tile_dir())
    day = date.today().isoformat()
    name = int(time.time())
    done, used = 0, set()
    # folders first, so Continue playing keeps the last game; the add-on's own tile takes what is left
    labels = [(k, kodi.L(i)) for k, (i, _) in FOLDERS.items()] + [(ROOT, kodi.L(30037))]   # favourites name the add-on beside it
    if not all(label for _, label in labels):           # Kodi has this version's strings only after a restart
        kodi.debug('tiles: names not loaded yet')
        return 0
    size = text_size([label for _, label in labels])
    for key, label in labels:
        if monitor.abortRequested():
            return done
        rom = pick(client, key, day, used)
        if rom is None:
            continue
        used.add(rom['id'])
        try:
            render(client.asset(picture(rom)), label, os.path.join(tile_dir(), '{}-{}.jpg'.format(key, name)), size)
            done += 1
        except (ApiError, OSError, ValueError) as e:        # PIL raises OSError for unreadable images
            kodi.debug('tile {}: {}'.format(key, e))
    if done:
        with open(stamp(), 'w') as f:
            f.write(drawing())
        tidy()
    kodi.log('tiles: drew {} of {}'.format(done, len(FOLDERS) + 1))
    return done


def tidy():
    """Delete drawings no longer shown: all but the newest, unless a favourite still points at it."""
    keep = set(favourite_thumbs())
    for key in [ROOT] + list(FOLDERS):
        for old in drawn(key)[:-1]:
            if old not in keep:
                os.remove(old)
    forget()


def forget():
    """Drop Kodi's cached copies of our tiles; it keeps them for a day and would never look at deleted ones again."""
    tag = quote('{}/tiles/'.format(kodi.ADDON_ID), safe='').replace('%2F', '%2f')   # as Kodi writes image:// paths
    found = kodi.jsonrpc('Textures.GetTextures', properties=['url'], filter={'field': 'url', 'operator': 'contains',
                                                                              'value': tag})
    for t in (found or {}).get('textures') or []:
        kodi.jsonrpc('Textures.RemoveTexture', textureid=t['textureid'])


# ---------------------------------------------------------------- favourites
def target(command):
    """The tile for a favourite opening this add-on, at its root or a top-level folder; None for others."""
    command = html.unescape(command)
    if re.search(r'RunAddon\(\s*"?{}"?\s*\)'.format(re.escape(kodi.ADDON_ID)), command):
        return ROOT
    found = re.search(r'plugin://{}/?(?:\?([^"),]*))?["),]'.format(re.escape(kodi.ADDON_ID)), command)
    if not found:
        return None
    query = dict(parse_qsl(found.group(1) or ''))
    return next((k for k, (_, q) in FOLDERS.items() if q == query), None) if query else ROOT


def favourites_file():
    return xbmcvfs.translatePath('special://profile/favourites.xml')


def favourite_thumbs():
    try:
        with open(favourites_file(), encoding='utf-8') as f:
            return [html.unescape(t) for t in re.findall(r'<favourite\b[^>]*\bthumb="([^"]*)"', f.read())]
    except OSError:
        return []


def point_favourites():
    """Kodi reads favourites.xml only at start: on the way out, point ours at their tiles, or back at the icon."""
    fav = favourites_file()
    try:
        with open(fav, encoding='utf-8') as f:
            text = f.read()
    except OSError:
        return
    on = kodi.fresh_setting('tiles') == 'true'

    def thumb(m):
        key = target(m.group(2))
        found = re.search(r'thumb="([^"]*)"', m.group(1))
        if key is None or not found or html.unescape(found.group(1)) not in [kodi.ICON] + drawn(key):
            return m.group(0)                       # not ours, or a picture someone chose
        want = current(key) if on and current(key) else kodi.ICON
        return m.group(0).replace(found.group(0), 'thumb="{}"'.format(escape(want, {'"': '&quot;'})), 1)

    new = re.sub(r'(<favourite\b[^>]*>)(.*?)</favourite>', thumb, text, flags=re.S)
    if new != text:
        with open(fav + '.tmp', 'w', encoding='utf-8') as f:
            f.write(new)
        os.replace(fav + '.tmp', fav)
        kodi.log('tiles: pointed favourites at {}'.format('tiles' if on else 'the icon'))
