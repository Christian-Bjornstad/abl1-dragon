import os,sys,tempfile,time,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication
from abl1_workstation.domain import ReviewStore,load_pilot
from abl1_workstation.ui import MainWindow
from abl1_workstation.workflow import allele_key

class BatchWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.app=QApplication.instance() or QApplication([])
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.folder=Path(self.temp.name)
        self.store=ReviewStore(self.folder/'state.sqlite');self.window=MainWindow(self.store,browser_enabled=False)
        session=load_pilot();v=session.data['variants'][0];session.data['variants']=[v,{**v,'sample':'Other'}]
        self.window._apply_session(session)
    def tearDown(self):
        self.window.close();self.app.processEvents();self.store.close();self.temp.cleanup()
    def finish(self):
        deadline=time.monotonic()+5
        while (self.window.loading or self.window.thread is not None) and time.monotonic()<deadline:
            self.app.processEvents();time.sleep(.005)
        self.app.processEvents();self.assertFalse(self.window.loading)
    def test_marks_survive_filter_and_batch_queries_each_allele_once(self):
        w=self.window;self.assertFalse(w.lookup_button.isEnabled());w.mark_visible()
        self.assertEqual(len(w.variant_model.selected_rows()),2)
        w.search.setText('no visible result');self.assertEqual(len(w.variant_model.selected_rows()),2)
        with patch('abl1_workstation.lookup.LookupService.lookup',return_value=[{'provider':'clinvar','status':'not_found'}]) as lookup:
            w.lookup_selected();self.finish();self.assertEqual(lookup.call_count,1)
        self.assertEqual(len(w.lookup_results),1)
        w.clear_marks();self.assertFalse(w.excel_button.isEnabled())
    def test_export_captures_each_sample_instead_of_reusing_current_variant(self):
        from PyQt6.QtGui import QImage,QColor
        from openpyxl import load_workbook
        w=self.window;w.mark_visible();w.settings.reference='synthetic_reference'
        w.run_files=SimpleNamespace(alignments={s:SimpleNamespace(sample=s) for s in ('DEMO-A','Other')})
        viewer=w.read_viewer;captured=[]
        def show(alignment,reference,variant):
            viewer.current_alignment=alignment;viewer.save_image_button.setEnabled(True);captured.append((alignment.sample,variant['sample']))
        def capture(path,callback):
            image=QImage(160,100,QImage.Format.Format_RGB32);image.fill(QColor('gray'));image.save(str(path));callback(str(path),None)
        path=self.folder/'selected.xlsx'
        with patch.object(viewer,'show_alignment',side_effect=show),patch.object(viewer,'capture_png',side_effect=capture):
            w.start_export(path);self.finish()
        self.assertEqual(captured,[('DEMO-A','DEMO-A'),('Other','Other')])
        book=load_workbook(path);self.assertEqual(len(book.worksheets),2)
        self.assertEqual([len(s._images) for s in book.worksheets],[1,1]);book.close()
        self.assertEqual(w.pages.currentIndex(),0)
    def test_cancelled_export_never_creates_a_partial_workbook(self):
        w=self.window;w.mark_visible();path=self.folder/'cancelled.xlsx'
        w.start_export(path);w.cancel_export();self.app.processEvents()
        self.assertFalse(path.exists());self.assertIsNone(w._export);self.assertFalse(w.loading)

if __name__=='__main__':unittest.main()
