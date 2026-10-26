@echo off
setlocal
chcp 65001 >nul
if not defined DRAGEN_IVANTI if defined ABL1_IVANTI set "DRAGEN_IVANTI=%ABL1_IVANTI%"
if not defined DRAGEN_PYTHON if defined ABL1_PYTHON set "DRAGEN_PYTHON=%ABL1_PYTHON%"
set "DRAGEN_SCRIPT=%~dp0start.py"
if not defined DRAGEN_IVANTI set "DRAGEN_IVANTI=C:\Program Files (x86)\Ivanti\Workspace Control\pwrgate.exe"

if not exist "%DRAGEN_SCRIPT%" goto missing_project
if not exist "%~dp0src\abl1_workstation\" goto missing_project
if not exist "%~dp0packaging\felles.py" goto missing_project
if /i "%DRAGEN_LOCAL_PYTHON%"=="1" goto select_local
if exist "%DRAGEN_IVANTI%" goto felles
:select_local
if defined DRAGEN_PYTHON goto custom_python
if exist "%~dp0.venv\Scripts\python.exe" goto venv_python
where py.exe >nul 2>nul
if not errorlevel 1 goto python_launcher
where python.exe >nul 2>nul
if errorlevel 1 goto missing_python
python.exe "%DRAGEN_SCRIPT%" %*
set "DRAGEN_EXIT=%errorlevel%"
goto local_done

:python_launcher
py.exe -3.14 "%DRAGEN_SCRIPT%" %*
set "DRAGEN_EXIT=%errorlevel%"
goto local_done

:venv_python
"%~dp0.venv\Scripts\python.exe" "%DRAGEN_SCRIPT%" %*
set "DRAGEN_EXIT=%errorlevel%"
goto local_done

:custom_python
if not exist "%DRAGEN_PYTHON%" goto missing_python
"%DRAGEN_PYTHON%" "%DRAGEN_SCRIPT%" %*
set "DRAGEN_EXIT=%errorlevel%"

:local_done
if not "%DRAGEN_EXIT%"=="0" if not defined ABL1_NO_PAUSE pause
exit /b %DRAGEN_EXIT%

:felles
powershell.exe -NoProfile -Command "$ErrorActionPreference='Stop'; $p=(Resolve-Path -LiteralPath $env:DRAGEN_SCRIPT).Path; $encoded=[Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($p)); Set-Clipboard -Value ('import runpy, base64; runpy.run_path(base64.b64decode(''' + $encoded + ''').decode(''utf-8''), run_name=''dragen_start_felles'')[''main'']()')"
set "DRAGEN_CLIPBOARD_EXIT=%errorlevel%"
start "" "%DRAGEN_IVANTI%" 15694
if errorlevel 1 goto felles_failed
if not "%DRAGEN_CLIPBOARD_EXIT%"=="0" goto clipboard_failed
echo Python FELLES opens through Ivanti.
echo Paste the copied command with Ctrl+V, then press Enter.
echo Keep the whole DRAGEN folder in its permanent location.
echo To forward command line options, use a local Python 3.14 launch.
if not defined ABL1_NO_PAUSE pause
exit /b 0

:missing_project
echo Cannot find the complete DRAGEN project. Extract the whole project first.
if not defined ABL1_NO_PAUSE pause
exit /b 1

:missing_python
echo Python 3.14 or Python FELLES was not found.
echo Set DRAGEN_PYTHON to its full executable path, or open Python FELLES through Ivanti.
if not defined ABL1_NO_PAUSE pause
exit /b 1

:clipboard_failed
echo Python FELLES was requested, but the command could not be copied.
echo Copy this line into Python FELLES:
echo import runpy; runpy.run_path(r"%DRAGEN_SCRIPT%",run_name="dragen_felles")["main"]()
if not defined ABL1_NO_PAUSE pause
exit /b 1

:felles_failed
echo Could not open Python FELLES through Ivanti.
if not defined ABL1_NO_PAUSE pause
exit /b 1
