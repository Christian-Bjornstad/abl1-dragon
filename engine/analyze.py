"""Offline BCR::ABL1 pilot VCF/QC importer, Python standard library only.

No external annotation, clinical classification, or CRAM phasing is performed.
"""
import argparse
import csv
import gzip
import hashlib
import json
import pathlib
import re
import sys

VERSION='0.1.0'
ROOT=pathlib.Path(__file__).resolve().parent
REFERENCE=json.loads((ROOT/'reference.json').read_text(encoding='utf-8'))
CODONS=[a+b+c for a in 'TCAG' for b in 'TCAG' for c in 'TCAG']
AA=dict(zip(CODONS,'FFLLSSSSYY**CC*WLLLLPPPPHHQQRRRRIIIMTTTTNNKKSSRRVVVVAAAADDEEGGGG'))

def number(value):
    if value in (None,'','.'):return None
    try:
        parsed=float(value)
        if not float('-inf')<parsed<float('inf'):return None
        return int(parsed) if parsed.is_integer() else parsed
    except (TypeError,ValueError):return None

def chrom_name(value):
    return 'chr9' if value=='9' else str(value)

def add_note(row,note):
    parts=row.get('notes','').split('; ') if row.get('notes') else []
    if note not in parts:parts.append(note)
    row['notes']='; '.join(parts)

def check_reference(assembly,reference):
    if assembly not in ('GRCh37','hg19'):raise ValueError('Piloten støtter bare bekreftet GRCh37/hg19. Ingen automatisk liftover.')
    if reference.get('assembly')!='GRCh37':raise ValueError('Lokal GRCh37-referanse mangler eller har feil assembly.')

