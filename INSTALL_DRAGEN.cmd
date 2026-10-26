@echo off
setlocal
set "ABL1_PROJECT=%~dp0"
call "%~dp0packaging\desktop.cmd" install %*
set "DRAGEN_EXIT=%errorlevel%"
if not "%DRAGEN_EXIT%"=="0" if not defined ABL1_NO_PAUSE pause
exit /b %DRAGEN_EXIT%
