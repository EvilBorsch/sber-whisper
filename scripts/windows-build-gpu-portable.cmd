@echo off
setlocal

call "%~dp0windows-vs-env.cmd"
if errorlevel 1 exit /b %errorlevel%

cd /d "%~dp0.."
taskkill /IM sber-whisper.exe /F >nul 2>nul
taskkill /IM sber-whisper-sidecar.exe /F >nul 2>nul

powershell -ExecutionPolicy Bypass -File scripts/build-sidecar.ps1 -Platform windows -Variant gpu
if errorlevel 1 exit /b %errorlevel%

rem The GPU sidecar with CUDA libraries is ~4.4 GB and NSIS cannot build installers above 2 GB
rem (makensis: "error mmapping file ... is out of range"), so the GPU variant is portable-only.
call npm run tauri build -- --no-bundle
if errorlevel 1 exit /b %errorlevel%

powershell -ExecutionPolicy Bypass -File scripts/package-portable.ps1
exit /b %errorlevel%
