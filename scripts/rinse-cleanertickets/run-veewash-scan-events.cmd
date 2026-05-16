@echo off
setlocal
cd /d "%~dp0"

echo ======================================
echo VeeWash Rinse scan-events export
echo ======================================
echo.

if not exist tenants\veewash\rinse-auth.json (
  echo ERROR: VeeWash login session not found.
  echo First double-click: save-veewash-session.cmd
  echo.
  pause
  exit /b 1
)

if not exist tenants\veewash\TODAY mkdir tenants\veewash\TODAY
if not exist tenants\veewash\ARCHIVE mkdir tenants\veewash\ARCHIVE

where node >nul 2>&1
if errorlevel 1 (
  echo ERROR: Node.js is not installed. Install LTS from https://nodejs.org/
  pause
  exit /b 1
)

if not exist node_modules (
  echo Installing npm dependencies...
  call npm install
  if errorlevel 1 goto :fail
)

echo Ensuring Chromium is installed...
call npx playwright install chromium
if errorlevel 1 goto :fail

for /f %%i in ('powershell -NoProfile -Command "Get-Date -Format yyyy-MM-dd-HHmm"') do set "DATESTAMP=%%i"

set "OUTPUT_CSV=%cd%\tenants\veewash\TODAY\veewash-scan-events-%DATESTAMP%.csv"
set "RINSE_TICKETS_URL=https://www.rinse.com/cleanertickets/?q=^&status=at_vendor^&page=1"
set "RINSE_SCAN_OUTPUT_LAYOUT=events_only"
set "RINSE_STORAGE_STATE=%cd%\tenants\veewash\rinse-auth.json"
set "OUTPUT_SCAN_EVENTS_CSV=%OUTPUT_CSV%"
set "OUTPUT_CSV=%OUTPUT_CSV%"

node scrape-scan-events.mjs
if errorlevel 1 goto :fail

echo.
echo Done.
echo Optional: upload in Laundry Ops - Rinse Events CSV:
echo %OUTPUT_CSV%
echo Does not replace the regular portal order CSV.
echo.
pause
exit /b 0

:fail
echo Scan-events export failed.
pause
exit /b 1
