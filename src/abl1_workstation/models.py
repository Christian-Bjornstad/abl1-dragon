"""Native, sortable view of original VCF components; flags are exploratory."""
from PyQt6.QtCore import QAbstractTableModel, QModelIndex, QSortFilterProxyModel, Qt
from PyQt6.QtGui import QColor
from .workflow import category,row_key


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
    if v.get('codon') is not None and v['codon']<=27:values.append('Native ABL1-ekson 1')
    return values


class VariantModel(QAbstractTableModel):
    HEADERS=['Prøve','GRCh37-posisjon','REF > ALT','cDNA','Protein, enkeltallel','AF (%)','ALT / DP','FILTER']

    def __init__(self,rows=None,parent=None):
        super().__init__(parent);self.rows=rows or [];self.checked=set()

    def replace(self,rows):
        self.beginResetModel();self.rows=rows;self.checked.clear();self.endResetModel()

    def selected_rows(self):return [v for v in self.rows if row_key(v) in self.checked]

    def flags(self,index):
        value=super().flags(index)
        return value|Qt.ItemFlag.ItemIsUserCheckable if index.isValid() and index.column()==0 else value

    def setData(self,index,value,role=Qt.ItemDataRole.EditRole):
        if not index.isValid() or index.column()!=0 or role!=Qt.ItemDataRole.CheckStateRole:return False
        key=row_key(self.rows[index.row()])
        if value in (Qt.CheckState.Checked,Qt.CheckState.Checked.value):self.checked.add(key)
        else:self.checked.discard(key)
        self.dataChanged.emit(index,index,[Qt.ItemDataRole.CheckStateRole]);return True

    def rowCount(self,parent=QModelIndex()):return 0 if parent.isValid() else len(self.rows)
    def columnCount(self,parent=QModelIndex()):return len(self.HEADERS)

    def headerData(self,section,orientation,role=Qt.ItemDataRole.DisplayRole):
        if role==Qt.ItemDataRole.DisplayRole:
            return self.HEADERS[section] if orientation==Qt.Orientation.Horizontal else section+1

    def data(self,index,role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():return None
        v=self.rows[index.row()];c=index.column()
        if role==Qt.ItemDataRole.CheckStateRole and c==0:
            return Qt.CheckState.Checked if row_key(v) in self.checked else Qt.CheckState.Unchecked
        if role==Qt.ItemDataRole.UserRole:
            return [v.get('sample',''),v.get('pos',0),v.get('ref','')+'>'+v.get('alt',''),v.get('cdna') or '',v.get('protein_snv_alone') or '',v.get('format_af') if v.get('format_af') is not None else -1,v.get('format_dp') if v.get('format_dp') is not None else -1,v.get('filter') or '',','.join(flags(v))][c]
        if role in (Qt.ItemDataRole.DisplayRole,Qt.ItemDataRole.ToolTipRole):
            return [v.get('sample',''),f"{v.get('chrom')}:{v.get('pos')}",f"{v.get('ref')}>{v.get('alt')}",v.get('cdna') or '–',v.get('protein_snv_alone') or '–',fmt(v.get('format_af'),True),f"{v.get('alt_ad') if v.get('alt_ad') is not None else '–'} / {v.get('format_dp') if v.get('format_dp') is not None else '–'}",v.get('filter') or '–',' · '.join(flags(v)) or '–'][c]
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
        if self.status in ('PASS + kontroll','PASS + kandidater') and category(v) not in ('PASS','Kontroll'):return False
        if self.status in ('Kontroll','Kandidater') and category(v)!='Kontroll':return False
        if self.status=='PASS' and v.get('filter')!='PASS':return False
        if self.status=='DRAGEN-filtrerte' and v.get('filter')=='PASS':return False
        if self.status=='Med kontrollflagg' and not flags(v):return False
        return not self.query or self.query in ' '.join(str(v.get(k) or '') for k in ('sample','chrom','pos','ref','alt','cdna','protein_snv_alone','filter','notes')).casefold()
