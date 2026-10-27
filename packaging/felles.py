"""Python FELLES entrypoints: same-interpreter install/start, app-local packages."""
from __future__ import annotations
import importlib
import hashlib
from importlib import metadata
from importlib.machinery import PathFinder
import json
import os
from pathlib import Path
import platform
import runpy
import sys
import sysconfig
import tempfile
import traceback
import uuid
from datetime import datetime, timezone

ROOT=Path(__file__).resolve().parents[1]
APP_MODULES=('PyQt6','PyQt6_sip','openpyxl','et_xmlfile','PIL','websocket')
PIP_WHEEL='pip-26.2.2-py3-none-any.whl'
PIP_SHA256='fd7f4dfa8190e014013b9f08f3e973f4e4c26ffd179a204895533a7254813a70'


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


def _bundled_pip(root):
    wheel=Path(root)/'packaging/vendor'/PIP_WHEEL
    try:
        if wheel.stat().st_size>5_000_000 or hashlib.sha256(wheel.read_bytes()).hexdigest()!=PIP_SHA256:
            raise RuntimeError('Den medfølgende pip-pakken er skadet. Pakk ut hele main-ZIP på nytt.')
    except FileNotFoundError:
        raise RuntimeError('Den medfølgende pip-pakken mangler. Pakk ut hele main-ZIP på nytt.') from None
    return wheel


def _run_pip(root,args):
    """Run the bundled CLI in FELLES without installing pip or starting Python."""
    wheel=_bundled_pip(root)
    paths=list(sys.path);argv=list(sys.argv)
    previous={n:m for n,m in sys.modules.items() if n=='pip' or n.startswith('pip.')}
    for name in previous:del sys.modules[name]
    try:
        sys.path.insert(0,str(wheel));sys.argv=['pip',*args]
        importlib.invalidate_caches()
        try:runpy.run_module('pip',run_name='__main__',alter_sys=True)
        except SystemExit as result:return result.code or 0
        return 0
    finally:
        sys.path[:]=paths;sys.argv[:]=argv
        for name in tuple(sys.modules):
            if name=='pip' or name.startswith('pip.'):del sys.modules[name]
        sys.modules.update(previous)
        importlib.invalidate_caches()


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
    package_writable,package_write_error=_probe_writeability(_package_slot(root).parent)
    common=list(project_errors)
    if not runtime['windows_x64']:common.append('Offline-pakken krever Windows med 64-bit x64-Python.')
    if runtime['implementation']!='cpython':common.append('Bruk CPython 3.12–3.14.')
    if runtime.get('free_threaded'):common.append('Bruk vanlig CPython; fri-trådet Python støttes ikke av denne offline-pakken.')
    if loaded_qt:common.append('Qt er lastet. Åpne et nytt Python FELLES-vindu før installasjon eller start.')
    start_blockers=list(common)
    if metadata_error:start_blockers.append('Pakkemetadata kunne ikke leses: '+metadata_error)
    if missing:start_blockers.append('Mangler lokale pakker: '+', '.join(missing))
    install_blockers=list(common)
    # The source checkout can be a shared/read-only UNC folder. Dependencies
    # always belong to this Windows user's local application cache.
    if not package_writable:
        try:
            _package_slot(root).parent.mkdir(parents=True,exist_ok=True)
            package_writable,package_write_error=_probe_writeability(_package_slot(root).parent)
        except OSError as error:package_write_error=str(error)
    if not package_writable:install_blockers.append('Lokal pakkemappe er ikke skrivbar: '+str(package_write_error))
    try:_bundled_pip(root)
    except (OSError,RuntimeError) as error:install_blockers.append(str(error))
    if not wheels.is_dir():install_blockers.append('Pakk ut hele offline-pakken med wheelhouse.')
    if wheel_error:install_blockers.append('Wheelhouse kunne ikke leses: '+wheel_error)
    if missing_wheels:install_blockers.append('Mangler kompatible wheels: '+', '.join(missing_wheels))
    if metadata_error:install_blockers.append('Pakkemetadata kunne ikke leses: '+metadata_error)
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


def _package_slot(root=ROOT):
    local=Path(os.environ.get('LOCALAPPDATA') or Path.home()/'AppData/Local').resolve()
    lock=(Path(root)/'requirements-desktop.txt').read_bytes()
    digest=hashlib.sha256(lock).hexdigest()[:20]
    runtime=f'cp{sys.version_info.major}{sys.version_info.minor}-{platform.machine().lower()}'
    return local/'DRAGEN/python-packages'/runtime/digest


