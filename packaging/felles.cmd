@echo off
setlocal
if not defined ABL1_IVANTI set "ABL1_IVANTI=C:\Program Files (x86)\Ivanti\Workspace Control\pwrgate.exe"
if not defined ABL1_IVANTI_APP_ID goto missing_config
if not exist "%ABL1_FELLES_SCRIPT%" goto missing
if not exist "%ABL1_IVANTI%" goto missing
powershell.exe -NoProfile -Command "$ErrorActionPreference='Stop'; $p=(Resolve-Path -LiteralPath $env:ABL1_FELLES_SCRIPT).Path; $b=[Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($p)); Set-Clipboard -Value ('import runpy,base64; runpy.run_path(base64.b64decode('''+$b+''').decode(''utf-8''),run_name=''abl1_felles'')[''main'']()')"
if errorlevel 1 goto failed
start "" "%ABL1_IVANTI%" "%ABL1_IVANTI_APP_ID%"
if errorlevel 1 goto failed
echo Python FELLES aapnes via Ivanti. Lim inn med Ctrl+V og trykk Enter.
echo Ved installasjon: lukk FELLES etterpaa og bruk Start med Python FELLES.cmd.
pause
exit /b 0
:missing_config
echo Sett ABL1_IVANTI_APP_ID til lokalt godkjent Python-program. Ingen organisasjonsspesifikk ID folger offentlig kildekode. 1>&2
pause
exit /b 1
:missing
echo Finner ikke hele ABL1-mappen eller Python FELLES/Ivanti. 1>&2
echo Bruk vanlig Installer ABL1.cmd / Start ABL1.cmd paa en PC med lokal Python. 1>&2
pause
exit /b 1
:failed
echo Kunne ikke kopiere kommandoen eller aapne Python FELLES. 1>&2
pause
exit /b 1
