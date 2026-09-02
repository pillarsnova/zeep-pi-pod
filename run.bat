@echo off
rem ZEEP Pod dashboard - one-command bootstrap for Windows:  run.bat
rem Options via env:  set PORT=8080  ·  set SKIP_MUSIC=1  ·  set API_TOKEN=xxx
cd /d "%~dp0"

where python >nul 2>nul
if errorlevel 1 (
  echo [error] Please install Python 3 from python.org first
  exit /b 1
)

if not exist .venv (
  echo [setup] creating virtualenv...
  python -m venv .venv
)
call .venv\Scripts\activate.bat
pip install -q --disable-pip-version-check -r requirements.txt

if not "%SKIP_MUSIC%"=="1" (
  if not exist music\*.wav (
    echo [setup] generating brainwave tracks - one time, ~1 minute...
    python generate_brainwaves.py --minutes 10
  )
)

where ffplay >nul 2>nul
if errorlevel 1 (
  where mpv >nul 2>nul
  if errorlevel 1 (
    echo [warn] no audio player found - install mpv or ffmpeg to enable sound playback
  )
)

if "%PORT%"=="" set PORT=8000
echo [run] open from a browser:  http://localhost:%PORT%
python app.py
