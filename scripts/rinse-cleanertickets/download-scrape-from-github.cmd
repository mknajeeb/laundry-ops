@echo off
setlocal EnableExtensions
cd /d "%~dp0"

echo Downloads full scrape.mjs from GitHub raw ^(~65 KB^).
echo Use this if scrape.mjs is only 1-2 KB ^(wrong paste / partial file^).
echo.

where powershell >nul 2>&1
if errorlevel 1 (
  echo ERROR: PowerShell not found.
  exit /b 1
)

set "OUT=%~dp0scrape.mjs"

powershell -NoProfile -ExecutionPolicy Bypass -Command "try { Invoke-WebRequest -Uri 'https://raw.githubusercontent.com/mknajeeb/laundry-ops/main/scripts/rinse-cleanertickets/scrape.mjs' -OutFile '%OUT%' -UseBasicParsing } catch { Write-Error $_; exit 1 }"
if errorlevel 1 (
  echo Download failed.
  pause
  exit /b 1
)

for %%I in ("%OUT%") do set "SZ=%%~zI"
echo Saved: %OUT%
echo Size: %SZ% bytes ^(expect about 65000-70000^)
if %SZ% LSS 20000 (
  echo.
  echo WARNING: File still looks too small. Check network / URL blocked.
  pause
  exit /b 1
)

echo.
echo OK. Run run-local-portal-csv.cmd or your batch again.
pause
exit /b 0
