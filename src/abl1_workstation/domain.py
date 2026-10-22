"""Offline data, review storage and exports for the native ABL1 workstation.

No Qt dependency. External files are data and never execute or resolve attachments.
"""
from __future__ import annotations

import base64
import binascii
import copy
import csv
from contextlib import contextmanager
from dataclasses import dataclass,field
from datetime import datetime,timezone
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import re
import sqlite3
import sys
import tempfile

STATUSES=('Ikke vurdert','Trenger oppfølging','Teknisk gjennomgått','Klar for faglig vurdering')
MAX_JSON=100*1024*1024
MAX_IMAGE=4*1024*1024
_ENGINE=None

def resource_root()->Path:
    if hasattr(sys,'_MEIPASS'):return Path(sys._MEIPASS).resolve()
    module=Path(__file__).resolve()
    resources=module.parent/'resources'
    if (resources/'desktop'/'data'/'pilot.json').is_file():return resources
    return module.parents[2]

def _engine():
    global _ENGINE
    if _ENGINE is None:
        spec=importlib.util.spec_from_file_location('_abl1_validated_engine',resource_root()/'engine'/'analyze.py')
        _ENGINE=importlib.util.module_from_spec(spec)
        spec.loader.exec_module(_ENGINE)
    return _ENGINE

def _canonical(value):
    return json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False)

def _fingerprint(data):
    return hashlib.sha256(_canonical(data).encode('utf-8')).hexdigest()

def _identity(v):
    return {'sample':v['sample'],'chrom':'chr9' if str(v['chrom']).lower() in ('9','chr9') else v['chrom'],'pos':v['pos'],'ref':v['ref'],'alt':v['alt']}

@dataclass
class AnalysisSession:
    data:dict
    run_id:str
    is_pilot:bool=False
    source_label:str=''
    pending_reviews:list=field(default_factory=list)

    def variant_key(self,v):
        return hashlib.sha256(_canonical({'run_id':self.run_id,**_identity(v)}).encode('utf-8')).hexdigest()

def _text(value,limit,field_name,default=''):
    value=default if value is None else value
    if not isinstance(value,str) or len(value)>limit or '\x00' in value:raise ValueError(f'Ugyldig tekstfelt: {field_name}.')
    return value

def _count(value,name,positive=False):
    if isinstance(value,bool):raise ValueError(f'Ugyldig telling: {name}.')
    try:number=float(value)
    except (ValueError,TypeError):raise ValueError(f'Ugyldig telling: {name}.') from None
    if not math.isfinite(number) or not number.is_integer() or number<(1 if positive else 0) or number>9007199254740991:raise ValueError(f'Ugyldig telling: {name}.')
    return int(number)

def _fraction(value,n,d,name):
    try:number=float(value)
    except (ValueError,TypeError):raise ValueError(f'Ugyldig fraksjon: {name}.') from None
    if not math.isfinite(number) or not 0<=number<=1 or d<=0 or abs(number-n/d)>1e-9:raise ValueError(f'Fraksjon og tellergrunnlag stemmer ikke: {name}.')
    return number

def _codon_protein(codon):
    aa3=dict(zip('ACDEFGHIKLMNPQRSTVWY*',['Ala','Cys','Asp','Glu','Phe','Gly','His','Ile','Lys','Leu','Met','Asn','Pro','Gln','Arg','Ser','Thr','Val','Trp','Tyr','Ter']))
    aa=_engine().AA[codon]
    return 'p.Thr315'+('=' if aa=='T' else aa3[aa])

