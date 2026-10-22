"""Native read pane must remain empty without supplied sequencing evidence."""
import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from pathlib import Path
import sys
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
from PyQt6.QtWidgets import QApplication
from abl1_workstation.domain import load_pilot
from abl1_workstation.read_view import ReadViewer,allowed_url,secure_asset,validate_svg

class PublicReadTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.app=QApplication.instance() or QApplication([])
    def test_synthetic_demo_never_grants_bundled_read_evidence(self):
        viewer=ReadViewer(enable_webengine=False)
        viewer.set_context(load_pilot(),{'sample':'DEMO-A','chrom':'chr9','pos':133748283})
        self.assertIsNone(viewer.report_path);self.assertIsNone(viewer.web_view);self.assertEqual(viewer.image_selector.count(),0)
        self.assertFalse(viewer.open_report_button.isEnabled());viewer.close()
    def test_local_resource_containment_and_external_network_block(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);asset=root/'demo.html';asset.write_text('<p>Synthetic</p>')
            self.assertTrue(allowed_url(asset.as_uri(),root))
            # Windows TEMP may use an 8.3 alias; verify the physical file identity.
            self.assertTrue(secure_asset(root,'demo.html').samefile(asset))
            self.assertFalse(allowed_url('https://example.org/',root));self.assertIsNone(secure_asset(root,'../outside.html'))
    def test_svg_accepts_static_shapes_and_rejects_active_content(self):
        self.assertTrue(validate_svg(b'<svg xmlns="http://www.w3.org/2000/svg"><rect width="2" height="2"/></svg>'))
        for bad in (b'<svg onload="alert(1)"/>',b'<svg><script/></svg>',b'<svg><image href="https://example.org/"/></svg>'):self.assertFalse(validate_svg(bad))

if __name__=='__main__':unittest.main()
