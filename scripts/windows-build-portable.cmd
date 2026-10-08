@echo off
setlocal

call "%~dp0windows-vs-env.cmd"
if errorlevel 1 exit /b %errorlevel%

cd /d "%~dp0.."
taskkill /IM sber-whisper.exe /F >nul 2>nul
taskkill /IM sber-whisper-sidecar.exe /F >nul 2>nul

powershell -ExecutionPolicy Bypass -File scripts/build-sidecar.ps1 -Platform windows
if errorlevel 1 exit /b %errorlevel%

call npm run tauri build -- --no-bundle
if errorlevel 1 exit /b %errorlevel%

powershell -ExecutionPolicy Bypass -File scripts/package-portable.ps1
exit /b %errorlevel%
