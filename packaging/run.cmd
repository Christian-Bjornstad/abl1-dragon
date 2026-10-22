@echo off
setlocal
chcp 65001 >nul
set "ABL1_SCRIPT=%ABL1_PROJECT%packaging\bootstrap.py"
if not exist "%ABL1_SCRIPT%" goto missing_source
if not exist "%ABL1_PROJECT%start_abl1.py" goto missing_source
if not exist "%ABL1_PROJECT%requirements-desktop.txt" goto missing_source
if /i "%~2"=="--python" set "ABL1_PYTHON=%~3"
if defined ABL1_PYTHON goto explicit_python
if exist "%ABL1_PROJECT%.venv\Scripts\python.exe" goto local_environment
where py.exe >nul 2>nul
if errorlevel 1 goto path_python
for %%V in (3.14 3.13 3.12) do (
  py.exe -%%V -c "import sys;sys.exit(0)" >nul 2>nul
  if not errorlevel 1 (
    py.exe -%%V "%ABL1_SCRIPT%" %*
    exit /b
  )
)
:path_python
where python.exe >nul 2>nul
if errorlevel 1 goto missing_python
python.exe "%ABL1_SCRIPT%" %*
exit /b
:explicit_python
if not exist "%ABL1_PYTHON%" goto missing_python
"%ABL1_PYTHON%" "%ABL1_SCRIPT%" %*
exit /b
:local_environment
"%ABL1_PROJECT%.venv\Scripts\python.exe" "%ABL1_SCRIPT%" %*
exit /b
:missing_source
echo Hele kildekodemappen maa pakkes ut. Startskript eller requirements mangler. 1>&2
exit /b 1
:missing_python
echo Ingen brukbar Python ble funnet. Velg Python med ABL1_PYTHON eller --python som foerste argument. 1>&2
echo Python-kravet staar i pyproject.toml. Ingen installasjon eller global endring er gjort. 1>&2
exit /b 1
