"""Native PyQt6 laboratory workspace, following the Archer/MPN desktop shell."""
from __future__ import annotations

import base64
from datetime import datetime, timezone
from html import escape
import json
from pathlib import Path

from PyQt6.QtCore import QMargins, QObject, QRect, QSignalBlocker, QThread, QTimer, Qt, QUrl, pyqtSignal
from PyQt6.QtGui import QCursor, QDesktopServices, QIcon, QImage, QPixmap
from PyQt6.QtWidgets import (
    QAbstractItemView, QApplication, QButtonGroup, QComboBox, QFileDialog, QFormLayout, QFrame,
    QHBoxLayout, QHeaderView, QInputDialog, QLabel, QLineEdit, QListWidget,
    QLayout, QMainWindow, QMessageBox, QPlainTextEdit, QProgressBar, QPushButton,
    QScrollArea, QSplitter, QStackedWidget, QTabWidget, QTableView, QTableWidget,
    QTableWidgetItem, QTextBrowser, QVBoxLayout, QWidget,
)

from .domain import (AnalysisSession, ReviewStore, STATUSES, export_csv, export_xlsx,
                     import_reviews, load_inputs, load_pilot, resource_root, save_project)
from .evidence import allele_options, exact_evidence, provider_url, source_allele
from .models import VariantFilter, VariantModel, codon315, flags, fmt
from .read_view import ReadViewer
from .database_panel import DatabasePanel
from .database_browser import EdgeBrowser


STYLE = '''
QMainWindow, QWidget#AppRoot, QWidget#ContentShell {background:#F4F3F6;color:#292633;}
QWidget {font-family:"Segoe UI";font-size:10pt;color:#292633;}
QFrame#NavigationRail {background:#292333;border:0;}
QLabel#Brand {color:white;font-size:24pt;font-weight:700;background:transparent;}
QLabel#BrandSubtitle {color:#D9CDE9;font-size:13pt;font-weight:600;background:transparent;}
QLabel#BrandMark {background:transparent;}
QLabel#RailSubtitle {color:#CDC4D8;font-size:9pt;background:transparent;}
QLabel#PilotState {color:#EAE3F2;background:#3B3149;border:1px solid #554662;border-radius:5px;padding:9px;font-size:9pt;}
QPushButton#SidebarButton {background:transparent;color:#DED8E6;border:0;text-align:left;padding:13px 12px;border-radius:5px;}
QPushButton#SidebarButton:checked {background:#EDE6F5;color:#3F2B5C;font-weight:600;}
QPushButton#SidebarButton:hover {background:#453650;color:white;}
QPushButton#SidebarButton:checked:hover {background:#E3D7F0;color:#3F2B5C;}
QLabel#PageTitle {font-size:20pt;font-weight:600;}
QLabel#Subtitle {color:#6A6374;}
QLabel#RunStatus {background:#EEEBF2;border:1px solid #DDD9E4;padding:10px 12px;border-radius:6px;}
QFrame#Card {background:white;border:1px solid #DDD9E4;border-radius:7px;}
QLabel#CardTitle {font-size:12pt;font-weight:600;background:transparent;}
QPushButton {background:white;border:1px solid #D5CFDE;border-radius:5px;padding:8px 12px;min-height:22px;}
QPushButton:hover {background:#EDE6F5;border-color:#9B82BA;}
QPushButton:pressed {background:#E2D7EF;}
QPushButton#PrimaryButton {background:#7150A1;color:white;border-color:#7150A1;font-weight:600;}
QPushButton#PrimaryButton:hover {background:#60428C;border-color:#60428C;}
QPushButton:disabled {color:#8D8796;background:#ECE9F0;border-color:#DDD9E4;}
QPushButton:focus, QLineEdit:focus, QComboBox:focus, QPlainTextEdit:focus, QTableView:focus, QListWidget:focus {border:2px solid #7150A1;}
QLineEdit,QComboBox,QPlainTextEdit {background:white;border:1px solid #D5CFDE;border-radius:4px;padding:7px;selection-background-color:#EDE6F5;selection-color:#292633;}
QTableView,QTableWidget,QTextBrowser,QListWidget {background:white;alternate-background-color:#F8F6FA;border:1px solid #DDD9E4;border-radius:4px;selection-background-color:#EDE6F5;selection-color:#292633;}
QHeaderView::section {background:#EEEBF2;color:#51465F;border:0;border-bottom:1px solid #DDD9E4;padding:8px;text-align:left;font-weight:600;}
QTableView::item {padding:5px;border-bottom:1px solid #EEEAF2;}
QTabWidget::pane {border:1px solid #DDD9E4;background:white;}
QTabBar::tab {background:#ECE8F1;color:#655B70;padding:10px 15px;border:1px solid #DDD9E4;}
QTabBar::tab:selected {background:white;color:#65418F;font-weight:600;}
QStatusBar {background:#EEEBF2;color:#6A6374;}
QSplitter::handle {background:#DDD9E4;}
QProgressBar {background:#E7E1ED;border:0;border-radius:3px;max-height:6px;}
QProgressBar::chunk {background:#7150A1;border-radius:3px;}
'''


def label(text='', name=None):
    item=QLabel(text);item.setTextFormat(Qt.TextFormat.PlainText);item.setWordWrap(True)
    if name:item.setObjectName(name)
    return item


def button(text, callback, primary=False):
    item=QPushButton(text);item.clicked.connect(callback)
    item.setCursor(Qt.CursorShape.PointingHandCursor)
    if primary:item.setObjectName('PrimaryButton')
    return item


