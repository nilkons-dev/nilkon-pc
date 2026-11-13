@echo off
title NILKON
cd /d "%~dp0"
echo Installing required packages...
py -m pip install PySide6 python-vlc
if errorlevel 1 (
  echo Required packages failed to install. Check Python and your internet connection.
  pause
  exit /b 1
)
echo Installing optional packages (real sound-wave analysis, song tags)...
py -m pip install numpy
py -m pip install miniaudio
py -m pip install mutagen
echo Installing online packages (music engine, Discord, ffmpeg)...
py -m pip install yt-dlp
py -m pip install pypresence
py -m pip install imageio-ffmpeg
py music_player.py
if errorlevel 1 pause
