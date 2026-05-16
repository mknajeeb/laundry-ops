@echo off
setlocal
cd /d "%~dp0"

echo ======================================
echo Saving VeeWash Rinse login session
echo ======================================
echo.

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

call npx playwright install chromium
if errorlevel 1 goto :fail

set "RINSE_STORAGE_STATE=%cd%\tenants\veewash\rinse-auth.json"
set "RINSE_TICKETS_URL=https://www.rinse.com/cleanertickets/?q=^&status=at_vendor^&page=1"

node save-session.mjs
if errorlevel 1 goto :fail

echo.
echo VeeWash session saved:
echo %cd%\tenants\veewash\rinse-auth.json
echo.
pause
exit /b 0

:fail
echo Failed.
pause
exit /b 1