def validate_package(package)->dict:
    """Check sample/locus/count identity and recompute SNV annotations locally."""
    if not isinstance(package,dict) or package.get('schema_version') not in (1,'1','1.0'):raise ValueError('Analysepakken krever schema_version 1.')
    data=copy.deepcopy(package)
    variants=data.get('variants');samples=data.get('samples')
    if not isinstance(variants,list) or not isinstance(samples,list) or len(variants)>10000 or not 0<len(samples)<=500:raise ValueError('Analysepakken må ha samples/variants innen pilotgrensene.')
    metadata=data.get('metadata') or {}
    if not isinstance(metadata,dict):raise ValueError('Ugyldig metadata.')
    assembly=metadata.get('assembly');genome=data.get('genome')
    if not assembly and not genome:raise ValueError('Eksplisitt referansebygg mangler.')
    if assembly and assembly not in ('GRCh37','hg19'):raise ValueError('Bare GRCh37/hg19 støttes.')
    if genome and genome not in ('GRCh37','hg19','GRCh37/hg19','hg19/GRCh37'):raise ValueError('Ukjent eller avvikende genomreferanse.')
    if data.get('transcript') not in (None,'NM_005157.6'):raise ValueError('Bare NM_005157.6 støttes.')
    names=[]
    for sample in samples:
        if not isinstance(sample,dict):raise ValueError('Ugyldig prøvepost.')
        name=_text(sample.get('sample'),200,'sample')
        if not name:raise ValueError('Tomt prøvenavn.')
        names.append(name)
    if len(set(names))!=len(names):raise ValueError('Dupliserte prøvenavn.')
    identities=set()
    for v in variants:
        if not isinstance(v,dict) or v.get('sample') not in names:raise ValueError('Variant koblet til ukjent prøve.')
        _text(v.get('chrom'),200,'chrom');v['pos']=_count(v.get('pos'),'POS',True)
        for key in ('ref','alt'):
            _text(v.get(key),10000,key)
            if not v[key]:raise ValueError('Tom REF/ALT.')
        if not re.fullmatch('[ACGTN]+',v['ref'],re.I):raise ValueError('Ugyldig REF.')
        for key in ('format_af','fraction_informative','soft_clip_ratio'):
            value=v.get(key)
            if value is not None and (isinstance(value,bool) or not isinstance(value,(float,int)) or not math.isfinite(value) or not 0<=value<=1):raise ValueError(f'Ugyldig {key}.')
        for key in ('format_dp','info_dp','ref_ad','alt_ad'):
            if v.get(key) is not None:v[key]=_count(v[key],key)
        v['filter']=_text(v.get('filter'),300,'filter',default='.')
        identity=_canonical(_identity(v))
        if identity in identities:raise ValueError('Duplisert allelidentitet i samme prøve.')
        identities.add(identity)
    for key in ('qc','phase_rows','read_rows','sources'):
        if data.get(key) is None:data[key]=[]
        if not isinstance(data[key],list) or len(data[key])>100000:raise ValueError('Ugyldig felt: '+key)
    groups={}
    for row in data['phase_rows']:
        if not isinstance(row,dict) or row.get('sample') not in names or row.get('hg19_interval1')!='chr9:133748282-133748284' or row.get('reference_codon')!='ACT' or not re.fullmatch('[ACGT]{3}',str(row.get('haplotype',''))):raise ValueError('Ugyldig haplotypeidentitet eller locus.')
        n=_count(row.get('fragments'),'fragments');d=_count(row.get('fragments_all'),'fragments_all',True)
        row['fragments']=n;row['fragments_all']=d;row['fragment_fraction']=_fraction(row.get('fragment_fraction'),n,d,'fragment_fraction')
        group=groups.setdefault((row['sample'],row.get('filter','')),{'denominator':d,'sum':0,'codons':set()})
        if group['denominator']!=d or row['haplotype'] in group['codons']:raise ValueError('Ulike nevnere eller duplisert haplotype.')
        group['sum']+=n;group['codons'].add(row['haplotype'])
        if row.get('total_evaluated_query_name_fragments') is not None:
            total=_count(row['total_evaluated_query_name_fragments'],'evaluated fragments');discordant=_count(row.get('discordant_fragments',0),'discordant fragments')
            if total!=d+discordant:raise ValueError('Samstemte og uenige grupper summerer ikke til vurderte fragmenter.')
        if row.get('reads') is not None:
            rn=_count(row['reads'],'reads');rd=_count(row.get('reads_all'),'reads_all',True)
            if rn>rd:raise ValueError('Read-teller overstiger nevner.')
        row['protein']=_codon_protein(row['haplotype'])
    if any(g['sum']!=g['denominator'] for g in groups.values()):raise ValueError('Haplotypenes sum stemmer ikke med nevner.')
    for row in data['qc']:
        if not isinstance(row,dict) or row.get('sample') not in names:raise ValueError('QC koblet til ukjent prøve.')
    for row in data['read_rows']:
        if not isinstance(row,dict) or row.get('sample') not in names:raise ValueError('Lesningsstøtte koblet til ukjent prøve.')
        pos=_count(row.get('pos1_hg19'),'read position',True)
        read_chrom='chr9' if str(row.get('chr')).lower() in ('9','chr9') else row.get('chr')
        if not any(v['sample']==row['sample'] and _identity(v)['chrom']==read_chrom and v['pos']==pos and v['ref']==row.get('ref') and v['alt']==row.get('alt') for v in variants):raise ValueError('Lesningsstøtte har ingen tilsvarende variantidentitet.')
        rn=_count(row.get('alt_reads'),'alt reads');rd=_count(row.get('read_total'),'read total')
        if rn>rd:raise ValueError('ALT-lesninger overstiger total.')
        if rd:row['alt_read_AF']=_fraction(row.get('alt_read_AF'),rn,rd,'alt read AF')
        elif row.get('alt_read_AF') is not None:raise ValueError('Lesningsfraksjon oppgitt uten nevner.')
        if row.get('alt_forward') is not None or row.get('alt_reverse') is not None:
            if _count(row.get('alt_forward'),'forward ALT')+_count(row.get('alt_reverse'),'reverse ALT')!=rn:raise ValueError('Strandtelling stemmer ikke med ALT-lesninger.')
        n=_count(row.get('alt_query_name_fragments'),'alt fragments');d=_count(row.get('query_name_fragments_total'),'fragment total')
        if n>d:raise ValueError('Lesningsstøtte: ALT-fragmenter overstiger total.')
        if d:row['alt_fragment_AF']=_fraction(row.get('alt_fragment_AF'),n,d,'alt fragment AF')
        elif row.get('alt_fragment_AF') is not None:raise ValueError('Fraksjon oppgitt uten fragmentnevner.')
        if row.get('total_evaluated_query_name_fragments') is not None and _count(row['total_evaluated_query_name_fragments'],'evaluated fragments')!=d+_count(row.get('discordant_fragments',0),'discordant fragments'):raise ValueError('Ugyldig fragmenttellergrunnlag.')
    # Always annotate from the original note text. The existing engine appends
    # technical notes; feeding its own generated text back would duplicate them
    # and change the run fingerprint each time a project was opened.
    to_annotate=[dict(v,source_notes=v.get('source_notes',v.get('notes','')),notes=v.get('source_notes',v.get('notes',''))) for v in variants]
    data['variants']=_engine().annotate_variants(to_annotate,assembly='GRCh37')
    for sample in samples:
        sample['observed_components']=[v for v in data['variants'] if v['sample']==sample['sample'] and v.get('sample_has_alt') is not False and v['filter']=='PASS' and v.get('protein_snv_alone') is not None]
    data['genome']='hg19/GRCh37';data['transcript']='NM_005157.6';data['metadata']={**metadata,'assembly':'GRCh37'}
    _canonical(data)
    return data

