@echo off
setlocal
call "%~dp0windows-vs-env.cmd"
if errorlevel 1 exit /b %errorlevel%
cd /d "%~dp0..\src-tauri"
cargo check
