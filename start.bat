@echo off
setlocal
pushd "%~dp0"

if not exist ".env" (
  copy ".env.example" ".env" >nul
  echo Created .env from .env.example. Add your Gemini API key before starting a live run.
)

where python >nul 2>nul
if errorlevel 1 (
  echo Python 3.11+ is required.
  pause
  popd
  exit /b 1
)

python -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)"
if errorlevel 1 (
  echo Python 3.11+ is required.
  pause
  popd
  exit /b 1
)

echo Installing backend dependencies...
python -m pip install -r backend\requirements.txt
if errorlevel 1 (
  echo Backend dependency installation failed.
  pause
  popd
  exit /b 1
)

echo Starting the DevOffice PyQt6 desktop app...
python -m backend.desktop_app
if errorlevel 1 (
  echo DevOffice exited with an error.
  pause
  popd
  exit /b 1
)

popd
endlocal
