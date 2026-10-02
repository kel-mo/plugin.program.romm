# -*- coding: utf-8 -*-
"""Menu tiles: a darkened game screenshot with the folder's name over it, drawn daily."""
import io
import os
import random
import re
import time
import xml.etree.ElementTree as ET
from datetime import date

import xbmc
import xbmcgui
import xbmcvfs

from . import kodi
from .api import ApiError

SIZE = 512                               # square, as Estuary shows folders
DIM = 0.5                                # picture brightness behind the name
SHADOW = 200                             # darkness of the halo round the name, of 255
FOLDERS = {'platforms': 30000, 'collections': 30001, 'smart_collections': 30009, 'last_played': 30002,
           'favourites': 30003, 'backlog': 30023, 'browse': 30030, 'search': 30004, 'random': 30008}
FONT_DIRS = ('special://skin/fonts', 'special://home/media/Fonts', 'special://xbmc/media/Fonts')
REPAIRING = 'tiles.repairing'            # Home window property: the add-on repairing favourites, as a sister add-on may too


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


def font(size):
    """The skin's font at this size, and the stroke that thickens a regular one."""
    from PIL import ImageFont
    file, bold = font_file()
    return (ImageFont.truetype(file, size) if file else ImageFont.load_default(size)), (0 if bold else max(1, size // 24))


def lines(draw, label, face, stroke):
    """The label as it fits 80 % of the width: one line, else two split where the longer is shortest; None if not."""
    width = lambda text: max(draw.textbbox((0, 0), t, font=face, stroke_width=stroke)[2] for t in text.split('\n'))
    words = label.split()
    tries = [label] + [' '.join(words[:i]) + '\n' + ' '.join(words[i:]) for i in range(1, len(words))]
    best = min(tries, key=lambda text: (width(text) > SIZE * 0.8, text.count('\n'), width(text)))
    return best if width(best) <= SIZE * 0.8 else None


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
        if all(lines(draw, label, face, stroke) for label in labels):
            break
        size = int(size * 0.9)
    return size


def halo(xy, text, face, stroke, size):
    """A soft dark halo, so bright pictures stay readable: the text as drawn, widened, then blurred.
    Widened afterwards, as a thicker stroke would space wrapped lines further apart than the text's."""
    from PIL import Image, ImageDraw, ImageFilter
    mask = Image.new('L', (SIZE, SIZE))
    ImageDraw.Draw(mask).text(xy, text, font=face, fill=SHADOW, stroke_width=stroke, stroke_fill=SHADOW, align='center')
    return mask.filter(ImageFilter.MaxFilter(2 * (size // 12) + 1)).filter(ImageFilter.GaussianBlur(size / 6))


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
    draw = ImageDraw.Draw(im)
    face, stroke = font(size)
    text = lines(draw, label, face, stroke) or label
    left, top, right, bottom = draw.textbbox((0, 0), text, font=face, stroke_width=stroke, align='center')
    xy = ((SIZE - (right - left)) / 2 - left, (SIZE - (bottom - top)) / 2 - top)
    im.paste((0, 0, 0), mask=halo(xy, text, face, stroke, size))
    draw.text(xy, text, font=face, fill=(255, 255, 255), stroke_width=stroke, stroke_fill=(255, 255, 255), align='center')
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



# ---------------------------------------------------------------- favourites
def repair_favourites(monitor):
    """Favourites still showing a tile from before 0.2.9, pointed back at the icon through Kodi's own
    favourites, as adding one that exists removes it: each from the first on is re-added in turn, so
    they keep their order. How many were fixed."""
    home = xbmcgui.Window(10000)
    for _ in range(60):                                       # one add-on at a time
        if not home.getProperty(REPAIRING):
            break
        if monitor.waitForAbort(1):
            return 0
    home.setProperty(REPAIRING, kodi.ADDON_ID)
    try:
        return repair(favourites_list())
    finally:
        home.clearProperty(REPAIRING)


def repair(favs):
    ours = lambda f: (f.get('thumbnail') or '').startswith(tile_dir() + os.sep)
    first = next((i for i, f in enumerate(favs) if ours(f)), len(favs))
    if any(f.get('type') == 'unknown' for f in favs[first:]):   # one Kodi can't re-add: leave the order alone
        kodi.log('tiles: favourites left alone, as one after the first with a tile is of a kind Kodi cannot re-add',
                 xbmc.LOGWARNING)
        return 0
    fixed = 0
    for f in favs[first:]:
        params = {k: f[k] for k in ('type', 'title', 'window', 'windowparameter', 'path') if f.get(k)}
        kodi.jsonrpc('Favourites.AddFavourite', **params)       # removes it, as it exists
        if any(same(f, g) for g in favourites_list()):          # not matched, so a copy was added instead
            kodi.jsonrpc('Favourites.AddFavourite', **params)   # which this removes again
            kodi.log('tiles: favourite {!r} could not be re-added'.format(f.get('title')), xbmc.LOGWARNING)
            return fixed
        if ours(f):
            params['thumbnail'] = kodi.ICON
            fixed += 1
        elif f.get('thumbnail'):
            params['thumbnail'] = f['thumbnail']
        kodi.jsonrpc('Favourites.AddFavourite', **params)       # back, at the end: in order
    if fixed:
        kodi.log('tiles: pointed {} favourites back at the icon'.format(fixed))
    return fixed


def same(f, g):
    return all(f.get(k) == g.get(k) for k in ('type', 'window', 'windowparameter', 'path'))


def favourites_list():
    found = kodi.jsonrpc('Favourites.GetFavourites', properties=['thumbnail', 'window', 'windowparameter', 'path'])
    return (found or {}).get('favourites') or []
