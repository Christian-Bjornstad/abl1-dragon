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
import sysconfig
import tempfile
import traceback
from datetime import datetime, timezone

ROOT=Path(__file__).resolve().parents[1]
APP_MODULES=('PyQt6','PyQt6_sip','openpyxl','et_xmlfile','PIL','websocket')


def _loaded_app_modules():
    return sorted(name for name in sys.modules if any(name==prefix or name.startswith(prefix+'.') for prefix in APP_MODULES))


def _isolated_paths(root,target):
    """Keep the active interpreter's standard library, not shared/user packages."""
    bases={Path(sys.base_prefix).resolve(),Path(sys.base_exec_prefix).resolve()}
    standard=[]
    for value in sys.path:
        if not value:continue
        path=Path(value).resolve()
        if any(part.casefold() in ('site-packages','dist-packages') for part in path.parts):continue
        if any(path.is_relative_to(base) for base in bases) and path not in standard:standard.append(path)
    for key in ('stdlib','platstdlib'):
        path=Path(sysconfig.get_path(key)).resolve()
        if path not in standard:standard.append(path)
    return [str(root/'src'),str(target),*[str(path) for path in standard]]


def _runtime_info():
    bits=64 if sys.maxsize>2**32 else 32
    tag=sysconfig.get_platform()
    return {'python_version':list(sys.version_info[:3]),'python_executable':sys.executable,
            'architecture_bits':bits,'platform':sys.platform,'platform_tag':tag,
            'implementation':sys.implementation.name,
            'free_threaded':bool(sysconfig.get_config_var('Py_GIL_DISABLED')),
            'windows_x64':sys.platform=='win32' and bits==64 and tag=='win-amd64'}


def _pip_available():
    try:return importlib.util.find_spec('pip') is not None
    except (ImportError,ValueError):return False


def _probe_writeability(root):
    try:
        with tempfile.TemporaryFile(dir=root):pass
        return True,None
    except OSError as error:return False,str(error)


def _normal_name(value):
    return value.lower().replace('_','-').replace('.','-')


def _installed_versions(target):
    return {_normal_name(d.metadata.get('Name','')):d.version
            for d in metadata.distributions(path=[str(target)])}


def _compatible_wheel(path, requirement, runtime):
    parts=path.stem.split('-')
    if len(parts) not in (5,6) or _normal_name(parts[0])!=_normal_name(requirement['name']) or parts[1]!=requirement['required']:
        return False
    python_tags,abi_tags,platform_tags=(part.split('.') for part in parts[-3:])
    if not {'any',runtime['platform_tag'].replace('-','_')}.intersection(platform_tags):return False
    major,minor=runtime['python_version'][:2]
    for tag in python_tags:
        if tag in ('py'+str(major),'py'+str(major)+str(minor)) and 'none' in abi_tags:return True
        if tag=='cp'+str(major)+str(minor) and runtime['implementation']=='cpython' and set(abi_tags).intersection({'none','abi3',tag}):return True
        if tag.startswith('cp') and tag[2:].isdigit() and len(tag)>3 and 'abi3' in abi_tags:
            minimum=(int(tag[2]),int(tag[3:]))
            if runtime['implementation']=='cpython' and major==minimum[0] and minor>=minimum[1]:return True
    return False


def _log_folders(root):
    return (Path(root)/'work/launcher-logs',Path(tempfile.gettempdir())/'ABL1Dragon/logs')


def _write_report(root,report):
    failure=None
    for folder in _log_folders(root):
        temporary=None
        try:
            folder.mkdir(parents=True,exist_ok=True)
            path=folder/'felles-check.json'
            report['report_path']=str(path.resolve())
            descriptor,temporary=tempfile.mkstemp(dir=folder,prefix='.felles-check-',suffix='.json')
            with os.fdopen(descriptor,'w',encoding='utf-8') as stream:
                json.dump(report,stream,ensure_ascii=False,indent=2);stream.write('\n')
            os.replace(temporary,path)
            return
        except OSError as error:failure=str(error)
        finally:
            if temporary is not None:
                try:Path(temporary).unlink(missing_ok=True)
                except OSError as error:report.setdefault('cleanup_errors',[]).append(str(error))
    report['report_path']=None
    report['report_error']=failure or 'Ingen skrivbar rapportmappe.'


