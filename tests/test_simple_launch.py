"""Public entrypoints: two CMDs and same-interpreter Python FELLES execution."""
import os,runpy,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]

class SimpleLaunchTests(unittest.TestCase):
    def test_only_install_and_start_cmd_are_present_in_main_folder(self):
        self.assertEqual({p.name for p in ROOT.glob('*.cmd')},{'INSTALL_DRAGEN.cmd','START_DRAGEN.cmd'})
    def test_python_entrypoints_call_same_interpreter_helpers_and_preserve_result(self):
        for action in ('start','install'):
            module=runpy.run_path(str(ROOT/(action+'.py')))
            calls=[]
            def entry(*args,**kwargs):calls.append((args,kwargs));return 7
            with patch('runpy.run_path',return_value={'entry':entry}) as loader:
                result=module['main'](['--data-dir','synthetic & data']) if action=='start' else module['main']()
            self.assertEqual(result,7);self.assertEqual(calls[0][0],(action,ROOT))
            if action=='start':self.assertEqual(calls[0][1]['argv'],['--data-dir','synthetic & data'])
            self.assertEqual(Path(loader.call_args.args[0]),ROOT/'packaging/felles.py')
    def test_ivanti_clipboard_command_roundtrips_special_path_without_shell_interpolation(self):
        import base64
        path="D:/Lab O'Neil & prøve Å/install.py"
        value=base64.b64encode(path.encode()).decode()
        statement="import runpy,base64; runpy.run_path(base64.b64decode('"+value+"').decode('utf-8'),run_name='dragen_felles')['main']()"
        with patch('runpy.run_path',return_value={'main':lambda:0}) as runner:exec(statement,{})
        self.assertEqual(runner.call_args.args[0],path)
        source=(ROOT/'packaging/desktop.cmd').read_text()
        self.assertIn('$env:ABL1_FELLES_SCRIPT',source)
        self.assertIn('set "ABL1_IVANTI_APP_ID=15694"',source)
        self.assertNotIn('ExecutionPolicy Bypass',source)
    def test_missing_source_exits_without_starting_ivanti_or_a_python_process(self):
        if os.name!='nt':self.skipTest('Windows CMD')
        import shutil,subprocess
        with tempfile.TemporaryDirectory(prefix="DRAGEN O'Neil & Å ") as folder:
            root=Path(folder);(root/'packaging').mkdir()
            for name in ('START_DRAGEN.cmd','INSTALL_DRAGEN.cmd'):shutil.copyfile(ROOT/name,root/name)
            shutil.copyfile(ROOT/'packaging/desktop.cmd',root/'packaging/desktop.cmd')
            for name in ('START_DRAGEN.cmd','INSTALL_DRAGEN.cmd'):
                result=subprocess.run(f'cmd.exe /d /s /c ""{root/name}""',env={**os.environ,'ABL1_NO_PAUSE':'1'},capture_output=True,timeout=10)
                self.assertEqual(result.returncode,1)
                self.assertIn(b'Pakk ut hele DRAGEN',result.stderr)

if __name__=='__main__':unittest.main()
