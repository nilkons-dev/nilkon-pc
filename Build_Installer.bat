@echo off
setlocal enableextensions
title NILKON - Build installer
cd /d "%~dp0"
echo Builds NILKON_Setup.exe on this PC.
echo Needs: Python 3.10+ (64-bit), VLC 64-bit and Inno Setup 6 (jrsoftware.org) installed.
echo.
where py >nul 2>nul
if errorlevel 1 (
  echo Python was not found. Install it from python.org and tick Add to PATH.
  pause
  exit /b 1
)
py -m pip install --upgrade pip
py -m pip install -r requirements.txt pyinstaller
if errorlevel 1 (
  echo Could not install the packages.
  pause
  exit /b 1
)
py build_release.py
if errorlevel 1 (
  echo Build failed. Scroll up to read the error.
  pause
  exit /b 1
)
echo.
echo Done. Your installer is in the installer_output folder.
start "" "%~dp0installer_output"
pause
