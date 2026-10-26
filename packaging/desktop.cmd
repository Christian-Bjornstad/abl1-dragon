@echo off
setlocal
chcp 65001 >nul
if not defined ABL1_IVANTI set "ABL1_IVANTI=C:\Program Files (x86)\Ivanti\Workspace Control\pwrgate.exe"
if /i "%~1"=="start" goto action_ok
if /i "%~1"=="install" goto action_ok
echo Ukjent DRAGEN-handling. 1>&2
exit /b 1
:action_ok
set "ABL1_FELLES_SCRIPT=%ABL1_PROJECT%%~1.py"
if not exist "%ABL1_FELLES_SCRIPT%" goto missing
if /i "%DRAGEN_LOCAL_PYTHON%"=="1" goto local_python
if not exist "%ABL1_IVANTI%" goto local_python
if not "%~2"=="" goto unsupported_arguments
if not defined ABL1_IVANTI_APP_ID set "ABL1_IVANTI_APP_ID=15694"
powershell.exe -NoProfile -Command "$ErrorActionPreference='Stop'; $p=(Resolve-Path -LiteralPath $env:ABL1_FELLES_SCRIPT).Path; $b=[Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($p)); Set-Clipboard -Value ('import runpy,base64; runpy.run_path(base64.b64decode('''+$b+''').decode(''utf-8''),run_name=''dragen_felles'')[''main'']()')"
if errorlevel 1 goto clipboard_failed
start "" "%ABL1_IVANTI%" "%ABL1_IVANTI_APP_ID%"
if errorlevel 1 exit /b 1
echo Python FELLES aapnes. Lim inn med Ctrl+V og trykk Enter.
if /i "%~1"=="install" echo Lukk Python FELLES etter installasjon. Bruk deretter START_DRAGEN.cmd.
if not defined ABL1_NO_PAUSE pause
exit /b 0
:local_python
call "%ABL1_PROJECT%packaging\run.cmd" %*
exit /b %errorlevel%
:missing
echo Pakk ut hele DRAGEN-mappen. Finner ikke install.py eller start.py. 1>&2
exit /b 1
:clipboard_failed
echo Kommandoen kunne ikke kopieres. Python FELLES ble ikke startet. 1>&2
exit /b 1
:unsupported_arguments
echo Tilleggsargumenter krever lokal Python: sett DRAGEN_LOCAL_PYTHON=1. 1>&2
exit /b 1
