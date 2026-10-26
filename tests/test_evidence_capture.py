import sys,tempfile,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from abl1_workstation.lookup_browser import PortalBrowser
from abl1_workstation.lookup import genomic_hgvs
from abl1_workstation.domain import load_pilot

class EvidenceCaptureTests(unittest.TestCase):
    def test_public_picture_requires_exact_hg19_allele_not_only_record_url(self):
        v=load_pilot().data['variants'][0]
        good={'url':'https://www.ncbi.nlm.nih.gov/clinvar/variation/TEST/','text':genomic_hgvs(v)}
        self.assertTrue(PortalBrowser._public_identity('clinvar',v,good))
        self.assertFalse(PortalBrowser._public_identity('clinvar',{**v,'alt':'G'},good))
        self.assertFalse(PortalBrowser._public_identity('clinvar',v,{**good,'url':'https://example.invalid/'}))
        self.assertFalse(PortalBrowser._public_identity('clinvar',v,{**good,'password_visible':True}))
    def test_navigation_during_capture_discards_picture_and_preserves_text_result(self):
        v=load_pilot().data['variants'][0]
        class ChangedPage:
            def capture_png(self,path):Path(path).write_bytes(b'TEST_ONLY_NOT_A_REAL_SCREENSHOT')
            def snapshot(self):return {'url':'https://www.ncbi.nlm.nih.gov/clinvar/','text':'different allele'}
        with tempfile.TemporaryDirectory() as folder:
            browser=PortalBrowser(folder)
            result=browser._capture('clinvar',v,ChangedPage(),{'status':'found','summary':'Verified text result'})
            self.assertNotIn('screenshot',result);self.assertIn('screenshot_error',result)
            self.assertEqual(result['summary'],'Verified text result')
            self.assertEqual(list(Path(folder).rglob('*.png')),[]);browser.close()
    def test_reference_protein_track_identifies_codon315_in_the_correct_genomic_frame(self):
        root=Path(__file__).resolve().parents[1]
        features=[line.split('\t') for line in (root/'assets/igv/protein.bed').read_text(encoding='utf-8').splitlines()]
        feature=next(f for f in features if int(f[1])<=133748282<int(f[2]))
        self.assertEqual(feature[3],'T');self.assertEqual((int(feature[1]),int(feature[2])),(133748281,133748284))

if __name__=='__main__':unittest.main()
