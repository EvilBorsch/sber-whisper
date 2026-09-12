@echo off
setlocal

call "%~dp0windows-vs-env.cmd"
if errorlevel 1 exit /b %errorlevel%

cd /d "%~dp0.."
taskkill /IM sber-whisper.exe /F >nul 2>nul
taskkill /IM sber-whisper-sidecar.exe /F >nul 2>nul

powershell -ExecutionPolicy Bypass -File scripts/build-sidecar.ps1 -Platform windows -Variant cpu
if errorlevel 1 exit /b %errorlevel%

rem npm is npm.cmd: without `call` control never returns to this script.
call npm run tauri build -- --bundles nsis
if errorlevel 1 exit /b %errorlevel%

powershell -ExecutionPolicy Bypass -File scripts/copy-artifacts.ps1 windows
exit /b %errorlevel%
