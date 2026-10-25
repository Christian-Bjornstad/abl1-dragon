"""Native workflow without automatic demo data or network calls."""
import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from pathlib import Path
import sys,tempfile,unittest
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
from PyQt6.QtWidgets import QApplication
from abl1_workstation.domain import ReviewStore,load_pilot
from abl1_workstation.ui import MainWindow
from abl1_workstation.workflow import allele_key

class PublicWindowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.app=QApplication.instance() or QApplication([])
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.folder=Path(self.temp.name)
        self.store=ReviewStore(self.folder/'reviews.sqlite');self.window=MainWindow(self.store,browser_enabled=False)
    def tearDown(self):
        self.window.close();self.app.processEvents();self.store.close();self.temp.cleanup()
    def test_start_is_empty_and_has_no_review_form(self):
        w=self.window
        self.assertIsNone(w.session);self.assertEqual(w.variant_model.rowCount(),0)
        self.assertFalse(w.excel_button.isEnabled());self.assertFalse(w.lookup_button.isEnabled())
        self.assertFalse(hasattr(w,'note'));self.assertFalse(hasattr(w,'review_status'))
        self.assertIsNone(w.read_viewer.web_view)
        self.assertEqual(len(w.nav_buttons),2)
        self.assertNotIn('Kontrollflagg',w.variant_model.HEADERS)
        self.assertFalse(hasattr(w,'run_status'))
    def test_explicit_session_filters_and_selected_identity_remain_correct(self):
        w=self.window;w._apply_session(load_pilot())
        self.assertEqual(w.variant_model.rowCount(),3)
        w.select_variant('DEMO-A',133748283)
        self.assertEqual(w.current_variant['protein_snv_alone'],'p.T315I')
        key=allele_key(w.current_variant)
        w._lookup_finished((key,[{'provider':'clinvar','status':'found','summary':'Synthetic class'}]))
        self.assertIn('Treff',w.source_badges['clinvar'].text())
        self.assertFalse(hasattr(w,'database_table'));self.assertFalse(hasattr(w,'detail_tabs'))
        w.select_variant('DEMO-B',133738330)
        self.assertIn('Ikke søkt',w.source_badges['clinvar'].text())
        self.assertIsNone(w.read_viewer.web_view)
    def test_empty_filter_clears_variant_and_database_results(self):
        w=self.window;w._apply_session(load_pilot());w.search.setText('NO MATCH POSSIBLE')
        self.assertIsNone(w.current_variant);self.assertEqual(w.source_badges,{})
        self.assertFalse(w.lookup_button.isEnabled())
    def test_new_run_clears_lookup_results(self):
        w=self.window;w._apply_session(load_pilot())
        w.lookup_results['old']=[{'status':'found'}];w._apply_session(load_pilot())
        self.assertEqual(w.lookup_results,{})

if __name__=='__main__':unittest.main()
