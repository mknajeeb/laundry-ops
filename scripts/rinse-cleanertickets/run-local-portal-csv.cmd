@echo off
setlocal
cd /d "%~dp0"

echo Rinse portal CSV scrape (local Windows)
echo See USER_LOCAL_SCRAPE.md in this folder for setup.
echo ========================================

if not exist ".env" (
  echo ERROR: Missing .env in this folder.
  echo   Copy .env.example to .env, edit RINSE_TICKETS_URL and RINSE_STORAGE_STATE.
  echo   One-time: run "npm run save-session" to create rinse-auth.json
  goto :fail
)

where node >nul 2>&1
if errorlevel 1 (
  echo ERROR: Node.js is not installed or not on PATH.
  echo   Install the LTS build from https://nodejs.org/ then open a new Command Prompt.
  goto :fail
)

if not exist "node_modules\" (
  echo Installing npm dependencies...
  call npm install
  if errorlevel 1 goto :fail
)

echo Ensuring Playwright Chromium...
call npx playwright install chromium
if errorlevel 1 goto :fail

set "RINSE_CSV_LAYOUT=portal"

if not "%~1"=="" (
  set "RINSE_MAX_PAGES=%~1"
  echo RINSE_MAX_PAGES=%RINSE_MAX_PAGES% ^(from argument^)
)

echo Running scrape...
call npm run scrape
if errorlevel 1 goto :fail

echo.
echo Done. Upload the CSV on Upload Orders ^(portal CSV to draft^), or use server import.
goto :ok

:fail
echo.
echo Finished with errors.
pause
exit /b 1

:ok
pause
exit /b 0
