import sys,tempfile,unittest
from pathlib import Path
from unittest.mock import Mock,patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from abl1_workstation.mtbp import parse_report,lookup_mtbp
from abl1_workstation.lookup import canonical_identity

V={'assembly':'GRCh37','chrom':'9','pos':133748283,'ref':'C','alt':'T',
   'cdna':'c.944C>T','protein_snv_alone':'p.T315I','sample':'NEVER_SEND'}
JOB={'analysis_id':'DRAGEN-'+'a'*32,'identity':canonical_identity(V),'query':'NM_005157.6:c.944C>T','cancer_type':'Blood'}
ROW={'gene':'ABL1','alteration':'p.Thr315Ile','identity_text':'p.Thr315Ile','section':'Functionally relevant: 1',
     'functional_evidence':'Evidence A','biomarkers':'Tier 1'}
PAGE={'url':'https://mtbp.org/patients/123/report/456/','text':JOB['analysis_id'],'rows':[ROW],'ready_state':'complete'}

class MtbpTests(unittest.TestCase):
    def test_one_requested_protein_is_bound_to_own_pseudonymous_report_and_query(self):
        result=parse_report(V,JOB,PAGE)
        self.assertEqual(result['status'],'found');self.assertTrue(result['identity_verified'])
        self.assertIn('protein',result['identity_method'].lower())
        self.assertEqual(result['url'],'');self.assertNotIn('/patients/',str(result))
        self.assertNotIn('NEVER_SEND',str(result));self.assertIn('Tier 1',result['summary'])
    def test_wrong_report_wrong_protein_conflicting_cdna_or_duplicate_row_is_rejected(self):
        for change in ({'text':'another analysis'},{'rows':[{**ROW,'alteration':'T315M','identity_text':'T315M'}]},
                       {'rows':[{**ROW,'identity_text':'NM_005157.6:c.944C>G p.T315I'}]},
                       {'rows':[{**ROW,'identity_text':'c.944C>T p.T315M'}]},
                       {'rows':[ROW,ROW]},{'url':'https://evil.invalid/patients/123/report/456/'}):
            self.assertNotEqual(parse_report(V,JOB,{**PAGE,**change})['status'],'found')
    def test_pending_job_is_resumed_without_submitting_another_report(self):
        import json
        from abl1_workstation.workflow import allele_key
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)/'evidence/databases'/allele_key(V);root.mkdir(parents=True)
            (root/'mtbp-job.json').write_text(json.dumps(JOB))
            browser=Mock();browser.data_dir=Path(folder);context=Mock();browser._context.return_value=context
            with patch('abl1_workstation.mtbp.find_report',return_value=None),patch('abl1_workstation.mtbp.submit') as submit:
                result=lookup_mtbp(browser,V,{'mtbp_wait_seconds':0})
            self.assertEqual(result['status'],'pending');submit.assert_not_called()
            self.assertNotIn('NEVER_SEND',str(result))
    def test_failed_submit_retains_receipt_and_never_retries_submission(self):
        with tempfile.TemporaryDirectory() as folder:
            browser=Mock();browser.data_dir=Path(folder);context=Mock();browser._context.return_value=context
            with patch('abl1_workstation.mtbp.prepare',return_value=True),patch('abl1_workstation.mtbp.submit',side_effect=TimeoutError('uncertain submission')) as submit,patch('abl1_workstation.mtbp.find_report',return_value=None):
                self.assertEqual(lookup_mtbp(browser,V,{'mtbp_wait_seconds':0})['status'],'pending')
                self.assertEqual(lookup_mtbp(browser,V,{'mtbp_wait_seconds':0})['status'],'pending')
                self.assertEqual(submit.call_count,1)
            job=next(Path(folder).rglob('mtbp-job.json')).read_text()
            self.assertNotIn('NEVER_SEND',job);self.assertIn('NM_005157.6:c.944C>T',job)
    def test_uncertain_native_submission_is_not_cancelled_by_report_list_navigation(self):
        with tempfile.TemporaryDirectory() as folder:
            browser=Mock();browser.data_dir=Path(folder)
            with patch('abl1_workstation.mtbp.prepare',return_value=True),patch('abl1_workstation.mtbp.submit'),patch('abl1_workstation.mtbp.wait_acceptance',return_value='unknown'),patch('abl1_workstation.mtbp.find_report') as find:
                self.assertEqual(lookup_mtbp(browser,V,{})['status'],'pending')
                find.assert_not_called()
    def test_positive_transcript_rejection_may_retry_genomic_query_once(self):
        with tempfile.TemporaryDirectory() as folder:
            import json
            browser=Mock();browser.data_dir=Path(folder)
            with patch('abl1_workstation.mtbp.prepare',return_value=True),patch('abl1_workstation.mtbp.submit') as submit,patch('abl1_workstation.mtbp.wait_acceptance',side_effect=['rejected','accepted']),patch('abl1_workstation.mtbp.find_report',return_value=None):
                self.assertEqual(lookup_mtbp(browser,V,{'mtbp_wait_seconds':0})['status'],'pending')
                self.assertEqual(submit.call_count,2)
            job=json.loads(next(Path(folder).rglob('mtbp-job.json')).read_text())
            self.assertEqual(job['query'],'chr9:g.133748283C>T')
    def test_certain_form_rejection_can_be_retried_without_retaining_false_pending_job(self):
        from abl1_workstation.mtbp import SubmissionNotSent
        with tempfile.TemporaryDirectory() as folder:
            browser=Mock();browser.data_dir=Path(folder)
            with patch('abl1_workstation.mtbp.prepare',return_value=True),patch('abl1_workstation.mtbp.submit',side_effect=SubmissionNotSent('Required form item is missing')):
                self.assertEqual(lookup_mtbp(browser,V,{})['status'],'error')
                self.assertEqual(list(Path(folder).rglob('mtbp-job.json')),[])
    def test_changed_report_during_png_capture_is_discarded(self):
        from abl1_workstation.mtbp import capture
        with tempfile.TemporaryDirectory() as folder:
            context=Mock();context.evaluate.return_value={'x':0,'y':0,'width':600,'height':240}
            context.capture_png.side_effect=lambda path,**k:Path(path).write_bytes(b'TEST_ONLY')
            with patch('abl1_workstation.mtbp.read_report',side_effect=[PAGE,{**PAGE,'rows':[{**ROW,'alteration':'T315M'}]}]),patch('abl1_workstation.mtbp.time.sleep'):
                result=capture(context,V,JOB,PAGE,parse_report(V,JOB,PAGE),Path(folder))
            self.assertEqual(result['screenshot_reason'],'capture_failed')
            self.assertEqual(list(Path(folder).rglob('*.png')),[])
    def test_completed_analysis_is_captured_and_saved_before_return_without_private_report_url(self):
        from abl1_workstation.evidence_store import EvidenceStore
        from abl1_workstation.workflow import allele_key
        with tempfile.TemporaryDirectory() as folder:
            import json
            root=Path(folder)/'evidence/databases'/allele_key(V);root.mkdir(parents=True)
            (root/'mtbp-job.json').write_text(json.dumps(JOB))
            browser=Mock();browser.data_dir=Path(folder);context=Mock();browser._context.return_value=context
            picture=root/'mtbp-picture.png';picture.write_bytes(b'TEST_ONLY')
            result={**parse_report(V,JOB,PAGE),'screenshot':str(picture)}
            with patch('abl1_workstation.mtbp.find_report',return_value=PAGE),patch('abl1_workstation.mtbp.capture',return_value=result),patch('abl1_workstation.mtbp.submit') as submit:
                self.assertEqual(lookup_mtbp(browser,V,{})['status'],'found');submit.assert_not_called()
            saved=EvidenceStore(folder).load(V)[0]
            self.assertEqual(saved['provider'],'mtbp');self.assertTrue(saved['screenshot'])
            self.assertNotIn('/patients/',json.dumps(saved))

if __name__=='__main__':unittest.main()
