"""Optional local BAM/CRAM read evidence; requires pysam, never downloads a reference.

Counts observations and concordant query-name/read-group fragments, not molecules.
The quality thresholds are exploratory, not validated assay acceptance criteria.
"""
import collections
import hashlib
import pathlib

import pysam

THRESHOLDS=((0,0),(20,20),(30,20),(30,60))
BASES='TCAG'
AA=dict(zip([a+b+c for a in BASES for b in BASES for c in BASES],'FFLLSSSSYY**CC*WLLLLPPPPHHQQRRRRIIIMTTTTNNKKSSRRVVVVAAAADDEEGGGG'))
AA3=dict(zip('ACDEFGHIKLMNPQRSTVWY*',['Ala','Cys','Asp','Glu','Phe','Gly','His','Ile','Lys','Leu','Met','Asn','Pro','Gln','Arg','Ser','Thr','Val','Trp','Tyr','Ter']))
_REFERENCE_CACHE={}

def validate_reference(path,reference):
    path=pathlib.Path(path).resolve()
    if not path.is_file() or not pathlib.Path(str(path)+'.fai').is_file():raise ValueError('Lokal FASTA og tilhørende .fai kreves; ingen referanse lastes ned.')
    key=(str(path),path.stat().st_size,path.stat().st_mtime_ns,reference['chrom'],reference.get('chrom_md5'))
    if key in _REFERENCE_CACHE:return _REFERENCE_CACHE[key]
    with pysam.FastaFile(str(path)) as fasta:
        chrom=reference['chrom']
        if chrom not in fasta.references:raise ValueError('FASTA mangler '+chrom)
        length=fasta.get_reference_length(chrom)
        if length!=reference['chrom_length']:raise ValueError('FASTA-kromosomlengde avviker fra bekreftet referanse.')
        digest=hashlib.md5()
        for start in range(0,length,1024*1024):digest.update(fasta.fetch(chrom,start,min(start+1024*1024,length)).upper().encode('ascii'))
        md5=digest.hexdigest()
        if md5!=reference.get('chrom_md5'):raise ValueError('FASTA MD5 avviker fra bekreftet GRCh37-referanse.')
    result={'chrom':chrom,'length':length,'sequence_md5':md5,'local_fasta':path.name}
    _REFERENCE_CACHE[key]=result
    return result

def primary(read):
    return not(read.is_unmapped or read.is_secondary or read.is_supplementary or read.is_qcfail)

def observations(alignment,chrom,positions):
    """Require every base and consecutive query bases for a complete codon."""
    wanted=set(positions);rows=[];excluded=collections.Counter()
    for count,read in enumerate(alignment.fetch(chrom,min(positions)-1,max(positions))):
        if count>=500000:raise ValueError('Over 500 000 alignments ved ett locus; pilotgrensen er nådd.')
        if not primary(read):excluded['nonprimary_or_qcfail']+=1;continue
        if not read.query_sequence or read.query_qualities is None:excluded['missing_sequence_or_quality']+=1;continue
        mapping={g+1:q for q,g in read.get_aligned_pairs(matches_only=False) if g is not None and g+1 in wanted}
        if any(mapping.get(p) is None for p in positions):excluded['partial_or_deletion']+=1;continue
        query=[mapping[p] for p in positions]
        if any(b!=a+1 for a,b in zip(query,query[1:])):excluded['nonconsecutive_codon_query_bases']+=1;continue
        seq=''.join(read.query_sequence[q].upper() for q in query)
        if any(base not in 'ACGT' for base in seq):excluded['non_acgt']+=1;continue
        name=read.query_name
        if not name:raise ValueError('Alignment uten query-name kan ikke telles som fragment.')
        identity=(read.get_tag('RG') if read.has_tag('RG') else '',name)
        rows.append({'sequence':seq,'bq':min(read.query_qualities[q] for q in query),'mq':read.mapping_quality,'reverse':read.is_reverse,'duplicate':read.is_duplicate,'fragment':identity})
    return rows,dict(excluded)