def _record_failure(root,action):
    detail=traceback.format_exc()
    for folder in _log_folders(root):
        try:
            folder.mkdir(parents=True,exist_ok=True)
            path=folder/'felles.log'
            with path.open('a',encoding='utf-8') as stream:
                stream.write('\n'+datetime.now(timezone.utc).isoformat()+' action='+action+'\n'+detail)
            return path.resolve()
        except OSError:continue
    return None


def check(root=ROOT):
    """Inspect local setup only; do not import Qt/pip or start other processes."""
    root=Path(root).resolve();runtime=_runtime_info();target=package_dir(root)
    project={};required=[];project_errors=[]
    try:
        project,required=requirements(root)
        expected=(*helpers(root)['RESOURCE_FILES'],'engine/reference.json')
        project_errors.extend('Ressurs mangler: '+name for name in expected if not (root/name).is_file())
    except (OSError,ValueError,RuntimeError,KeyError) as error:project_errors.append(str(error))
    installed={};metadata_error=None
    try:installed=_installed_versions(target) if target.is_dir() else {}
    except (OSError,ValueError,TypeError) as error:metadata_error=str(error)
    missing=[row['name']+'=='+row['required'] for row in required if installed.get(_normal_name(row['name']))!=row['required']]
    wheels=root/'wheelhouse';wheel_error=None
    try:wheel_paths=sorted(p for p in wheels.glob('*.whl') if p.is_file())
    except OSError as error:wheel_paths=[];wheel_error=str(error)
    available={row['name']:[path.name for path in wheel_paths if _compatible_wheel(path,row,runtime)] for row in required}
    missing_wheels=[row['name']+'=='+row['required'] for row in required if not available[row['name']]]
    writable,write_error=_probe_writeability(root)
    pip_available=_pip_available()
    loaded_qt=sorted(name for name in sys.modules if name.startswith('PyQt6'))
    partial=target.with_name(target.name+'.installing').exists()
    common=list(project_errors)
    if not runtime['windows_x64']:common.append('Offline-pakken krever Windows med 64-bit x64-Python.')
    if runtime['implementation']!='cpython':common.append('Bruk CPython 3.12–3.14.')
    if runtime.get('free_threaded'):common.append('Bruk vanlig CPython; fri-trådet Python støttes ikke av denne offline-pakken.')
    if loaded_qt:common.append('Qt er lastet. Åpne et nytt Python FELLES-vindu før installasjon eller start.')
    start_blockers=list(common)
    if metadata_error:start_blockers.append('Pakkemetadata kunne ikke leses: '+metadata_error)
    if missing:start_blockers.append('Mangler lokale pakker: '+', '.join(missing))
    install_blockers=list(common)
    if not writable:install_blockers.append('Programmappen er ikke skrivbar: '+str(write_error))
    if not pip_available:install_blockers.append('pip mangler i Python FELLES. Bruk godkjent runtime med pip.')
    if not wheels.is_dir():install_blockers.append('Pakk ut hele offline-pakken med wheelhouse.')
    if wheel_error:install_blockers.append('Wheelhouse kunne ikke leses: '+wheel_error)
    if missing_wheels:install_blockers.append('Mangler kompatible wheels: '+', '.join(missing_wheels))
    if metadata_error:install_blockers.append('Pakkemetadata kunne ikke leses: '+metadata_error)
    if partial:install_blockers.append('En tidligere .installing-mappe finnes. Bevar eller flytt den før nytt forsøk.')
    if target.exists() and missing:install_blockers.append('Eksisterende pakkemappe er ufullstendig eller eldre. Bevar eller flytt den før ny installasjon.')
    report={'checked_at_utc':datetime.now(timezone.utc).isoformat(),'project':str(root),
            'application_version':project.get('version'),'requires_python':project.get('requires-python'),
            **runtime,'package_dir':str(target),'project_writable':writable,'write_error':write_error,
            'pip_available':pip_available,'wheelhouse':str(wheels),'compatible_wheels':available,
            'missing_wheels':missing_wheels,'installed_versions':installed,'missing_packages':missing,
            'loaded_qt_modules':loaded_qt,'partial_install_exists':partial,
            'ready_for_install':not install_blockers,'ready_for_start':not start_blockers,
            'install_blockers':install_blockers,'start_blockers':start_blockers,
            'dependency_imports_tested':False,'gui_started':False,'network_used':False}
    _write_report(root,report)
    print('DRAGEN · FELLES-kontroll')
    print('Python '+'.'.join(map(str,runtime['python_version']))+' · '+str(runtime['architecture_bits'])+' bit · '+runtime['platform_tag'])
    print('Installasjon: '+('klar' if report['ready_for_install'] else 'ikke klar'))
    print('Oppstart: '+('klar' if report['ready_for_start'] else 'ikke klar'))
    for reason in dict.fromkeys(install_blockers+start_blockers):print('- '+reason)
    print('Rapport: '+str(report['report_path'] or 'kunne ikke lagres'))
    return report


