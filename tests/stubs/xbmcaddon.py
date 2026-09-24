"""Kodi stub: settings come from the real Kodi profile (token, server), strings from strings.po."""
import os, re, tempfile
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PROFILE = os.path.join(tempfile.gettempdir(), 'romm-test-profile')
SETTINGS = {}
_S = os.path.expanduser('~/.var/app/tv.kodi.Kodi/data/userdata/addon_data/plugin.program.romm/settings.xml')
if os.path.exists(_S):
    for k, v in re.findall(r'<setting id="([^"]+)"[^>]*>([^<]*)<', open(_S).read()): SETTINGS[k] = v
SETTINGS.setdefault('sort_by', 'name')
STRINGS = {}
_P = os.path.join(ROOT, 'resources', 'language', 'resource.language.en_gb', 'strings.po')
for i, t in re.findall(r'msgctxt "#(\d+)"\nmsgid "((?:[^"\\]|\\.)*)"', open(_P).read()): STRINGS[int(i)] = t
class Addon:
    def __init__(self, id=None): pass
    def getAddonInfo(self, k): return {'id': 'plugin.program.romm', 'name': 'RomM', 'version': '0.2.0',
        'path': ROOT, 'profile': PROFILE}[k]
    def getLocalizedString(self, i): return STRINGS.get(i, '#%d' % i)
    def getSetting(self, k): return SETTINGS.get(k, '')
    def getSettingBool(self, k): return SETTINGS.get(k, 'false') == 'true'
    def getSettingInt(self, k): return int(SETTINGS.get(k) or 0)
    def setSetting(self, k, v): SETTINGS[k] = v
    def openSettings(self): pass