def package_dir(root=ROOT):
    slot=_package_slot(root)
    try:
        marker=slot/'active.json'
        if marker.stat().st_size>512:raise ValueError('Ugyldig pakkepeker.')
        name=json.loads(marker.read_text(encoding='utf-8'))
        import re
        if not isinstance(name,str) or not re.fullmatch(r'packages-[0-9a-f]{32}',name):raise ValueError('Ugyldig pakkepeker.')
        target=slot/name
        if target.resolve().parent!=slot.resolve():raise ValueError('Ugyldig pakkemappe.')
        return target
    except FileNotFoundError:return slot/'packages'


def _select_packages(slot,target):
    if target.parent!=slot or target.resolve().parent!=slot.resolve():raise RuntimeError('Ugyldig lokal pakkemappe.')
    descriptor,temporary=tempfile.mkstemp(prefix='.active-',suffix='.json',dir=slot)
    try:
        with os.fdopen(descriptor,'w',encoding='utf-8') as stream:
            json.dump(target.name,stream);stream.flush();os.fsync(stream.fileno())
        os.replace(temporary,slot/'active.json')
    finally:Path(temporary).unlink(missing_ok=True)


def helpers(root):
    return runpy.run_path(str(Path(root)/'packaging/bootstrap.py'),run_name='abl1_bootstrap_helpers')


def requirements(root):
    h=helpers(root);project=h['project_metadata'](Path(root))
    return project,h['pinned_requirements'](Path(root))


def _local_spec(name,target,paths=None,*,allow_missing=False):
    """Resolve app dependencies from their selected generation, not host hooks."""
    target=Path(target).resolve()
    spec=PathFinder.find_spec(name,[str(target)] if paths is None else paths)
    if spec is None:
        if allow_missing:return None
        raise ModuleNotFoundError('Feil pakkekilde for '+name+'. Forventet: '+str(target)+
                                  '. Funnet: ikke funnet. Kjør INSTALL_DRAGEN.cmd i et nytt FELLES-vindu.',name=name)
    locations=[] if spec is None else list(spec.submodule_search_locations or [])
    origin=None if spec is None else spec.origin
    candidates=([origin] if origin and origin not in ('built-in','frozen') else [])+locations
    if not candidates or any(not Path(p).resolve().is_relative_to(target) for p in candidates):
        actual=origin or ', '.join(locations) or 'ikke funnet'
        raise RuntimeError('Feil pakkekilde for '+name+'. Forventet: '+str(target)+
                           '. Funnet: '+str(actual)+'. Kjør INSTALL_DRAGEN.cmd i et nytt FELLES-vindu.')
    return spec


def _verify_package_files(target,required):
    names={_normal_name(row['name']) for row in required}
    for distribution,module in (('pyqt6','PyQt6'),('openpyxl','openpyxl'),
                                 ('et-xmlfile','et_xmlfile'),('pillow','PIL'),('websocket-client','websocket')):
        if distribution not in names:continue
        spec=_local_spec(module,target)
        if module=='PyQt6':
            for child in ('QtCore','sip'):
                _local_spec('PyQt6.'+child,target,list(spec.submodule_search_locations or []))


class _LocalAppFinder:
    """Keep FELLES import integrations from selecting a different app runtime."""
    def __init__(self,target):self.target=Path(target).resolve()

    def find_spec(self,fullname,path=None,target=None):
        if fullname.split('.')[0] not in APP_MODULES:return None
        return _local_spec(fullname,self.target,path,allow_missing=True)


def activate(root=ROOT):
    root=Path(root).resolve();project,required=requirements(root);target=package_dir(root).resolve()
    if not target.is_dir():raise RuntimeError('Kjør INSTALL_DRAGEN.cmd først.')
    loaded=_loaded_app_modules()
    if loaded:
        raise RuntimeError('Pakker er allerede lastet ('+', '.join(loaded[:5])+'). Start et nytt Python FELLES-vindu før DRAGEN.')
    installed={d.metadata['Name'].lower().replace('_','-'):d.version for d in metadata.distributions(path=[str(target)])}
    missing=[r['name']+'=='+r['required'] for r in required if installed.get(r['name'].lower().replace('_','-'))!=r['required']]
    if missing:raise RuntimeError('Mangler lokale FELLES-pakker: '+', '.join(missing))
    _verify_package_files(target,required)
    sys.path[:]=_isolated_paths(root,target)
    importlib.invalidate_caches()
    sys.meta_path.insert(0,_LocalAppFinder(target))
    return project


