"""Screenshot status and restart receipts must describe the page actually captured."""
import io
import sys
import tempfile
import unittest
from pathlib import Path

from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from abl1_workstation.evidence_store import EvidenceStore
from abl1_workstation.lookup_browser import PortalBrowser, parse_portal_snapshot


V = {'assembly': 'GRCh37', 'chrom': '9', 'pos': 133748283, 'ref': 'C', 'alt': 'T'}
PAGE = {
    'url': 'https://www.oncokb.org/hgvsg/9:g.133748283C%3ET?refGenome=GRCh37',
    'text': 'GRCh37\n9:g.133748283C>T\nOncogenicity\nOncogenic',
    'ready_state': 'complete',
}
NEGATIVE_PAGE = {**PAGE, 'text': 'GRCh37\n9:g.133748283C>T\nNo matching variant'}


def picture():
    image = Image.new('RGB', (600, 240), 'white')
    ImageDraw.Draw(image).rectangle((20, 20, 400, 100), fill='purple')
    stream = io.BytesIO()
    image.save(stream, format='PNG')
    return stream.getvalue()


class Page:
    def __init__(self):
        self.current = PAGE
        self.captures = 0

    def snapshot(self): return self.current
    def is_alive(self): return True
    def close(self): pass

    def capture_png(self, path, **options):
        self.captures += 1
        Path(path).write_bytes(picture())


class CaptureReceiptTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.browser = PortalBrowser(self.temp.name)

    def tearDown(self):
        self.browser.close()
        self.temp.cleanup()

    def result(self):
        return {'provider': 'oncokb', **parse_portal_snapshot('oncokb', V, PAGE)}

    def test_negative_current_page_cannot_supply_picture_for_previous_positive_result(self):
        page = Page()
        page.current = NEGATIVE_PAGE
        self.browser._contexts['oncokb'] = page

        result = self.browser.recapture_result('oncokb', V, self.result())

        self.assertEqual(page.captures, 0)
        self.assertNotIn('screenshot', result)
        self.assertIn('screenshot_error', result)

    def test_page_turning_negative_between_views_cannot_add_negative_picture(self):
        class ChangedPage(Page):
            def evidence_views(self, provider):
                yield 'Verified overview', None
                self.current = NEGATIVE_PAGE
                yield 'No matching variant', None

        page = ChangedPage()
        result = self.browser._capture('oncokb', V, page, self.result())

        self.assertEqual(page.captures, 1)
        self.assertEqual([r['label'] for r in result['screenshots']], ['Verified overview'])
        self.assertIn('screenshot_error', result)

    def test_interrupted_multi_view_capture_has_partial_status_in_restart_receipt(self):
        class InterruptedPage(Page):
            def evidence_views(self, provider):
                yield 'Verified overview', None
                raise KeyboardInterrupt('simulate interruption before the remaining views')

        with self.assertRaises(KeyboardInterrupt):
            self.browser._capture('oncokb', V, InterruptedPage(), self.result())

        saved = EvidenceStore(self.temp.name).load(V)[0]
        self.assertEqual(len(saved['screenshots']), 1)
        self.assertTrue(Path(saved['screenshot']).is_file())
        self.assertEqual(saved.get('screenshot_reason'), 'partial_capture')
        self.assertTrue(saved.get('screenshot_error'))

    def test_successful_capture_clears_previous_error_in_return_value_and_restart_receipt(self):
        class CompletePage(Page):
            def evidence_views(self, provider):
                yield 'Verified overview', None
                yield 'Verified details', None

        previous = {**self.result(), 'screenshot_reason': 'capture_failed',
                    'screenshot_error': 'Previous attempt did not finish'}
        result = self.browser._capture('oncokb', V, CompletePage(), previous)

        saved = EvidenceStore(self.temp.name).load(V)[0]
        for receipt in (result, saved):
            self.assertEqual(len(receipt['screenshots']), 2)
            self.assertNotIn('screenshot_reason', receipt)
            self.assertNotIn('screenshot_error', receipt)


if __name__ == '__main__':
    unittest.main()
