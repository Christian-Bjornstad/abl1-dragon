"""Single-sheet result export with original caller fields and source status."""
from datetime import datetime
from pathlib import Path
from . import APP_NAME, __version__
from .models import flags
from .workflow import allele_key,category

PROVIDER_NAMES={'clinvar':'ClinVar','gnomad':'gnomAD','cosmic':'COSMIC',
                'oncokb':'OncoKB','franklin':'Franklin','mtbp':'MTBP'}
STATUS_NAMES={'not_found':'Ingen treff','login_required':'Innlogging kreves',
              'license_required':'Tilgang kreves','error':'Feil','unsupported':'Ikke tilgjengelig'}


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


def export_report(session,rows,lookup_results,path,*,providers=('clinvar','gnomad','cosmic','oncokb','franklin'),samples=None,selection=''):
    from openpyxl import Workbook
    from openpyxl.styles import Alignment,Font,PatternFill
    from openpyxl.worksheet.table import Table,TableStyleInfo
    from openpyxl.comments import Comment
    book=Workbook();sheet=book.active;sheet.title='Resultater'
    sheet.append([APP_NAME,__version__,'GRCh37 / NM_005157.6',datetime.now().isoformat(timespec='minutes')])
    sheet.append(['Analyse',safe_text(session.source_label or session.run_id[:12]),'Utvalg',safe_text(selection)])
    headers=['Prøve','GRCh37-posisjon','REF > ALT','cDNA','Protein (enkeltallel)','FILTER','Kategori',
             'AF (%)','ALT / DP']+[PROVIDER_NAMES.get(p,p) for p in providers]
    sheet.append(headers)
    rows=list(rows)
    sample_names=[s['sample'] for s in session.data['samples']] if samples is None else list(samples)
    represented={v['sample'] for v in rows}
    export_rows=rows+[{'sample':name,'empty_selection':True} for name in sample_names if name not in represented]
    for v in export_rows:
        sources={r['provider']:r for r in lookup_results.get(allele_key(v),[])}
        values=[v.get('sample'),f"{v.get('chrom')}:{v.get('pos')}",f"{v.get('ref')}>{v.get('alt')}",
                v.get('cdna'),v.get('protein_snv_alone'),v.get('filter'),category(v),
                v['format_af']*100 if v.get('format_af') is not None else None,
                f"{v.get('alt_ad') if v.get('alt_ad') is not None else '–'} / {v.get('format_dp') if v.get('format_dp') is not None else '–'}"]+[source_text(sources.get(p)) for p in providers]
        if v.get('empty_selection'):
            values=[v['sample'],'','','','','','Ingen varianter i utvalget',None,'']+['–']*len(providers)
        sheet.append([safe_text(x) for x in values])
        notes=flags(v)
        if notes:sheet.cell(sheet.max_row,5).comment=Comment(safe_text('; '.join(notes)),APP_NAME)
        for col,provider in enumerate(providers,10):
            result=sources.get(provider)
            if result:
                # Keep provenance in the cell without widening the report.
                provenance='\n'.join(str(result.get(k) or '') for k in ('provider','checked_at','accession','url'))
                sheet.cell(sheet.max_row,col).comment=Comment(safe_text(provenance),APP_NAME)
    sheet.freeze_panes='D4';sheet.sheet_view.showGridLines=False
    for cell in sheet[1]:cell.font=Font(bold=True,color='7150A1')
    for cell in sheet[3]:
        cell.font=Font(bold=True,color='FFFFFF');cell.fill=PatternFill('solid',fgColor='7150A1')
    if export_rows:
        from openpyxl.utils import get_column_letter
        table=Table(displayName='Variantresultater',ref=f'A3:{get_column_letter(len(headers))}{len(export_rows)+3}')
        table.tableStyleInfo=TableStyleInfo(name='TableStyleMedium4',showRowStripes=True)
        sheet.add_table(table)
    widths=[22,27,22,23,24,22,26,12,18]+[45]*len(providers)
    for i,width in enumerate(widths,1):
        sheet.column_dimensions[sheet.cell(3,i).column_letter].width=width
    for row in sheet.iter_rows(min_row=4):
        for cell in row:cell.alignment=Alignment(vertical='top',wrap_text=True)
        row[7].number_format='0.00'
    sheet.print_title_rows='1:3';sheet.sheet_properties.pageSetUpPr.fitToPage=True
    sheet.page_setup.orientation='landscape';sheet.page_setup.paperSize=sheet.PAPERSIZE_A3
    sheet.page_setup.fitToWidth=1;sheet.page_setup.fitToHeight=0
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True);book.save(path)
    book.close()
