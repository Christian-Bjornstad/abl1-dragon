import runpy,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]

class DependencyIsolationTests(unittest.TestCase):
    def setUp(self):self.f=runpy.run_path(str(ROOT/'packaging/felles.py'))
    def test_shared_hemafrag_and_user_packages_are_excluded_from_runtime_path(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);target=root/'.felles-packages/cp314';hema=root/'HemaFrag';user=root/'user/site-packages'
            with patch.object(sys,'path',[str(hema),str(user),str(Path(sys.base_prefix)/'Lib/site-packages'),str(Path(sys.base_prefix)/'DLLs'),'']):
                paths=self.f['_isolated_paths'](root,target)
            self.assertEqual(paths[:2],[str(root/'src'),str(target)])
            self.assertNotIn(str(hema),paths);self.assertNotIn(str(user),paths)
            self.assertFalse(any('site-packages' in p for p in paths[2:]))
    def test_preloaded_pillow_or_openpyxl_is_rejected_before_activation(self):
        for name in ('PIL','openpyxl','websocket','PyQt6'):
            with patch.dict(sys.modules,{name:object()}):self.assertIn(name,self.f['_loaded_app_modules']())
    def test_offline_install_ignores_shared_resolver_and_never_installs_numpy(self):
        source=(ROOT/'packaging/felles.py').read_text()
        self.assertIn("'--no-deps'",source);self.assertIn("'--ignore-installed'",source)
        requirements=(ROOT/'requirements-desktop.txt').read_text().lower()
        self.assertNotIn('numpy',requirements);self.assertNotIn('pandas',requirements)

if __name__=='__main__':unittest.main()
