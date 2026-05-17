@echo off
setlocal
cd /d "%~dp0"

echo ======================================
echo Running WashPro Rinse portal CSV scrape
echo ======================================
echo.

if not exist tenants\washpro\rinse-auth.json (
  echo ERROR: WashPro login session not found.
  echo First double-click: save-washpro-session.cmd
  echo.
  pause
  exit /b 1
)

if not exist tenants\washpro\TODAY mkdir tenants\washpro\TODAY
if not exist tenants\washpro\ARCHIVE mkdir tenants\washpro\ARCHIVE

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

set "OUTPUT_CSV=%cd%\tenants\washpro\TODAY\washpro-portal-%DATESTAMP%.csv"
set "RINSE_TICKETS_URL=https://www.rinse.com/cleanertickets/?page=1"
set "RINSE_CSV_LAYOUT=portal"
set "RINSE_STORAGE_STATE=%cd%\tenants\washpro\rinse-auth.json"

echo RINSE_TICKETS_URL=%RINSE_TICKETS_URL%

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
