@echo off
setlocal
chcp 65001 >nul
if /i "%~1"=="start" goto action_ok
if /i "%~1"=="install" goto action_ok
echo Ukjent DRAGEN-handling. 1>&2
exit /b 1
:action_ok
set "ABL1_FELLES_SCRIPT=%ABL1_PROJECT%%~1.py"
if not exist "%ABL1_FELLES_SCRIPT%" goto missing
if /i "%DRAGEN_LOCAL_PYTHON%"=="1" goto local_python
if defined ABL1_IVANTI goto ivanti_selected
for %%P in ("%ProgramFiles(x86)%\Ivanti\Workspace Control\pwrgate.exe" "%ProgramFiles%\Ivanti\Workspace Control\pwrgate.exe" "%ProgramFiles(x86)%\RES Software\Workspace Manager\pwrgate.exe" "%ProgramFiles%\RES Software\Workspace Manager\pwrgate.exe") do if exist "%%~P" if not defined ABL1_IVANTI set "ABL1_IVANTI=%%~P"
if defined ABL1_IVANTI goto ivanti_selected
for /f "delims=" %%P in ('where pwrgate.exe 2^>nul') do if not defined ABL1_IVANTI set "ABL1_IVANTI=%%P"
:ivanti_selected
if not defined ABL1_IVANTI goto missing_ivanti
if not exist "%ABL1_IVANTI%" goto missing_ivanti
if not "%~2"=="" goto unsupported_arguments
if not defined ABL1_IVANTI_APP_ID set "ABL1_IVANTI_APP_ID=15694"
powershell.exe -NoProfile -Command "$ErrorActionPreference='Stop'; $p=(Resolve-Path -LiteralPath $env:ABL1_FELLES_SCRIPT).Path; $b=[Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($p)); Set-Clipboard -Value ('import runpy,base64; runpy.run_path(base64.b64decode('''+$b+''').decode(''utf-8''),run_name=''dragen_felles'')[''main'']()')"
set "DRAGEN_CLIPBOARD_EXIT=%errorlevel%"
start "" "%ABL1_IVANTI%" "%ABL1_IVANTI_APP_ID%"
if errorlevel 1 goto launch_failed
if not "%DRAGEN_CLIPBOARD_EXIT%"=="0" goto clipboard_failed
echo Ivanti er startet fra "%ABL1_IVANTI%" med program-ID %ABL1_IVANTI_APP_ID%.
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
echo Ivanti er startet, men kommandoen kunne ikke kopieres automatisk. 1>&2
echo Kopier denne linjen inn i Python FELLES og trykk Enter:
echo import runpy; runpy.run_path(r"%ABL1_FELLES_SCRIPT%",run_name="dragen_felles")["main"]()
exit /b 1
:launch_failed
echo Ivanti kunne ikke startes fra "%ABL1_IVANTI%" med program-ID %ABL1_IVANTI_APP_ID%. 1>&2
exit /b 1
:unsupported_arguments
echo Tilleggsargumenter krever lokal Python: sett DRAGEN_LOCAL_PYTHON=1. 1>&2
exit /b 1
:missing_ivanti
echo Python FELLES kunne ikke aapnes: finner ikke Ivanti pwrgate.exe. 1>&2
echo Sett ABL1_IVANTI til riktig Ivanti-bane fra MolStat paa denne jobb-PC-en. 1>&2
echo Lokal Python startes ikke automatisk. For lokal PC: sett DRAGEN_LOCAL_PYTHON=1. 1>&2
exit /b 1
