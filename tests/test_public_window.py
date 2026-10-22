"""Native public demo checks: invented data and no browser activity."""
import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from pathlib import Path
import sys
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
from PyQt6.QtWidgets import QApplication
from abl1_workstation.domain import ReviewStore,load_inputs,save_project
from abl1_workstation.ui import MainWindow

class PublicWindowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.app=QApplication.instance() or QApplication([])
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.folder=Path(self.temp.name)
        self.store=ReviewStore(self.folder/'reviews.sqlite');self.window=MainWindow(self.store,browser_enabled=False)
    def tearDown(self):
        self.window.close();self.app.processEvents();self.store.close();self.temp.cleanup()
    def test_window_has_only_explicit_demo_rows_without_read_ground_truth(self):
        window=self.window
        self.assertEqual(window.variant_model.rowCount(),3);self.assertEqual(window.sample_table.rowCount(),2)
        self.assertIn('Syntetisk',window.overview_notice.text())
        self.assertEqual(window.session.data['qc'],[]);self.assertEqual(window.session.data['phase_rows'],[]);self.assertEqual(window.session.data['read_rows'],[])
        window.select_variant('DEMO-A',133748283);self.assertEqual(window.current_variant['protein_snv_alone'],'p.T315I')
        window.navigate(2)
        self.assertIsNone(window.read_viewer.report_path);self.assertIsNone(window.read_viewer.web_view);self.assertEqual(window.read_viewer.image_selector.count(),0)
    def test_source_panel_tracks_selected_demo_allele_without_sending_label(self):
        window=self.window;window.select_variant('DEMO-A',133748283);window.navigate(3)
        self.assertEqual(window.source_scope.count(),1)
        self.assertIn('C>T',window.database_panel.search_text.text());self.assertNotIn('DEMO-',window.database_panel.search_text.text())
        window.select_variant('DEMO-B',133738330);window.navigate(3)
        self.assertIn('A>G',window.database_panel.search_text.text());self.assertNotIn('C>T',window.database_panel.search_text.text())
        self.assertNotIn('DEMO-',window.database_panel.search_text.text())
    def test_note_and_review_status_survive_project_roundtrip(self):
        window=self.window;window.select_variant('DEMO-B',133738330)
        window.note.setPlainText('Synthetic review note');window.reviewer.setText('TEST');window.review_status.setCurrentText('Trenger oppfølging');window.save_review()
        project=self.folder/'demo.abl1.json';save_project(window.session,self.store,project)
        restored=load_inputs([project]);self.assertFalse(restored.is_pilot);self.assertEqual(len(restored.pending_reviews),1)
        window._apply_session(restored);window.select_variant('DEMO-B',133738330)
        self.assertEqual(window.note.toPlainText(),'Synthetic review note');self.assertEqual(window.review_status.currentText(),'Trenger oppfølging')

if __name__=='__main__':unittest.main()
