@echo off
setlocal EnableDelayedExpansion
cd /d "%~dp0"

if not exist "scrape.mjs" (
  echo ERROR: Missing scrape.mjs
  pause
  exit /b 1
)

for /f "delims=" %%v in ('call pick-rinse-vendor.cmd') do set "RINSE_VENDOR=%%v"
if errorlevel 1 goto :fail

if not exist "tenants\%RINSE_VENDOR%" mkdir "tenants\%RINSE_VENDOR%"

if not exist "tenants\%RINSE_VENDOR%\.env" (
  if exist "tenants\%RINSE_VENDOR%\.env.example" (
    copy "tenants\%RINSE_VENDOR%\.env.example" "tenants\%RINSE_VENDOR%\.env"
    echo Created tenants\%RINSE_VENDOR%\.env — edit email/password/URL if needed.
  )
)

set "RINSE_STORAGE_STATE=%CD%\tenants\%RINSE_VENDOR%\rinse-auth.json"

echo.
echo Saving session for %RINSE_VENDOR% ...
echo Auth file: %RINSE_STORAGE_STATE%
echo Log in with that vendor's Rinse email in the browser, then press Enter in this window.
echo.

if not exist "node_modules\" call npm install
call npx playwright install chromium

set HEADED=1
call node save-session.mjs
if errorlevel 1 goto :fail

echo Done.
pause
exit /b 0

:fail
echo Failed.
pause
exit /b 1