def browser(handler=None):
    item=QTextBrowser();item.setOpenLinks(False);item.setOpenExternalLinks(False)
    item.document().setDefaultStyleSheet('a {color:#7150A1;} h3 {color:#44364F;font-size:12pt;} th {color:#51465F;}')
    item.anchorClicked.connect(lambda url:handler(url.toString()) if handler else QDesktopServices.openUrl(url) if url.scheme()=='https' else None)
    return item


def html_table(rows, headers=None):
    out='<table width="100%" cellspacing="0" cellpadding="7">'
    if headers:out+='<tr bgcolor="#EEEBF2">'+''.join('<th align="left">'+escape(str(h))+'</th>' for h in headers)+'</tr>'
    return out+''.join('<tr>'+''.join('<td style="border-bottom:1px solid #E8E3ED">'+escape(str(c if c is not None else 'Ikke oppgitt'))+'</td>' for c in row)+'</tr>' for row in rows)+'</table>'


def card(title, body):
    frame=QFrame();frame.setObjectName('Card');layout=QVBoxLayout(frame)
    layout.setContentsMargins(16,12,16,14);layout.addWidget(label(title,'CardTitle'));layout.addWidget(body)
    return frame


def initial_window_geometry(available, frame_margins=None):
    """Fit the preferred client area and its native frame on one screen."""
    margins=frame_margins if frame_margins is not None else QMargins(8,32,8,8)
    horizontal=margins.left()+margins.right();vertical=margins.top()+margins.bottom()
    if not available.isValid() or available.width()<=horizontal or available.height()<=vertical:
        raise ValueError('Skjermens tilgjengelige arbeidsområde er for lite.')
    padding=min(12,(available.width()-horizontal-1)//2,(available.height()-vertical-1)//2)
    width=min(1500,available.width()-2*padding-horizontal)
    height=min(940,available.height()-2*padding-vertical)
    x=available.x()+(available.width()-width-horizontal)//2+margins.left()
    y=available.y()+(available.height()-height-vertical)//2+margins.top()
    return QRect(x,y,width,height)


class ImportWorker(QObject):
    finished=pyqtSignal(object)
    failed=pyqtSignal(str)

    def __init__(self,paths,assembly):super().__init__();self.paths=paths;self.assembly=assembly

    def run(self):
        try:self.finished.emit(load_inputs(self.paths,self.assembly))
        except Exception as error:self.failed.emit(str(error))


class MainWindow(QMainWindow):
    PAGES=[('Prøveoversikt','Prøver, QC og vurderinger'),
           ('Varianter','VCF-kall og variantvurdering'),
           ('Lesninger og IGV','Alignments, haplotyper og bilder'),
           ('Kilder og databaser','Alleler og kildegrunnlag'),
           ('Metode og sporbarhet','Referanse, metode og lagring')]

    def __init__(self,store:ReviewStore,*,browser_enabled=True,session=None,database_browser=None):
        super().__init__();self.store=store;self.session=None;self.current_variant=None
        self.thread=None;self.worker=None;self.loading=False;self.attachments=[];self.browser_enabled=browser_enabled
        self.catalogue=json.loads((resource_root()/'app/data/knowledge.json').read_text(encoding='utf-8'))
        self.database_browser=database_browser or EdgeBrowser(self.store.path.parent)
        self.setWindowTitle('ABL1 Dragon')
        self._startup_screen=QApplication.screenAt(QCursor.pos()) or self.screen() or QApplication.primaryScreen()
        self._initial_geometry_pending=True
        brand_icon=resource_root()/'assets/brand/abl1-dragon.png'
        if brand_icon.is_file():self.setWindowIcon(QIcon(str(brand_icon)))
        self._build_ui();self.setStyleSheet(STYLE)
        self.save_timer=QTimer(self);self.save_timer.setSingleShot(True);self.save_timer.setInterval(600)
        self.save_timer.timeout.connect(self._auto_save)
        self._apply_session(session or load_pilot())
        self._fit_startup_geometry()

    def _fit_startup_geometry(self,actual_frame=False):
        if self._startup_screen is None:return
        available=self._startup_screen.availableGeometry()
        margins=None
        if actual_frame:
            frame=self.frameGeometry();client=self.geometry()
            margins=QMargins(max(0,client.left()-frame.left()),max(0,client.top()-frame.top()),
                             max(0,frame.right()-client.right()),max(0,frame.bottom()-client.bottom()))
        geometry=initial_window_geometry(available,margins)
        # A small display can be narrower than the workspace. Native scrolling
        # keeps all controls reachable instead of placing the frame off-screen.
        self.setMinimumSize(min(1050,geometry.width()),min(700,geometry.height()))
        self.setGeometry(geometry)

    def showEvent(self,event):
        super().showEvent(event)
        if self._initial_geometry_pending:
            self._initial_geometry_pending=False
            QTimer.singleShot(0,lambda:self._fit_startup_geometry(actual_frame=True))

    def _build_ui(self):
        root=QWidget();root.setObjectName('AppRoot');shell=QHBoxLayout(root);shell.setContentsMargins(0,0,0,0);shell.setSpacing(0)
        rail=QFrame();rail.setObjectName('NavigationRail');rail.setFixedWidth(204);nav=QVBoxLayout(rail);nav.setContentsMargins(14,22,14,18)
        brand=QHBoxLayout();brand.setSpacing(10)
        brand_icon=QPixmap(str(resource_root()/'assets/brand/abl1-dragon.png'))
        if not brand_icon.isNull():
            mark=label('','BrandMark');mark.setFixedSize(44,44)
            mark.setPixmap(brand_icon.scaled(44,44,Qt.AspectRatioMode.KeepAspectRatio,Qt.TransformationMode.SmoothTransformation))
            mark.setAccessibleName('ABL1 Dragon');brand.addWidget(mark)
        brand_text=QVBoxLayout();brand_text.setSpacing(0);brand_text.addWidget(label('ABL1','Brand'));brand_text.addWidget(label('Dragon','BrandSubtitle'))
        brand.addLayout(brand_text);brand.addStretch();nav.addLayout(brand);nav.addSpacing(25)
        self.nav_group=QButtonGroup(self);self.nav_buttons=[]
        for i,(name,_) in enumerate(self.PAGES):
            b=button(name,lambda checked=False,index=i:self.navigate(index));b.setObjectName('SidebarButton');b.setCheckable(True)
            self.nav_group.addButton(b,i);self.nav_buttons.append(b);nav.addWidget(b)
        nav.addStretch();nav.addWidget(label('Pilot · ikke klinisk validert','PilotState'))
        nav.addWidget(button('Åpne demo',self.restore_pilot));shell.addWidget(rail)
        content=QWidget();content.setObjectName('ContentShell');layout=QVBoxLayout(content);layout.setContentsMargins(18,16,18,10);layout.setSpacing(10)
        header=QHBoxLayout();titles=QVBoxLayout();self.page_title=label('','PageTitle');self.subtitle=label('','Subtitle');titles.addWidget(self.page_title);titles.addWidget(self.subtitle);header.addLayout(titles,1)
        self.import_button=button('Importer filer',self.choose_inputs,True);header.addWidget(self.import_button)
        self.open_button=button('Åpne prosjekt',self.choose_project);header.addWidget(self.open_button)
        self.save_button=button('Lagre prosjekt',self.save_project_dialog);header.addWidget(self.save_button)
        self.excel_button=button('Eksporter Excel',self.export_excel_dialog);header.addWidget(self.excel_button);layout.addLayout(header)
        self.run_status=label('','RunStatus');layout.addWidget(self.run_status)
        self.progress=QProgressBar();self.progress.setRange(0,0);self.progress.setTextVisible(False);self.progress.hide();layout.addWidget(self.progress)
        self.pages=QStackedWidget();self.pages.addWidget(self._overview_page());self.pages.addWidget(self._variants_page())
        self.pages.addWidget(self._reads_page());self.pages.addWidget(self._sources_page());self.pages.addWidget(self._method_page());layout.addWidget(self.pages,1)
        shell.addWidget(content,1)
        shell.setSizeConstraint(QLayout.SizeConstraint.SetMinimumSize)
        self.workspace_scroll=QScrollArea();self.workspace_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.workspace_scroll.setWidgetResizable(True);self.workspace_scroll.setWidget(root)
        self.setCentralWidget(self.workspace_scroll);self.statusBar().showMessage('Klar · endringer lagres lokalt.')

    def _overview_page(self):
        page=QWidget();layout=QVBoxLayout(page);layout.setContentsMargins(0,0,0,0)
        self.stats=label('','CardTitle');layout.addWidget(card('Aktiv kjøring',self.stats))
        actions=QHBoxLayout();actions.addWidget(button('Analyser VCF/QC-mappe',self.choose_folder));actions.addWidget(button('Se varianter',lambda:self.navigate(1)));actions.addStretch();layout.addLayout(actions)
        self.overview_notice=label();layout.addWidget(self.overview_notice)
        self.sample_table=QTableWidget(0,7);self.sample_table.setHorizontalHeaderLabels(['Prøve','Historisk forventning','VCF-poster','Middeldybde','Mål ≥100×','Kontroll','Vurderinger'])
        self.sample_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers);self.sample_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.sample_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.sample_table.cellDoubleClicked.connect(lambda row,col:self.select_variant(self.session.data['samples'][row]['sample']))
        layout.addWidget(self.sample_table,1)
        layout.addWidget(label('Dobbeltklikk en prøve for å åpne variantene.','Subtitle'))
        return page

    def _variants_page(self):
        page=QWidget();layout=QVBoxLayout(page);layout.setContentsMargins(0,0,0,0);filters=QHBoxLayout()
        self.sample_filter=QComboBox();self.sample_filter.setAccessibleName('Prøvefilter');self.status_filter=QComboBox();self.status_filter.setAccessibleName('Variantfilter')
        self.status_filter.addItems(['Alle poster','PASS','DRAGEN-filtrerte','Med kontrollflagg'])
        self.search=QLineEdit();self.search.setPlaceholderText('Søk i posisjon, HGVS, prøve eller filter');self.search.setAccessibleName('Variantsøk')
        filters.addWidget(label('Prøve'));filters.addWidget(self.sample_filter);filters.addWidget(self.status_filter);filters.addWidget(self.search,1)
        filters.addWidget(button('Eksporter utvalg',self.export_csv_dialog));layout.addLayout(filters)
        self.variant_count=label('','Subtitle');layout.addWidget(self.variant_count)
        self.variant_model=VariantModel();self.proxy=VariantFilter();self.proxy.setSourceModel(self.variant_model)
        self.variant_table=QTableView();self.variant_table.setModel(self.proxy);self.variant_table.setSortingEnabled(True)
        self.variant_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows);self.variant_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.variant_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers);self.variant_table.setAlternatingRowColors(True)
        self.variant_table.verticalHeader().hide();self.variant_table.horizontalHeader().setStretchLastSection(True)
        self.variant_table.selectionModel().currentRowChanged.connect(self._row_changed)
        self.detail_tabs=QTabWidget();self.identity=browser();self.support=browser();self.detail_tabs.addTab(self.identity,'Variant og QC');self.detail_tabs.addTab(self.support,'Lesningsstøtte')
        self.detail_tabs.addTab(self._review_panel(),'Egen vurdering')
        splitter=QSplitter(Qt.Orientation.Vertical);splitter.addWidget(self.variant_table);splitter.addWidget(self.detail_tabs);splitter.setSizes([370,350]);layout.addWidget(splitter,1)
        self.sample_filter.currentTextChanged.connect(self._filter_changed);self.status_filter.currentTextChanged.connect(self._filter_changed);self.search.textChanged.connect(self._filter_changed)
        return page

    def _review_panel(self):
        page=QWidget();layout=QHBoxLayout(page);form=QVBoxLayout();fields=QFormLayout()
        self.review_status=QComboBox();self.review_status.addItems(STATUSES);self.reviewer=QLineEdit();self.reviewer.setMaxLength(200)
        fields.addRow('Arbeidsstatus',self.review_status);fields.addRow('Vurdert av',self.reviewer);form.addLayout(fields)
        form.addWidget(label('Notat'));self.note=QPlainTextEdit();self.note.setPlaceholderText('Kontroller, kilder og oppfølging');form.addWidget(self.note,1)
        buttons=QHBoxLayout();buttons.addWidget(button('Lagre vurdering',self.save_review));buttons.addWidget(button('Kilder for varianten',lambda:self.navigate(3)));buttons.addWidget(button('IGV og bilder',lambda:self.navigate(2)));form.addLayout(buttons)
        layout.addLayout(form,3);images=QVBoxLayout();images.addWidget(label('Kildebilder'));self.attachment_list=QListWidget();self.attachment_list.setMaximumHeight(100);images.addWidget(self.attachment_list)
        self.attachment_preview=label('Ingen vedlegg');self.attachment_preview.setAlignment(Qt.AlignmentFlag.AlignCenter);self.attachment_preview.setMinimumSize(240,90);images.addWidget(self.attachment_preview,1)
        image_actions=QHBoxLayout();image_actions.addWidget(button('Legg til bilde',self.attach_image));image_actions.addWidget(button('Lagre bilde',self.save_attachment));image_actions.addWidget(button('Fjern',self.remove_attachment));images.addLayout(image_actions)
        images.addWidget(label('PNG/JPEG/WebP · 4 MB per bilde · maks. 8','Subtitle'));layout.addLayout(images,2)
        self.review_status.currentTextChanged.connect(self._review_changed);self.reviewer.textEdited.connect(self._review_changed);self.note.textChanged.connect(self._review_changed)
        self.attachment_list.currentRowChanged.connect(self._preview_attachment)
        return page

    def _reads_page(self):
        page=QWidget();layout=QVBoxLayout(page);layout.setContentsMargins(0,0,0,0);actions=QHBoxLayout();actions.addWidget(label('Prøve'))
        self.read_sample=QComboBox();actions.addWidget(self.read_sample);actions.addStretch();actions.addWidget(button('Vis prøvevarianter',lambda:self.select_variant(self.read_sample.currentText())));layout.addLayout(actions)
        self.read_counts=browser();self.read_counts.setMaximumHeight(200);layout.addWidget(self.read_counts)
        self.read_viewer=ReadViewer(enable_webengine=self.browser_enabled);layout.addWidget(self.read_viewer,1)
        self.read_sample.currentTextChanged.connect(self._refresh_reads);return page

    def _sources_page(self):
        page=QWidget();layout=QVBoxLayout(page);layout.setContentsMargins(0,0,0,0)
        self.source_identity=label('','CardTitle');layout.addWidget(self.source_identity)
        row=QHBoxLayout();row.addWidget(label('Allel for oppslag'));self.source_scope=QComboBox();row.addWidget(self.source_scope,1)
        row.addWidget(button('Velg annen variant',lambda:self.navigate(1)));layout.addLayout(row)
        self.database_panel=DatabasePanel(self.database_browser,self.catalogue.get('providers',[]))
        layout.addWidget(card('Edge og databaseinnlogging',self.database_panel))
        self.source_text=browser(self.database_panel.open_url);layout.addWidget(self.source_text,1);self.source_scope.currentIndexChanged.connect(self._refresh_sources)
        return page

    def _method_page(self):
        page=QWidget();layout=QVBoxLayout(page);layout.setContentsMargins(0,0,0,0);self.method_text=browser();layout.addWidget(self.method_text,1)
        layout.addWidget(button('Eksporter analysegrunnlag',self.export_analysis_dialog));return page

    def navigate(self,index):
        if not 0<=index<len(self.PAGES):return
        if not self._auto_save():
            self.nav_buttons[self.pages.currentIndex()].setChecked(True);return
        self.pages.setCurrentIndex(index);self.nav_buttons[index].setChecked(True)
        self.page_title.setText(self.PAGES[index][0]);self.subtitle.setText(self.PAGES[index][1])
        if index==2:
            if self.current_variant:
                with QSignalBlocker(self.read_sample):self.read_sample.setCurrentText(self.current_variant['sample'])
            self._refresh_reads()
        if index==3:self._refresh_sources()

    def _apply_session(self,session:AnalysisSession):
        if self.session and not self._auto_save():return
        conflicts=sum(bool(self.store.get(row['key'])) and any(self.store.get(row['key']).get(k)!=row.get(k) for k in ('status','note','reviewer','attachments')) for row in session.pending_reviews)
        import_reviews(session,self.store,session.pending_reviews)
        self.loading=True;self.session=session;self.current_variant=None;self.attachments=[];data=session.data
        self.sample_filter.clear();self.sample_filter.addItems(['Alle prøver']+[s['sample'] for s in data['samples']]);self.read_sample.clear();self.read_sample.addItems([s['sample'] for s in data['samples']])
        if data['samples']:self.read_sample.setCurrentText(data['samples'][0]['sample'])
        self.status_filter.setCurrentIndex(0);self.search.clear();self.variant_model.replace(data['variants']);self.proxy.set_filters(sample='Alle prøver',status='Alle poster',query='')
        self.variant_table.resizeColumnsToContents();self.variant_table.setColumnWidth(8,270);self.variant_table.setColumnWidth(2,140)
        self.run_status.setText(f"{session.source_label}  ·  GRCh37 / hg19  ·  NM_005157.6")
        self.stats.setText(f"{len(data['samples'])} prøver     {len(data['variants'])} variantposter     {sum(v.get('filter')=='PASS' for v in data['variants'])} PASS     {len(data.get('qc',[]))} QC-rader")
        self.overview_notice.setText('Syntetisk demo · tallene er konstruert.' if data.get('metadata',{}).get('synthetic_demo') else 'Se tilgjengelig QC og lesningsgrunnlag for hver prøve.')
        self._fill_samples();self._refresh_method();self.loading=False
        if not session.is_pilot:self.read_viewer.set_context(session,None,self.read_sample.currentText())
        self._filter_changed();self.navigate(0)
        if conflicts:self.statusBar().showMessage(f'{conflicts} eksisterende lokale vurderinger ble beholdt. Prosjektfilen har andre versjoner; den opprinnelige filen er uendret.')

    def _fill_samples(self):
        data=self.session.data;self.sample_table.setRowCount(len(data['samples']))
        for row,s in enumerate(data['samples']):
            sample=s['sample'];q=next((q for q in data.get('qc',[]) if q['sample']==sample),{});vs=[v for v in data['variants'] if v['sample']==sample]
            control='Lav dekning' if any(v.get('format_dp') is not None and v['format_dp']<30 for v in vs) else 'Krever gjennomgang'
            reviewed=sum(bool(self.store.get(self.session.variant_key(v))) for v in vs)
            values=[sample,s.get('expected') or 'Ikke oppgitt',len(vs),fmt(q.get('mean_target_depth')),fmt(q.get('pct_ge100')/100,True) if q.get('pct_ge100') is not None else 'Ikke oppgitt',control,f'{reviewed} / {len(vs)}']
            for col,value in enumerate(values):self.sample_table.setItem(row,col,QTableWidgetItem(str(value)))

    def _filter_changed(self,*args):
        if self.loading or not self.session:return
        if not self._auto_save():
            with QSignalBlocker(self.sample_filter):self.sample_filter.setCurrentText(self.proxy.sample)
            with QSignalBlocker(self.status_filter):self.status_filter.setCurrentText(self.proxy.status)
            with QSignalBlocker(self.search):self.search.setText(self.proxy.query)
            return
        self.proxy.set_filters(sample=self.sample_filter.currentText(),status=self.status_filter.currentText(),query=self.search.text())
        self.variant_count.setText(f'{self.proxy.rowCount()} av {len(self.session.data["variants"])} poster')
        if self.proxy.rowCount():self.variant_table.setCurrentIndex(self.proxy.index(0,0))
        else:
            self.current_variant=None;self.identity.setPlainText('Ingen poster passer til utvalget.');self.support.clear()
            self.loading=True;self.note.clear();self.reviewer.clear();self.review_status.setCurrentIndex(0)
            self.attachments=[];self._fill_attachments();self.source_scope.clear();self.loading=False
            self.detail_tabs.setEnabled(False)
            self._refresh_sources()

    def _row_changed(self,index,old):
        if self.loading or not index.isValid():return
        if not self._auto_save():
            if self.current_variant in self.variant_model.rows:
                previous=self.variant_model.rows.index(self.current_variant)
                with QSignalBlocker(self.variant_table.selectionModel()):self.variant_table.setCurrentIndex(self.proxy.mapFromSource(self.variant_model.index(previous,0)))
            return
        source=self.proxy.mapToSource(index);self.current_variant=self.variant_model.rows[source.row()]
        self.detail_tabs.setEnabled(True)
        self._refresh_detail()

    def select_variant(self,sample,pos=None):
        if not self.session:return
        if sample not in [s['sample'] for s in self.session.data['samples']]:
            self.statusBar().showMessage('Prøven finnes ikke i denne kjøringen.');return
        self.navigate(1);self.sample_filter.setCurrentText(sample)
        for row in range(self.proxy.rowCount()):
            v=self.variant_model.rows[self.proxy.mapToSource(self.proxy.index(row,0)).row()]
            if pos is None or v['pos']==pos:
                self.variant_table.setCurrentIndex(self.proxy.index(row,0));self.variant_table.scrollTo(self.proxy.index(row,0));break

    def _refresh_detail(self):
        v=self.current_variant
        if not v:return
        fields=[('Prøve',v['sample']),('Referanse','GRCh37 / hg19'),('Transkript','NM_005157.6'),('Genomisk endring',f"{v['chrom']}:{v['pos']} {v['ref']}>{v['alt']}"),('cDNA',v.get('cdna')),('Protein, SNV alene',v.get('protein_snv_alone')),('AF, caller',fmt(v.get('format_af'),True)),('Informativ DP',fmt(v.get('format_dp'))),('INFO DP',fmt(v.get('info_dp'))),('AD REF / ALT',f"{v.get('ref_ad')} / {v.get('alt_ad')}"),('FILTER',v.get('filter')),('Kildefil',v.get('source')),('VCF-linje',v.get('source_line')),('Kontrollflagg',' · '.join(flags(v)))]
        html='<h3>'+escape(v['sample']+' · '+str(v.get('cdna') or v['pos']))+'</h3>'+html_table(fields)
        html+='<p>'+escape(v.get('notes') or '')+'</p>'
        if v.get('phase_required') or codon315(v):html+='<p><b>Vurder samlet kodon.</b> Enkelt-SNV kan avvike fra samlet proteinendring.</p>'
        q=next((q for q in self.session.data.get('qc',[]) if q['sample']==v['sample']),None)
        html+='<h3>Prøvekvalitet</h3>'+(html_table([(k,q.get(key)) for k,key in [('Middeldybde','mean_target_depth'),('Mål ≥20× (%)','pct_ge20'),('Mål ≥50× (%)','pct_ge50'),('Mål ≥100× (%)','pct_ge100'),('DRAGEN callable-baser','callable_bases')]]) if q else '<p>Ingen QC-data. Fravær av variantlinje dokumenterer ikke sikkert negativt resultat.</p>')
        self.identity.setHtml(html);self.support.setHtml(self._counts_html(v['sample'],v))
        review=self.store.get(self.session.variant_key(v));self.loading=True
        self.review_status.setCurrentText(review.get('status','Ikke vurdert'));self.reviewer.setText(review.get('reviewer',''));self.note.setPlainText(review.get('note',''));self.attachments=list(review.get('attachments',[]));self._fill_attachments()
        self.source_scope.clear()
        for key,title in allele_options(v,self.session.data.get('phase_rows',[])):self.source_scope.addItem(title,key)
        self.loading=False;self._refresh_sources()

    def _counts_html(self,sample,variant=None):
        data=self.session.data;html=''
        phase=[r for r in data.get('phase_rows',[]) if r['sample']==sample and r.get('filter')=='BQ30_MQ20']
        if phase and (variant is None or codon315(variant)):
            html+='<h3>Kodon 315 · BQ≥30 / MQ≥20</h3>'+html_table([(r['haplotype'],str(r.get('protein',''))+(' · undersøkelsesfunn' if r['haplotype']=='CTT' else ''),f"{r['fragments']} / {r['fragments_all']}",fmt(r['fragment_fraction'],True)) for r in phase],['Kodon','Protein','Samstemte fragmenter','Andel'])
        rows=[r for r in data.get('read_rows',[]) if r['sample']==sample and (not variant or (r.get('pos1_hg19')==variant['pos'] and r.get('ref')==variant['ref'] and r.get('alt')==variant['alt'] and str(r.get('chr')).removeprefix('chr')==str(variant['chrom']).removeprefix('chr')))]
        if rows:html+='<h3>Beregnet enkeltbasestøtte · BQ≥30 / MQ≥20</h3>'+html_table([(f"{r['chr']}:{r['pos1_hg19']} {r['ref']}>{r['alt']}",f"{r['alt_reads']} / {r['read_total']}",f"{r['alt_query_name_fragments']} / {r['query_name_fragments_total']}",r.get('discordant_fragments')) for r in rows],['Posisjon','ALT / lesninger','ALT / samstemte fragmenter','Uenige'])
        if not html:html='<p>Lesningsgrunnlag mangler for valgt komponent. VCF alene dokumenterer ikke fase.</p>'
        return html+'<p>Read group/query-name-tellinger er ikke molekyltall eller validert VAF. Uenige grupper er utelatt fra fragmentnevneren.</p>'

    def _refresh_reads(self,*args):
        if self.loading or not self.session:return
        sample=self.read_sample.currentText();v=self.current_variant if self.current_variant and self.current_variant['sample']==sample else None
        self.read_counts.setHtml(self._counts_html(sample));self.read_viewer.set_context(self.session,v,sample)

    def _refresh_sources(self,*args):
        if self.loading or not self.session:return
        v=source_allele(self.current_variant,self.source_scope.currentData() or 'vcf',self.session.data.get('phase_rows',[]))
        self.database_panel.set_variant(v)
        self.source_identity.setText(f"{v['sample']} · {v.get('cdna') or v['pos']} · {v['chrom']}:{v['pos']} {v['ref']}>{v['alt']}" if v else 'Velg en variant fra variantlisten')
        html='<h3>Lagret kildegrunnlag</h3>'
        records=exact_evidence(self.catalogue.get('evidence',[]),v)
        for r in records:
            html+='<h3>'+escape(r.get('database','')+' · '+r.get('accession','Ingen accession'))+'</h3><p>'+escape(r.get('summary',''))+'</p>'
            axes=r.get('classifications',{});rows=[]
            for key,title in [('germline','Germline-klassifikasjon'),('somatic_clinical_impact','Somatisk klinisk betydning'),('oncogenicity','Onkogenisitet')]:
                a=axes.get(key) or {};rows.append((title,a.get('description') or 'Ingen klassifikasjon i snapshot',a.get('review_status') or 'Ikke oppgitt',a.get('date_last_evaluated') or 'Ikke oppgitt'))
            html+=html_table(rows,['Akse','Klassifikasjon','Review-status','Sist vurdert'])+'<p>Hentet '+escape(r.get('fetched_at','Ikke oppgitt'))+' · eksakt GRCh37-allel. Germline-klassifikasjon angir ikke variantens opphav.</p>'
        if not records:html+='<p>Ingen klassifikasjon lagret for denne allelen. Manglende treff betyr ikke benign.</p>'
        html+='<h3>Kilder og tilgang</h3>'
        for p in self.catalogue.get('providers',[]):
            url=provider_url(p,v);html+='<h3>'+escape(p['name'])+' · '+escape(p.get('status',''))+'</h3><p>'+escape(p.get('description',''))+'</p><p><b>Tilgang:</b> '+escape(p.get('access',''))+'</p>'
            if url:html+='<p><a href="'+escape(url,quote=True)+'">Åpne '+escape(p['name'])+'</a></p>'
        self.source_text.setHtml(html)

    def _refresh_method(self):
        d=self.session.data
        html='<h3>Aktiv kjøring</h3>'+html_table([('Kilde',self.session.source_label),('Kjørings-ID',self.session.run_id),('Referanse','GRCh37 / hg19 · NM_005157.6'),('QC / fase / punktobservasjoner',f"{len(d.get('qc',[]))} / {len(d.get('phase_rows',[]))} / {len(d.get('read_rows',[]))}"),('Arbeidslagring',str(self.store.path))])
        html+='<h3>Varianttolkning</h3><p>SNV-konsekvens gjelder én base på fast ABL1-transkript. Endringer i samme kodon vurderes samlet. FORMAT AF/DP, INFO DP og AD holdes atskilt. DP&lt;30 og BED-kant≤3 er utforskende visningsflagg, ikke kliniske eksklusjonsregler. PASS er callerens filterstatus.</p>'
        html+='<h3>Lesningsgrunnlag</h3><p>Fragmenter grupperes etter read group og query-name. Uenige grupper er utelatt fra fragmentnevneren. Gruppene er ikke uavhengige originalmolekyler, validert VAF eller et mål på klonstørrelse. VCF alene dokumenterer ikke negativ dekning eller haplotyper.</p>'
        html+='<h3>Import og metodegrenser</h3><p>Nye importer arver ikke bilder, QC eller historiske forventninger gjennom prøvenavn. En analysepakke viser sitt eget grunnlag. Nye BAM/CRAM-data analyseres ikke fra dette vinduet. FASTQ-realignment er ikke utført. Primer-/bibliotekdesign og faktisk fusjonsreferanse må avklares.</p>'
        html+='<h3>Kilder</h3><p>Kildeklassifikasjon, analytisk støtte og historisk forventning holdes atskilt. Germline-klassifikasjon fastslår ikke arvelig opphav eller somatisk behandlingstier. Kontroller kildeversjon og tilgang ved bruk. Franklin, OncoKB, COSMIC og MTBP krever relevant organisasjonstilgang eller lisens; API-er er ikke koblet til. Eksterne sider åpnes ved klikk. Prøvefiler overføres ikke av appen; oppslag sender variantfeltene i lenken til valgt tjeneste.</p>'
        html+='<h3>Arbeidslagring</h3><p>Vurderinger lagres lokalt i SQLite. Prosjektfilen inneholder analyse, vurderinger og bildevedlegg og kan eksporteres for arkivering. Arbeidsdatabasen er ikke et journalsystem. Arbeidsstatus er ingen klinisk signering.</p>'
        html+='<h3>Proveniens</h3><pre>'+escape(json.dumps(d.get('provenance',{}),ensure_ascii=False,indent=2))+'</pre>'
        self.method_text.setHtml(html)

    def _review_changed(self,*args):
        if not self.loading and self.current_variant:self.save_timer.start()

    def _auto_save(self):
        if self.loading or not self.current_variant:return True
        self.save_timer.stop();v=self.current_variant
        try:
            key=self.session.variant_key(v);existing=self.store.get(key)
            payload={'status':self.review_status.currentText(),'reviewer':self.reviewer.text(),'note':self.note.toPlainText(),'attachments':self.attachments}
            if existing and all(existing.get(k)==value for k,value in payload.items()):return True
            if not existing and not payload['note'].strip() and not payload['reviewer'].strip() and self.review_status.currentIndex()==0 and not self.attachments:return True
            self.store.put(key,{**payload,'updated_at':datetime.now(timezone.utc).isoformat()})
            self.statusBar().showMessage('Vurdering lagret lokalt. Lagre prosjekt for arkivering.');return True
        except Exception as error:self.statusBar().showMessage('Kunne ikke lagre vurderingen: '+str(error));return False

    def save_review(self):
        if self._auto_save():self._fill_samples()

    def _fill_attachments(self):
        self.attachment_list.clear();self.attachment_list.addItems([a['name'] for a in self.attachments]);self.attachment_preview.clear()
        if self.attachments:self.attachment_list.setCurrentRow(0)
        else:self.attachment_preview.setText('Ingen vedlegg')

    def _preview_attachment(self,row):
        if not 0<=row<len(self.attachments):self.attachment_preview.clear();return
        raw=base64.b64decode(self.attachments[row]['data'].split(',',1)[-1]);pix=QPixmap();pix.loadFromData(raw)
        self.attachment_preview.setPixmap(pix.scaled(420,180,Qt.AspectRatioMode.KeepAspectRatio,Qt.TransformationMode.SmoothTransformation))

    def attach_image(self):
        if not self.current_variant:return
        files,_=QFileDialog.getOpenFileNames(self,'Fest lokale kildebilder','','Bilder (*.png *.jpg *.jpeg *.webp)')
        try:
            if len(self.attachments)+len(files)>8:raise ValueError('Maksimalt åtte bilder per variant.')
            additions=[]
            for name in files:
                path=Path(name)
                if path.stat().st_size>4*1024*1024:raise ValueError('Bildet overstiger 4 MB.')
                raw=path.read_bytes();image=QImage.fromData(raw)
                if image.isNull() or image.width()*image.height()>25_000_000:raise ValueError('Ugyldig eller for stort bilde.')
                mime='image/png' if raw.startswith(b'\x89PNG\r\n\x1a\n') else 'image/jpeg' if raw.startswith(b'\xff\xd8\xff') else 'image/webp' if raw.startswith(b'RIFF') and raw[8:12]==b'WEBP' else None
                if not mime:raise ValueError('Bruk PNG, JPEG eller WebP.')
                additions.append({'name':path.name,'mime':mime,'data':f'data:{mime};base64,'+base64.b64encode(raw).decode()})
            self.attachments.extend(additions);self._auto_save();self._fill_attachments()
        except Exception as error:self._error(str(error))

    def save_attachment(self):
        row=self.attachment_list.currentRow()
        if not 0<=row<len(self.attachments):return
        a=self.attachments[row];path,_=QFileDialog.getSaveFileName(self,'Lagre kildebilde',a['name'])
        if path:
            try:Path(path).write_bytes(base64.b64decode(a['data'].split(',',1)[-1]))
            except OSError as error:self._error(str(error))

    def remove_attachment(self):
        row=self.attachment_list.currentRow()
        if 0<=row<len(self.attachments):self.attachments.pop(row);self._auto_save();self._fill_attachments()

    def _confirmed_assembly(self):
        value,ok=QInputDialog.getItem(self,'Bekreft genomreferanse','Filene er analysert mot:', ['Velg referansebygg','GRCh37 / hg19'],0,False)
        return 'GRCh37' if ok and value=='GRCh37 / hg19' else None

    def choose_inputs(self):
        files,_=QFileDialog.getOpenFileNames(self,'Importer lokale analysefiler','','VCF eller analyse (*.vcf *.vcf.gz *.json)')
        if files:
            assembly=self._confirmed_assembly()
            if assembly:self.start_import([Path(x) for x in files],assembly)

    def choose_folder(self):
        folder=QFileDialog.getExistingDirectory(self,'Velg mappe med VCF og DRAGEN-QC')
        if folder:
            assembly=self._confirmed_assembly()
            if assembly:self.start_import([Path(folder)],assembly)

    def choose_project(self):
        path,_=QFileDialog.getOpenFileName(self,'Åpne lagret ABL1-prosjekt','','ABL1-prosjekt (*.json)')
        if path:self.start_import([Path(path)],'GRCh37')

    def start_import(self,paths,assembly):
        if self.thread and self.thread.isRunning():return
        if not self._auto_save():self._error('Lagre eller eksporter vurderingen før import.');return
        self.thread=QThread(self);self.worker=ImportWorker(paths,assembly);self.worker.moveToThread(self.thread)
        self.thread.started.connect(self.worker.run);self.worker.finished.connect(self._import_done);self.worker.failed.connect(self._import_failed)
        self.worker.finished.connect(self.thread.quit);self.worker.failed.connect(self.thread.quit);self.thread.finished.connect(self.worker.deleteLater);self.thread.finished.connect(self._import_finished)
        for b in (self.import_button,self.open_button,self.save_button,self.excel_button):b.setEnabled(False)
        self.progress.show();self.statusBar().showMessage('Leser og kontrollerer lokale filer …');self.thread.start()

    def _import_done(self,session):
        try:self._apply_session(session)
        except Exception as error:self._error(str(error))

    def _import_failed(self,message):self._error(message)

    def _import_finished(self):
        self.progress.hide()
        for b in (self.import_button,self.open_button,self.save_button,self.excel_button):b.setEnabled(True)
        self.thread.deleteLater();self.thread=None;self.worker=None

    def restore_pilot(self):
        if self.thread and self.thread.isRunning():return
        try:self._apply_session(load_pilot())
        except Exception as error:self._error(str(error))

    def save_project_dialog(self):
        if not self._auto_save():return
        path,_=QFileDialog.getSaveFileName(self,'Lagre analyse og vurderinger','ABL1_prosjekt.abl1.json','ABL1-prosjekt (*.json)')
        if path:
            try:save_project(self.session,self.store,Path(path));self.statusBar().showMessage('Prosjekt lagret: '+path)
            except Exception as error:self._error(str(error))

    def export_excel_dialog(self):
        if not self._auto_save():return
        path,_=QFileDialog.getSaveFileName(self,'Eksporter arbeidsbok','ABL1_vurdering.xlsx','Excel (*.xlsx)')
        if path:
            try:export_xlsx(self.session,self.store,Path(path));self.statusBar().showMessage('Excel-arbeidsbok lagret: '+path)
            except Exception as error:self._error(str(error))

    def export_csv_dialog(self):
        if not self._auto_save():return
        path,_=QFileDialog.getSaveFileName(self,'Eksporter variantutvalg','ABL1_variantutvalg.csv','CSV (*.csv)')
        if path:
            try:
                rows=[self.variant_model.rows[self.proxy.mapToSource(self.proxy.index(i,0)).row()] for i in range(self.proxy.rowCount())]
                export_csv(self.session,rows,Path(path),self.store);self.statusBar().showMessage('Variantutvalg eksportert.')
            except Exception as error:self._error(str(error))

    def export_analysis_dialog(self):
        path,_=QFileDialog.getSaveFileName(self,'Eksporter analysegrunnlag','ABL1_analyse.json','JSON (*.json)')
        if path:
            try:Path(path).write_text(json.dumps(self.session.data,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
            except Exception as error:self._error(str(error))

    def _error(self,message):
        self.statusBar().showMessage('Operasjonen ble stoppet: '+message);QMessageBox.warning(self,'ABL1 Dragon',message)

    def closeEvent(self,event):
        if self.thread and self.thread.isRunning():self.statusBar().showMessage('Vent til importen er ferdig før appen lukkes.');event.ignore();return
        if not self._auto_save():QMessageBox.warning(self,'Lagring mislyktes','Vurderingen kunne ikke lagres. Eksporter prosjekt før du lukker.');event.ignore();return
        self.store.close();event.accept()