def _load_json(path):
    path=Path(path)
    if path.stat().st_size>MAX_JSON:raise ValueError('JSON overstiger 100 MB.')
    try:return json.loads(path.read_text(encoding='utf-8-sig'),parse_constant=lambda value:(_ for _ in ()).throw(ValueError('Ikke-endelig tall i JSON.')))
    except (json.JSONDecodeError,RecursionError) as error:raise ValueError('Ugyldig JSON-fil.') from error

def load_pilot()->AnalysisSession:
    data=validate_package(_load_json(resource_root()/'desktop'/'data'/'pilot.json'))
    if data.get('metadata',{}).get('synthetic_demo') is not True:
        raise ValueError('Den offentlige pakken forventer bare en eksplisitt syntetisk demonstrasjon.')
    return AnalysisSession(data,_fingerprint(data),False,'Syntetisk demonstrasjon – oppdiktede tall')

def is_demo(session)->bool:
    return isinstance(session,AnalysisSession) and session.data.get('metadata',{}).get('synthetic_demo') is True

def load_inputs(paths:list[Path],assembly='GRCh37')->AnalysisSession:
    if assembly not in ('GRCh37','hg19'):raise ValueError('Bare bekreftet GRCh37/hg19 støttes.')
    paths=[Path(path) for path in paths]
    if not paths:raise ValueError('Ingen filer valgt.')
    if len(paths)==1 and paths[0].suffix.lower()=='.json':
        raw=_load_json(paths[0]);project=isinstance(raw,dict) and raw.get('format')=='abl1-project/1'
        data=validate_package(raw.get('analysis') if project else raw);run_id=_fingerprint(data)
        if project and raw.get('run_id')!=run_id:raise ValueError('Prosjektets run_id/fingeravtrykk stemmer ikke med analyseidentiteten.')
        session=AnalysisSession(data,run_id,False,paths[0].name)
        if project:session.pending_reviews=_validate_review_rows(session,raw.get('reviews',[]))
        return session
    if any(path.suffix.lower()=='.json' for path in paths):raise ValueError('Importer én JSON-pakke eller VCF-filer, ikke begge samtidig.')
    results=[_engine().analyze_path(path,assembly) for path in paths]
    merged=copy.deepcopy(results[0]);seen=set()
    for sample in merged['samples']:seen.add(sample['sample'])
    for result in results[1:]:
        if any(sample['sample'] in seen for sample in result['samples']):raise ValueError('Samme prøvenavn finnes i flere valgte filer.')
        seen.update(sample['sample'] for sample in result['samples'])
        for key in ('variants','samples','qc','phase_rows','read_rows'):merged[key].extend(result.get(key,[]))
        merged['provenance']['files'].extend(result.get('provenance',{}).get('files',[]))
    merged['totals']={key:sum(result.get('totals',{}).get(key,0) for result in results) for key in ('records','passed','filtered','snv','insertions','deletions')}
    data=validate_package(merged)
    return AnalysisSession(data,_fingerprint(data),False,', '.join(path.name for path in paths))

