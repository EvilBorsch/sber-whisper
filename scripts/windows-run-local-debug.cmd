@echo off
setlocal

set VSDEVCMD=C:\Program Files\Microsoft Visual Studio\2022\Community\Common7\Tools\VsDevCmd.bat
if not exist "%VSDEVCMD%" (
  echo Visual Studio Developer tools not found at "%VSDEVCMD%".
  exit /b 1
)

call "%VSDEVCMD%" -arch=x64
if errorlevel 1 exit /b %errorlevel%

set PATH=%USERPROFILE%\.cargo\bin;%PATH%

where cargo >nul 2>nul
if errorlevel 1 (
  echo cargo not found in PATH. Install Rust and reopen terminal.
  exit /b 1
)

set SDK_KERNEL32=%WindowsSdkDir%Lib\%WindowsSDKLibVersion%um\x64\kernel32.lib
if not exist "%SDK_KERNEL32%" (
  echo kernel32.lib not found at "%SDK_KERNEL32%".
  echo Install Windows SDK via Visual Studio Installer.
  exit /b 1
)

cd /d d:\sber-whisper

taskkill /IM sber-whisper.exe /F >nul 2>nul
taskkill /IM sber-whisper-sidecar.exe /F >nul 2>nul

if /i "%SKIP_SIDECAR_BUILD%"=="1" (
  echo SKIP_SIDECAR_BUILD=1, using existing sidecar build.
) else (
  echo Rebuilding sidecar for local debug...
  powershell -ExecutionPolicy Bypass -File scripts/build-sidecar.ps1 -Platform windows
  if errorlevel 1 exit /b %errorlevel%
)

echo Building local debug app (no installer)...
npm run tauri build -- --debug --no-bundle
if errorlevel 1 exit /b %errorlevel%

taskkill /IM sber-whisper.exe /F >nul 2>nul
start "" src-tauri\target\debug\sber-whisper.exe

echo Local app started from src-tauri\target\debug\sber-whisper.exe
exit /b 0
