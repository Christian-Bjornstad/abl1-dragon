"""Native, sortable view of original VCF components; flags are exploratory."""
from PyQt6.QtCore import QAbstractTableModel, QModelIndex, QSortFilterProxyModel, Qt
from PyQt6.QtGui import QColor


def fmt(value, percent=False):
    if value is None or not isinstance(value,(int,float)):
        return 'Ikke oppgitt'
    return (f'{value*100:.2f} %' if percent else f'{value:,.2f}'.rstrip('0').rstrip('.')).replace(',', ' ').replace('.', ',')


def codon315(v):
    return str(v.get('chrom','')).removeprefix('chr')=='9' and 133748282<=v.get('pos',0)<=133748284


def flags(v):
    values=[]
    if v.get('filter')!='PASS':values.append('FILTER ikke vurdert' if v.get('filter')=='.' else v.get('filter') or 'FILTER mangler')
    if v.get('format_dp') is None:values.append('Dybde mangler')
    elif v['format_dp']<30:values.append('Få observasjoner')
    if v.get('bed_edge_bp') is not None and v['bed_edge_bp']<=3:values.append('Nær målkant')
    if v.get('phase_required') or codon315(v):values.append('Samlet kodonvurdering')
    if v.get('reference_match') is False:values.append('REF-avvik')
    if v.get('normal_transcript_continuation'):values.append('Transkriptfortsettelse')
    if v.get('sample_has_alt') is False:values.append('ALT ikke kalt i GT')
    return values


class VariantModel(QAbstractTableModel):
    HEADERS=['Prøve','GRCh37-posisjon','REF > ALT','cDNA','Protein, SNV alene','AF, caller','ALT / DP','FILTER','Kontrollflagg']

    def __init__(self,rows=None,parent=None):
        super().__init__(parent);self.rows=rows or []

    def replace(self,rows):
        self.beginResetModel();self.rows=rows;self.endResetModel()

    def rowCount(self,parent=QModelIndex()):return 0 if parent.isValid() else len(self.rows)
    def columnCount(self,parent=QModelIndex()):return len(self.HEADERS)

    def headerData(self,section,orientation,role=Qt.ItemDataRole.DisplayRole):
        if role==Qt.ItemDataRole.DisplayRole:
            return self.HEADERS[section] if orientation==Qt.Orientation.Horizontal else section+1

    def data(self,index,role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():return None
        v=self.rows[index.row()];c=index.column()
        if role==Qt.ItemDataRole.UserRole:
            return [v.get('sample',''),v.get('pos',0),v.get('ref','')+'>'+v.get('alt',''),v.get('cdna') or '',v.get('protein_snv_alone') or '',v.get('format_af') if v.get('format_af') is not None else -1,v.get('format_dp') if v.get('format_dp') is not None else -1,v.get('filter') or '',','.join(flags(v))][c]
        if role in (Qt.ItemDataRole.DisplayRole,Qt.ItemDataRole.ToolTipRole):
            return [v.get('sample',''),f"{v.get('chrom')}:{v.get('pos')}",f"{v.get('ref')}>{v.get('alt')}",v.get('cdna') or 'Ikke annotert',v.get('protein_snv_alone') or 'Krever vurdering',fmt(v.get('format_af'),True),f"{v.get('alt_ad') if v.get('alt_ad') is not None else '–'} / {v.get('format_dp') if v.get('format_dp') is not None else '–'}",v.get('filter') or 'Ikke oppgitt',' · '.join(flags(v)) or 'Ingen visningsflagg'][c]
        if role==Qt.ItemDataRole.ForegroundRole and c in (7,8) and flags(v):return QColor('#A15C00')


class VariantFilter(QSortFilterProxyModel):
    def __init__(self,parent=None):
        super().__init__(parent);self.sample='Alle prøver';self.status='Alle poster';self.query=''
        self.setSortRole(Qt.ItemDataRole.UserRole)

    def set_filters(self,*,sample=None,status=None,query=None):
        if sample is not None:self.sample=sample
        if status is not None:self.status=status
        if query is not None:self.query=query.casefold().strip()
        self.invalidateFilter()

    def filterAcceptsRow(self,row,parent):
        v=self.sourceModel().rows[row]
        if self.sample!='Alle prøver' and v['sample']!=self.sample:return False
        if self.status=='PASS' and v.get('filter')!='PASS':return False
        if self.status=='DRAGEN-filtrerte' and v.get('filter')=='PASS':return False
        if self.status=='Med kontrollflagg' and not flags(v):return False
        return not self.query or self.query in ' '.join(str(v.get(k) or '') for k in ('sample','chrom','pos','ref','alt','cdna','protein_snv_alone','filter','notes')).casefold()
