@echo off
setlocal
set "ABL1_FELLES_SCRIPT=%~dp0check_python_felles.py"
call "%~dp0packaging\felles.cmd"
exit /b %errorlevel%
