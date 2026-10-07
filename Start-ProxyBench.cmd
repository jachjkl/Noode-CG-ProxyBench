@echo off
cd /d "%~dp0"
python main.py dashboard --auto-start
if errorlevel 1 pause
