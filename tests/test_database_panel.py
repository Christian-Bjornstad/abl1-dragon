import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from PyQt6.QtWidgets import QApplication
from abl1_workstation.database_panel import DatabasePanel


class FakeEdge:
    profile_dir = Path('C:/app data/EdgeProfil')

    def __init__(self): self.opened = []
    def diagnostics(self): return {'executable': 'C:/Edge/msedge.exe'}
    def open_url(self, url): self.opened.append(url)


class DatabasePanelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        root = Path(__file__).resolve().parents[1]
        self.providers = json.loads((root/'app/data/knowledge.json').read_text(encoding='utf-8'))['providers']
        self.edge = FakeEdge()
        self.panel = DatabasePanel(self.edge, self.providers)

    def tearDown(self): self.panel.close()

    def test_login_opens_home_only_and_does_not_claim_authentication(self):
        self.panel.providers.setCurrentIndex(self.panel.providers.findData('franklin'))
        self.panel.login_button.click()
        self.assertEqual(self.edge.opened, ['https://franklin.genoox.com/clinical-db/home'])
        self.assertIn('ikke kontrollert', self.panel.status.text())

    def test_allele_query_excludes_sample_identity_and_updates_on_variant_change(self):
        self.panel.providers.setCurrentIndex(self.panel.providers.findData('gnomad'))
        self.panel.set_variant({'sample':'PATIENT_UNIQUE', 'chrom':'chr9', 'pos':133748283,
                                'ref':'CT', 'alt':'TG', 'cdna':'c.944_945delinsTG', 'protein_snv_alone':'p.T315M'})
        self.panel.query_button.click()
        self.assertIn('9-133748283-CT-TG', self.edge.opened[-1])
        self.assertNotIn('PATIENT', self.edge.opened[-1])
        self.assertIn('CT>TG', self.panel.search_text.text())
        self.panel.set_variant(None)
        self.assertFalse(self.panel.query_button.isEnabled())
        self.assertEqual(self.panel.search_text.text(), '')

    def test_open_failure_is_visible_and_emits_no_success(self):
        def fail(url): raise OSError('Edge er blokkert')
        self.edge.open_url = fail
        self.panel.login_button.click()
        self.assertIn('Edge er blokkert', self.panel.status.text())
        self.assertNotIn('Nettleser åpnet', self.panel.status.text())

    def test_copy_text_uses_selected_multibase_allele(self):
        self.panel.set_variant({'chrom':'chr9','pos':133748283,'ref':'CT','alt':'TG',
                                'cdna':'c.944_945delinsTG','protein_snv_alone':'p.T315M'})
        self.panel.copy_button.click()
        self.assertIn('CT>TG', self.app.clipboard().text())
        self.assertIn('GRCh37', self.app.clipboard().text())


if __name__ == '__main__': unittest.main()
