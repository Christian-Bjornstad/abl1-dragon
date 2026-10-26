import base64,io,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import Mock
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
