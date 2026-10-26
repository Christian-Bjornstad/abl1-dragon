"""Exercise actual CMD branches with invisible synthetic executables, never real Ivanti."""
import os,shutil,subprocess,tempfile,time,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]

@unittest.skipUnless(os.name=='nt','Windows launcher')
class IvantiLaunchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory(prefix="DRAGEN fake Ivanti Å ")
        cls.folder=Path(cls.temp.name);cls.stub=cls.folder/'powershell.exe'
        # Windows subsystem prevents even a brief console window during tests.
        code='''using System; using System.IO; using System.Diagnostics;
        public class Stub { public static int Main(string[] args) {
          var name=Path.GetFileName(Process.GetCurrentProcess().MainModule.FileName);
          var output=Environment.GetEnvironmentVariable("DRAGEN_TEST_RECEIPT");
          File.WriteAllText(output+"."+name+".pid",Process.GetCurrentProcess().Id.ToString());
          File.WriteAllLines(output+"."+name,args);
          return name=="powershell.exe" ? Int32.Parse(Environment.GetEnvironmentVariable("DRAGEN_TEST_CLIPBOARD_EXIT")) : 0;
        }}'''
        source=cls.folder/'stub.cs';source.write_text(code)
        command='$ErrorActionPreference="Stop"; Add-Type -Path $env:DRAGEN_TEST_SOURCE -OutputAssembly $env:DRAGEN_TEST_EXE -OutputType WindowsApplication'
        result=subprocess.run(['powershell.exe','-NoProfile','-Command',command],env={**os.environ,'DRAGEN_TEST_SOURCE':str(source),'DRAGEN_TEST_EXE':str(cls.stub)},capture_output=True,timeout=30)
        if result.returncode:raise AssertionError(result.stderr.decode(errors='replace'))
    @classmethod
    def tearDownClass(cls):cls.temp.cleanup()
    def invoke(self,*,clipboard=0,legacy=False,action='START_DRAGEN.cmd'):
        with tempfile.TemporaryDirectory(prefix="DRAGEN launch O'Neil & Å ") as directory:
            folder=Path(directory);receipt=folder/'receipt'
            target=folder/'RES Software/Workspace Manager/pwrgate.exe' if legacy else folder/'pwrgate.exe'
            target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(self.stub,target)
            env={**os.environ,'PATH':str(self.folder)+os.pathsep+os.environ['PATH'],'ABL1_NO_PAUSE':'1',
                 'DRAGEN_TEST_RECEIPT':str(receipt),'DRAGEN_TEST_CLIPBOARD_EXIT':str(clipboard)}
            env.pop('DRAGEN_LOCAL_PYTHON',None);env.pop('ABL1_IVANTI_APP_ID',None)
            if legacy:
                env.pop('ABL1_IVANTI',None);env['ProgramFiles(x86)']=str(folder);env['ProgramFiles']=str(folder)
            else:env['ABL1_IVANTI']=str(target)
            result=subprocess.run(f'cmd.exe /d /s /c ""{ROOT/action}""',env=env,capture_output=True,timeout=15)
            record=Path(str(receipt)+'.pwrgate.exe');deadline=time.monotonic()+5
            while not record.exists() and time.monotonic()<deadline:time.sleep(.02)
            self.assertTrue(record.exists(),result.stdout+result.stderr)
            import ctypes
            from ctypes import wintypes
            kernel=ctypes.WinDLL('kernel32',use_last_error=True)
            kernel.OpenProcess.argtypes=[wintypes.DWORD,wintypes.BOOL,wintypes.DWORD];kernel.OpenProcess.restype=wintypes.HANDLE
            kernel.WaitForSingleObject.argtypes=[wintypes.HANDLE,wintypes.DWORD];kernel.WaitForSingleObject.restype=wintypes.DWORD
            kernel.CloseHandle.argtypes=[wintypes.HANDLE]
            handle=kernel.OpenProcess(0x00100000,False,int(Path(str(record)+'.pid').read_text()))
            if handle:
                try:self.assertEqual(kernel.WaitForSingleObject(handle,5000),0)
                finally:kernel.CloseHandle(handle)
            self.assertEqual(record.read_text().splitlines(),['15694'])
            self.assertTrue(Path(str(receipt)+'.powershell.exe').exists())
            return result
    def test_start_launches_ivanti_with_molstat_id(self):self.assertEqual(self.invoke().returncode,0)
    def test_install_discovers_legacy_res_path(self):self.assertEqual(self.invoke(legacy=True,action='INSTALL_DRAGEN.cmd').returncode,0)
    def test_clipboard_failure_still_opens_ivanti_and_prints_manual_command(self):
        result=self.invoke(clipboard=1)
        self.assertEqual(result.returncode,1)
        self.assertIn(b'Ivanti er startet',result.stderr)
        self.assertIn(b'import runpy;',result.stdout)

if __name__=='__main__':unittest.main()
