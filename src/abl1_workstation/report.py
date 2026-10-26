"""One worksheet per selected sample/allele, with local evidence images."""
from datetime import datetime
from pathlib import Path
import math,os,re,tempfile
from urllib.parse import urlsplit
from . import APP_NAME,__version__
from .models import flags
from .workflow import allele_key,row_key

PROVIDER_NAMES={'clinvar':'ClinVar','gnomad':'gnomAD','cosmic':'COSMIC','oncokb':'OncoKB','franklin':'Franklin','mtbp':'MTBP'}
STATUS_NAMES={'not_found':'Ingen treff','login_required':'Innlogging kreves','license_required':'Tilgang kreves','error':'Feil','unsupported':'Ikke tilgjengelig'}

def source_text(result):
    if not result:return 'Ikke slått opp'
    status=result.get('status')
    if status!='found':return STATUS_NAMES.get(status,status or 'Ukjent status')
    parts=[]
    for field in ('classification','evidence_level','summary'):
        value=result.get(field)
        if value and str(value) not in parts:parts.append(str(value))
    return ' · '.join(parts) or str(result.get('accession') or 'Treff')

def safe_text(value):
    if isinstance(value,str):
        value=''.join(c for c in value if ord(c)>=32 or c in '\n\t')
        if value.lstrip().startswith(('=','+','-','@')):value="'"+value
        return value[:32767]
    return value

def _sheet_name(variant,used):
    raw=str(variant.get('protein_snv_alone') or variant.get('cdna') or variant.get('pos') or 'Variant')
    base=re.sub(r'[\[\]:*?/\\\x00-\x1f]','_',raw.removeprefix('p.')).strip(" '") or 'Variant'
    name=base[:31];number=1
    while name.casefold() in used:
        suffix=' '+str(number+1);name=base[:31-len(suffix)]+suffix;number+=1
    used.add(name.casefold());return name

def _image(sheet,path,row):
    from PIL import Image as PillowImage
    from openpyxl.drawing.image import Image
    path=Path(path)
    if path.stat().st_size>20*1024*1024:raise ValueError('Bildet er for stort.')
    with PillowImage.open(path) as source:
        if source.format!='PNG' or source.width*source.height>32_000_000:raise ValueError('Ugyldig PNG-bilde.')
        source.verify()
    image=Image(str(path));scale=min(1,1000/image.width)
    image.width=round(image.width*scale);image.height=round(image.height*scale)
    sheet.add_image(image,'A'+str(row))
    return row+math.ceil(image.height/20)+2

def export_report(session,rows,lookup_results,path,*,providers=('clinvar','gnomad','cosmic','oncokb','franklin'),samples=None,selection='',igv_images=None,igv_errors=None):
    from openpyxl import Workbook
    from openpyxl.styles import Alignment,Font,PatternFill
    from openpyxl.comments import Comment
    rows=list(rows)
    if not rows:raise ValueError('Merk minst én variant før eksport.')
    book=Workbook();book.remove(book.active);used=set()
    for variant in rows:
        sheet=book.create_sheet(_sheet_name(variant,used));sheet.sheet_view.showGridLines=False
        for column in 'ABCDEFGH':sheet.column_dimensions[column].width=18
        def block(row,text,*,heading=False):
            sheet.merge_cells(start_row=row,start_column=1,end_row=row,end_column=8)
            cell=sheet.cell(row,1,safe_text(text));cell.alignment=Alignment(vertical='center',wrap_text=True)
            cell.font=Font(name='Calibri',size=12 if heading else 11,bold=heading,color='FFFFFF' if heading else '292633')
            if heading:cell.fill=PatternFill('solid',fgColor='7150A1')
            sheet.row_dimensions[row].height=28 if heading else 34
            return cell
        block(1,str(variant.get('protein_snv_alone') or variant.get('cdna') or 'Variant')+' · '+str(variant.get('sample','')),heading=True)
        block(2,APP_NAME+' · '+__version__+' · GRCh37 / NM_005157.6 · '+datetime.now().isoformat(timespec='minutes'))
        facts=[('Prøve',variant.get('sample')),('Genomisk posisjon',f"{variant.get('chrom')}:{variant.get('pos')} {variant.get('ref')}>{variant.get('alt')}"),
               ('cDNA',variant.get('cdna')),('Protein, enkeltallel',variant.get('protein_snv_alone')),
               ('AF (%)',variant.get('format_af')*100 if variant.get('format_af') is not None else 'Ikke oppgitt'),
               ('ALT / DP',f"{variant.get('alt_ad','–')} / {variant.get('format_dp','–')}"),('FILTER',variant.get('filter'))]
        for row,(name,value) in enumerate(facts,4):
            sheet.merge_cells(start_row=row,start_column=1,end_row=row,end_column=2)
            sheet.cell(row,1,name).font=Font(bold=True,color='7150A1')
            sheet.merge_cells(start_row=row,start_column=3,end_row=row,end_column=8)
            cell=sheet.cell(row,3,safe_text(value));cell.alignment=Alignment(wrap_text=True,vertical='top')
            sheet.row_dimensions[row].height=24
            if name=='AF (%)':cell.number_format='0.00'
            if name=='Protein, enkeltallel' and flags(variant):cell.comment=Comment(safe_text('; '.join(flags(variant))),APP_NAME)
        row=12;block(row,'IGV',heading=True);row+=1
        picture=(igv_images or {}).get(row_key(variant))
        if picture:row=_image(sheet,picture,row)
        else:
            block(row,'Ikke tilgjengelig: '+str((igv_errors or {}).get(row_key(variant)) or 'BAM/CRAM og kontrollert referanse kreves.'));row+=2
        sources={r['provider']:r for r in lookup_results.get(allele_key(variant),[])}
        for provider in providers:
            result=sources.get(provider);cell=block(row,PROVIDER_NAMES.get(provider,provider),heading=True);row+=1
            text=block(row,source_text(result));sheet.row_dimensions[row].height=64
            if result:
                text.comment=Comment(safe_text('\n'.join(str(result.get(k) or '') for k in ('provider','checked_at','accession','url','identity_method'))),APP_NAME)
                url=str(result.get('url') or '')
                if urlsplit(url).scheme=='https':cell.hyperlink=url
            row+=2
            picture=result.get('screenshot') if result and result.get('status')=='found' and result.get('identity_verified') else None
            if picture:row=_image(sheet,picture,row)
            elif result and result.get('screenshot_error'):block(row,'Bilde: '+str(result['screenshot_error']));row+=2
        sheet.freeze_panes='C4';sheet.print_options.horizontalCentered=True
        sheet.sheet_properties.pageSetUpPr.fitToPage=True
        sheet.page_setup.orientation='landscape';sheet.page_setup.paperSize=sheet.PAPERSIZE_A3
        sheet.page_setup.fitToWidth=1;sheet.page_setup.fitToHeight=0;sheet.print_title_rows='1:2'
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    descriptor,temporary=tempfile.mkstemp(prefix='.DRAGEN-',suffix='.xlsx',dir=path.parent);os.close(descriptor)
    try:book.save(temporary);os.replace(temporary,path)
    finally:
        book.close()
        if Path(temporary).exists():Path(temporary).unlink()
