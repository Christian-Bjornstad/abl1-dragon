"""Python FELLES entrypoints: same-interpreter install/start, app-local packages."""
from __future__ import annotations
import importlib
from importlib import metadata
import json
import os
from pathlib import Path
import platform
import runpy
import sys

ROOT=Path(__file__).resolve().parents[1]


def package_dir(root=ROOT):
    return Path(root)/'.felles-packages'/f'cp{sys.version_info.major}{sys.version_info.minor}-{platform.machine().lower()}'


def helpers(root):
    return runpy.run_path(str(Path(root)/'packaging/bootstrap.py'),run_name='abl1_bootstrap_helpers')


def requirements(root):
    h=helpers(root);project=h['project_metadata'](Path(root))
    return project,h['pinned_requirements'](Path(root))


def activate(root=ROOT):
    root=Path(root).resolve();project,required=requirements(root);target=package_dir(root)
    if not target.is_dir():raise RuntimeError('Kjør Installer med Python FELLES.cmd først.')
    if any(name.startswith('PyQt6') for name in sys.modules):
        raise RuntimeError('Qt er allerede lastet. Start et nytt Python FELLES-vindu før ABL1.')
    installed={d.metadata['Name'].lower().replace('_','-'):d.version for d in metadata.distributions(path=[str(target)])}
    missing=[r['name']+'=='+r['required'] for r in required if installed.get(r['name'].lower().replace('_','-'))!=r['required']]
    if missing:raise RuntimeError('Mangler lokale FELLES-pakker: '+', '.join(missing))
    sys.path[:0]=[str(root/'src'),str(target)]
    importlib.invalidate_caches()
    return project


def install(root=ROOT):
    root=Path(root).resolve();project,required=requirements(root)
    if any(name.startswith('PyQt6') for name in sys.modules):
        raise RuntimeError('Lukk tidligere Qt-apper og bruk et nytt Python FELLES-vindu før installasjon.')
    wheels=root/'wheelhouse'
    if not wheels.is_dir():raise RuntimeError('FELLES-installasjon krever medfølgende wheelhouse. Pakk ut hele offline-pakken.')
    target=package_dir(root)
    # First install only. Never overwrite a package already loaded by this host.
    if target.exists():
        distributions={d.metadata['Name'].lower().replace('_','-'):d.version for d in metadata.distributions(path=[str(target)])}
        if all(distributions.get(r['name'].lower().replace('_','-'))==r['required'] for r in required):
            print('Lokale FELLES-pakker finnes. Bruk Start med Python FELLES.cmd i et nytt vindu.');return 0
        raise RuntimeError('Ufullstendig/eldre FELLES-pakkemappe: '+str(target)+'. Bevar eller flytt denne før nytt forsøk.')
    temporary=target.with_name(target.name+'.installing')
    temporary.mkdir(parents=True,exist_ok=False)
    args=['install','--isolated','--no-index','--find-links',str(wheels),'--only-binary=:all:',
          '--no-user','--no-input','--disable-pip-version-check','--target',str(temporary),'-r',str(root/'requirements-desktop.txt')]
    print('Installerer offline i appens egen FELLES-pakkemappe. Globale pakker endres ikke.')
    try:
        # Python FELLES may prohibit a child python.exe. Run pip once in this
        # interpreter, then require a fresh FELLES window before app startup.
        original_argv=sys.argv[:]
        sys.argv=['pip',*args]
        try:
            runpy.run_module('pip',run_name='__main__',alter_sys=True)
            code=0
        except SystemExit as result:code=result.code or 0
        finally:sys.argv=original_argv
        if code:raise RuntimeError('Offline pip feilet. Delvis installasjon beholdes i '+str(temporary))
        distributions={d.metadata['Name'].lower().replace('_','-'):d.version for d in metadata.distributions(path=[str(temporary)])}
        if not all(distributions.get(r['name'].lower().replace('_','-'))==r['required'] for r in required):
            raise RuntimeError('Versjonskontroll feilet. Delvis mappe beholdes: '+str(temporary))
        temporary.rename(target)
    except Exception:
        print('Installasjon ble stoppet. Kontroller eventuell .installing-mappe før nytt forsøk.');raise
    print('Installasjonen er kontrollert. Lukk dette FELLES-vinduet og bruk Start med Python FELLES.cmd.')
    return 0


def start(root=ROOT,argv=None):
    activate(root)
    from abl1_workstation.__main__ import main
    return main(list(argv or []))


def entry(action,root=ROOT):
    try:return install(root) if action=='install' else start(root)
    except Exception as error:
        print('ABL1 Python FELLES: '+str(error));return 1
