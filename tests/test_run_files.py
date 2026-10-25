"""Only invented VCF, alignment/index names and local reference candidates."""
import gzip
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from abl1_workstation.domain import _engine, load_inputs
from abl1_workstation.run_files import discover_run


def vcf(sample='CASE-A',alt='T',filter_value='PASS'):
    return ('##fileformat=VCFv4.2\n#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\t'+sample+'\n'
            'chr9\t133748283\t.\tC\t'+alt+'\t.\t'+filter_value+'\t.\tGT:AF:AD:DP\t0/1:0.2:80,20:100\n')


class RunFilesTests(unittest.TestCase):
    def setUp(self):self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
    def tearDown(self):self.tmp.cleanup()
    def write(self,name,text):
        p=self.root/name;p.parent.mkdir(parents=True,exist_ok=True)
        if name.lower().endswith('.gz'):p.write_bytes(gzip.compress(text.encode()))
        else:p.write_text(text,encoding='utf-8')
        return p.resolve()
    def alignment(self,name):
        p=self.write(name,'invented alignment filename fixture')
        index=self.write(name+('.crai' if name.endswith('.cram') else '.bai'),'invented index')
        return p,index
    def fasta(self,name='reference/chr9.fa',length=141213431):
        p=self.write(name,'>chr9\nA\n')
        self.write(name+'.fai',f'chr9\t{length}\t6\t1\t2\n')
        return p

    def test_recursive_hard_filtered_preference_retains_filtered_calls(self):
        chosen=self.write('Case/output/CASE-A.hard-filtered.vcf.gz',vcf(filter_value='low_af'))
        self.write('Case/output/CASE-A.vcf',vcf(alt='G'))
        got=discover_run(self.root)
        self.assertEqual(got.vcfs,[chosen]);self.assertTrue(got.warnings)
        analysis=load_inputs([self.root]).data
        self.assertEqual(len(analysis['variants']),1)
        self.assertEqual(analysis['variants'][0]['filter'],'low_af')

    def test_identical_plain_gzip_and_copied_content_are_not_counted_twice(self):
        self.write('a/CASE-A.hard-filtered.vcf',vcf())
        preferred=self.write('a/CASE-A.hard-filtered.vcf.gz',vcf())
        self.write('copy/CASE-A.hard-filtered.vcf.gz',vcf())
        self.assertEqual(discover_run(self.root).vcfs,[preferred])
        self.assertEqual(len(load_inputs([self.root]).data['variants']),1)

    def test_conflicting_plain_compressed_pair_and_same_sample_inputs_raise(self):
        self.write('a/CASE-A.hard-filtered.vcf',vcf())
        self.write('a/CASE-A.hard-filtered.vcf.gz',vcf(alt='G'))
        with self.assertRaisesRegex(ValueError,'CASE-A'):discover_run(self.root)

    def test_joint_and_reference_blocks_are_ignored_with_visible_reason(self):
        accepted=self.write('Case/CASE-A.hard-filtered.vcf',vcf())
        self.write('Case/CASE-A.g.vcf.gz',vcf(alt='<NON_REF>'))
        self.write('reference-blocks.vcf',vcf(alt='<NON_REF>'))
        self.write('joint.vcf',vcf(sample='CASE-A\tCASE-B').replace('0/1:0.2:80,20:100\n','0/1:0.2:80,20:100\t0/1:0.2:80,20:100\n'))
        got=discover_run(self.root);self.assertEqual(got.vcfs,[accepted])
        self.assertTrue(any('gVCF' in text for text in got.warnings))
        self.assertTrue(any('joint' in text for text in got.warnings))

    def test_only_gvcf_never_becomes_variant_analysis(self):
        self.write('CASE-A.g.vcf.gz',vcf(alt='<NON_REF>'))
        with self.assertRaisesRegex(ValueError,'VCF'):discover_run(self.root)

    def test_symbolic_structural_variant_end_is_not_discarded_as_reference_block(self):
        text=vcf(alt='<DEL>').replace('\tPASS\t.\tFORMAT','\tPASS\tEND=133748300\tFORMAT')
        text=text.replace('\tPASS\t.\tGT:', '\tPASS\tEND=133748300\tGT:')
        accepted=self.write('CASE-A.vcf',text)
        self.assertEqual(discover_run(self.root).vcfs,[accepted])
        self.assertEqual(load_inputs([self.root]).data['variants'][0]['alt'],'<DEL>')

    def test_alignment_and_indexes_match_exact_sample_not_prefix(self):
        self.write('CASE-A.hard-filtered.vcf',vcf())
        alignment,index=self.alignment('sub/CASE-A_tumor.cram')
        self.alignment('other/CASE-A2.bam')
        reference=self.fasta()
        got=discover_run(self.root)
        self.assertEqual(set(got.alignments),{'CASE-A'})
        self.assertEqual(got.alignments['CASE-A'].path,alignment)
        self.assertEqual(got.alignments['CASE-A'].index,index)
        self.assertEqual(got.alignments['CASE-A'].kind,'cram')
        self.assertEqual(got.reference_fasta,reference)

    def test_missing_index_is_a_warning_and_no_usable_alignment_is_claimed(self):
        self.write('CASE-A.vcf',vcf());self.write('CASE-A.bam','invented')
        got=discover_run(self.root)
        self.assertEqual(got.alignments,{})
        self.assertTrue(any('indeks' in text.lower() for text in got.warnings))

    def test_two_possible_alignments_or_conflicting_indexes_raise(self):
        self.write('CASE-A.vcf',vcf());self.alignment('CASE-A.bam');self.alignment('CASE-A_tumor.cram')
        with self.assertRaisesRegex(ValueError,'BAM/CRAM'):discover_run(self.root)
        (self.root/'CASE-A_tumor.cram').unlink();(self.root/'CASE-A_tumor.cram.crai').unlink()
        self.write('CASE-A.bai','different index')
        with self.assertRaisesRegex(ValueError,'indeks'):discover_run(self.root)

    def test_multiple_references_raise_and_wrong_build_is_not_guessed(self):
        self.write('CASE-A.vcf',vcf());self.fasta(length=138394717)
        got=discover_run(self.root);self.assertIsNone(got.reference_fasta)
        self.assertTrue(any('FASTA' in text for text in got.warnings))
        self.fasta('a/hg19.fa');self.fasta('b/chr9.fasta')
        with self.assertRaisesRegex(ValueError,'FASTA'):discover_run(self.root)

    def test_reference_accepts_9_alias_but_rejects_two_chr9_aliases(self):
        self.write('CASE-A.vcf',vcf());reference=self.fasta()
        index=self.root/'reference/chr9.fa.fai'
        index.write_text('9\t141213431\t3\t1\t2\n')
        self.assertEqual(discover_run(self.root).reference_fasta,reference)
        index.write_text('9\t141213431\t3\t1\t2\nchr9\t141213431\t3\t1\t2\n')
        self.assertIsNone(discover_run(self.root).reference_fasta)

    def test_qc_comes_only_from_selected_vcf_parent_and_report_prefix(self):
        self.write('selected/REPORT.hard-filtered.vcf',vcf())
        self.write('selected/REPORT.mapping_metrics.csv','MAPPING,,Total input reads,100\n')
        self.write('selected/REPORT.target_bed_coverage_metrics.csv','COVERAGE,,Average alignment coverage over target region,250\n')
        self.write('unrelated/CASE-A.mapping_metrics.csv','MAPPING,,Total input reads,999999\n')
        got=load_inputs([self.root]).data
        self.assertEqual(len(got['qc']),1)
        self.assertEqual(got['qc'][0]['sample'],'CASE-A')
        self.assertEqual(got['qc'][0]['total_reads'],100)
        self.assertEqual(got['qc'][0]['mean_target_depth'],250)

    def test_conflicting_qc_at_identical_vcf_copies_is_not_silently_chosen(self):
        for folder,count in [('a',100),('b',200)]:
            self.write(folder+'/CASE-A.hard-filtered.vcf',vcf())
            self.write(folder+'/CASE-A.mapping_metrics.csv',f'MAPPING,,Total input reads,{count}\n')
        with self.assertRaisesRegex(ValueError,'QC'):discover_run(self.root)

    def test_header_without_sample_uses_same_basename_for_discovery_and_parser(self):
        content='##fileformat=VCFv4.2\n#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\nchr9\t133748283\t.\tC\tT\t.\tPASS\t.\n'
        self.write('nested/CASE-A.hard-filtered.vcf',content)
        alignment,index=self.alignment('nested/CASE-A.bam')
        got=discover_run(self.root)
        self.assertEqual(got.alignments['CASE-A'].path,alignment)
        self.assertEqual(load_inputs([self.root]).data['samples'][0]['sample'],'CASE-A')

    def test_equal_headerless_text_in_different_named_samples_is_not_deduplicated(self):
        content='##fileformat=VCFv4.2\n#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\nchr9\t133748283\t.\tC\tT\t.\tPASS\t.\n'
        self.write('CASE-A.hard-filtered.vcf',content);self.write('CASE-B.hard-filtered.vcf',content)
        got=load_inputs([self.root]).data
        self.assertEqual({s['sample'] for s in got['samples']},{'CASE-A','CASE-B'})
        self.assertEqual(len(got['variants']),2)

    def test_alignment_filename_prefix_alias_still_uses_vcf_header_sample(self):
        self.write('selected/REPORT.hard-filtered.vcf',vcf())
        alignment,index=self.alignment('selected/REPORT_tumor.bam')
        got=discover_run(self.root)
        self.assertEqual(got.alignments['CASE-A'].path,alignment)
        self.assertEqual(got.alignments['CASE-A'].sample,'CASE-A')

    def test_matching_qc_symlink_outside_run_is_not_read(self):
        self.write('selected/CASE-A.hard-filtered.vcf',vcf())
        with tempfile.TemporaryDirectory() as outside:
            target=Path(outside)/'CASE-A.mapping_metrics.csv';target.write_text('MAPPING,,Total input reads,999999\n')
            link=self.root/'selected/CASE-A.mapping_metrics.csv'
            try:link.symlink_to(target)
            except OSError:self.skipTest('Creating symlinks is not permitted by this Windows account.')
            got=load_inputs([self.root]).data
            self.assertEqual(got['qc'],[])


if __name__=='__main__':unittest.main()
