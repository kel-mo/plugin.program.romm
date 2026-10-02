# -*- coding: utf-8 -*-
"""Menu tiles: a darkened game screenshot with the folder's name over it, drawn daily."""
import io
import os
import random
import re
import time
import xml.etree.ElementTree as ET
from datetime import date

import xbmcvfs

from . import kodi
from .api import ApiError

SIZE = 512                               # square, as Estuary shows folders
DIM = 0.5                                # picture brightness behind the name
SHADOW = 200                             # darkness of the halo round the name, of 255
OVER = 201                               # px: a skin's font may hint badly below this, as Estuary's does; names are drawn larger and shrunk
FOLDERS = {'platforms': 30000, 'collections': 30001, 'smart_collections': 30009, 'last_played': 30002,
           'favourites': 30003, 'backlog': 30023, 'browse': 30030, 'search': 30004, 'random': 30008}
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


SOURCES = {'favourites': (favourites, anything), 'last_played': (last_played, anything),
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


def scale(size):
    return OVER // size + 1


def font(size):
    """The skin's font at this size, as drawn larger, and the stroke that thickens a regular one."""
    from PIL import ImageFont
    file, bold = font_file()
    big = size * scale(size)
    return (ImageFont.truetype(file, big) if file else ImageFont.load_default(big)), (0 if bold else max(1, size // 24) * scale(size))


def lines(draw, label, face, stroke, limit):
    """The label as it fits the limit: one line, else two split where the longer is shortest; None if not."""
    width = lambda text: max(draw.textbbox((0, 0), t, font=face, stroke_width=stroke)[2] for t in text.split('\n'))
    words = label.split()
    tries = [label] + [' '.join(words[:i]) + '\n' + ' '.join(words[i:]) for i in range(1, len(words))]
    best = min(tries, key=lambda text: (width(text) > limit, text.count('\n'), width(text)))
    return best if width(best) <= limit else None


def text_size(labels):
    """One size for every tile, so the names match: the largest at which each fits, wrapped onto two lines if need be."""
    try:
        from PIL import Image, ImageDraw
    except ImportError:
        return SIZE // 5
    draw = ImageDraw.Draw(Image.new('L', (1, 1)))
    size = SIZE // 5
    while size > 12:
        face, stroke = font(size)
        if all(lines(draw, label, face, stroke, fit(size)) for label in labels):
            break
        size = int(size * 0.9)
    return size


def fit(size):
    """How wide a name may be as drawn: 80 % of the tile."""
    return SIZE * 0.8 * scale(size)


def text_mask(text, face, stroke, size):
    """The name centred on a tile-sized mask, drawn larger and shrunk."""
    from PIL import Image, ImageDraw
    big = SIZE * scale(size)
    mask = Image.new('L', (big, big))
    draw = ImageDraw.Draw(mask)
    left, top, right, bottom = draw.textbbox((0, 0), text, font=face, stroke_width=stroke, align='center')
    draw.text(((big - (right - left)) / 2 - left, (big - (bottom - top)) / 2 - top), text, font=face, fill=255,
              stroke_width=stroke, stroke_fill=255, align='center')
    return mask.resize((SIZE, SIZE), Image.LANCZOS)


def halo(mask, size):
    """A soft dark halo, so bright pictures stay readable: the text as drawn, widened, then blurred.
    Widened afterwards, as a thicker stroke would space wrapped lines further apart than the text's."""
    from PIL import ImageFilter
    dark = mask.point(lambda v: v * SHADOW // 255)
    return dark.filter(ImageFilter.MaxFilter(2 * (size // 12) + 1)).filter(ImageFilter.GaussianBlur(size / 6))


def render(data, label, dest, size=SIZE // 5):
    """A square crop, darkened, with the label centred; the plain picture when Kodi's Python lacks PIL."""
    tmp = dest + '.tmp'
    try:
        from PIL import Image, ImageDraw, ImageEnhance, ImageOps
    except ImportError:
        with open(tmp, 'wb') as f:
            f.write(data)
        os.replace(tmp, dest)
        return
    im = ImageOps.exif_transpose(Image.open(io.BytesIO(data))).convert('RGB')
    im = ImageEnhance.Brightness(ImageOps.fit(im, (SIZE, SIZE), Image.LANCZOS)).enhance(DIM)
    face, stroke = font(size)
    mask = text_mask(lines(ImageDraw.Draw(im), label, face, stroke, fit(size)) or label, face, stroke, size)
    im.paste((0, 0, 0), mask=halo(mask, size))
    im.paste((255, 255, 255), mask=mask)
    im.save(tmp, 'JPEG', quality=88)
    os.replace(tmp, dest)


# ------------------------------------------------------------------- refresh
def stamp():
    return os.path.join(tile_dir(), 'drawn')


def drawing(day=None):
    """What the stamp records: the day, and the version, so an update redraws at once."""
    return '{} {}'.format(day or date.today().isoformat(), kodi.ADDON_VERSION)


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
    labels = [(k, kodi.L(i)) for k, i in FOLDERS.items()]
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
            f.write(drawing(day))                         # the day it started, should it run past midnight
        tidy()
    kodi.log('tiles: drew {} of {}'.format(done, len(FOLDERS)))
    return done


def tidy():
    """Delete drawings no longer shown: all but each folder's newest, and those of tiles since dropped."""
    keep = {current(key) for key in FOLDERS} | {stamp()}
    for name in os.listdir(tile_dir()):
        if os.path.join(tile_dir(), name) not in keep:
            os.remove(os.path.join(tile_dir(), name))
    forget()


def forget():
    """Drop Kodi's cached copies of our tiles; it keeps them for a day and would never look at deleted ones again."""
    found = kodi.jsonrpc('Textures.GetTextures', properties=['url'],                 # Kodi keys plain files by path
                         filter={'field': 'url', 'operator': 'contains', 'value': '{}/tiles/'.format(kodi.ADDON_ID)})
    for t in (found or {}).get('textures') or []:
        kodi.jsonrpc('Textures.RemoveTexture', textureid=t['textureid'])

