import sys
from pathlib import Path
import tempfile
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from abl1_workstation.domain import load_pilot
from abl1_workstation.workflow import category, allele_key, candidate_rows
from abl1_workstation.report import export_report,source_text


class WorkflowReportTests(unittest.TestCase):
    def test_empty_sample_is_retained_without_claiming_a_negative_result(self):
        from openpyxl import load_workbook
        session=load_pilot()
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'empty.xlsx'
            export_report(session,[],{},path,providers=[],samples=['DEMO-A'],selection='DEMO-A · PASS')
            book=load_workbook(path);sheet=book.active
            self.assertEqual(sheet.max_row,4)
            self.assertEqual(sheet.cell(4,1).value,'DEMO-A')
            self.assertEqual(sheet.cell(4,7).value,'Ingen varianter i utvalget')
            self.assertIn('DEMO-A',sheet.cell(2,4).value);book.close()
    def test_found_classification_and_evidence_are_visible_beside_record_title(self):
        text=source_text({'status':'found','classification':'Germline: Likely pathogenic',
                          'evidence_level':'criteria provided','summary':'Record title'})
        for value in ('Germline: Likely pathogenic','criteria provided','Record title'):
            self.assertIn(value,text)
    def test_candidates_keep_filters_without_promoting_artifacts(self):
        base={'chrom':'chr9','pos':133748283,'ref':'C','alt':'T','reference_match':True,
              'cdna':'c.944C>T','filter':'PASS','alt_ad':1,'sample_has_alt':True}
        self.assertEqual(category(base),'PASS')
        filtered={**base,'filter':'LowAF'}
        self.assertEqual(category(filtered),'Kontroll')
        self.assertEqual(category({**base,'reference_match':False}),'REF-avvik')
        self.assertEqual(category({**base,'normal_transcript_continuation':True}),'Transkriptfortsettelse')
        self.assertEqual(category({**filtered,'alt_ad':0}),'Øvrige')
        self.assertEqual(candidate_rows([base,filtered,{**base,'reference_match':False}]),[base,filtered])
        self.assertEqual(filtered['filter'],'LowAF')

    def test_lookup_identity_has_no_sample_and_distinguishes_alleles(self):
        v=load_pilot().data['variants'][0]
        self.assertEqual(allele_key(v),allele_key({**v,'sample':'different','chrom':'9'}))
        self.assertNotEqual(allele_key(v),allele_key({**v,'alt':'G'}))

    def test_one_sheet_export_retains_phase_flags_and_source_state(self):
        from openpyxl import load_workbook
        session=load_pilot();rows=session.data['variants'];rows[0]['sample']='=UNTRUSTED'
        results={allele_key(rows[0]):[{'provider':'clinvar','status':'found','summary':'Test classification',
                 'checked_at':'2026-10-25T17:00Z','url':'https://www.ncbi.nlm.nih.gov/clinvar/variation/123/'}]}
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'report.xlsx'
            export_report(session,rows,results,path,providers=['clinvar','franklin'])
            book=load_workbook(path)
            self.assertEqual(book.sheetnames,['Resultater'])
            sheet=book.active
            self.assertEqual(sheet.max_row,len(rows)+3)
            self.assertEqual(sheet.cell(4,1).value,"'=UNTRUSTED")
            self.assertIn('Test classification',[c.value for c in sheet[4]])
            self.assertIn('Ikke slått opp',[c.value for c in sheet[4]])
            self.assertIn('kodon',sheet.cell(4,5).comment.text.lower())
            self.assertNotIn('Kontrollflagg',[c.value for c in sheet[3]])
            self.assertIn('2026-10-25',sheet.cell(4,10).comment.text)
            self.assertIn('/variation/123/',sheet.cell(4,10).comment.text)
            self.assertEqual(sheet.freeze_panes,'D4');book.close()
