@echo off
call "C:\Program Files\Microsoft Visual Studio\2022\Community\Common7\Tools\VsDevCmd.bat" -arch=x64
echo LIB=%LIB%
where kernel32.lib
where link.exe
