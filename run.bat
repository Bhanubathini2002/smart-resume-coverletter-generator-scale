@echo off
rem Intern / Entry-Level Resume & Cover Letter Generator — double-click or: run.bat [Input\file.xlsx] [--model X] [--workers N] [--redo]
cd /d "%~dp0"
python run.py %*
pause
