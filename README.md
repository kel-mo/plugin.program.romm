# RomM for Kodi

A Kodi add-on that browses the library of a self-hosted [RomM](https://romm.app)
server, downloads games (and their BIOS files) on demand, and plays them with
Kodi's built-in RetroPlayer and `game.libretro.*` emulator add-ons.

Think of it as the RomM desktop app or Playnite plugin, but for the TV: RomM
holds the ROMs and metadata, Kodi does the playing.

## Status

Early development (0.2.x). Working: pairing, browsing platforms, collections,
genres, regions and play status, search, continue playing, favourites and
backlog, server-side sort order, screenshots, other versions of a game,
download with resume, multi-disc m3u generation, zip extraction, BIOS
mirroring into each core's system directory, per-platform emulator choice,
cache size limit, in-game save sync, play-time reporting and activity
heartbeat.

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

## Using the library

The context menu on a game offers details, screenshots, other versions
(regional releases RomM groups as siblings), download only, and RomM's
per-user properties: favourite, backlog, play status and hide. These are
stored on the server, so the RomM web interface and other clients see them.
Hidden games disappear from every listing; unhide them in the RomM web
interface.

Add-ons paired before 0.2.0 lack the permission to change favourites; choose
"Pair with server" again to grant it.

## Settings

| Section | Setting | What it does |
| --- | --- | --- |
| Server | RomM server URL | Base URL of the server, e.g. `https://romm.example.org`. |
| Server | Pair with server / with a code | Device-code (QR) pairing, or an 8-digit code from RomM's Client API tokens page. |
| Server | Sign out | Forget the token. |
| Playback | Start the preferred emulator without asking | Pin the best installed core (or your per-platform choice) instead of Kodi's emulator chooser. |
| Playback | Copy BIOS files from RomM | Mirror the platform's firmware into the core's system directory before launch. |
| Playback | Reset emulator choices | Forget per-platform emulator overrides. |
| Library | Games per page | Page size for game listings. |
| Library | Hide platforms without an installed emulator | Only list platforms Kodi can play. |
| Library | Sort games by | Name, release date, rating, recently added or last played (also in the context menu). |
| Saves and activity | Sync in-game saves with RomM | Pull the latest save before a game starts, push it when the game ends. Save states stay local. |
| Saves and activity | When both sides changed a save | Keep the newest, the RomM copy or the Kodi copy; the losing copy is kept as a backup. |
| Saves and activity | Report play time to RomM | Heartbeat while playing and play sessions afterwards. |
| Saves and activity | Sync saves now | Negotiate saves for every downloaded game. |
| Downloads | Download folder | Where games are cached; defaults to the add-on data folder. |
| Downloads | Keep at most | Cache size limit in GB; oldest games are evicted first. 0 disables. |
| Downloads | Delete all downloaded games | Empty the cache. |
| Advanced | Debug logging | Log every request at INFO level. |

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