def _clean_review(review):
    if not isinstance(review,dict):raise ValueError('Vurderingen må være et objekt.')
    status=review.get('status') or 'Ikke vurdert'
    if status not in STATUSES:raise ValueError('Ukjent vurderingsstatus.')
    clean={'status':status,'note':_text(review.get('note'),20000,'note'),'reviewer':_text(review.get('reviewer'),200,'reviewer'),'updated_at':_text(review.get('updated_at'),100,'updated_at',datetime.now(timezone.utc).isoformat()),'attachments':[]}
    images=review.get('attachments') or []
    if not isinstance(images,list) or len(images)>8:raise ValueError('Høyst åtte kildebilder per vurdering.')
    for image in images:
        if not isinstance(image,dict) or any(key in image for key in ('path','url','file')):raise ValueError('Vedlegg skal være innbakte bildebytes, aldri filstier eller URL-er.')
        name=_text(image.get('name'),200,'image name');mime=image.get('mime');data=image.get('data')
        if not name or any(c in name for c in '/\\\x00') or mime not in ('image/png','image/jpeg','image/webp') or not isinstance(data,str):raise ValueError('Ugyldig bildevedlegg.')
        if data.startswith('data:'):
            prefix=f'data:{mime};base64,'
            if not data.startswith(prefix):raise ValueError('Vedleggets MIME-type stemmer ikke.')
            data=data[len(prefix):]
        if len(data)>(MAX_IMAGE+2)//3*4:raise ValueError('Bildet overstiger 4 MB.')
        try:raw=base64.b64decode(data,validate=True)
        except (ValueError,binascii.Error) as error:raise ValueError('Ugyldig base64-bilde.') from error
        signatures={'image/png':raw.startswith(b'\x89PNG\r\n\x1a\n'),'image/jpeg':raw.startswith(b'\xff\xd8\xff'),'image/webp':raw.startswith(b'RIFF') and raw[8:12]==b'WEBP'}
        if not raw or len(raw)>MAX_IMAGE or not signatures[mime]:raise ValueError('Bildeformatet stemmer ikke med MIME-type.')
        clean['attachments'].append({'name':name,'mime':mime,'data':f'data:{mime};base64,'+base64.b64encode(raw).decode('ascii')})
    return clean

