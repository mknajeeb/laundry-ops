@echo off
setlocal EnableDelayedExpansion
cd /d "%~dp0"
if not "%RINSE_VENDOR%"=="" (
  echo %RINSE_VENDOR%
  exit /b 0
)
echo.
echo Which Rinse vendor?
echo   1) WashPro
echo   2) VeeWash
echo.
set /p PICK="Enter 1 or 2: "
if "!PICK!"=="1" (
  echo washpro
  exit /b 0
)
if "!PICK!"=="2" (
  echo veewash
  exit /b 0
)
if /i "!PICK!"=="washpro" (
  echo washpro
  exit /b 0
)
if /i "!PICK!"=="veewash" (
  echo veewash
  exit /b 0
)
echo Invalid choice.
exit /b 1
