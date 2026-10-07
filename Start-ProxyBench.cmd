@echo off
cd /d "%~dp0"
python main.py dashboard
if errorlevel 1 pause
