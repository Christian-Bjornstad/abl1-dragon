import json,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import Mock
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from abl1_workstation.lookup import LookupService,PROVIDERS
from abl1_workstation.report import PROVIDER_NAMES
from abl1_workstation.settings import Settings,HOMES,PORTALS


class RemovedSourcesTests(unittest.TestCase):
    def test_removed_sources_cannot_start_network_or_browser_requests(self):
        variant={'assembly':'GRCh37','chrom':'9','pos':133748283,'ref':'C','alt':'T'}
        with tempfile.TemporaryDirectory() as directory:
            network=Mock();browser=Mock()
            results=LookupService(directory,transport=network,browser_adapter=browser).lookup(variant,['cosmic','gnomad'],settings={'provider_modes':{'cosmic':'browser','gnomad':'browser'}})
            self.assertEqual([r['status'] for r in results],['unsupported','unsupported'])
            network.assert_not_called();browser.lookup.assert_not_called()
    def test_only_remaining_sources_are_available_and_old_preferences_are_migrated(self):
        allowed={'clinvar','franklin','oncokb','mtbp'}
        self.assertEqual(set(PROVIDERS),allowed);self.assertEqual(set(PROVIDER_NAMES),allowed)
        self.assertEqual(set(HOMES),allowed);self.assertEqual(set(PORTALS),allowed-{'clinvar'})
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'settings.json'
            path.write_text(json.dumps({'providers':['clinvar','cosmic','gnomad','franklin']}))
            settings=Settings(directory)
            self.assertEqual(settings.providers,['clinvar','franklin'])
            self.assertEqual(json.loads(path.read_text())['providers'],['clinvar','franklin'])
    def test_old_removed_source_results_are_excluded_from_new_excel_even_if_requested(self):
        from openpyxl import load_workbook
        from abl1_workstation.domain import load_pilot
        from abl1_workstation.report import export_report
        from abl1_workstation.workflow import allele_key
        session=load_pilot();variant=session.data['variants'][0]
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'report.xlsx'
            old={allele_key(variant):[{'provider':'cosmic','status':'found','summary':'OLD_SOURCE_COSMIC'},
                                    {'provider':'gnomad','status':'found','summary':'OLD_SOURCE_GNOMAD'}]}
            export_report(session,[variant],old,path,providers=['clinvar','cosmic','gnomad','franklin'])
            book=load_workbook(path);text=' '.join(str(c.value or '') for s in book for row in s for c in row)
            self.assertNotIn('COSMIC',text.upper());self.assertNotIn('GNOMAD',text.upper())
            book.close()

if __name__=='__main__':unittest.main()
