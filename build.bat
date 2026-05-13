@echo off
cd /d "%~dp0"
py -m buildozer android debug
pause
