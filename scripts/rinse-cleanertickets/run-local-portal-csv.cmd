@echo off
setlocal EnableDelayedExpansion
cd /d "%~dp0"

echo Rinse portal CSV scrape (Windows)
echo ==================================

if not exist "scrape.mjs" (
  echo ERROR: Missing scrape.mjs
  goto :fail
)

for /f "delims=" %%v in ('call pick-rinse-vendor.cmd') do set "RINSE_VENDOR=%%v"
if errorlevel 1 goto :fail

if not exist "tenants\%RINSE_VENDOR%\.env" (
  echo ERROR: Missing tenants\%RINSE_VENDOR%\.env
  echo   copy tenants\%RINSE_VENDOR%\.env.example tenants\%RINSE_VENDOR%\.env
  echo   Run save-session.cmd for %RINSE_VENDOR% first.
  goto :fail
)

set "RINSE_STORAGE_STATE=%CD%\tenants\%RINSE_VENDOR%\rinse-auth.json"
if not exist "%RINSE_STORAGE_STATE%" (
  echo ERROR: No session for %RINSE_VENDOR%. Run save-session.cmd first.
  goto :fail
)

if not exist "tenants\%RINSE_VENDOR%\TODAY" mkdir "tenants\%RINSE_VENDOR%\TODAY"
if not exist "tenants\%RINSE_VENDOR%\ARCHIVE" mkdir "tenants\%RINSE_VENDOR%\ARCHIVE"

REM Load shared .env then per-vendor .env via bash helper on Git Bash only.
REM Windows CMD: set vars from vendor .env manually or use Git Bash run-local-portal-csv.sh

for /f "usebackq tokens=1,* delims==" %%a in ("tenants\%RINSE_VENDOR%\.env") do (
  set "line=%%a"
  if not "!line:~0,1!"=="#" (
    if "%%a"=="RINSE_TICKETS_URL" set "RINSE_TICKETS_URL=%%b"
    if "%%a"=="RINSE_EMAIL" set "RINSE_EMAIL=%%b"
    if "%%a"=="RINSE_PASSWORD" set "RINSE_PASSWORD=%%b"
  )
)

if exist ".env" for /f "usebackq tokens=1,* delims==" %%a in (".env") do (
  if "%%a"=="RINSE_TICKETS_URL" if not defined RINSE_TICKETS_URL set "RINSE_TICKETS_URL=%%b"
)

REM Windows CMD: always use page-only list URL (avoid ^ / %%5E escaping from .env filters).
set "RINSE_TICKETS_URL=https://www.rinse.com/cleanertickets/?page=1"
echo RINSE_TICKETS_URL=%RINSE_TICKETS_URL%

if not exist "node_modules\" (
  call npm install
  if errorlevel 1 goto :fail
)
call npx playwright install chromium

set "RINSE_CSV_LAYOUT=portal"
if not "%~1"=="" set "RINSE_MAX_PAGES=%~1"

for /f %%d in ('powershell -NoProfile -Command "Get-Date -Format yyyy-MM-dd"') do set "TODAY=%%d"
set "OUTPUT_CSV=%CD%\tenants\%RINSE_VENDOR%\TODAY\Rinse-%TODAY%-run.csv"

echo.
echo Vendor: %RINSE_VENDOR%
echo Output: %OUTPUT_CSV%
echo.

call npm run scrape
if errorlevel 1 goto :fail

echo.
echo Done. CSV: %OUTPUT_CSV%
goto :ok

:fail
echo Finished with errors.
pause
exit /b 1

:ok
pause
exit /b 0