class ReviewStore:
    def __init__(self,path):
        self.path=Path(path);self.path.parent.mkdir(parents=True,exist_ok=True)
        with self._connect() as db:db.execute('CREATE TABLE IF NOT EXISTS reviews (key TEXT PRIMARY KEY, data TEXT NOT NULL)')
    @contextmanager
    def _connect(self):
        db=sqlite3.connect(str(self.path),timeout=10)
        try:
            with db:yield db
        finally:db.close()
    def get(self,key)->dict:
        with self._connect() as db:row=db.execute('SELECT data FROM reviews WHERE key=?',(str(key),)).fetchone()
        return json.loads(row[0]) if row else {}
    def put(self,key,reviewdict):
        key=_text(key,512,'review key');review=_clean_review(reviewdict)
        with self._connect() as db:db.execute('INSERT INTO reviews(key,data) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET data=excluded.data',(key,_canonical(review)))
    def export_for(self,session)->list:
        rows=[]
        for v in session.data['variants']:
            key=session.variant_key(v);review=self.get(key)
            if review:rows.append({'key':key,**review,'identity':{'run_id':session.run_id,**_identity(v)}})
        return rows
    def close(self):pass

def _validate_review_rows(session,rows):
    if not isinstance(rows,list) or len(rows)>len(session.data['variants']):raise ValueError('Ugyldig vurderingsliste.')
    allowed={session.variant_key(v):{'run_id':session.run_id,**_identity(v)} for v in session.data['variants']};output=[];seen=set()
    for row in rows:
        if not isinstance(row,dict) or row.get('key') not in allowed or row['key'] in seen:raise ValueError('Vurderingen tilhører ikke en unik variant i denne kjøringen.')
        if row.get('identity') is not None and row['identity']!=allowed[row['key']]:raise ValueError('Vurderingens variantidentitet stemmer ikke.')
        seen.add(row['key']);output.append({'key':row['key'],**_clean_review(row),'identity':allowed[row['key']]})
    return output

def import_reviews(session,store,rows,*,overwrite=False):
    """Restore absent reviews; implicit project opening preserves local work.

    Timestamps do not grant an imported record authority over local content.
    Callers may expose a separate explicit restore action with overwrite=True.
    Identical content is a no-op, preserving the local timestamp in either mode.
    """
    cleaned=_validate_review_rows(session,rows)
    imported=0
    for row in cleaned:
        existing=store.get(row['key'])
        if existing:
            comparable=lambda review:{k:v for k,v in review.items() if k not in ('key','identity','updated_at')}
            if comparable(existing)==comparable(row) or not overwrite:continue
        store.put(row['key'],row);imported+=1
    return imported

