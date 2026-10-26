"""Startup bounds on laptops and multi-monitor desktops, without browser pages."""
import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from pathlib import Path
import sys
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from PyQt6.QtCore import QMargins, QRect
from PyQt6.QtWidgets import QApplication, QScrollArea
from abl1_workstation.domain import ReviewStore
from abl1_workstation import ui


class WindowGeometryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.app=QApplication.instance() or QApplication([])

    def test_first_show_keeps_actual_frame_and_statusbar_on_available_screen(self):
        with tempfile.TemporaryDirectory() as folder:
            window=ui.MainWindow(ReviewStore(Path(folder)/'reviews.sqlite'),browser_enabled=False)
            try:
                window.show();self.app.processEvents()
                available=window.screen().availableGeometry()
                self.assertTrue(available.contains(window.frameGeometry()),
                                (available.getRect(),window.frameGeometry().getRect()))
                status_top=window.statusBar().mapToGlobal(window.statusBar().rect().topLeft())
                status_bottom=window.statusBar().mapToGlobal(window.statusBar().rect().bottomRight())
                self.assertTrue(available.contains(status_top));self.assertTrue(available.contains(status_bottom))
                self.assertIsNone(window.read_viewer.web_view)
            finally:window.close();self.app.processEvents()

    def test_laptop_and_offset_monitors_keep_outer_frame_inside_target_screen(self):
        margins=QMargins(8,31,8,8)
        for available in (QRect(0,0,1366,728),QRect(-1366,100,1366,728),QRect(1920,-768,1366,728)):
            with self.subTest(available=available.getRect()):
                client=ui.initial_window_geometry(available,margins)
                self.assertTrue(available.contains(client.marginsAdded(margins)))
                self.assertGreaterEqual(client.width(),1050)
                self.assertGreaterEqual(client.height(),600)
                self.assertLess(client.width(),available.width())

    def test_large_desktop_retains_working_space_without_filling_screen(self):
        available=QRect(0,0,1920,1040);margins=QMargins(8,31,8,8)
        client=ui.initial_window_geometry(available,margins)
        self.assertEqual((client.width(),client.height()),(1500,940))
        outer=client.marginsAdded(margins)
        self.assertTrue(available.contains(outer));self.assertNotEqual(outer,available)

    def test_small_screen_content_is_reachable_by_native_scrollbars(self):
        with tempfile.TemporaryDirectory() as folder:
            window=ui.MainWindow(ReviewStore(Path(folder)/'reviews.sqlite'),browser_enabled=False)
            try:
                window.show();self.app.processEvents()
                scroll=window.centralWidget().findChild(QScrollArea)
                self.assertIsInstance(scroll,QScrollArea)
                window.resize(760,640);self.app.processEvents()
                # Both ends of a wider native workspace remain reachable.
                self.assertGreater(scroll.horizontalScrollBar().maximum(),0)
                scroll.horizontalScrollBar().setValue(scroll.horizontalScrollBar().maximum())
                self.app.processEvents()
                button_point=window.lookup_button.mapTo(scroll.viewport(),window.lookup_button.rect().center())
                self.assertTrue(scroll.viewport().rect().contains(button_point))
                scroll.horizontalScrollBar().setValue(0);self.app.processEvents()
                first_nav=window.analysis_button
                nav_point=first_nav.mapTo(window.centralWidget(),first_nav.rect().center())
                self.assertTrue(window.centralWidget().rect().contains(nav_point))
                footer=window.excel_button.mapTo(window.centralWidget(),window.excel_button.rect().bottomRight())
                self.assertTrue(window.centralWidget().rect().contains(footer))
            finally:window.close();self.app.processEvents()


if __name__=='__main__':unittest.main()