def summarize(rows,min_bq,min_mq):
    reads=[row for row in rows if row['bq']>=min_bq and row['mq']>=min_mq]
    fragments=collections.defaultdict(set)
    for row in reads:fragments[row['fragment']].add(row['sequence'])
    consensus=collections.Counter(next(iter(values)) if len(values)==1 else 'discordant' for values in fragments.values())
    by_sequence=collections.Counter(row['sequence'] for row in reads)
    concordant_total=len(fragments)-consensus.get('discordant',0)
    return {'rows':reads,'reads':by_sequence,'fragments':consensus,'read_total':len(reads),'fragment_total':concordant_total,'total_evaluated_query_name_fragments':len(fragments),'overlap_extra':len(reads)-len(fragments),'duplicate_flagged_reads':sum(row['duplicate'] for row in reads)}

def analyze_alignment(path,sample,variants,reference_path,reference,thresholds=THRESHOLDS):
    verified=validate_reference(reference_path,reference)
    path=pathlib.Path(path)
    mode='rc' if path.suffix.lower()=='.cram' else 'rb'
    kwargs={'reference_filename':str(reference_path)} if mode=='rc' else {}
    phase_rows=[];read_rows=[];qc={'sample':sample,'threshold_note':'Exploratory thresholds, not clinically validated','duplicates':'Retained; flagged read counts recorded','fragment_definition':'Concordant complete observations grouped by read-group + query-name form fragment fraction denominators; discordant groups excluded from fractions and reported separately alongside total evaluated groups; never unique original molecules','reference':verified}
    with pysam.AlignmentFile(str(path),mode,**kwargs) as alignment:
        if not alignment.has_index():raise ValueError('Alignment-indeks (.bai/.crai) mangler.')
        sq=next((row for row in alignment.header.to_dict().get('SQ',[]) if row.get('SN')==reference['chrom']),None)
        if not sq or sq.get('LN')!=verified['length']:raise ValueError('Alignment-kromosom/lenge avviker fra referansen.')
        if sq.get('M5') and sq['M5'].lower()!=verified['sequence_md5']:raise ValueError('Alignment M5 avviker fra lokal FASTA.')
        if mode=='rc' and not sq.get('M5'):raise ValueError('CRAM mangler referanse-M5; sikker dekoding sperret.')
        qc['alignment_reference_m5_verified']=bool(sq.get('M5'))
        if not sq.get('M5'):qc['reference_warning']='BAM-header has no M5; chromosome length checked, original alignment reference not proven by BAM header'
        positions=sorted(int(pos) for pos,cp in reference['coding_map'].items() if 943<=cp<=945)
        if len(positions)!=3:raise ValueError('Referansen mangler fullstendig ABL1-kodon 315.')
        codon_reads,excluded=observations(alignment,reference['chrom'],positions)
        qc['codon315_excluded_records']=excluded
        for min_bq,min_mq in thresholds:
            label=f'BQ{min_bq}_MQ{min_mq}';summary=summarize(codon_reads,min_bq,min_mq)
            qc['discordant_codon_fragments_'+label]=summary['fragments'].get('discordant',0)
            qc['total_evaluated_codon_fragments_'+label]=summary['total_evaluated_query_name_fragments']
            qc['concordant_codon_fragments_'+label]=summary['fragment_total']
            qc['duplicate_flagged_codon_reads_'+label]=summary['duplicate_flagged_reads']
            for haplotype,reads in sorted(summary['reads'].items()):
                matching=[row for row in summary['rows'] if row['sequence']==haplotype]
                protein='p.Thr315=' if haplotype=='ACT' else 'p.Thr315'+AA3[AA[haplotype]]
                fragments=summary['fragments'].get(haplotype,0)
                phase_rows.append({'sample':sample,'codon':315,'hg19_interval1':f"{reference['chrom']}:{positions[0]}-{positions[-1]}",'reference_codon':'ACT','haplotype':haplotype,'protein':protein,'filter':label,'reads':reads,'reads_all':summary['read_total'],'read_fraction':reads/summary['read_total'] if summary['read_total'] else None,'read_forward':sum(not row['reverse'] for row in matching),'read_reverse':sum(row['reverse'] for row in matching),'fragments':fragments,'fragments_all':summary['fragment_total'],'fragment_fraction':fragments/summary['fragment_total'] if summary['fragment_total'] else None,'discordant_fragments':summary['fragments'].get('discordant',0),'evidence_status':'Local read evidence; no clinical classification or clone inference'})
                phase_rows[-1]['total_evaluated_query_name_fragments']=summary['total_evaluated_query_name_fragments']
                phase_rows[-1]['fragment_denominator_definition']='Concordant complete-codon query-name/read-group fragments; discordant fragments reported separately'
        seen=set()
        for variant in variants:
            key=(variant['chrom'],variant['pos'],variant['ref'],variant['alt'])
            if key in seen or variant['sample']!=sample or variant['type']!='SNV' or variant.get('reference_match') is not True or variant.get('sample_has_alt') is False:continue
            seen.add(key)
            rows,_=observations(alignment,reference['chrom'],[variant['pos']]);summary=summarize(rows,30,20)
            alt=variant['alt'];alt_rows=[row for row in summary['rows'] if row['sequence']==alt]
            read_rows.append({'sample':sample,'chr':reference['chrom'],'pos1_hg19':variant['pos'],'ref':variant['ref'],'alt':alt,'protein_NM005157_6':variant.get('protein_snv_alone'),'filter':'primary; BQ>=30; MQ>=20','read_total':summary['read_total'],'alt_reads':summary['reads'].get(alt,0),'alt_read_AF':summary['reads'].get(alt,0)/summary['read_total'] if summary['read_total'] else None,'alt_forward':sum(not row['reverse'] for row in alt_rows),'alt_reverse':sum(row['reverse'] for row in alt_rows),'query_name_fragments_total':summary['fragment_total'],'alt_query_name_fragments':summary['fragments'].get(alt,0),'alt_fragment_AF':summary['fragments'].get(alt,0)/summary['fragment_total'] if summary['fragment_total'] else None,'overlap_extra_observations':summary['overlap_extra'],'discordant_fragments':summary['fragments'].get('discordant',0),'duplicate_flagged_reads':summary['duplicate_flagged_reads'],'caveat':'query-name/read-group fragments are not unique original molecules; local read fractions are not validated VAFs'})
            read_rows[-1]['total_evaluated_query_name_fragments']=summary['total_evaluated_query_name_fragments']
            read_rows[-1]['fragment_denominator_definition']='Concordant base observations grouped by query-name/read-group; discordant fragments reported separately'
    return {'phase_rows':phase_rows,'read_rows':read_rows,'alignment_qc':qc}

