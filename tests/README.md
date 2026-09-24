# Offline tests

`stubs/` replaces Kodi's `xbmc*` modules so the add-on can run outside Kodi. Settings (server
URL, token) are read from the flatpak Kodi profile; the add-on profile is a temp directory.

```
PYTHONPATH=tests/stubs:. python3 -c 'from resources.lib import plugin; \
    plugin.run(["plugin://x/", "1", "?action=browse"])'
```

Listed items are in `xbmcplugin.ITEMS`, dialogs answer from `xbmcgui.ANSWERS`. Actions run
against the live server: stick to read-only ones unless you revert what you change.
