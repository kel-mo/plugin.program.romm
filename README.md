# RomM for Kodi

A Kodi add-on that browses the library of a self-hosted [RomM](https://romm.app)
server, downloads games (and their BIOS files) on demand, and plays them with
Kodi's built-in RetroPlayer and `game.libretro.*` emulator add-ons.

Think of it as the RomM desktop app or Playnite plugin, but for the TV: RomM
holds the ROMs and metadata, Kodi does the playing.

## Status

Early development (0.1.x). Working: pairing, browsing platforms, collections,
search, favourites and recently played, download with resume, multi-disc m3u
generation, zip extraction, BIOS mirroring into each core's system directory,
per-platform emulator choice, cache size limit.

Not yet: save sync, play-time reporting, activity heartbeat, Kodi add-on
repository. See the project notes for the phased plan.

## Requirements

- Kodi 22 "Piers" with the RetroPlayer fix that plays the resolved path of
  plugin items (xbmc PR pending). Without it Kodi reports the game as not
  compatible with any emulator. The Kodi flatpak beta ships all the libretro
  cores this add-on maps to.
- RomM 5.0 or newer.

## Install (sideload)

```
./build.py                      # writes dist/plugin.program.romm-<version>.zip
```

Then in Kodi: Settings > Add-ons > Install from zip file. Or, for a development
loop, copy or symlink this directory into Kodi's `addons/` folder (flatpak:
`~/.var/app/tv.kodi.Kodi/data/addons/plugin.program.romm`).

## Pairing

Open the add-on, enter the server URL in its settings, then choose "Pair with
server". Kodi shows a short code; approve it in the RomM web interface at
`/pair/device`. Alternatively generate a pairing code under RomM Settings >
Client API tokens and use "Pair with a code".

## How it works

- Games are cached under the add-on data folder (or a folder of your choice)
  as `<rom id>/<server file name>`, so Kodi save states and in-game saves,
  which are keyed by file name, survive re-downloads.
- `resources/data/platform_cores.json` maps RomM platform slugs to Kodi game
  add-ons, best first. Use the context menu on a platform to override.
- `resources/data/core_bios.json` lists BIOS files per core; firmware stored
  in RomM for a platform is copied into
  `addon_data/game.libretro.<core>/resources/system/` before launch.
- By default Kodi's own emulator and save state chooser is shown; enable
  "Always start the preferred emulator" to skip it.

## License

GPL-2.0-or-later.