def attach_read_evidence(analysis,folder,reference_path,reference):
    folder=pathlib.Path(folder).resolve()
    if not folder.is_dir():raise ValueError('Alignment-mapppen finnes ikke.')
    analysis['alignment_qc']=[]
    for sample in analysis['samples']:
        name=sample['sample'];accepted={f'{name}_tumor.cram',f'{name}.cram',f'{name}_tumor.bam',f'{name}.bam'}
        matches=sorted(path for path in folder.rglob('*') if path.is_file() and path.name in accepted)
        if len(matches)!=1:raise ValueError('Krever nøyaktig én BAM/CRAM per prøve, navngitt <sample>[_tumor].cram eller .bam.')
        path=matches[0]
        result=analyze_alignment(path,name,analysis['variants'],reference_path,reference)
        analysis['phase_rows'].extend(result['phase_rows']);analysis['read_rows'].extend(result['read_rows']);analysis['alignment_qc'].append(result['alignment_qc'])
        digest=hashlib.sha256(path.read_bytes()).hexdigest()
        analysis['provenance']['files'].append({'file':path.relative_to(folder).as_posix(),'sha256':digest,'kind':'alignment'})
        sample['status']='VCF, tilgjengelig QC og lokal lesningsstøtte importert; funn og klinisk rapportering krever faglig vurdering'
    analysis['mode']='vcf_with_read_evidence'
    analysis['metadata']['alignment_engine']='pysam '+pysam.__version__
    analysis['metadata']['alignment_scope']='All imported SNVs and full codon 315 only; no FASTQ realignment, fusion linkage, indel evidence model, or validated VAF'
    analysis['provenance']['source']='Local deterministic VCF/QC import and explicitly requested BAM/CRAM read evidence; no external queries or clinical classification'
    return analysis