def annotate_variants(variants,assembly='GRCh37',reference=None):
    reference=reference or REFERENCE
    check_reference(assembly,reference)
    output=[]
    for source in variants:
        row=dict(source,cdna=None,protein_snv_alone=None,ref_codon=None,alt_codon=None,codon=None,bed_edge_bp=None,bed_name=None,reference_match=None,normal_transcript_continuation=False,phase_required=False)
        row['notes']=source.get('notes') or ''
        chrom=chrom_name(row['chrom']);pos=int(row['pos']);ref=row['ref'].upper();alt=row['alt'].upper()
        row['type']='SNV' if len(ref)==len(alt)==1 else 'INS' if len(alt)>len(ref) else 'DEL' if len(alt)<len(ref) else 'MNV'
        if not re.fullmatch('[ACGTN]+',alt):row['type']='SYMBOLIC'
        offset=pos-1-reference['genomic_start0']
        if chrom==reference['chrom'] and offset>=0 and offset+len(ref)<=len(reference['genomic_sequence']):
            row['reference_match']=reference['genomic_sequence'][offset:offset+len(ref)]==ref
            if not row['reference_match']:add_note(row,'REF avviker fra lokal GRCh37-referanse; annotasjon sperret')
        else:add_note(row,'Utenfor lokal ABL1-referanse; proteinannotasjon utilgjengelig')
        hit=next((b for b in reference['bed'] if chrom_name(b['chrom'])==chrom and b['start']<pos<=b['end']),None)
        if hit:
            row['bed_name']=hit['name'];row['bed_edge_bp']=min(pos-hit['start']-1,hit['end']-pos)
            if row['bed_edge_bp']<=3:add_note(row,'Nær BED-kant (screeningflagg; ikke automatisk eksklusjon)')
        cp=reference['coding_map'].get(str(pos)) if chrom==reference['chrom'] else None
        if row['reference_match'] is True and row['type']=='SNV' and cp and re.fullmatch('[ACGT]',alt):
            at=reference['cds_start_t0']+((cp-1)//3)*3
            row['ref_codon']=reference['transcript_sequence'][at:at+3];k=(cp-1)%3
            row['alt_codon']=row['ref_codon'][:k]+alt+row['ref_codon'][k+1:]
            row['codon']=(cp-1)//3+1
            row['cdna']=f'c.{cp}{ref}>{alt}'
            row['protein_snv_alone']=f"p.{AA[row['ref_codon']]}{row['codon']}{AA[row['alt_codon']]}"
            if row['codon']<=26:add_note(row,'Native ABL1 exon1a; relevans må vurderes mot faktisk BCR::ABL1-fusjonsreferanse')
            if row['codon']==27:add_note(row,'Kodon 27 berører native exon1a; må kontrolleres mot faktisk BCR::ABL1-fusjonsreferanse')
        if row['reference_match'] is True and row['type']=='INS' and alt.startswith(ref) and chrom==reference['chrom']:
            exon=next((e for e in reference['exons'] if e['start0']<pos<=e['end0']),None)
            if exon:
                t=exon['transcript_start0']+pos-exon['start0']-1+len(ref);inserted=alt[len(ref):]
                row['normal_transcript_continuation']=reference['transcript_sequence'][t:t+len(inserted)]==inserted
                if row['normal_transcript_continuation']:add_note(row,'Innsatt sekvens matcher direkte fortsettelse i normalt ABL1-transkript')
        if row['filter']=='.':add_note(row,'FILTER ikke evaluert (.); regnes ikke som PASS')
        elif row['filter']!='PASS':add_note(row,'VCF-filtrert: '+row['filter'])
        output.append(row)
    groups={}
    for row in output:
        if row['codon'] is not None and row.get('sample_has_alt') is not False:groups.setdefault((row['sample'],chrom_name(row['chrom']),row['codon']),[]).append(row)
    for group in groups.values():
        if len(group)>1:
            for row in group:
                row['phase_required']=True
                add_note(row,'Flere variantkomponenter i samme kodon: lesningsbasert fase kreves; VCF alene avgjør ikke haplotype')
    return output

def allele_value(value,definition,alt_index,alt_count):
    if not isinstance(value,str) or value=='.':return None
    parts=value.split(',');count=definition.get('Number')
    def typed(part):return None if part=='.' else part if definition.get('Type') in ('String','Character') else number(part)
    if count=='A':return typed(parts[alt_index]) if len(parts)==alt_count else None
    if count=='R':return typed(parts[alt_index+1]) if len(parts)==alt_count+1 else None
    if alt_count>1:return None
    return typed(parts[0]) if len(parts)==1 else None


def vcf_sample_fallback(filename):
    name=pathlib.Path(str(filename)).name
    return re.sub(r'(?:\.hard-filtered)?\.vcf(?:\.gz)?$','',name,flags=re.I) or 'Ukjent'


def read_vcf_text(path):
    path=pathlib.Path(path)
    if path.name.lower().endswith('.gz'):
        with gzip.open(path,'rt',encoding='utf-8-sig') as stream:text=stream.read(25*1024*1024+1)
    else:
        with path.open('rt',encoding='utf-8-sig') as stream:text=stream.read(25*1024*1024+1)
    if len(text)>25*1024*1024:raise ValueError('VCF overskrider grensen på 25 MB: '+path.name)
    return text


def vcf_samples(text,filename):
    headers=[line.split('\t') for line in text.lstrip('\ufeff').splitlines() if line.startswith('#CHROM\t')]
    if len(headers)!=1:raise ValueError('Krever én #CHROM-header i '+str(filename))
    header=headers[0]
    if header[:8]!=['#CHROM','POS','ID','REF','ALT','QUAL','FILTER','INFO'] or (len(header)!=8 and (len(header)<10 or header[8]!='FORMAT')):
        raise ValueError('Ugyldig VCF-header i '+str(filename))
    names=header[9:] or [vcf_sample_fallback(filename)]
    if any(not value for value in names) or len(names)!=len(set(names)):raise ValueError('Ugyldige/dupliserte prøvenavn i '+str(filename))
    return tuple(names)


def qc_prefix(file,sample):
    """Only exact identifiers beside the selected VCF may supply its QC."""
    file=pathlib.Path(file);prefixes=list(dict.fromkeys((sample,vcf_sample_fallback(file.name))))
    found=[prefix for prefix in prefixes if any(_local_file(file.parent/(prefix+'.'+suffix),file.parent) for suffix in ('mapping_metrics.csv','target_bed_coverage_metrics.csv','target_bed_somatic_callable_regions.bed'))]
    if len(found)>1:
        for suffix in ('mapping_metrics.csv','target_bed_coverage_metrics.csv','target_bed_somatic_callable_regions.bed'):
            values=[(file.parent/(prefix+'.'+suffix)).read_bytes() for prefix in found if _local_file(file.parent/(prefix+'.'+suffix),file.parent)]
            if len(set(values))>1:raise ValueError('Motstridende QC-prefikser for '+sample+' ved '+file.name)
    return found[0] if found else sample


def _local_file(path,folder):
    return path.is_file() and path.resolve().is_relative_to(folder.resolve())


def _qc_signature(file,sample):
    prefix=qc_prefix(file,sample)
    return {suffix:hashlib.sha256((file.parent/(prefix+'.'+suffix)).read_bytes()).hexdigest()
            for suffix in ('mapping_metrics.csv','target_bed_coverage_metrics.csv','target_bed_somatic_callable_regions.bed')
            if _local_file(file.parent/(prefix+'.'+suffix),file.parent)}


def select_vcf_paths(input_path):
    """Select one unambiguous single-sample callset per sample, locally only."""
    path=pathlib.Path(input_path).resolve()
    if not path.exists():raise ValueError('Inndata finnes ikke.')
    base=path if path.is_dir() else path.parent
    candidates=sorted((p for p in (path.rglob('*') if path.is_dir() else [path]) if p.is_file() and p.name.lower().endswith(('.vcf','.vcf.gz'))),key=lambda p:p.relative_to(base).as_posix().casefold())
    warnings=[];entries=[]
    for file in candidates:
        resolved=file.resolve()
        if not resolved.is_relative_to(base):
            warnings.append('Ignorerer VCF utenfor valgt mappe: '+file.name);continue
        name=file.relative_to(base).as_posix()
        if re.search(r'(?:\.g|\.gvcf)\.vcf(?:\.gz)?$|\.gvcf(?:\.gz)?$',file.name,re.I):
            warnings.append('Ignorerer gVCF: '+name);continue
        text=read_vcf_text(file);samples=vcf_samples(text,file.name)
        if len(samples)!=1:
            warnings.append('Ignorerer joint/flerprøve-VCF: '+name);continue
        if any('<NON_REF>' in line or '<*>' in line or (not line.startswith('#') and len(line.split('\t'))>7 and line.split('\t')[4]=='.' and re.search(r'(?:^|;)END=',line.split('\t')[7])) for line in text.splitlines() if line):
            warnings.append('Ignorerer gVCF/referanseblokker: '+name);continue
        entries.append({'path':resolved,'sample':samples[0],'text_hash':hashlib.sha256(text.encode('utf-8')).hexdigest(),'hard':bool(re.search(r'\.hard-filtered\.vcf(?:\.gz)?$',file.name,re.I))})
    chosen=[]
    for sample in sorted({row['sample'] for row in entries},key=str.casefold):
        rows=[row for row in entries if row['sample']==sample]
        hard=[row for row in rows if row['hard']]
        if hard:
            for row in rows:
                if row not in hard:warnings.append('Bruker hard-filtered VCF for '+sample+'; utelater '+row['path'].relative_to(base).as_posix())
            rows=hard
        hashes={row['text_hash'] for row in rows}
        if len(hashes)!=1:raise ValueError('Flere ulike VCF-kallsett for '+sample+'. Velg én kjøring/fil.')
        signatures=[_qc_signature(row['path'],sample) for row in rows]
        for suffix in set().union(*(set(signature) for signature in signatures)):
            if len({signature[suffix] for signature in signatures if suffix in signature})>1:raise ValueError('Motstridende QC ved duplikat-VCF for '+sample)
        best=sorted(rows,key=lambda row:(-len(_qc_signature(row['path'],sample)),not row['path'].name.lower().endswith('.gz'),row['path'].relative_to(base).as_posix().casefold()))[0]
        chosen.append(best['path'])
        for row in rows:
            if row is not best:warnings.append('Identisk VCF-duplikat utelatt: '+row['path'].relative_to(base).as_posix())
    if not chosen:raise ValueError('Ingen entydig enkeltprøve-VCF funnet. '+(' '.join(warnings)))
    return sorted(chosen,key=lambda p:p.relative_to(base).as_posix().casefold()),warnings

def parse_vcf(text,filename='local.vcf',assembly='GRCh37',reference=None):
    reference=reference or REFERENCE
    check_reference(assembly,reference)
    if not isinstance(text,str) or len(text)>25*1024*1024:raise ValueError('VCF må være tekst og høyst 25 MB i piloten.')
    definitions={'FORMAT':{},'INFO':{}};reference_headers=[];raw=[];header=None;sample_names=[];fileformat=False
    for i,line in enumerate(text.lstrip('\ufeff').splitlines(),1):
        if not line:continue
        if line.startswith('##fileformat=VCFv4.'):fileformat=True
        if line.startswith(('##FORMAT=<','##INFO=<')):
            group='FORMAT' if line.startswith('##FORMAT') else 'INFO'
            definition={k:v.strip('"') for k,v in re.findall(r'(?:^|,)([A-Za-z0-9_]+)=("(?:[^"\\]|\\.)*"|[^,]*)',line[line.index('<')+1:-1])}
            if definition.get('ID'):definitions[group][definition['ID']]=definition
        if re.match('##(?:reference|assembly|contig)=',line,re.I):
            if re.search('GRCh38|hg38|hs38',line,re.I):raise ValueError('VCF-header angir GRCh38/hg38; annotasjon mot GRCh37 er sperret.')
            if not line.startswith('##contig='):reference_headers.append(line)
        if line.startswith('##'):continue
        if line.startswith('#CHROM\t'):
            if header:raise ValueError('Duplisert VCF-kolonneheader.')
            header=line.split('\t')
            if header[:8]!=['#CHROM','POS','ID','REF','ALT','QUAL','FILTER','INFO'] or (len(header)!=8 and (len(header)<10 or header[8]!='FORMAT')):raise ValueError('Ugyldig VCF-kolonneheader.')
            sample_names=header[9:]
            if len(set(sample_names))!=len(sample_names):raise ValueError('Dupliserte prøvenavn i VCF-header.')
            continue
        if line.startswith('#'):continue
        if not header:raise ValueError('VCF-kolonneheader (#CHROM) mangler.')
        c=line.split('\t')
        if len(c)!=len(header):raise ValueError(f'VCF linje {i}: feil antall kolonner.')
        if not re.fullmatch('[0-9]+',c[1]) or int(c[1])<1 or int(c[1])>9007199254740991:raise ValueError(f'VCF linje {i}: ugyldig POS-posisjon.')
        pos=int(c[1])
        if not re.fullmatch('[ACGTN]+',c[3],re.I):raise ValueError(f'VCF linje {i}: ugyldig REF.')
        alts=c[4].split(',')
        if any(not alt or alt=='.' or (not re.fullmatch('[ACGTN]+',alt,re.I) and not re.fullmatch(r'<[^<>\s]+>',alt) and alt!='*' and not re.search(r'[\[\]]',alt)) for alt in alts):raise ValueError(f'VCF linje {i}: ugyldig ALT.')
        info={}
        for part in c[7].split(';'):
            if part!='.':
                key,sep,value=part.partition('=');info[key]=value if sep else True
        names=sample_names or [vcf_sample_fallback(filename)]
        format_keys=c[8].split(':') if len(c)>8 else []
        for sample_index,sample in enumerate(names):
            values=c[9+sample_index].split(':') if len(c)>9+sample_index else []
            fmt=dict(zip(format_keys,values))
            for ai,alt in enumerate(alts):
                ad=fmt['AD'].split(',') if fmt.get('AD') not in (None,'.') else [];valid_ad=len(ad)==len(alts)+1 and definitions['FORMAT'].get('AD',{'Number':'R'}).get('Number')=='R'
                row={'sample':sample,'chrom':c[0],'pos':pos,'ref':c[3].upper(),'alt':alt.upper(),'type':None,'filter':c[6],'format_af':allele_value(fmt.get('AF'),definitions['FORMAT'].get('AF',{'Number':'A'}),ai,len(alts)),'format_dp':number(fmt.get('DP')),'ref_ad':number(ad[0]) if valid_ad else None,'alt_ad':number(ad[ai+1]) if valid_ad else None,'sq':allele_value(fmt.get('SQ'),definitions['FORMAT'].get('SQ',{'Number':'A'}),ai,len(alts)),'info_dp':number(info.get('DP')),'fraction_informative':number(info.get('FractionInformativeReads')),'soft_clip_ratio':number(info.get('SoftClipRatio')),'f1r2':fmt.get('F1R2'),'f2r1':fmt.get('F2R1'),'sb':fmt.get('SB'),'mb':fmt.get('MB'),'gt':fmt.get('GT'),'ps':fmt.get('PS'),'source':filename,'source_line':i,'alt_index':ai+1,'alt_count':len(alts),'notes':'','expected_component':False,'excel_range':None,'format_allele_fields':{},'info_allele_fields':{}}
                gt=re.split(r'[|/]',fmt.get('GT') or '.')
                row['format_af']=number(row['format_af']);row['sq']=number(row['sq'])
                row['sample_has_alt']=None if all(v=='.' for v in gt) else str(ai+1) in gt
                if row['sample_has_alt'] is False:add_note(row,'ALT er ikke kalt i denne prøvens GT; beholdes som VCF-post, ikke som påvist variant')
                for kind,source,key in [('FORMAT',fmt,'format_allele_fields'),('INFO',info,'info_allele_fields')]:
                    for field,definition in definitions[kind].items():
                        if definition.get('Number') in ('A','R') and field in source:row[key][field]=allele_value(source[field],definition,ai,len(alts))
                if row['format_af'] is None:add_note(row,'FORMAT/AF mangler eller kan ikke fordeles entydig; ingen AF beregnet fra AD')
                raw.append(row)
                if len(raw)>200000:raise ValueError('VCF overskrider pilotgrensen på 200 000 variantkomponenter.')
    if not fileformat or not header:raise ValueError('Gyldig VCFv4-fil og #CHROM-header kreves.')
    variants=annotate_variants(raw,assembly,reference)
    names=sample_names or [vcf_sample_fallback(filename)]
    samples=[{'sample':sample,'expected':'Ukjent','expected_cdna':None,'expected_protein':None,'observed_components':[v for v in variants if v['sample']==sample and v['sample_has_alt'] is not False and v['type']=='SNV' and v['filter']=='PASS' and v['protein_snv_alone'] is not None],'status':'Kun VCF: funn krever vurdering; negativitet, dekning og haplotyper er ikke validert','note':''} for sample in names]
    return {'schema_version':1,'mode':'vcf_only','date':None,'transcript':reference['transcript'],'protein':reference['protein'],'genome':'hg19/GRCh37','variants':variants,'samples':samples,'qc':[],'phase_rows':[],'read_rows':[],'intervals':[],'bed':reference['bed'],'sources':[],'metadata':{'assembly':'GRCh37','assembly_confirmation':'Selected by user; no liftover','reference_headers':reference_headers,'transcript':reference['transcript'],'engine_version':VERSION,'clinical_validation':'Not clinically validated'},'provenance':{'source':'Local VCF import; no network or alignment analysis','files':[{'file':filename}]},'totals':{'records':len(variants),'passed':sum(v['filter']=='PASS' for v in variants),'filtered':sum(v['filter']!='PASS' for v in variants),'snv':sum(v['type']=='SNV' for v in variants),'insertions':sum(v['type']=='INS' for v in variants),'deletions':sum(v['type']=='DEL' for v in variants)}}

def parse_qc(folder,sample,variants,prefix=None):
    """Read supplied DRAGEN metrics. Missing metrics remain None; no QC threshold inference."""
    metrics={};files=[];prefix=prefix or sample
    for suffix in ['mapping_metrics.csv','target_bed_coverage_metrics.csv']:
        path=folder/f'{prefix}.{suffix}'
        if not _local_file(path,folder):continue
        files.append(path)
        for row in csv.reader(path.read_text(encoding='utf-8-sig').splitlines()):
            if len(row)>3 and row[1]=='':metrics[row[2]]=row[3:]
    if not metrics:return None,files
    def metric(name,pct=False):
        values=metrics.get(name,[]);index=1 if pct else 0
        return number(values[index]) if len(values)>index else None
    callable_path=folder/f'{prefix}.target_bed_somatic_callable_regions.bed'
    callable_bases=None
    if _local_file(callable_path,folder):
        files.append(callable_path);intervals={}
        for row in csv.reader(callable_path.read_text(encoding='utf-8-sig').splitlines(),delimiter='\t'):
            if len(row)>=3 and not row[0].startswith('#'):intervals.setdefault(row[0],[]).append((int(row[1]),int(row[2])))
        callable_bases=0
        for spans in intervals.values():
            end=-1
            for start,stop in sorted(spans):
                callable_bases+=max(0,stop-max(start,end));end=max(end,stop)
    # The denominator is only used if this run includes the identical research BED.
    target_bases=None
    for bed in folder.glob('*RESEARCH_ONLY.bed'):
        if not _local_file(bed,folder):continue
        rows=[]
        for line in bed.read_text(encoding='utf-8-sig').splitlines():
            c=line.split('\t')
            if len(c)>=3 and not c[0].startswith('#'):rows.append((c[0],int(c[1]),int(c[2])))
        if rows==[(b['chrom'],b['start'],b['end']) for b in REFERENCE['bed']]:target_bases=sum(end-start for _,start,end in rows);files.append(bed);break
    calls=[v for v in variants if v['sample']==sample]
    return {'sample':sample,'total_reads':metric('Total input reads'),'mapped_pct':metric('Mapped reads',True),'q30_pct':metric('Q30 bases',True),'mean_target_depth':metric('Average alignment coverage over target region'),'pct_ge20':metric('PCT of target region with coverage [  20x: inf)'),'pct_ge50':metric('PCT of target region with coverage [  50x: inf)'),'pct_ge100':metric('PCT of target region with coverage [ 100x: inf)'),'callable_bases':callable_bases,'target_bases':target_bases,'callable_pct':100*callable_bases/target_bases if callable_bases is not None and target_bases else None,'vcf_records':len(calls),'pass_records':sum(v['filter']=='PASS' for v in calls),'pass_snv':sum(v['filter']=='PASS' and v['type']=='SNV' for v in calls),'mismatch_r1_pct':metric('Mismatched bases R1 (excl. indels)',True),'mismatch_r2_pct':metric('Mismatched bases R2 (excl. indels)',True)},files

def analyze_path(input_path,assembly,alignments=None,reference_fasta=None):
    check_reference(assembly,REFERENCE)
    path=pathlib.Path(input_path).resolve()
    if not path.exists():raise ValueError('Inndata finnes ikke.')
    base=path if path.is_dir() else path.parent
    paths,discovery_warnings=select_vcf_paths(path)
    results=[];sample_names=set();manifest=[];qc_rows=[]
    for file in paths:
        name=file.relative_to(base).as_posix();raw=file.read_bytes()
        text=read_vcf_text(file)
        result=parse_vcf(text,name,assembly)
        for sample in result['samples']:
            if sample['sample'] in sample_names:raise ValueError('Samme prøvenavn finnes i flere VCF-filer; fjern duplikater før import.')
            sample_names.add(sample['sample'])
            qc,files=parse_qc(file.parent,sample['sample'],result['variants'],prefix=qc_prefix(file,sample['sample']))
            if qc:qc_rows.append(qc)
            for qfile in files:manifest.append({'file':qfile.relative_to(base).as_posix(),'sha256':hashlib.sha256(qfile.read_bytes()).hexdigest(),'kind':'qc_or_bed'})
        manifest.append({'file':name,'sha256':hashlib.sha256(raw).hexdigest(),'kind':'vcf'})
        results.append(result)
    out=dict(results[0]);out['variants']=[v for result in results for v in result['variants']];out['samples']=[s for result in results for s in result['samples']];out['qc']=qc_rows
    out['mode']='vcf_with_qc' if qc_rows else 'vcf_only'
    out['provenance']={'source':'Local deterministic VCF/QC import; no alignment processing, external queries, or clinical classification','files':manifest,'reference_sha256':hashlib.sha256((ROOT/'reference.json').read_bytes()).hexdigest()}
    out['metadata']['discovery_warnings']=discovery_warnings
    out['totals']={key:sum(result['totals'].get(key,0) for result in results) for key in ('records','passed','filtered','snv','insertions','deletions')}
    if qc_rows:
        for sample in out['samples']:sample['status']='VCF og eventuelle QC-målinger importert; funn, negativitet og haplotyper krever faglig vurdering'
    if bool(alignments)!=bool(reference_fasta):raise ValueError('--alignments og --reference må oppgis sammen.')
    if alignments:
        try:
            from read_evidence import attach_read_evidence
        except ImportError as error:
            raise ValueError('Lesningsanalyse krever lokal pysam-installasjon (valgfri); VCF/QC-import bruker bare Python standardbibliotek.') from error
        out=attach_read_evidence(out,alignments,reference_fasta,REFERENCE)
    return out

def main(argv=None):
    parser=argparse.ArgumentParser(description='Lokal BCR::ABL1 forskningspilot. Leser VCF og tilgjengelige DRAGEN QC-filer; sender ingenting ut.')
    parser.add_argument('--input',required=True,type=pathlib.Path,help='VCF(.gz) eller kjøringsmappe')
    parser.add_argument('--assembly',required=True,choices=['GRCh37','hg19'],help='Bekreftet genomreferanse; ingen liftover')
    parser.add_argument('--output',required=True,type=pathlib.Path,help='Ny analyse-JSON. Eksisterende fil overskrives ikke.')
    parser.add_argument('--alignments',type=pathlib.Path,help='Valgfritt: mappe med <sample>[_tumor].cram/.bam og indekser; krever pysam')
    parser.add_argument('--reference',type=pathlib.Path,help='Valgfritt: lokal komplett hg19 chr9 FASTA med .fai; brukes sammen med --alignments')
    args=parser.parse_args(argv)
    try:
        result=analyze_path(args.input,args.assembly,args.alignments,args.reference)
        args.output.parent.mkdir(parents=True,exist_ok=True)
        with args.output.open('x',encoding='utf-8') as stream:json.dump(result,stream,ensure_ascii=False,indent=2,allow_nan=False)
    except (ValueError,OSError,UnicodeError,csv.Error) as error:
        parser.exit(2,f'Import stoppet: {error}\n')
    print(f"Lagret {len(result['variants'])} variantkomponenter, {len(result['samples'])} prøver, {len(result['qc'])} QC-rader og {len(result['phase_rows'])} haplotyperader. Ingen nettverkskall.")

if __name__=='__main__':
    main()
