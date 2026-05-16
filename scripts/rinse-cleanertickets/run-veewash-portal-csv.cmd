@echo off
setlocal
cd /d "%~dp0"

echo ======================================
echo Running VeeWash Rinse portal CSV scrape
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

set "OUTPUT_CSV=%cd%\tenants\veewash\TODAY\veewash-portal-%DATESTAMP%.csv"
set "RINSE_TICKETS_URL=https://www.rinse.com/cleanertickets/?q=^&status=at_vendor^&page=1"
set "RINSE_CSV_LAYOUT=portal"
set "RINSE_STORAGE_STATE=%cd%\tenants\veewash\rinse-auth.json"

node scrape.mjs
if errorlevel 1 goto :fail

echo.
echo Done.
echo Upload this file in Laundry Ops (Rinse / CSV):
echo %OUTPUT_CSV%
echo.
pause
exit /b 0

:fail
echo Scrape failed.
pause
exit /b 1
