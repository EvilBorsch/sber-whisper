@echo off
setlocal

call "%~dp0windows-vs-env.cmd"
if errorlevel 1 exit /b %errorlevel%

cd /d "%~dp0.."
taskkill /IM sber-whisper.exe /F >nul 2>nul
taskkill /IM sber-whisper-sidecar.exe /F >nul 2>nul

if /i "%SKIP_SIDECAR_BUILD%"=="1" (
  echo SKIP_SIDECAR_BUILD=1, using existing sidecar build.
) else (
  if "%SIDECAR_VARIANT%"=="" set SIDECAR_VARIANT=cpu
  echo Rebuilding sidecar for local debug...
  powershell -ExecutionPolicy Bypass -File scripts/build-sidecar.ps1 -Platform windows -Variant %SIDECAR_VARIANT%
  if errorlevel 1 exit /b %errorlevel%
)

echo Building local debug app (no installer)...
rem npm is npm.cmd: without `call` control never returns here and the app is never started.
call npm run tauri build -- --debug --no-bundle
if errorlevel 1 exit /b %errorlevel%

taskkill /IM sber-whisper.exe /F >nul 2>nul
start "" src-tauri\target\debug\sber-whisper.exe

echo Local app started from src-tauri\target\debug\sber-whisper.exe
exit /b 0
