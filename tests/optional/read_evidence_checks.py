"""Optional pysam tests: run in an environment with pysam installed."""
import hashlib
import importlib.util
import pathlib
import tempfile
import unittest

import pysam

ROOT=pathlib.Path(__file__).resolve().parents[2]
spec=importlib.util.spec_from_file_location('read_evidence',ROOT/'engine'/'read_evidence.py')
evidence=importlib.util.module_from_spec(spec)
spec.loader.exec_module(evidence)

class ReadEvidenceTests(unittest.TestCase):
    def test_overlapping_mates_do_not_double_count_and_unphased_reads_do_not_join(self):
        with tempfile.TemporaryDirectory() as temp:
            folder=pathlib.Path(temp);seq='A'*100+'ACT'+'A'*97;md5=hashlib.md5(seq.encode()).hexdigest()
            ref=folder/'ref.fa';ref.write_text('>chr9\n'+seq+'\n');pysam.faidx(str(ref))
            bam=folder/'case.bam'
            header={'HD':{'VN':'1.6','SO':'coordinate'},'SQ':[{'SN':'chr9','LN':200,'M5':md5}]}
            with pysam.AlignmentFile(str(bam),'wb',header=header) as writer:
                for name,haplotype,bq,flag in [('pair','ATG',40,99),('pair','ATG',40,147),('single','ATT',40,0),('discordant','ATG',40,0),('discordant','ATT',40,0),('lowq','CTT',9,0),('secondary','ATG',40,256)]:
                    read=pysam.AlignedSegment(writer.header);read.query_name=name;read.query_sequence='A'*20+haplotype+'A'*27;read.flag=flag;read.reference_id=0;read.reference_start=80;read.mapping_quality=60;read.cigarstring='50M';read.query_qualities=[bq]*50;writer.write(read)
            pysam.index(str(bam))
            reference={'chrom':'chr9','chrom_length':200,'chrom_md5':md5,'genomic_start0':0,'genomic_sequence':seq,'coding_map':{'101':943,'102':944,'103':945},'transcript':'NM_005157.6'}
            variants=[{'sample':'Case','chrom':'chr9','pos':102,'ref':'C','alt':'T','type':'SNV','reference_match':True,'protein_snv_alone':'p.T315I'}]
            got=evidence.analyze_alignment(bam,'Case',variants,ref,reference)
            phase=[row for row in got['phase_rows'] if row['filter']=='BQ30_MQ20']
            atg=next(row for row in phase if row['haplotype']=='ATG');att=next(row for row in phase if row['haplotype']=='ATT')
            self.assertEqual(atg['reads'],3)
            self.assertEqual(atg['fragments'],1)
            self.assertEqual(att['fragments'],1)
            self.assertEqual(atg['fragments_all'],2)
            self.assertEqual(atg['total_evaluated_query_name_fragments'],3)
            self.assertEqual(sum(row['fragments'] for row in phase),atg['fragments_all'])
            self.assertEqual(got['alignment_qc']['discordant_codon_fragments_BQ30_MQ20'],1)
            self.assertFalse(any(row['haplotype']=='CTT' for row in phase))
            self.assertEqual(got['read_rows'][0]['read_total'],5)
            self.assertEqual(got['read_rows'][0]['query_name_fragments_total'],3)

    def test_discordant_fragment_is_separate_from_phase_and_point_denominators(self):
        rows=[
            {'sequence':'ATG','bq':40,'mq':60,'reverse':False,'duplicate':False,'fragment':('rg','concordant')},
            {'sequence':'ATG','bq':40,'mq':60,'reverse':False,'duplicate':False,'fragment':('rg','discordant')},
            {'sequence':'ATT','bq':40,'mq':60,'reverse':True,'duplicate':False,'fragment':('rg','discordant')},
        ]
        summary=evidence.summarize(rows,30,20)
        self.assertEqual(summary['fragment_total'],1)
        self.assertEqual(summary['total_evaluated_query_name_fragments'],2)
        self.assertEqual(summary['fragments']['discordant'],1)
        self.assertEqual(sum(count for haplotype,count in summary['fragments'].items() if haplotype!='discordant'),summary['fragment_total'])
        self.assertEqual(summary['fragments']['ATG']/summary['fragment_total'],1)
        points=[dict(row,sequence=row['sequence'][-1]) for row in rows]
        point=evidence.summarize(points,30,20)
        self.assertEqual(point['fragment_total'],1)
        self.assertEqual(point['total_evaluated_query_name_fragments'],2)
        self.assertEqual(point['fragments']['discordant'],1)

    def test_wrong_fasta_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            ref=pathlib.Path(temp)/'bad.fa';ref.write_text('>chr9\nAAAA\n');pysam.faidx(str(ref))
            with self.assertRaisesRegex(ValueError,'MD5'):
                evidence.validate_reference(ref,{'chrom':'chr9','chrom_length':4,'chrom_md5':'invalid'})

if __name__=='__main__':unittest.main()
