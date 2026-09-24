<img src="resources/icon.png" alt="RomM for Kodi icon" width="128" align="right">

# RomM for Kodi

Play the library of your self-hosted [RomM](https://romm.app) server on Kodi.
Browse your games, and Kodi downloads each one (with its BIOS files) when you
play it, using its built-in RetroPlayer and `game.libretro.*` emulators. Saves
and play time sync back to RomM.

Needs RomM 5.0 or newer, and Kodi 22 with the RetroPlayer fix from
[xbmc#29393](https://github.com/xbmc/xbmc/pull/29393). Without that fix Kodi
says the game is not compatible with any emulator.

## Install

1. In Kodi, turn on *Settings → System → Add-ons → Unknown sources*.
2. Download the `repository.kelmo-<version>.zip` linked at the top of
   <https://kel-mo.github.io/repository.kelmo/>.
3. *Add-ons → Install from zip file* and pick that zip.
4. *Install from repository → kel-mo Add-on Repository → Game add-ons → Game
   providers → RomM → Install*.

Kodi keeps RomM up to date from the repository.

## Pair

1. Open RomM in Kodi and enter your server URL in its settings.
2. Choose *Pair with server (device code)*. Scan the QR code with your phone,
   or open `/pair/device` on your RomM server and enter the code shown.

Or create a pairing code in RomM under *Settings → Client API tokens* and use
*Pair with a code from RomM (Client API tokens)* instead.

---

GPL-2.0-or-later. Not affiliated with the RomM project.
