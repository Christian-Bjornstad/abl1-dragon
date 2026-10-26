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
            reference=Path(folder)/'custom.fa';reference.write_text('>chr9\nA\n')
            Path(str(reference)+'.fai').write_text('chr9\t1\t6\t1\t2\n')
            settings.providers=['clinvar','franklin'];settings.reference=str(reference)
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
    def test_open_saves_typed_account_before_browser_login_without_extra_save_click(self):
        from abl1_workstation.credentials import CredentialStore
        from test_credentials import MemoryVault
        class Browser:
            def set_credentials(self,store):self.store=store
            def open_login(self,p):self.account=self.store.get(p)
            def status(self,p):return {'status':'logged_out','summary':'Ikke innlogget'}
        with tempfile.TemporaryDirectory() as folder:
            vault=CredentialStore(folder,backend=MemoryVault());browser=Browser()
            panel=SettingsPanel(Settings(folder),browser,credential_store=vault)
            panel.emails['franklin'].setText('synthetic@example.invalid');panel.passwords['franklin'].setText('SYNTHETIC_ONLY')
            panel.open_source('franklin')
            deadline=time.monotonic()+3
            while panel.busy and time.monotonic()<deadline:self.app.processEvents();time.sleep(.005)
            self.assertFalse(panel.busy);self.assertEqual(browser.account,('synthetic@example.invalid','SYNTHETIC_ONLY'))
            self.assertEqual(panel.passwords['franklin'].text(),'');panel.close()
    def test_saved_account_is_restored_masked_and_can_be_forgotten_without_json_secrets(self):
        from abl1_workstation.credentials import CredentialStore
        from test_credentials import MemoryVault
        with tempfile.TemporaryDirectory() as folder:
            vault=CredentialStore(folder,backend=MemoryVault());settings=Settings(folder)
            panel=SettingsPanel(settings,object(),credential_store=vault)
            panel.emails['franklin'].setText('synthetic@example.invalid');panel.passwords['franklin'].setText('SYNTHETIC_ONLY')
            panel.save_login('franklin');settings.save()
            self.assertEqual(panel.passwords['franklin'].text(),'');self.assertIn('Lagret',panel.passwords['franklin'].placeholderText())
            panel.close();restored=SettingsPanel(Settings(folder),object(),credential_store=vault)
            self.assertEqual(restored.emails['franklin'].text(),'synthetic@example.invalid')
            self.assertEqual(restored.passwords['franklin'].text(),'')
            self.assertNotIn('SYNTHETIC_ONLY',settings.path.read_text())
            restored.forget_login('franklin');self.assertEqual(vault.get('franklin'),('',''));restored.close()
    def test_source_statuses_are_independent_and_prior_confirmation_is_identified(self):
        with tempfile.TemporaryDirectory() as folder:
            panel=SettingsPanel(Settings(folder),object())
            first={'status':'logged_in','summary':'Innlogget','checked_at':'2026-10-25T18:00:00Z'}
            panel._results({'franklin':first})
            panel._results({'oncokb':dict(first)})
            self.assertEqual(panel.status_labels['franklin'].text(),'Innlogget')
            previous={'status':'last_confirmed','summary':'Innlogget · sist bekreftet 19:00',
                      'confirmed_at':first['checked_at'],'checked_at':'2026-10-25T18:00:06Z'}
            panel._results({'franklin':previous})
            self.assertIn('sist bekreftet',panel.status_labels['franklin'].text())
            self.assertEqual(panel.login_buttons['franklin'].text(),'Åpne')
            self.assertIn(first['checked_at'],panel.status_labels['franklin'].toolTip())
            self.assertEqual(panel.status_labels['oncokb'].text(),'Innlogget')
            panel._results({'franklin':{'status':'logged_out','summary':'Ikke innlogget'}})
            self.assertEqual(panel.login_buttons['franklin'].text(),'Åpne / logg inn')
            self.assertEqual(panel.status_labels['oncokb'].text(),'Innlogget');panel.close()

    @classmethod
    def setUpClass(cls):
        from PyQt6.QtWidgets import QApplication
        cls.app=QApplication.instance() or QApplication([])

    def test_login_state_is_refreshed_with_masked_credential_fields(self):
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
            self.assertEqual(len(panel.findChildren(QLineEdit)),9)
            self.assertTrue(all(field.echoMode()==QLineEdit.EchoMode.Password for field in panel.passwords.values()))
            self.assertFalse(hasattr(panel,'tokens'));panel.close()
