"""Fresh-interpreter FELLES boundaries; no Ivanti, clipboard or global installs."""
from pathlib import Path
import ensurepip
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
import zipfile

ROOT=Path(__file__).resolve().parents[1]


class FellesTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(prefix='FELLES Å ');self.root=Path(self.tmp.name)
        shutil.copytree(ROOT/'packaging',self.root/'packaging')
        for name in ('pyproject.toml','requirements-desktop.txt','start_abl1.py'):shutil.copyfile(ROOT/name,self.root/name)
        (self.root/'src/abl1_workstation').mkdir(parents=True)
    def tearDown(self):self.tmp.cleanup()
    def invoke(self,body):
        code="import json,runpy,sys,os\nfrom pathlib import Path\nroot=Path(sys.argv[1])\nos.environ['LOCALAPPDATA']=str(root/'user-local')\nf=runpy.run_path(str(root/'packaging/felles.py'))\n"+body
        return subprocess.run([sys.executable,'-I','-c',code,str(self.root)],capture_output=True,encoding='utf-8',errors='replace',timeout=30)
    def diagnostic_fixture(self):
        (self.root/'requirements-desktop.txt').write_text('pip=='+ensurepip.version()+'\n',encoding='utf-8')
        for name in ('engine/analyze.py','engine/reference.json','desktop/data/pilot.json','app/data/knowledge.json','app/data/igv-manifest.json'):
            path=self.root/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_text('{}')
        wheels=self.root/'wheelhouse';wheels.mkdir()
        (wheels/('pip-'+ensurepip.version()+'-py3-none-any.whl')).write_bytes(b'synthetic filename fixture')
    def check_result(self,setup=''):
        result=self.invoke(setup+"r=f['check'](root)\nprint(json.dumps(r))")
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        return json.loads(result.stdout.splitlines()[-1])
    def test_missing_offline_wheels_never_creates_target(self):
        result=self.invoke("f['install'](root,offline=True)")
        self.assertNotEqual(result.returncode,0);self.assertIn('wheelhouse',result.stderr)
        self.assertFalse((self.root/'.felles-packages').exists())
    def test_bundled_pip_runs_without_site_packages_ensurepip_network_or_child_process(self):
        code=("import subprocess,socket\n"
              "sys.path[:]=[p for p in sys.path if 'site-packages' not in p]\n"
              "sys.modules['ensurepip']=None\n"
              "def blocked(*a,**k):raise AssertionError('network or child process')\n"
              "subprocess.Popen=blocked\nsocket.create_connection=blocked\n"
              "assert __import__('importlib').util.find_spec('pip') is None\n"
              "before=list(sys.path);argv=list(sys.argv)\n"
              "assert f['_run_pip'](root,['--version'])==0\n"
              "assert sys.path==before and sys.argv==argv\n"
              "assert not any(n=='pip' or n.startswith('pip.') for n in sys.modules)\n")
        result=self.invoke(code)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        self.assertIn('pip 26.2.2',result.stdout)
    def test_modified_bundled_pip_is_rejected_before_execution(self):
        wheel=next((self.root/'packaging/vendor').glob('pip-*.whl'))
        wheel.write_bytes(b'not the official wheel')
        result=self.invoke("f['_run_pip'](root,['--version'])")
        self.assertNotEqual(result.returncode,0)
        self.assertIn('pip-pakken',result.stderr)
    def test_real_offline_install_with_no_pip_or_ensurepip_keeps_global_packages_untouched(self):
        (self.root/'requirements-desktop.txt').write_text('dragen-probe==1.0\n')
        wheels=self.root/'wheelhouse';wheels.mkdir()
        with zipfile.ZipFile(wheels/'dragen_probe-1.0-py3-none-any.whl','w') as wheel:
            wheel.writestr('dragen_probe.py','VALUE=42\n')
            wheel.writestr('dragen_probe-1.0.dist-info/METADATA','Metadata-Version: 2.1\nName: dragen-probe\nVersion: 1.0\n')
            wheel.writestr('dragen_probe-1.0.dist-info/WHEEL','Wheel-Version: 1.0\nGenerator: DRAGEN regression\nRoot-Is-Purelib: true\nTag: py3-none-any\n')
            wheel.writestr('dragen_probe-1.0.dist-info/RECORD','')
        result=self.invoke("import subprocess\nsys.path[:]=[p for p in sys.path if 'site-packages' not in p]\n"
                           "sys.modules['ensurepip']=None\n"
                           "def blocked(*a,**k):raise AssertionError('child process')\n"
                           "subprocess.Popen=blocked\n"
                           "assert f['install'](root,offline=True)==0\n"
                           "assert (f['package_dir'](root)/'dragen_probe.py').is_file()\n"
                           "assert __import__('importlib').util.find_spec('dragen_probe') is None\n"
                           "assert __import__('importlib').util.find_spec('pip') is None\n")
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        self.assertIn('DRAGEN ER FERDIG INSTALLERT',result.stdout)
    def test_shared_source_packages_are_never_used_or_renamed_and_each_user_installs_locally(self):
        (self.root/'requirements-desktop.txt').write_text('pip=='+ensurepip.version()+'\n')
        code=("shared=root/'.felles-packages'/('cp'+str(sys.version_info.major)+str(sys.version_info.minor)+'-amd64');shared.mkdir(parents=True)\n"
              "(shared/'locked.txt').write_text('another user is running this')\n"
              "from unittest.mock import patch\n"
              "def fake_pip(args):\n"
              " target=Path(args[args.index('--target')+1]);dist=target/'pip-test.dist-info';dist.mkdir()\n"
              " (dist/'METADATA').write_text('Name: pip\\nVersion: "+ensurepip.version()+"\\n')\n"
              " return 0\n"
              "with patch.object(Path,'rename',side_effect=PermissionError(5,'access denied')):\n"
              " assert f['install'](root,pip_main=fake_pip)==0\n"
              "selected=f['package_dir'](root)\nassert selected.is_relative_to((root/'user-local').resolve())\n"
              "assert (shared/'locked.txt').read_text()=='another user is running this'\n"
              "os.environ['LOCALAPPDATA']=str(root/'second-user')\n"
              "assert f['package_dir'](root)!=selected\n")
        result=self.invoke(code)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
    def test_github_source_without_wheelhouse_installs_online_in_same_interpreter(self):
        (self.root/'requirements-desktop.txt').write_text('pip=='+ensurepip.version()+'\n')
        code=("calls=[]\n"
              "def fake_pip(args):\n"
              " calls.append(args)\n"
              " target=Path(args[args.index('--target')+1]);dist=target/'pip-test.dist-info';dist.mkdir()\n"
              " (dist/'METADATA').write_text('Name: pip\\nVersion: "+ensurepip.version()+"\\n')\n"
              " return 0\n"
              "result=f['install'](root,pip_main=fake_pip)\n"
              "assert result==0\nassert len(calls)==1\n"
              "assert '--no-index' not in calls[0]\nassert '--find-links' not in calls[0]\n"
              "assert '--no-user' in calls[0] and '--no-deps' in calls[0]\n"
              "assert f['package_dir'](root).is_dir()\nprint('source-install-ok')")
        result=self.invoke(code)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        self.assertIn('source-install-ok',result.stdout)
        self.assertIn('DRAGEN ER FERDIG INSTALLERT',result.stdout)
        self.assertIn('START_DRAGEN.cmd',result.stdout)
    def test_already_installed_shows_completion_without_running_pip(self):
        (self.root/'requirements-desktop.txt').write_text('pip=='+ensurepip.version()+'\n')
        code=("t=f['package_dir'](root);dist=t/'pip-test.dist-info';dist.mkdir(parents=True)\n"
              "(dist/'METADATA').write_text('Name: pip\\nVersion: "+ensurepip.version()+"\\n')\n"
              "def forbidden(args):raise AssertionError('pip must not run')\n"
              "assert f['install'](root,pip_main=forbidden)==0\n")
        result=self.invoke(code)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        self.assertIn('DRAGEN ER FERDIG INSTALLERT',result.stdout)
    def test_reference_preparation_has_user_local_fallback_for_read_only_shared_sources(self):
        helper=self.root/'src/abl1_workstation/reference_bundle.py'
        helper.write_text("from pathlib import Path\nimport os\ndef bundled_reference(root,state_folder=None):\n if state_folder is None:raise PermissionError('Shared source is read only')\n state_folder=Path(state_folder)\n assert state_folder.is_relative_to(Path(os.environ['LOCALAPPDATA']).resolve())\n assert not state_folder.is_relative_to(Path(root)/'reference')\n return state_folder/'reference/hg19/chr9.fa'\n")
        result=self.invoke("f['_installation_finished'](root)")
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        self.assertIn('DRAGEN ER FERDIG INSTALLERT',result.stdout)
    def test_missing_packages_does_not_fall_back_to_global_qt(self):
        result=self.invoke("f['package_dir'](root).mkdir(parents=True)\nf['activate'](root)")
        self.assertNotEqual(result.returncode,0);self.assertIn('Mangler lokale',result.stderr)
    def test_partial_target_is_preserved_and_not_overwritten(self):
        (self.root/'wheelhouse').mkdir()
        result=self.invoke("t=f['package_dir'](root)\nt.mkdir(parents=True)\n(t/'bevar.txt').write_text('bevar')\nf['install'](root,pip_main=lambda args:7)")
        self.assertNotEqual(result.returncode,0);self.assertIn('Pakkeinstallasjonen feilet',result.stderr)
        self.assertNotIn('DRAGEN ER FERDIG INSTALLERT',result.stdout)
        self.assertIn('DRAGEN-INSTALLASJONEN BLE IKKE FULLFORT',result.stdout)
        self.assertEqual(next((self.root/'user-local').rglob('bevar.txt')).read_text(),'bevar')
    def test_repair_preserves_old_packages_and_ignores_an_abandoned_install_folder(self):
        (self.root/'requirements-desktop.txt').write_text('pip=='+ensurepip.version()+'\n')
        code=("t=f['package_dir'](root)\nt.mkdir(parents=True)\n(t/'bevar.txt').write_text('bevar')\n"
              "stale=t.with_name(t.name+'.installing');stale.mkdir();(stale/'old.txt').write_text('keep')\n"
              "def fake_pip(args):\n"
              " target=Path(args[args.index('--target')+1]);dist=target/'pip-test.dist-info';dist.mkdir()\n"
              " (dist/'METADATA').write_text('Name: pip\\nVersion: "+ensurepip.version()+"\\n')\n"
              " return 0\n"
              "assert f['install'](root,pip_main=fake_pip)==0\n"
              "assert (t/'bevar.txt').read_text()=='bevar'\n"
              "assert f['package_dir'](root)!=t\nassert not (f['package_dir'](root)/'bevar.txt').exists()\n"
              "assert (stale/'old.txt').read_text()=='keep'\n")
        result=self.invoke(code)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
    def test_loaded_qt_blocks_install(self):
        result=self.invoke("sys.modules['PyQt6']=object()\nf['install'](root)")
        self.assertNotEqual(result.returncode,0);self.assertIn('nytt Python FELLES',result.stderr)
        self.assertFalse((self.root/'.felles-packages').exists())

    def test_first_check_distinguishes_install_ready_from_start_ready_without_loading_qt(self):
        self.diagnostic_fixture()
        report=self.check_result()
        self.assertTrue(report['ready_for_install'])
        self.assertFalse(report['ready_for_start'])
        self.assertEqual(report['missing_packages'],['pip=='+ensurepip.version()])
        self.assertEqual(report['loaded_qt_modules'],[])
        self.assertFalse(report['dependency_imports_tested'])
        self.assertFalse((self.root/'.felles-packages').exists())
        stored=json.loads(Path(report['report_path']).read_text(encoding='utf-8'))
        self.assertEqual(stored,report)

    def test_check_accepts_bundled_installer_when_felles_has_no_pip(self):
        self.diagnostic_fixture()
        report=self.check_result("f['check'].__globals__['_pip_available']=lambda: False\n")
        self.assertFalse(report['pip_available'])
        self.assertTrue(report['ready_for_install'])

    def test_existing_packages_can_start_without_pip_wheels_or_writable_program_root(self):
        self.diagnostic_fixture()
        shutil.rmtree(self.root/'wheelhouse')
        code=("target=f['package_dir'](root)\n"
              "metadata=target/'pip-test.dist-info'\nmetadata.mkdir(parents=True)\n"
              "(metadata/'METADATA').write_text('Name: pip\\nVersion: "+ensurepip.version()+"\\n')\n"
              "f['check'].__globals__['_probe_writeability']=lambda root: (False,'synthetic read-only root')\n"
              "f['check'].__globals__['_pip_available']=lambda: False\n")
        report=self.check_result(code)
        self.assertTrue(report['ready_for_start'])
        self.assertFalse(report['ready_for_install'])
        self.assertFalse(report['project_writable'])
        self.assertEqual(report['missing_packages'],[])

    def test_wrong_platform_and_loaded_qt_make_both_readiness_states_false(self):
        self.diagnostic_fixture()
        code=("original=f['_runtime_info']\n"
              "f['check'].__globals__['_runtime_info']=lambda: dict(original(), architecture_bits=32, windows_x64=False)\n"
              "sys.modules['PyQt6']=object()\n")
        report=self.check_result(code)
        self.assertFalse(report['ready_for_start'])
        self.assertFalse(report['ready_for_install'])
        self.assertTrue(report['loaded_qt_modules'])
        self.assertTrue(any('64' in reason for reason in report['install_blockers']))

    def test_partial_install_is_reported_and_preserved(self):
        self.diagnostic_fixture()
        report=self.check_result("p=f['package_dir'](root).with_name(f['package_dir'](root).name+'.installing')\np.mkdir(parents=True)\n(p/'bevar.txt').write_text('bevar')\n")
        self.assertTrue(report['ready_for_install'])
        self.assertTrue(report['partial_install_exists'])
        self.assertEqual(next((self.root/'user-local').rglob('bevar.txt')).read_text(),'bevar')

    def test_failed_repair_keeps_active_generation_and_requirement_changes_use_a_new_slot(self):
        (self.root/'requirements-desktop.txt').write_text('pip=='+ensurepip.version()+'\n')
        code=("slot=f['_package_slot'](root);slot.mkdir(parents=True)\n"
              "old=slot/('packages-'+'a'*32);old.mkdir()\n(old/'keep.txt').write_text('running app')\n"
              "f['_select_packages'](slot,old)\n"
              "try:f['install'](root,pip_main=lambda args:7)\nexcept RuntimeError:pass\n"
              "assert f['package_dir'](root)==old\nassert (old/'keep.txt').read_text()=='running app'\n"
              "(root/'requirements-desktop.txt').write_text('pip==0.0.0\\n')\n"
              "assert f['_package_slot'](root)!=slot\n")
        result=self.invoke(code)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)

    def test_free_threaded_python_is_not_reported_ready_for_regular_cpython_wheels(self):
        self.diagnostic_fixture()
        report=self.check_result("original=f['_runtime_info']\nf['check'].__globals__['_runtime_info']=lambda: dict(original(), free_threaded=True)\n")
        self.assertFalse(report['ready_for_install'])
        self.assertFalse(report['ready_for_start'])
        self.assertTrue(any('fri-trådet' in reason for reason in report['install_blockers']))

    def test_wrong_python_wheel_is_not_treated_as_install_ready(self):
        self.diagnostic_fixture()
        shutil.rmtree(self.root/'wheelhouse');(self.root/'wheelhouse').mkdir()
        (self.root/'wheelhouse'/('pip-'+ensurepip.version()+'-cp399-cp399-win_amd64.whl')).write_bytes(b'synthetic')
        report=self.check_result()
        self.assertFalse(report['ready_for_install'])
        self.assertEqual(report['missing_wheels'],['pip=='+ensurepip.version()])

    def test_report_and_failure_logs_fall_back_when_program_log_folder_is_unavailable(self):
        self.diagnostic_fixture()
        (self.root/'work').write_text('blocks log directory')
        report=self.check_result()
        self.assertTrue(Path(report['report_path']).is_file())
        self.assertFalse(Path(report['report_path']).is_relative_to(self.root))
        result=self.invoke("print(f['entry']('unknown-action',root))")
        self.assertEqual(result.returncode,0)
        self.assertIn('felles.log',result.stdout)
        self.assertIn('1',result.stdout.splitlines()[-1])

    def test_failed_entry_persists_traceback_with_action(self):
        result=self.invoke("print(f['entry']('start',root))")
        self.assertEqual(result.returncode,0)
        self.assertEqual(result.stdout.splitlines()[-1],'1')
        log=(self.root/'work/launcher-logs/felles.log').read_text(encoding='utf-8')
        self.assertIn('action=start',log)
        self.assertIn('Traceback',log)
        self.assertIn('INSTALL_DRAGEN.cmd',log)

    def test_check_does_not_import_qt_or_pip_or_start_processes_or_network(self):
        self.diagnostic_fixture()
        code=("import builtins,socket,subprocess\n"
              "original_import=builtins.__import__\n"
              "def guarded_import(name,*args,**kwargs):\n"
              "    if name=='pip' or name.startswith('PyQt6'):raise AssertionError('unexpected package import')\n"
              "    return original_import(name,*args,**kwargs)\n"
              "def blocked(*args,**kwargs):raise AssertionError('unexpected process or network')\n"
              "builtins.__import__=guarded_import\nsubprocess.Popen=blocked\nsocket.socket=blocked\n")
        report=self.check_result(code)
        self.assertTrue(report['ready_for_install'])
        self.assertFalse(report['gui_started'])
        self.assertFalse(report['network_used'])


if __name__=='__main__':unittest.main()
