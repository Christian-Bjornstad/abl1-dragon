@echo off
setlocal
set "ABL1_PROJECT=%~dp0"
call "%~dp0packaging\run.cmd" install %*
set "ABL1_EXIT=%errorlevel%"
if not "%ABL1_EXIT%"=="0" if not defined ABL1_NO_PAUSE pause
exit /b %ABL1_EXIT%