def package_dir(root=ROOT):
    return Path(root)/'.felles-packages'/f'cp{sys.version_info.major}{sys.version_info.minor}-{platform.machine().lower()}'


def helpers(root):
    return runpy.run_path(str(Path(root)/'packaging/bootstrap.py'),run_name='abl1_bootstrap_helpers')


def requirements(root):
    h=helpers(root);project=h['project_metadata'](Path(root))
    return project,h['pinned_requirements'](Path(root))


def activate(root=ROOT):
    root=Path(root).resolve();project,required=requirements(root);target=package_dir(root)
    if not target.is_dir():raise RuntimeError('Kjør INSTALL_DRAGEN.cmd først.')
    loaded=_loaded_app_modules()
    if loaded:
        raise RuntimeError('Pakker er allerede lastet ('+', '.join(loaded[:5])+'). Start et nytt Python FELLES-vindu før DRAGEN.')
    installed={d.metadata['Name'].lower().replace('_','-'):d.version for d in metadata.distributions(path=[str(target)])}
    missing=[r['name']+'=='+r['required'] for r in required if installed.get(r['name'].lower().replace('_','-'))!=r['required']]
    if missing:raise RuntimeError('Mangler lokale FELLES-pakker: '+', '.join(missing))
    sys.path[:]=_isolated_paths(root,target)
    importlib.invalidate_caches()
    for name in ('PyQt6','openpyxl','et_xmlfile','PIL','websocket'):
        spec=importlib.util.find_spec(name)
        if spec is None or not spec.origin or not Path(spec.origin).resolve().is_relative_to(target):
            raise RuntimeError('Feil pakkekilde for '+name+'. Kjør INSTALL_DRAGEN.cmd i et nytt FELLES-vindu.')
    return project


