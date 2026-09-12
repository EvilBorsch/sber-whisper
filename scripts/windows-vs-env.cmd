@echo off
rem Sets up the MSVC environment for cargo/tauri. Invoke with `call` so the variables stay in the caller.
rem Finds any Visual Studio edition (Community/Professional/Enterprise/Build Tools) via vswhere.
rem Override with VSDEVCMD=<path to VsDevCmd.bat> if needed.
rem Keep this file ASCII-only: cmd.exe misparses batch files with multibyte characters under code page 65001.

set "VSWHERE=%ProgramFiles(x86)%\Microsoft Visual Studio\Installer\vswhere.exe"
if not defined VSDEVCMD if exist "%VSWHERE%" (
  for /f "usebackq delims=" %%i in (`"%VSWHERE%" -latest -products * -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath`) do set "VSDEVCMD=%%i\Common7\Tools\VsDevCmd.bat"
)
if not defined VSDEVCMD (
  echo Visual Studio with C++ tools not found. Install "Desktop development with C++" ^(Build Tools are enough^):
  echo   winget install Microsoft.VisualStudio.2022.BuildTools --override "--quiet --wait --add Microsoft.VisualStudio.Workload.VCTools --includeRecommended"
  exit /b 1
)
if not exist "%VSDEVCMD%" (
  echo VsDevCmd.bat not found at "%VSDEVCMD%".
  exit /b 1
)

rem VsDevCmd.bat itself runs a bare `vswhere.exe` and prints "not recognized" when the Installer dir is not on PATH.
set "PATH=%ProgramFiles(x86)%\Microsoft Visual Studio\Installer;%PATH%"
call "%VSDEVCMD%" -arch=x64 -no_logo
if errorlevel 1 exit /b %errorlevel%

set "PATH=%USERPROFILE%\.cargo\bin;%PATH%"
where cargo >nul 2>nul
if errorlevel 1 (
  echo cargo not found in PATH. Install Rust: winget install Rustlang.Rustup
  exit /b 1
)

set "SDK_KERNEL32=%WindowsSdkDir%Lib\%WindowsSDKLibVersion%um\x64\kernel32.lib"
if not exist "%SDK_KERNEL32%" (
  echo kernel32.lib not found at "%SDK_KERNEL32%".
  echo Install Windows 10/11 SDK via Visual Studio Installer.
  exit /b 1
)

echo Using MSVC from "%VSDEVCMD%"
exit /b 0
