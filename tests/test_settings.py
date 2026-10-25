import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from pathlib import Path
import sys,tempfile,unittest
import time
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from abl1_workstation.settings import Settings,SettingsPanel


class SettingsTests(unittest.TestCase):
    def test_bundled_reference_is_selected_without_copying_patient_files(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);reference=root/'reference/chr9.fa'
            reference.parent.mkdir();reference.write_text('>chr9\nA\n')
            with patch('abl1_workstation.settings.resource_root',return_value=root):
                self.assertEqual(Settings(root/'state').reference,str(reference))

    def test_only_non_secret_settings_survive_restart(self):
        with tempfile.TemporaryDirectory() as folder:
            settings=Settings(folder);settings.tokens={'franklin':'SECRET_TEST_TOKEN'}
            settings.providers=['clinvar','franklin'];settings.reference='D:/reference/chr9.fa'
            settings.save()
            self.assertNotIn('SECRET_TEST_TOKEN',settings.path.read_text())
            restored=Settings(folder);self.assertFalse(hasattr(restored,'tokens'))
            self.assertEqual(restored.providers,['clinvar','franklin'])
            self.assertEqual(restored.reference,settings.reference)
            self.assertNotIn('provider_modes',settings.path.read_text())

    def test_corrupt_settings_fall_back_without_credentials_or_browser_launch(self):
        with tempfile.TemporaryDirectory() as folder:
            Path(folder,'settings.json').write_text('{broken')
            settings=Settings(folder);self.assertFalse(hasattr(settings,'tokens'))
            self.assertEqual(settings.providers,['clinvar','gnomad','cosmic'])


class SettingsPanelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PyQt6.QtWidgets import QApplication
        cls.app=QApplication.instance() or QApplication([])

    def test_login_state_is_refreshed_without_credential_fields(self):
        from PyQt6.QtWidgets import QLineEdit
        class Browser:
            state='logged_out'
            def open_login(self,p):self.provider=p
            def status(self,p):return {'status':self.state,'summary':'Innlogget' if self.state=='logged_in' else 'Ikke innlogget'}
        with tempfile.TemporaryDirectory() as folder:
            browser=Browser();panel=SettingsPanel(Settings(folder),browser);panel.show()
            def finish():
                deadline=time.monotonic()+3
                while panel.busy and time.monotonic()<deadline:self.app.processEvents();time.sleep(.005)
                self.app.processEvents();self.assertFalse(panel.busy)
            self.app.processEvents();finish()
            panel.open_source('franklin');finish()
            self.assertEqual(browser.provider,'franklin')
            self.assertEqual(panel.status_labels['franklin'].text(),'Ikke innlogget')
            browser.state='logged_in';panel.refresh_status();finish()
            self.assertEqual(panel.status_labels['franklin'].text(),'Innlogget')
            self.assertEqual(panel.login_buttons['franklin'].text(),'Åpne')
            self.assertEqual(len(panel.findChildren(QLineEdit)),1)
            self.assertFalse(hasattr(panel,'tokens'));panel.close()
