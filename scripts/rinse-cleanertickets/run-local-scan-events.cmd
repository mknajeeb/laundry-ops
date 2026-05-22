@echo off
REM Rinse scan-events export (local). Does NOT run production scrape.mjs.
cd /d "%~dp0"
if not exist .env (
  echo Missing .env — copy .env.example and run npm run save-session
  exit /b 1
)
if not exist node_modules (
  echo Installing npm dependencies...
  call npm install
)
call npx playwright install chromium
if not "%~1"=="" (
  set RINSE_MAX_PAGES=%~1
  shift
)
set "RINSE_TICKETS_URL=https://www.rinse.com/cleanertickets/?page=1"
echo RINSE_TICKETS_URL=%RINSE_TICKETS_URL%
echo Running scan-events scrape...
node scrape-scan-events.mjs
if "%~1"=="--apply" (
  for /f "delims=" %%F in ('dir /b /o-d scan-events-*.csv 2^>nul') do (
    set "LATEST_CSV=%%F"
    goto :found
  )
  :found
  if not defined LATEST_CSV (
    echo No scan-events CSV found.
    exit /b 1
  )
  cd ..\..
  python -m backend.rinse_scan_events_cli apply --csv "%~dp0%LATEST_CSV%" --json-summary
)
pause
