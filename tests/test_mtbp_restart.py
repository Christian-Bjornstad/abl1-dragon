"""Resuming a durable MTBP job in a newly launched, app-owned browser."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from abl1_workstation.lookup import canonical_identity
from abl1_workstation.mtbp import find_report, lookup_mtbp
from abl1_workstation.workflow import allele_key

V = {'assembly': 'GRCh37', 'chrom': '9', 'pos': 133748283, 'ref': 'C', 'alt': 'T',
     'cdna': 'c.944C>T', 'protein_snv_alone': 'p.T315I'}
JOB = {'analysis_id': 'DRAGEN-' + 'b' * 32, 'identity': canonical_identity(V),
       'query': 'NM_005157.6:c.944C>T', 'cancer_type': 'Blood'}
REPORT = 'https://mtbp.org/patients/123/sample/123/report/456/'
PAGE = {'url': REPORT, 'text': JOB['analysis_id'], 'ready_state': 'complete',
        'rows': [{'gene': 'ABL1', 'alteration': 'p.Thr315Ile', 'identity_text': 'p.Thr315Ile',
                  'section': 'Functionally relevant: 1', 'functional_evidence': 'Evidence A', 'biomarkers': 'Tier 1'}]}


class RestartPage:
    def __init__(self, *, needs_login=False):
        self.url = 'about:blank'
        self.urls = []
        self.needs_login = needs_login

    def navigate(self, url):
        self.urls.append(url)
        self.url = 'https://mtbp.org/login/' if self.needs_login else url

    def auth_snapshot(self):
        return {'url': self.url, 'ready_state': 'complete',
                'password_visible': self.needs_login and '/login' in self.url}

    def evaluate(self, expression):
        if not self.url.startswith('https://mtbp.org/'):
            raise RuntimeError('Unexpected source page')
        if 'const rows=' in expression:
            return PAGE if self.url == REPORT else None
        if 'const links=' in expression:
            return REPORT if self.url == 'https://mtbp.org/patients/' else None
        raise AssertionError('Unexpected evaluation')


class MtbpRestartTests(unittest.TestCase):
    def setup_job(self, folder, context):
        root = Path(folder) / 'evidence/databases' / allele_key(V)
        root.mkdir(parents=True)
        path = root / 'mtbp-job.json'
        path.write_text(json.dumps(JOB), encoding='utf-8')
        browser = Mock()
        browser.data_dir = Path(folder)
        browser._context.return_value = context
        return browser, path

    def test_existing_job_opens_trusted_report_list_before_reading_new_blank_context(self):
        with tempfile.TemporaryDirectory() as folder:
            context = RestartPage()
            browser, path = self.setup_job(folder, context)
            original = path.read_bytes()
            with patch('abl1_workstation.mtbp.submit') as submit, \
                 patch('abl1_workstation.mtbp.capture', side_effect=lambda c, v, j, p, r, root: r), \
                 patch('abl1_workstation.mtbp.time.sleep'):
                result = lookup_mtbp(browser, V, {'mtbp_wait_seconds': 5})
            self.assertEqual(result['status'], 'found')
            self.assertEqual(context.urls, ['https://mtbp.org/patients/', REPORT])
            self.assertEqual(path.read_bytes(), original)
            submit.assert_not_called()

    def test_existing_job_reuses_saved_login_once_without_resubmitting_analysis(self):
        with tempfile.TemporaryDirectory() as folder:
            context = RestartPage(needs_login=True)
            browser, path = self.setup_job(folder, context)
            original = path.read_bytes()
            def login(provider, page):
                self.assertEqual(provider, 'mtbp')
                context.needs_login = False
                context.url = 'https://mtbp.org/analyse/'
                return True
            browser._saved_login.side_effect = login
            with patch('abl1_workstation.mtbp.submit') as submit, \
                 patch('abl1_workstation.mtbp.capture', side_effect=lambda c, v, j, p, r, root: r), \
                 patch('abl1_workstation.mtbp.time.sleep'):
                result = lookup_mtbp(browser, V, {'mtbp_wait_seconds': 5})
            self.assertEqual(result['status'], 'found')
            browser._saved_login.assert_called_once_with('mtbp', context)
            submit.assert_not_called()
            self.assertEqual(path.read_bytes(), original)

    def test_existing_job_requires_login_if_saved_login_cannot_be_confirmed(self):
        with tempfile.TemporaryDirectory() as folder:
            context = RestartPage(needs_login=True)
            browser, path = self.setup_job(folder, context)
            original = path.read_bytes()
            browser._saved_login.return_value = False
            with patch('abl1_workstation.mtbp.submit') as submit, patch('abl1_workstation.mtbp.time.sleep'):
                result = lookup_mtbp(browser, V, {'mtbp_wait_seconds': 5})
            self.assertEqual(result['status'], 'login_required')
            browser._saved_login.assert_called_once_with('mtbp', context)
            submit.assert_not_called()
            self.assertEqual(path.read_bytes(), original)

    def test_new_blank_context_does_not_restart_navigation_while_response_is_pending(self):
        context = RestartPage()
        context.navigate = Mock()
        self.assertIsNone(find_report(context, JOB))
        self.assertIsNone(find_report(context, JOB))
        context.navigate.assert_called_once_with('https://mtbp.org/patients/')

    def test_unexpected_host_does_not_read_or_navigate_its_page(self):
        context = RestartPage()
        context.url = 'https://example.invalid/patients/'
        with patch.object(context, 'evaluate') as evaluate:
            with self.assertRaises(ValueError):
                find_report(context, JOB)
        evaluate.assert_not_called()
        self.assertEqual(context.urls, [])


if __name__ == '__main__':
    unittest.main()