def install(root=ROOT,*,offline=None,pip_main=None):
    root=Path(root).resolve();project,required=requirements(root)
    if _loaded_app_modules():
        raise RuntimeError('Lukk tidligere apper og bruk et nytt Python FELLES-vindu før installasjon.')
    wheels=root/'wheelhouse'
    use_offline=wheels.is_dir() if offline is None else offline
    if use_offline and not wheels.is_dir():raise RuntimeError('Offline-installasjon krever wheelhouse. Kjør install.py uten --offline for GitHub-kildekode.')
    target=package_dir(root)
    private_root=root/'.felles-packages'
    if private_root.resolve()!=private_root or target.resolve()!=target:
        raise RuntimeError('DRAGENs pakkemappe peker utenfor programmappen.')
    # Build a complete replacement before moving any existing app-owned packages.
    if target.exists():
        distributions={d.metadata['Name'].lower().replace('_','-'):d.version for d in metadata.distributions(path=[str(target)])}
        if all(distributions.get(r['name'].lower().replace('_','-'))==r['required'] for r in required):
            print('Lokale FELLES-pakker finnes. Bruk START_DRAGEN.cmd i et nytt vindu.');return 0
        print('Reparerer DRAGENs lokale pakker; eksisterende mappe bevares som sikkerhetskopi.')
    target.parent.mkdir(parents=True,exist_ok=True)
    temporary=Path(tempfile.mkdtemp(prefix=target.name+'.installing-',dir=target.parent))
    args=['install','--isolated','--no-deps','--ignore-installed','--only-binary=:all:',
          '--no-user','--no-input','--disable-pip-version-check','--target',str(temporary),'-r',str(root/'requirements-desktop.txt')]
    if use_offline:args+=['--no-index','--find-links',str(wheels)]
    print(('Installerer fra wheelhouse' if use_offline else 'Installerer fra Python-pakkeregisteret')+' i DRAGENs egen pakkemappe. Globale pakker endres ikke.')
    try:
        # Python FELLES may prohibit a child python.exe. Run pip once in this
        # interpreter, then require a fresh FELLES window before app startup.
        if pip_main is None:
            try:from pip._internal.cli.main import main as pip_main
            except ImportError:
                raise RuntimeError('pip mangler i aktiv Python. Bruk samme Python FELLES som PRONTO.') from None
        code=pip_main(args) or 0
        if code:raise RuntimeError('Pakkeinstallasjonen feilet. Delvis installasjon beholdes i '+str(temporary))
        distributions={d.metadata['Name'].lower().replace('_','-'):d.version for d in metadata.distributions(path=[str(temporary)])}
        if not all(distributions.get(r['name'].lower().replace('_','-'))==r['required'] for r in required):
            raise RuntimeError('Versjonskontroll feilet. Delvis mappe beholdes: '+str(temporary))
        backup=None
        if target.exists():
            backup=target.with_name(target.name+'.previous-'+datetime.now().strftime('%Y%m%d%H%M%S%f'))
            target.rename(backup)
        try:temporary.rename(target)
        except OSError:
            if backup is not None and not target.exists():backup.rename(target)
            raise
    except Exception:
        print('Installasjon ble stoppet. Kontroller eventuell .installing-mappe før nytt forsøk.');raise
    print('Installasjonen er kontrollert. Lukk dette FELLES-vinduet og bruk START_DRAGEN.cmd.')
    return 0


def start(root=ROOT,argv=None):
    activate(root)
    # FELLES can reuse a console after an update; never start cached app code.
    for name in tuple(sys.modules):
        if name=='abl1_workstation' or name.startswith('abl1_workstation.'):del sys.modules[name]
    import abl1_workstation
    if not Path(abl1_workstation.__file__).resolve().is_relative_to(Path(root).resolve()/'src/abl1_workstation'):
        raise RuntimeError('DRAGEN ble lastet fra feil programmappe.')
    from abl1_workstation.__main__ import main
    return main(list(argv or []))


def entry(action,root=ROOT,argv=None):
    try:
        if action=='check':
            report=check(root)
            return 0 if report['ready_for_install'] or report['ready_for_start'] else 1
        if action=='install':
            import argparse
            parser=argparse.ArgumentParser(description='Installer DRAGEN')
            mode=parser.add_mutually_exclusive_group()
            mode.add_argument('--offline',dest='offline',action='store_true')
            mode.add_argument('--online',dest='offline',action='store_false')
            parser.set_defaults(offline=None)
            return install(root,offline=parser.parse_args(list(argv or [])).offline)
        if action=='start':return start(root,argv=argv)
        raise ValueError('Ukjent FELLES-handling: '+str(action))
    except Exception as error:
        path=_record_failure(root,str(action))
        print('DRAGEN Python FELLES: '+str(error))
        print('Feillogg: '+str(path or 'kunne ikke lagres'))
        return 1
