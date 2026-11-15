"""A completed search owns both its durable pictures and its browser cleanup."""
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from abl1_workstation.lookup_browser import PortalBrowser,login_status
from abl1_workstation.evidence_store import EvidenceStore

V={'assembly':'GRCh37','chrom':'9','pos':133748283,'ref':'C','alt':'T'}
PAGE={'url':'https://www.ncbi.nlm.nih.gov/clinvar/variation/12624/',
      'text':'NC_000009.11:g.133748283C>T','ready_state':'complete'}


class Page:
    def __init__(self):self.closed=False;self.captures=0;self.page=PAGE
    def snapshot(self):return self.page
    def is_alive(self):return not self.closed
    def navigate(self,url):pass
    def evidence_views(self,provider):yield 'Variantresultat',None
    def capture_png(self,path,**kwargs):
        self.captures+=1;Path(path).write_bytes(b'\x89PNG\r\n\x1a\nsynthetic')
    def close(self):self.closed=True


class CompletionTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.browser=PortalBrowser(self.temp.name)
        self.page=Page();self.browser._contexts['clinvar']=self.page
        self.result={'provider':'clinvar','status':'found','identity':V,'url':PAGE['url']}
    def tearDown(self):self.browser.close();self.temp.cleanup()

    def test_successful_public_capture_is_saved_before_its_window_closes(self):
        saved_at_close=[]
        def close():
            saved_at_close.extend(EvidenceStore(self.temp.name).load(V));self.page.closed=True
        self.page.close=close
        with patch.object(self.browser,'_context',return_value=self.page):
            result=self.browser.capture_result('clinvar',V,self.result)
        self.assertTrue(Path(result['screenshot']).is_file())
        self.assertTrue(self.page.closed)
        self.assertNotIn('clinvar',self.browser._contexts)
        self.assertEqual(saved_at_close[0]['screenshot'],result['screenshot'])
        self.assertNotIn('screenshot_error',saved_at_close[0])

    def test_successful_manual_resume_also_closes_completed_window(self):
        result=self.browser.recapture_result('clinvar',V,self.result)
        self.assertTrue(Path(result['screenshot']).is_file());self.assertTrue(self.page.closed)

    def test_incomplete_capture_keeps_window_for_manual_resume(self):
        self.page.page={**PAGE,'text':'Verify you are human CAPTCHA'}
        with patch('abl1_workstation.lookup_browser.time.sleep'),patch('abl1_workstation.lookup_browser.time.monotonic',side_effect=[0,0,21]):
            result=self.browser.recapture_result('clinvar',V,self.result)
        self.assertEqual(result['screenshot_reason'],'manual_check_required')
        self.assertFalse(self.page.closed)

    def test_transient_picture_failure_retries_same_page_and_saves_one_picture(self):
        def capture(path,**kwargs):
            self.page.captures+=1
            if self.page.captures==1:raise ValueError('blank screenshot during reflow')
            Path(path).write_bytes(b'\x89PNG\r\n\x1a\nsynthetic')
        self.page.capture_png=capture
        with patch('abl1_workstation.lookup_browser.time.sleep'):
            result=self.browser.recapture_result('clinvar',V,self.result)
        self.assertEqual(self.page.captures,2)
        self.assertEqual(len(result.get('screenshots',[])),1)
        self.assertNotIn('screenshot_error',result)

    def test_retry_never_captures_changed_allele(self):
        def capture(path,**kwargs):
            self.page.captures+=1;self.page.page={**PAGE,'text':'NC_000009.11:g.133748283C>G'}
            raise ValueError('blank screenshot')
        self.page.capture_png=capture
        with patch('abl1_workstation.lookup_browser.time.sleep'):
            result=self.browser.recapture_result('clinvar',V,self.result)
        self.assertEqual(self.page.captures,1)
        self.assertEqual(result['screenshot_reason'],'identity_mismatch')
        self.assertFalse(self.page.closed)

    def test_public_franklin_home_does_not_confirm_a_login(self):
        result=login_status('franklin',{'url':'https://franklin.genoox.com/clinical-db/home',
                                      'franklin_search':True,'login_visible':True})
        self.assertEqual(result['status'],'logged_out')

    def test_franklin_rejected_saved_login_does_not_silently_use_public_results(self):
        self.browser._contexts['franklin']=self.page
        with patch.object(self.browser,'_context',return_value=self.page),patch.object(self.browser,'_has_saved_account',return_value=True),patch.object(self.browser,'_saved_login',return_value=False):
            result=self.browser.lookup('franklin',V)
        self.assertEqual(result['status'],'login_required');self.assertEqual(self.page.captures,0)

    def test_auto_closed_window_retains_its_last_confirmed_login_status(self):
        self.page.page={'url':'https://www.oncokb.org/','oncokb_account_visible':True}
        self.browser._contexts['oncokb']=self.page
        confirmed=self.browser.status('oncokb')
        self.browser._finish_result('oncokb',V,{**self.result,'provider':'oncokb','screenshot':'synthetic.png','capture_complete':True})
        status=self.browser.status('oncokb')
        self.assertEqual(status['status'],'last_confirmed')
        self.assertEqual(status['confirmed_at'],confirmed['checked_at'])
        self.assertIn('lagret',status['summary'])

    def test_image_retry_keeps_completed_sources_whose_windows_were_auto_closed(self):
        result=self.browser.recapture_result('clinvar',V,self.result)
        self.browser._contexts.clear()
        retried=self.browser.recapture_result('clinvar',V,result)
        self.assertEqual(retried,result)
        self.assertNotIn('screenshot_error',retried)

    def test_legacy_receipt_without_completion_marker_can_be_recaptured(self):
        result=self.browser.recapture_result('clinvar',V,self.result)
        result.pop('capture_complete',None)
        self.page.closed=False;self.browser._contexts['clinvar']=self.page
        retried=self.browser.recapture_result('clinvar',V,result)
        self.assertEqual(self.page.captures,2)
        self.assertTrue(retried.get('capture_complete'))


if __name__=='__main__':unittest.main()
