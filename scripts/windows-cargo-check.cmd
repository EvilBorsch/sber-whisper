@echo off
call "C:\Program Files\Microsoft Visual Studio\2022\Community\Common7\Tools\VsDevCmd.bat" -arch=x64
set PATH=%USERPROFILE%\.cargo\bin;%PATH%
cd /d d:\sber-whisper\src-tauri
cargo check
