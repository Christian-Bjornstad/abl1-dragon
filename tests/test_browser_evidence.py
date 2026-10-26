import base64,io,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import Mock,patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from PIL import Image,ImageDraw
from abl1_workstation.lookup_browser import PortalBrowser,_EdgeContext,parse_portal_snapshot

V={'assembly':'GRCh37','chrom':'9','pos':133748283,'ref':'C','alt':'T','cdna':'c.944C>T'}
PAGE={'url':'https://franklin.genoox.com/clinical-db/variant/snp/chr9-133748283-C-T',
      'text':'GRCh37 chr9-133748283-C-T\nSuggested classification\nPathogenic','ready_state':'complete'}

def png_bytes(blank=False):
    image=Image.new('RGB',(600,240),'white')
    if not blank:ImageDraw.Draw(image).rectangle((20,20,400,100),fill='purple')
    stream=io.BytesIO();image.save(stream,format='PNG');return stream.getvalue()


class BrowserEvidenceTests(unittest.TestCase):
    def test_oncokb_uses_scoped_mutation_tile_for_resistance_and_biological_effect(self):
        page={'url':'https://www.oncokb.org/hgvsg/9:g.133748283C%3ET?refGenome=GRCh37',
              'text':'GRCh37\n9:g.133748283C>T\nOncogenicity\nBiological Effect\nResistance\nLikely Gain-of-function\nClinical Implications for this Biomarker',
              'oncokb_result_visible':True,'oncokb_fields':{'Oncogenicity':'Resistance','Biological Effect':'Likely Gain-of-function'}}
        result=parse_portal_snapshot('oncokb',V,page)
        self.assertEqual(result['status'],'found');self.assertEqual(result['classification'],'Resistance')
        self.assertIn('Likely Gain-of-function',result['summary'])
        page['oncokb_fields']={'Oncogenicity':'Unrecognized badge'}
        self.assertEqual(parse_portal_snapshot('oncokb',V,page)['classification'],'')

    def test_capture_waits_for_viewport_reflow_instead_of_losing_verified_picture(self):
        class Page:
            busy=False;checks=0
            def snapshot(self):
                self.checks+=1
                return {**PAGE,'page_busy':self.busy and self.checks==2}
            def evidence_views(self,provider):
                self.busy=True
                yield 'Variant overview',None
            def capture_png(self,path,**options):Path(path).write_bytes(png_bytes())
        with tempfile.TemporaryDirectory() as folder:
            browser=PortalBrowser(folder)
            with patch('abl1_workstation.lookup_browser.time.sleep'):
                result=browser._capture('franklin',V,Page(),parse_portal_snapshot('franklin',V,PAGE))
            self.assertIn('screenshot',result);browser.close()
    def test_each_view_is_captured_checked_and_labelled_and_partial_images_are_kept(self):
        class Page:
            def snapshot(self):return PAGE
            def evidence_views(self,provider):
                yield 'Variant overview',None
                yield 'Oncogenic Classification',{'x':0,'y':0,'width':600,'height':240}
                raise RuntimeError('third panel unavailable')
            def capture_png(self,path,**options):Path(path).write_bytes(png_bytes())
        with tempfile.TemporaryDirectory() as folder:
            browser=PortalBrowser(folder)
            result=browser._capture('franklin',V,Page(),parse_portal_snapshot('franklin',V,PAGE))
            self.assertEqual([r['label'] for r in result['screenshots']],['Variant overview','Oncogenic Classification'])
            self.assertIn('screenshot_error',result)
            self.assertTrue(all(Path(r['path']).is_file() for r in result['screenshots']))
            browser.close()
    def test_target_switch_between_views_does_not_attach_wrong_variant_image(self):
        class Page:
            current=PAGE
            def snapshot(self):return self.current
            def evidence_views(self,provider):
                yield 'Overview',None
                self.current={**PAGE,'text':PAGE['text'].replace('C-T','C-G')}
                yield 'Wrong variant',None
            def capture_png(self,path,**options):Path(path).write_bytes(png_bytes())
        with tempfile.TemporaryDirectory() as folder:
            browser=PortalBrowser(folder)
            result=browser._capture('franklin',V,Page(),parse_portal_snapshot('franklin',V,PAGE))
            self.assertEqual(len(result['screenshots']),1)
            self.assertEqual(len(list(Path(folder).rglob('*.png'))),1)
            self.assertEqual(result['screenshot_reason'],'identity_mismatch');browser.close()
    def test_real_capture_rejects_blank_png_and_accepts_content_with_clip(self):
        context=object.__new__(_EdgeContext)
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'picture.png'
            context._page_call=Mock(return_value={'data':base64.b64encode(png_bytes(blank=True)).decode()})
            with self.assertRaises(ValueError):context.capture_png(path)
            self.assertFalse(path.exists())
            context._page_call=Mock(return_value={'data':base64.b64encode(png_bytes()).decode()})
            context.capture_png(path,clip={'x':0,'y':0,'width':600,'height':240})
            self.assertTrue(path.exists())
            self.assertTrue(context._page_call.call_args.args[1]['captureBeyondViewport'])
    def test_franklin_somatic_route_is_supported_without_inventing_a_label(self):
        page={**PAGE,'url':PAGE['url'].replace('/snp/','/snpTumor/'),
              'text':'hg19 chr9:133748283 C>T\nSomatic Clinical Evidence\nAMP Classification\nEvidence for T315I',
              'franklin_result_visible':True}
        result=parse_portal_snapshot('franklin',V,page)
        self.assertEqual(result['status'],'found');self.assertEqual(result['classification'],'')
        self.assertNotEqual(parse_portal_snapshot('franklin',{**V,'alt':'G'},page)['status'],'found')

if __name__=='__main__':unittest.main()
