"""Fresh-interpreter FELLES boundaries; no Ivanti, clipboard or global installs."""
from pathlib import Path
import ensurepip
import json
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]


class FellesTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(prefix='FELLES Å ');self.root=Path(self.tmp.name)
        shutil.copytree(ROOT/'packaging',self.root/'packaging')
        for name in ('pyproject.toml','requirements-desktop.txt','start_abl1.py'):shutil.copyfile(ROOT/name,self.root/name)
        (self.root/'src/abl1_workstation').mkdir(parents=True)
    def tearDown(self):self.tmp.cleanup()
    def invoke(self,body):
        code="import json,runpy,sys\nfrom pathlib import Path\nroot=Path(sys.argv[1])\nf=runpy.run_path(str(root/'packaging/felles.py'))\n"+body
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
        result=self.invoke("f['install'](root)")
        self.assertNotEqual(result.returncode,0);self.assertIn('wheelhouse',result.stderr)
        self.assertFalse((self.root/'.felles-packages').exists())
    def test_missing_packages_does_not_fall_back_to_global_qt(self):
        result=self.invoke("f['package_dir'](root).mkdir(parents=True)\nf['activate'](root)")
        self.assertNotEqual(result.returncode,0);self.assertIn('Mangler lokale',result.stderr)
    def test_partial_target_is_preserved_and_not_overwritten(self):
        (self.root/'wheelhouse').mkdir()
        result=self.invoke("t=f['package_dir'](root)\nt.mkdir(parents=True)\n(t/'bevar.txt').write_text('bevar')\nf['install'](root)")
        self.assertNotEqual(result.returncode,0);self.assertIn('Ufullstendig',result.stderr)
        self.assertEqual(next((self.root/'.felles-packages').rglob('bevar.txt')).read_text(),'bevar')
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
        self.assertFalse(report['ready_for_install'])
        self.assertTrue(report['partial_install_exists'])
        self.assertEqual(next((self.root/'.felles-packages').rglob('bevar.txt')).read_text(),'bevar')

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
        self.assertIn('Installer med Python FELLES.cmd',log)

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