def _atomic_json(path,payload):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True);content=_canonical(payload)
    if len(content.encode('utf-8'))>MAX_JSON:raise ValueError('Prosjektet overstiger 100 MB.')
    handle=None
    try:
        with tempfile.NamedTemporaryFile(mode='w',encoding='utf-8',dir=path.parent,prefix='.'+path.name+'.',suffix='.tmp',delete=False) as stream:
            handle=Path(stream.name);stream.write(content);stream.flush();os.fsync(stream.fileno())
        os.replace(handle,path)
    finally:
        if handle and handle.exists():handle.unlink()

def save_project(session,store,path):
    data=validate_package(session.data)
    if _fingerprint(data)!=session.run_id:raise ValueError('Analysedata er endret etter import; run_id stemmer ikke.')
    _atomic_json(path,{'format':'abl1-project/1','analysis':data,'run_id':session.run_id,'reviews':store.export_for(session)})

def _excel_safe(value):
    if value is None:return ''
    if isinstance(value,(dict,list)):value=_canonical(value)
    if isinstance(value,str) and value.lstrip().startswith(('=','+','-','@')):return "'"+value
    if isinstance(value,str) and value.startswith(('\t','\r','\n')):return "'"+value
    return value

EXPORT_FIELDS=('sample','chrom','pos','ref','alt','filter','cdna','protein_snv_alone','format_af','format_dp','info_dp','ref_ad','alt_ad','bed_edge_bp','phase_required','notes','status','note','reviewer','updated_at')

def export_csv(session,rows,path,store):
    allowed={session.variant_key(v) for v in session.data['variants']};output=[]
    for v in rows:
        key=session.variant_key(v)
        if key not in allowed:raise ValueError('Kan ikke eksportere variant utenfor denne kjøringen.')
        output.append({**v,**store.get(key)})
    with Path(path).open('w',encoding='utf-8-sig',newline='') as stream:
        writer=csv.writer(stream,delimiter=';');writer.writerow(EXPORT_FIELDS)
        for row in output:writer.writerow([_excel_safe(row.get(key)) for key in EXPORT_FIELDS])

def export_xlsx(session,store,path):
    try:from openpyxl import Workbook
    except ImportError as error:raise ImportError('Excel-eksport krever openpyxl i det lokale miljøet.') from error
    wb=Workbook();wb.remove(wb.active)
    def sheet(name,rows,fields=None):
        ws=wb.create_sheet(name);fields=fields or list(dict.fromkeys(key for row in rows for key in row))
        if not fields:fields=['Ingen data']
        ws.append(fields)
        for row in rows:ws.append([_excel_safe(row.get(key)) for key in fields])
        ws.freeze_panes='A2';ws.auto_filter.ref=ws.dimensions
        for col in ws.columns:ws.column_dimensions[col[0].column_letter].width=min(60,max(14,len(str(col[0].value or ''))+2))
        return ws
    sheet('Oppsummering',[{'run_id':session.run_id,'kilde':session.source_label,'prøver':len(session.data['samples']),'variantposter':len(session.data['variants']),'status':'Teknisk pilot; ikke klinisk validert'}])
    sheet('Varianter',[{**v,**store.get(session.variant_key(v))} for v in session.data['variants']],list(EXPORT_FIELDS))
    for name,key in [('Prøver','samples'),('QC','qc'),('Haplotyper','phase_rows'),('Lesninger','read_rows'),('Kilder','sources')]:sheet(name,session.data.get(key,[]))
    sheet('Sporbarhet',[{'felt':'metadata','verdi':session.data.get('metadata',{})},{'felt':'provenance','verdi':session.data.get('provenance',{})},{'felt':'tolkningsgrense','verdi':'Databasefunn, analytisk støtte og klinisk vurdering er separate. Fragmentobservasjoner er ikke unike molekyler eller validerte VAF-er.'}])
    wb.save(path)
