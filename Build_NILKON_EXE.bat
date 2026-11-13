@echo off
setlocal enableextensions
title NILKON - Build EXE
cd /d "%~dp0"

echo ==============================================================
echo   NILKON  -  build a Windows .exe application
echo ==============================================================
echo.
echo   [1] Folder build  - fastest start-up, recommended
echo   [2] Single file   - one NILKON.exe (starts a little slower)
echo.
choice /c 12 /n /m "Choose 1 or 2: "
if errorlevel 2 (set MODE=--onefile) else (set MODE=--onedir)

where py >nul 2>nul
if not errorlevel 1 goto haspy
echo Python was not found. Install Python 3.10 or newer from python.org and tick Add to PATH.
pause
exit /b 1
:haspy

echo.
echo [1/3] Installing required packages...
py -m pip install --upgrade pip
py -m pip install PySide6 python-vlc pyinstaller
if errorlevel 1 (
  echo Could not install the required packages. Check your internet connection.
  pause
  exit /b 1
)
echo Installing optional packages (real sound waves, song tags)...
py -m pip install numpy
py -m pip install miniaudio
py -m pip install mutagen
py -m pip install yt-dlp
py -m pip install pypresence
py -m pip install imageio-ffmpeg

set EXTRA=
py -c "import mutagen" >nul 2>nul && set EXTRA=%EXTRA% --collect-submodules mutagen
py -c "import miniaudio" >nul 2>nul && set EXTRA=%EXTRA% --collect-all miniaudio
py -c "import yt_dlp" >nul 2>nul && set EXTRA=%EXTRA% --collect-all yt_dlp
py -c "import imageio_ffmpeg" >nul 2>nul && set EXTRA=%EXTRA% --collect-all imageio_ffmpeg
py -c "import pypresence" >nul 2>nul && set EXTRA=%EXTRA% --collect-submodules pypresence

echo.
echo [2/3] Building NILKON (this takes a few minutes)...
py -m PyInstaller --noconfirm --clean --windowed %MODE% ^
  --name NILKON ^
  --icon "assets\logo.ico" ^
  --add-data "assets;assets" ^
  --hidden-import PySide6.QtSvg ^
  --exclude-module tkinter ^
  --exclude-module PySide6.QtWebEngineCore ^
  --exclude-module PySide6.QtWebEngineWidgets ^
  --exclude-module PySide6.QtQuick ^
  --exclude-module PySide6.QtQml ^
  --exclude-module PySide6.Qt3DCore ^
  --exclude-module PySide6.QtCharts ^
  --exclude-module PySide6.QtDataVisualization ^
  %EXTRA% ^
  music_player.py
if errorlevel 1 (
  echo.
  echo Build failed. Scroll up to read the error message.
  pause
  exit /b 1
)

echo.
echo [3/3] Done!
if "%MODE%"=="--onefile" goto onefile
echo   Your app:  %~dp0dist\NILKON\NILKON.exe
echo   Keep the whole NILKON folder together. You can pin NILKON.exe to the taskbar.
goto shown
:onefile
echo   Your app:  %~dp0dist\NILKON.exe
:shown
echo.
echo NOTE: VLC media player (64-bit) must be installed on the computer that runs NILKON.
echo.
choice /c YN /n /m "Open the output folder now? (Y/N) "
if errorlevel 2 goto end
start "" "%~dp0dist"
:end
endlocal
