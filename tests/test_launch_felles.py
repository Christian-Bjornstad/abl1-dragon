"""Fresh-interpreter FELLES boundaries; no Ivanti, clipboard or global installs."""
from pathlib import Path
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
        code="import runpy,sys\nfrom pathlib import Path\nroot=Path(sys.argv[1])\nf=runpy.run_path(str(root/'packaging/felles.py'))\n"+body
        return subprocess.run([sys.executable,'-I','-c',code,str(self.root)],capture_output=True,encoding='utf-8',errors='replace',timeout=30)
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


if __name__=='__main__':unittest.main()