def _installation_finished(root):
    helper=Path(root)/'src/abl1_workstation/reference_bundle.py'
    if helper.is_file():
        print('Klargjør medfølgende hg19 chr9-referanse …',flush=True)
        # Match the existing AppLocalDataLocation used by the desktop entry
        # point. A read-only shared checkout must not fail after pip succeeded.
        local=Path(os.environ.get('LOCALAPPDATA') or Path.home()/'AppData/Local').resolve()
        prepared=runpy.run_path(str(helper))['bundled_reference'](root,local/'ABL1Dragon/ABL1Dragon')
        if prepared:print('chr9 FASTA og indeks er klare. Ingen referansenedlasting kreves.',flush=True)
    print('\n'+'='*48)
    print('DRAGEN ER FERDIG INSTALLERT')
    print('Alle pakkeversjoner er kontrollert.')
    print('Pakker for denne Windows-brukeren: '+str(package_dir(root)),flush=True)
    print('Lukk dette Python FELLES-vinduet.')
    print('Kjor START_DRAGEN.cmd for aa starte appen.')
    print('='*48+'\n',flush=True)


def install(root=ROOT,*,offline=None,pip_main=None):
    root=Path(root).resolve();project,required=requirements(root)
    if _loaded_app_modules():
        raise RuntimeError('Lukk tidligere apper og bruk et nytt Python FELLES-vindu før installasjon.')
    wheels=root/'wheelhouse'
    use_offline=wheels.is_dir() if offline is None else offline
    if use_offline and not wheels.is_dir():raise RuntimeError('Offline-installasjon krever wheelhouse. Kjør install.py uten --offline for GitHub-kildekode.')
    target=package_dir(root)
    slot=_package_slot(root)
    if target.resolve().parent!=slot.resolve():raise RuntimeError('Ugyldig lokal pakkemappe.')
    # Never rename or overwrite packages which another process may have loaded.
    # Old generations stay intact. Publish a new generation atomically only
    # after pip and every pinned version have passed verification.
    if target.exists():
        distributions={d.metadata['Name'].lower().replace('_','-'):d.version for d in metadata.distributions(path=[str(target)])}
        valid=all(distributions.get(r['name'].lower().replace('_','-'))==r['required'] for r in required)
        if valid:
            try:_verify_package_files(target,required)
            except (ImportError,RuntimeError):valid=False
        if valid:
            _installation_finished(root);return 0
        print('Reparerer lokale DRAGEN-pakker for denne brukeren. Eksisterende pakker beholdes.')
    target.parent.mkdir(parents=True,exist_ok=True)
    temporary=target.parent/('packages-'+uuid.uuid4().hex);temporary.mkdir()
    args=['install','--isolated','--no-deps','--ignore-installed','--only-binary=:all:',
          '--no-user','--no-input','--disable-pip-version-check','--target',str(temporary),'-r',str(root/'requirements-desktop.txt')]
    if use_offline:args+=['--no-index','--find-links',str(wheels)]
    print(('Installerer fra wheelhouse' if use_offline else 'Installerer fra Python-pakkeregisteret')+' i DRAGENs egen pakkemappe. Globale pakker endres ikke.')
    try:
        # Python FELLES may prohibit a child python.exe. Run pip once in this
        # interpreter, then require a fresh FELLES window before app startup.
        code=(_run_pip(root,args) if pip_main is None else pip_main(args)) or 0
        if code:raise RuntimeError('Pakkeinstallasjonen feilet. Delvis installasjon beholdes i '+str(temporary))
        distributions={d.metadata['Name'].lower().replace('_','-'):d.version for d in metadata.distributions(path=[str(temporary)])}
        if not all(distributions.get(r['name'].lower().replace('_','-'))==r['required'] for r in required):
            raise RuntimeError('Versjonskontroll feilet. Delvis mappe beholdes: '+str(temporary))
        _verify_package_files(temporary,required)
        _select_packages(slot,temporary)
    except Exception:
        print('DRAGEN-INSTALLASJONEN BLE IKKE FULLFORT. Se feilen nedenfor.');raise
    _installation_finished(root)
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
