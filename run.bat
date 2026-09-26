@echo off
rem Smart Resume & Cover Letter Generator (Scale) — double-click or: run.bat [Input\file.xlsx] [--model X] [--workers N] [--redo]
cd /d "%~dp0"
python run.py %*
pause
