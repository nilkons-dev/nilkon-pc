# NILKON Music Player

Private, offline, dark black-and-blue liquid-glass music player (PySide6 + VLC).

## Run (Windows)
Recommended: Python 3.12 or 3.13 (64-bit) and VLC 64-bit.

1. Install **VLC 64-bit** (videolan.org) and **Python 3.10+**.
2. Double-click `Run_NILKON.bat`.

Optional packages: `numpy` + `miniaudio` make the sound waves follow the real song
(without them the waves are simulated); `mutagen` reads titles, artists and cover art.

## Real Windows installer (recommended)
`NILKON_Setup_<version>.exe` installs NILKON like any other program (Start menu, desktop shortcut, uninstaller). VLC is
built into the app, so nothing else needs to be installed. Build it either on GitHub (workflow `Build NILKON for Windows`,
download the artifact `NILKON-Windows`) or on your PC with `Build_Installer.bat` (needs Python, VLC 64-bit, Inno Setup 6).

## Make a Windows .exe
Double-click `Build_NILKON_EXE.bat`, choose folder build (fast start) or single file. The app appears in `dist\`, with the NILKON logo as its icon. VLC 64-bit must be installed on the PC that runs it.

## Online music
Open **Online** in the sidebar and start typing - results (songs only) appear as you type. Press play to stream; the player then keeps playing related songs automatically, like a radio. Use the ⋯ menu to add a song to any playlist or to your favourites without downloading it - those songs are there every time you open NILKON. The download button saves a song to your library for offline listening (default folder `~/Music/NILKON`, change it in Settings > Online & Discord). MP3 conversion needs ffmpeg, which `imageio-ffmpeg` provides. Only download music you are allowed to keep. If online playback stops working, press "Update music engine" in Settings.

Crash diagnostics are written to `~/.nilkon_music/crash.log`.

## Discord "Listening to"
1. discord.com/developers/applications > New Application (name it NILKON).
2. Copy the Application ID into Settings > Online & Discord.
3. Optional: Rich Presence > Art Assets > upload the logo with key `nilkon`.
Keep the Discord desktop app open.

## Features
- Multiple playlists, favorites, recently played, drag songs to reorder
- Play button on every song; ⋯ menu: rename, favorite, add to playlist, per-song equalizer, remove/delete
- Waves/spectrum/seek-bar waveform computed from the actual audio
- Settings: dark/light, colour + wave themes, built-in or custom background image, wave style, equalizer
- Remembers last song/position; Home suggests songs you play most
- Shortcuts: Space, Ctrl+←/→, Ctrl+↑/↓, Ctrl+E, Ctrl+, , Ctrl+O

Data is stored in `~/.nilkon_music`. Renaming a song changes its display name only, not the file.

## What's new in 1.7.0
- Real sound waves for online songs start within about a second of pressing play (live analysis straight from the stream).
- Paste a song link in the online search box to find that exact song.
- No more "not a bot" noise in the console: the music engine tries several clients quietly. If a song still asks for
  verification, choose your browser in Settings → Online & Discord.
- Settings: new Playback page (resume, start page, similar-songs autoplay, volume / skip steps, sleep timer),
  wave sensitivity and smoothness, window-title and pop-up options.
- Shortcuts: Alt + Left / Right skip inside a song.
- Safer library file (damaged or pruned files are kept as copies), many playback / radio fixes.

## 1.7.1 - speed
- Online songs now stream through a local buffering helper: one download ahead of the playback position, shared by the
  player and the sound waves. Songs start as soon as the first bytes arrive and do not stall mid-song while the download
  is ahead. The next song's first seconds are fetched in advance, and the first search results are prepared before you press Play.
- Search is lighter: a kept-alive connection and compressed answers; pictures are smaller, load newest-first and are
  remembered on disk (`~/.nilkon_music/img_cache`).
- Waves for local and online songs start within a fraction of a second (progressive analysis) and no longer jump when the analysis completes.
- Buttons, sliders and menus now follow the song colours.

## 1.8.0 - speed, suggestions, new title bar
- Online songs load faster: three stream lookups race in parallel, the song downloads in parallel pieces over
  kept-alive connections, and the first results are looked up in advance.
- Online page: "Made for you" suggestions - random at first, then they follow what you search, play, like and skip.
  Settings > Library > Reset listening statistics also resets this.
- New themed window bar (minimise / maximise / close) that follows the colour theme.

## 1.7.2 - connection handling
- No internet (or it drops while a song plays): NILKON waits, shows "Waiting for internet…", and continues the same song
  from the same second as soon as the connection is back. Searches and pictures that failed offline repeat by themselves.
- Songs no longer skip when the connection stops for a moment (the download keeps retrying for ~75 s).
- Play has its own lane (never waits behind searches), the same song is only looked up once, the first part of a song is
  smaller so it starts sooner on slow lines, and the music engine is warmed up when the app starts.
- When the music service asks for verification, a public relay is tried as a last resort before showing the message.
