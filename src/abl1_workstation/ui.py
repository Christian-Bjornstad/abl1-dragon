"""Folder → selected variants → local IGV and sources → per-variant Excel."""
from pathlib import Path
from datetime import datetime
import time,uuid
from PyQt6.QtCore import QMargins,QObject,QSignalBlocker,QThread,QTimer,Qt,pyqtSignal
from PyQt6.QtGui import QCursor,QIcon,QPixmap
from PyQt6.QtWidgets import (QAbstractItemView,QApplication,QComboBox,QFileDialog,QHBoxLayout,QFrame,QGridLayout,QStackedWidget,
    QHeaderView,QLabel,QLayout,QMainWindow,QMessageBox,QPlainTextEdit,QProgressBar,QScrollArea,QSplitter,
    QTableView,QVBoxLayout,QWidget,QSizePolicy)
from . import APP_NAME
from .domain import ReviewStore,load_inputs,resource_root
from .models import VariantModel,VariantFilter
from .workflow import allele_key,row_key
from .report import export_sample_reports,sample_report_paths,PROVIDER_NAMES
from .database_browser import EdgeBrowser
from .lookup_browser import PortalBrowser
from .settings import Settings,SettingsPanel
from .ui_common import STYLE,label,button,initial_window_geometry


class Task(QObject):
    finished=pyqtSignal(object)
    failed=pyqtSignal(str)
    progress=pyqtSignal(object)
    def __init__(self,operation,*,stream=False):super().__init__();self.operation=operation;self.stream=stream
    def run(self):
        try:self.finished.emit(self.operation(self.progress.emit) if self.stream else self.operation())
        except Exception as error:self.failed.emit(str(error))


class MainWindow(QMainWindow):
    def __init__(self,store:ReviewStore,*,browser_enabled=True,session=None,database_browser=None):
        super().__init__();self.store=store;self.session=None;self.current_variant=None
        self.run_files=None;self.lookup_results={};self.thread=None;self.worker=None
        self._export=None
        self.capture_timer=QTimer(self);self.capture_timer.setInterval(200);self.capture_timer.timeout.connect(self._poll_capture)
        self.browser_enabled=browser_enabled;self.loading=False
        self.settings=Settings(store.path.parent)
        self.database_browser=database_browser or PortalBrowser(store.path.parent,edge_browser=EdgeBrowser(store.path.parent))
        self.setWindowTitle(APP_NAME);self.setWindowIcon(QIcon(str(resource_root()/'assets/brand/abl1-dragon.ico')))
        self._startup_screen=QApplication.screenAt(QCursor.pos()) or self.screen() or QApplication.primaryScreen()
        self._initial_geometry_pending=True;self._build_ui();self.setStyleSheet(STYLE)
        if session:self._apply_session(session)
        self._fit_startup_geometry()

    def _fit_startup_geometry(self,actual_frame=False):
        if self._startup_screen is None:return
        margins=None
        if actual_frame:
            frame=self.frameGeometry();client=self.geometry()
            margins=QMargins(max(0,client.left()-frame.left()),max(0,client.top()-frame.top()),
                             max(0,frame.right()-client.right()),max(0,frame.bottom()-client.bottom()))
        geometry=initial_window_geometry(self._startup_screen.availableGeometry(),margins)
        self.setMinimumSize(min(1050,geometry.width()),min(700,geometry.height()));self.setGeometry(geometry)

    def showEvent(self,event):
        super().showEvent(event)
        if self._initial_geometry_pending:
            self._initial_geometry_pending=False;QTimer.singleShot(0,lambda:self._fit_startup_geometry(True))

    def _build_ui(self):
        from .igv_live import LiveIgvWidget
        root=QWidget();root.setObjectName('AppRoot')
        shell=QHBoxLayout(root);shell.setContentsMargins(0,0,0,0);shell.setSpacing(0)
        rail=QFrame();rail.setObjectName('NavigationRail');rail.setFixedWidth(180)
        nav=QVBoxLayout(rail);nav.setContentsMargins(14,24,14,18);nav.setSpacing(10)
        mark=label('','BrandMark');mark.setPixmap(QPixmap(str(resource_root()/'assets/brand/abl1-dragon.png')).scaled(68,68,Qt.AspectRatioMode.KeepAspectRatio,Qt.TransformationMode.SmoothTransformation))
        brand_title=label(APP_NAME,'Brand')
        for item in (mark,brand_title):
            item.setAlignment(Qt.AlignmentFlag.AlignCenter);nav.addWidget(item)
        nav.addSpacing(24)
        self.analysis_button=button('Analyse',lambda:self.navigate(0));self.igv_button=button('IGV',lambda:self.navigate(1))
        self.settings_button=button('Innstillinger',lambda:self.navigate(2))
        self.nav_buttons=[self.analysis_button,self.igv_button,self.settings_button]
        for item in self.nav_buttons:item.setObjectName('SidebarButton');item.setCheckable(True);nav.addWidget(item)
        self.analysis_button.setChecked(True);nav.addStretch()
        self.import_button=button('Velg analysemappe',self.choose_folder)
        self.excel_button=button('Eksporter Excel',self.export_excel_dialog)
        nav.addWidget(self.import_button);nav.addWidget(self.excel_button);shell.addWidget(rail)
        content=QWidget();content.setObjectName('ContentShell');layout=QVBoxLayout(content)
        layout.setContentsMargins(20,18,20,12);layout.setSpacing(12)
        self.pages=QStackedWidget();self.pages.setSizePolicy(QSizePolicy.Policy.Expanding,QSizePolicy.Policy.Ignored)
        analysis=QWidget();page=QVBoxLayout(analysis);page.setContentsMargins(0,0,0,0);page.setSpacing(10)
        page.addWidget(label('Varianter','PageTitle'))
        self.progress=QProgressBar();self.progress.setRange(0,0);self.progress.setTextVisible(False);self.progress.hide();page.addWidget(self.progress)
        filters=QHBoxLayout();self.sample_filter=QComboBox();self.sample_filter.addItem('Alle prøver');self.sample_filter.setAccessibleName('Prøve')
        self.status_filter=QComboBox();self.status_filter.addItems(['PASS + kandidater','PASS','Kandidater','Alle']);self.status_filter.setAccessibleName('Variantutvalg')
        from PyQt6.QtWidgets import QLineEdit
        self.search=QLineEdit();self.search.setPlaceholderText('Posisjon, cDNA eller protein');self.search.setAccessibleName('Variantsøk')
        self.count_label=label('')
        filters.addWidget(self.sample_filter);filters.addWidget(self.status_filter);filters.addWidget(self.search,1);filters.addWidget(self.count_label);page.addLayout(filters)
        selection=QHBoxLayout()
        self.mark_visible_button=button('Merk synlige',self.mark_visible)
        self.clear_marks_button=button('Fjern merking',self.clear_marks)
        selection.addWidget(self.mark_visible_button);selection.addWidget(self.clear_marks_button);selection.addStretch();page.addLayout(selection)
        self.variant_model=VariantModel();self.variant_proxy=VariantFilter(self);self.variant_proxy.setSourceModel(self.variant_model)
        self.variant_model.dataChanged.connect(lambda *args:self._update_actions())
        self.variant_table=QTableView();self.variant_table.setModel(self.variant_proxy);self.variant_table.setSortingEnabled(True)
        self.variant_table.sortByColumn(0,Qt.SortOrder.AscendingOrder)
        self.variant_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.variant_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.variant_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.variant_table.setAlternatingRowColors(True);self.variant_table.verticalHeader().hide()
        self.variant_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        self.variant_table.horizontalHeader().setStretchLastSection(True)
        for i,w in enumerate((95,150,90,135,145,85,90,110)):self.variant_table.setColumnWidth(i,w)
        self.variant_table.selectionModel().currentRowChanged.connect(self._selected)
        detail=QWidget();detail_layout=QVBoxLayout(detail);detail_layout.setContentsMargins(0,0,0,0);detail_layout.setSpacing(8)
        selected=QHBoxLayout();self.variant_title=label('Ingen variant valgt','CardTitle');selected.addWidget(self.variant_title,1)
        self.open_igv_button=button('Åpne IGV',lambda:self.navigate(1));selected.addWidget(self.open_igv_button)
        self.lookup_button=button('Søk i databaser',self.lookup_selected,True);selected.addWidget(self.lookup_button);detail_layout.addLayout(selected)
        self.variant_info=label('','Subtitle');detail_layout.addWidget(self.variant_info)
        self.source_states=QWidget();self.source_layout=QGridLayout(self.source_states);self.source_layout.setContentsMargins(0,0,0,0)
        self.source_badges={};detail_layout.addWidget(self.source_states)
        image_actions=QHBoxLayout()
        self.retry_images_button=button('Hent bilder fra åpne sider',self.retry_database_images)
        self.retry_images_button.setToolTip('For valgt variant: fullfør innlogging eller nettleserkontroll i Edge og hent bildet uten nytt søk.')
        image_actions.addWidget(self.retry_images_button);image_actions.addStretch();detail_layout.addLayout(image_actions)
        detail_layout.addWidget(label('Logg','CardTitle'))
        self.event_log=QPlainTextEdit();self.event_log.setReadOnly(True);self.event_log.setMaximumBlockCount(500)
        self.event_log.setAccessibleName('Hendelseslogg');detail_layout.addWidget(self.event_log,1)
        split=QSplitter(Qt.Orientation.Vertical);split.addWidget(self.variant_table);split.addWidget(detail);split.setSizes([300,440]);page.addWidget(split,1)
        self.pages.addWidget(analysis)
        igv_page=QWidget();igv_layout=QVBoxLayout(igv_page);igv_layout.setContentsMargins(0,0,0,0)
        igv_layout.addWidget(label('IGV','PageTitle'));self.igv_title=label('Ingen variant valgt','CardTitle');igv_layout.addWidget(self.igv_title)
        self.read_viewer=LiveIgvWidget(enable_webengine=self.browser_enabled,edge_data_dir=self.store.path.parent)
        self.read_viewer.message.connect(self.log_event);igv_layout.addWidget(self.read_viewer,1)
        self.pages.addWidget(igv_page)
        self.settings_panel=SettingsPanel(self.settings,self.database_browser)
        self.settings_panel.changed.connect(self._settings_changed)
        self.settings_panel.busyChanged.connect(lambda busy:self._update_actions())
        self.pages.addWidget(self.settings_panel);layout.addWidget(self.pages,1)
        content.setMinimumSize(940,650)
        scroll=QScrollArea();scroll.setWidgetResizable(True);scroll.setWidget(content);shell.addWidget(scroll,1)
        self.cancel_export_button=button('Avbryt eksport',self.cancel_export);self.cancel_export_button.hide()
        layout.addWidget(self.cancel_export_button)
        for control in (self.sample_filter,self.status_filter):control.currentTextChanged.connect(self._filter)
        self.search.textChanged.connect(self._filter);self.variant_proxy.rowsInserted.connect(self._update_count)
        shell.setSizeConstraint(QLayout.SizeConstraint.SetDefaultConstraint)
        self.setCentralWidget(root)
        self.statusBar().showMessage('Velg analysemappe');self._render_sources();self._update_actions()

    def navigate(self,index):
        if self.settings_panel.busy:return
        changed=self.pages.currentIndex()!=index
        self.pages.setCurrentIndex(index)
        for i,item in enumerate(self.nav_buttons):item.setChecked(i==index)
        if index==1 and changed:self._show_alignment()

    def log_event(self,text):
        self.event_log.appendPlainText(datetime.now().strftime('%H:%M:%S')+'  '+str(text))

    def _settings_changed(self):
        self._render_sources();self._update_actions()

    def choose_folder(self):
        folder=QFileDialog.getExistingDirectory(self,'Velg analysemappe')
        if folder:self.load_folder(Path(folder))

    def load_folder(self,folder):
        from .run_files import discover_run
        def operation():
            files=discover_run(folder)
            session=load_inputs(files.vcfs,'GRCh37');session.source_label=Path(folder).name
            return session,files
        self._start_task(operation,self._imported,'Leser analysemappe …')

    def _imported(self,result):
        session,files=result;self._apply_session(session,files)

    def _apply_session(self,session,files=None):
        self.read_viewer.clear();self.current_variant=None;self.run_files=files;self.lookup_results={};self.session=session
        from .evidence_store import EvidenceStore
        evidence=EvidenceStore(self.store.path.parent)
        for variant in session.data['variants']:
            key=allele_key(variant)
            if key not in self.lookup_results:
                restored=evidence.load(variant)
                if restored:self.lookup_results[key]=restored
        self.navigate(0);self.event_log.clear()
        self.log_event(f"Analyse lastet: {len(session.data['samples'])} prøver, {len(session.data['variants'])} VCF-kall.")
        self.variant_model.replace(session.data['variants'])
        with QSignalBlocker(self.sample_filter):
            self.sample_filter.clear();self.sample_filter.addItem('Alle prøver')
            self.sample_filter.addItems([s['sample'] for s in session.data['samples']])
        self.status_filter.setCurrentIndex(0);self.search.clear();self._filter()
        self.import_button.setToolTip(session.source_label)
        self.statusBar().showMessage('GRCh37 · NM_005157.6')
        self.navigate(0)
        if self.variant_proxy.rowCount():self.variant_table.setCurrentIndex(self.variant_proxy.index(0,0))
        else:self._clear_variant()
        self._update_actions()

    def _filter(self,*args):
        self.variant_proxy.set_filters(sample=self.sample_filter.currentText(),status=self.status_filter.currentText(),query=self.search.text())
        self._update_count()
        current=self.variant_table.currentIndex()
        if not current.isValid():
            if self.variant_proxy.rowCount():self.variant_table.setCurrentIndex(self.variant_proxy.index(0,0))
            else:self._clear_variant()

    def _update_count(self,*args):self.count_label.setText(f'{self.variant_proxy.rowCount()} varianter')

    def visible_rows(self):
        return [self.variant_model.rows[self.variant_proxy.mapToSource(self.variant_proxy.index(i,0)).row()] for i in range(self.variant_proxy.rowCount())]

    def mark_visible(self):
        for i in range(self.variant_proxy.rowCount()):
            self.variant_proxy.setData(self.variant_proxy.index(i,0),Qt.CheckState.Checked,Qt.ItemDataRole.CheckStateRole)

    def clear_marks(self):
        for i in range(self.variant_model.rowCount()):
            self.variant_model.setData(self.variant_model.index(i,0),Qt.CheckState.Unchecked,Qt.ItemDataRole.CheckStateRole)

    def select_variant(self,sample,pos=None):
        self.sample_filter.setCurrentText(sample)
        for i,v in enumerate(self.visible_rows()):
            if pos is None or v['pos']==pos:
                self.variant_table.setCurrentIndex(self.variant_proxy.index(i,0));return

    def _clear_variant(self):
        self.current_variant=None;self.variant_title.setText('Ingen variant valgt');self.variant_info.clear()
        self.igv_title.setText('Ingen variant valgt')
        self._render_sources();self.read_viewer.clear();self._update_actions()

    def _selected(self,current,previous):
        if not current.isValid():self._clear_variant();return
        self.current_variant=self.variant_model.rows[self.variant_proxy.mapToSource(current).row()]
        v=self.current_variant
        self.variant_title.setText(f"{v['sample']}  ·  {v.get('cdna') or str(v['pos'])}  ·  {v.get('protein_snv_alone') or v['ref']+'>'+v['alt']}")
        self.variant_info.setText(f"{v['chrom']}:{v['pos']} {v['ref']}>{v['alt']}  ·  {v.get('filter') or '–'}")
        self.igv_title.setText(self.variant_title.text());self.read_viewer.clear()
        self._render_sources();self._update_actions()
        if self.pages.currentIndex()==1:self._show_alignment()

    def _show_alignment(self):
        v=self.current_variant
        if v is None:self.read_viewer.clear();return
        alignment=self.run_files.alignments.get(v['sample']) if self.run_files and v else None
        reference=Path(self.settings.reference) if self.settings.reference else self.run_files.reference_fasta if self.run_files else None
        if alignment:
            self.log_event('IGV: åpner '+str(v['sample'])+'.')
            try:self.read_viewer.show_alignment(alignment,reference,v)
            except (ValueError,OSError,RuntimeError) as error:
                self.read_viewer.clear();self.statusBar().showMessage(str(error))
        else:
            self.read_viewer.show_alignment(None,reference,v)
            if v:self.log_event('IGV: BAM/CRAM med indeks mangler for '+str(v['sample'])+'.')

    def lookup_selected(self):
        if self.loading:return
        from .lookup import LookupService
        rows={allele_key(v):dict(v) for v in self.variant_model.selected_rows()};providers=tuple(self.settings.providers)
        if not rows:return
        modes={p:'browser' for p in ('franklin','oncokb','mtbp')}
        def operation(emit):
            from .evidence_store import EvidenceStore
            receipts=EvidenceStore(self.store.path.parent)
            service=LookupService(self.store.path.parent,browser_adapter=self.database_browser)
            for key,v in rows.items():
                delivered=set()
                def completed(item):
                    if self.browser_enabled and hasattr(self.database_browser,'capture_result'):
                        item=self.database_browser.capture_result(item['provider'],v,item)
                    # Legacy adapters may omit identity on errors. Never infer
                    # identity for a successful result at this boundary.
                    if item.get('identity'):
                        try:receipts.save(v,item)
                        except OSError:item={**item,'persistence_error':'Databaseresultatet kunne ikke lagres lokalt.'}
                    emit((key,[item]));delivered.add(item['provider'])
                found=service.lookup(v,providers,settings={'provider_modes':modes},completed=completed)
                for item in found:
                    if item['provider'] not in delivered:completed(item)
        self._start_task(operation,lambda _:None,f'Søker i databaser: {len(rows)} merkede alleler …',progress_callback=self._lookup_finished)

    def _lookup_finished(self,result):
        key,results=result
        merged={item['provider']:item for item in self.lookup_results.get(key,[])}
        merged.update({item['provider']:item for item in results})
        self.lookup_results[key]=list(merged.values());self._render_sources()
        for item in results:
            state={'found':'treff','not_found':'ingen treff','login_required':'innlogging kreves','license_required':'tilgang kreves','unsupported':'ikke tilgjengelig','error':'feil','pending':'analyse venter – søk igjen for å hente resultatet'}.get(item.get('status'),'ukjent status')
            self.log_event(PROVIDER_NAMES.get(item['provider'],item['provider'])+': '+state+'.')
            if item.get('screenshot_error'):self.log_event(PROVIDER_NAMES.get(item['provider'],item['provider'])+' · bilde: '+str(item['screenshot_error']))
            elif item.get('screenshot'):self.log_event(PROVIDER_NAMES.get(item['provider'],item['provider'])+' · bilde lagret.')
            if item.get('persistence_error'):self.log_event(item['persistence_error'])
        self._update_actions()

    def retry_database_images(self):
        if self.loading or self.current_variant is None or not hasattr(self.database_browser,'recapture_result'):return
        variant=dict(self.current_variant);key=allele_key(variant)
        results=[dict(item) for item in self.lookup_results.get(key,[])]
        if not results:return
        def operation():
            from .evidence_store import EvidenceStore
            receipts=EvidenceStore(self.store.path.parent);updated=[]
            for item in results:
                current=self.database_browser.recapture_result(item['provider'],variant,item) if item.get('status') in ('found','login_required','error') else item
                if current.get('identity'):receipts.save(variant,current)
                updated.append(current)
            return key,updated
        self._start_task(operation,self._lookup_finished,'Henter bilder fra åpne databasesider for '+str(variant.get('protein_snv_alone') or variant['pos'])+' …')

    def _render_sources(self):
        while self.source_layout.count():
            item=self.source_layout.takeAt(0)
            if item.widget():item.widget().deleteLater()
        self.source_badges={}
        if not self.current_variant:return
        results=self.lookup_results.get(allele_key(self.current_variant),[])
        by_provider={r['provider']:r for r in results}
        states={'found':'Treff','not_found':'Ingen treff','login_required':'Logg inn',
                'license_required':'Tilgang kreves','error':'Feil','unsupported':'Ikke tilgjengelig','pending':'Analyse venter'}
        for i,provider in enumerate(self.settings.providers):
            result=by_provider.get(provider,{})
            state=states.get(result.get('status'),'Ikke søkt')
            if result.get('status')=='found':
                state+=(' · delvis bilder' if result.get('screenshot_error') else ' · bilde klart') if result.get('screenshot') else ' · bilde mangler'
            badge=label(PROVIDER_NAMES.get(provider,provider)+' · '+state,'SourceBadge')
            badge.setToolTip(('Kontrollert: '+str(result.get('checked_at',''))+'\n'+str(result.get('screenshot_error') or result.get('summary') or '')).strip() if result else '')
            badge.setProperty('found',result.get('status')=='found')
            self.source_badges[provider]=badge;self.source_layout.addWidget(badge,i//3,i%3)

    def open_settings(self):self.navigate(2)

    def export_excel_dialog(self):
        if not self.session or not self.variant_model.selected_rows() or self.loading:return
        rows=self.variant_model.selected_rows();names=sample_report_paths(rows,Path('.'))
        if len(names)==1:
            suggested=next(iter(names.values())).name
            path,_=QFileDialog.getSaveFileName(self,'Eksporter Excel',suggested,'Excel (*.xlsx)')
            if path:self.start_export(path if path.lower().endswith('.xlsx') else path+'.xlsx')
        else:
            folder=QFileDialog.getExistingDirectory(self,'Velg mappe for Excel-filer per prøve')
            if not folder:return
            paths=sample_report_paths(rows,folder);existing=[p.name for p in paths.values() if p.exists()]
            if existing:
                answer=QMessageBox.question(self,APP_NAME,'Erstatt eksisterende rapporter?\n'+'\n'.join(existing),QMessageBox.StandardButton.Yes|QMessageBox.StandardButton.No,QMessageBox.StandardButton.No)
                if answer!=QMessageBox.StandardButton.Yes:return
            self.start_export(folder)

    def start_export(self,path):
        rows=[dict(v) for v in self.variant_model.selected_rows()]
        if not rows or self.loading:return
        sample_report_paths(rows,path)
        self._export={'path':path,'rows':rows,'queue':list(rows),'images':{},'errors':{},'current':None}
        self.loading=True;self.progress.show();self.cancel_export_button.show();self._update_actions()
        self.pages.setCurrentIndex(1)
        for i,item in enumerate(self.nav_buttons):item.setChecked(i==1)
        self.log_event(f'Excel: tar IGV-bilder for {len(rows)} merkede varianter.')
        QTimer.singleShot(0,self._export_next)

    def cancel_export(self):
        self.capture_timer.stop();self._export=None;self.loading=False;self.progress.hide();self.cancel_export_button.hide()
        self.read_viewer.clear();self._update_actions();self.log_event('Excel-eksport avbrutt.')
        self.igv_title.setText(self.variant_title.text())
        self.navigate(0)

    def _export_next(self):
        if not self._export:return
        if not self._export['queue']:
            job=self._export;self._export=None;self.loading=False;self.cancel_export_button.hide()
            self.igv_title.setText(self.variant_title.text());self.read_viewer.clear()
            self.navigate(0)
            def operation():
                return export_sample_reports(self.session,job['rows'],self.lookup_results,job['path'],providers=tuple(self.settings.providers),igv_images=job['images'],igv_errors=job['errors'])
            def saved(paths):
                for path in paths:self.log_event('Excel lagret: '+str(path))
            self._start_task(operation,saved,'Lagrer Excel per prøve …')
            return
        variant=self._export['queue'].pop(0);self._export['current']=variant
        self.igv_title.setText(f"{variant['sample']} · {variant.get('protein_snv_alone') or variant.get('cdna') or variant['pos']}")
        alignment=self.run_files.alignments.get(variant['sample']) if self.run_files else None
        reference=Path(self.settings.reference) if self.settings.reference else self.run_files.reference_fasta if self.run_files else None
        if not alignment or not reference:
            self._export['errors'][row_key(variant)]='BAM/CRAM med indeks eller referanse mangler.'
            QTimer.singleShot(0,self._export_next);return
        self.read_viewer.show_alignment(alignment,reference,variant)
        self._capture_deadline=time.monotonic()+45;self.capture_timer.start()

    def _poll_capture(self):
        if not self._export:self.capture_timer.stop();return
        viewer=self.read_viewer;variant=self._export['current'];job=self._export
        def complete(path,error):
            if self._export is not job:return
            if error:job['errors'][row_key(variant)]=error
            else:job['images'][row_key(variant)]=path
            QTimer.singleShot(0,self._export_next)
        if viewer.save_image_button.isEnabled():
            self.capture_timer.stop()
            folder=self.store.path.parent/'evidence/igv';folder.mkdir(parents=True,exist_ok=True)
            viewer.capture_png(folder/(row_key(variant)+'-'+uuid.uuid4().hex+'.png'),complete)
        elif time.monotonic()>self._capture_deadline or (viewer._pending is None and viewer.current_alignment is None) or viewer.web_view and viewer.web_view.title().startswith('ABL1_IGV_ERROR'):
            self.capture_timer.stop();complete(None,viewer.status_label.text())

    def _start_task(self,operation,callback,message,*,progress_callback=None):
        if self.thread is not None:return
        self.log_event(message)
        self.loading=True;self.progress.show();self._update_actions();self.statusBar().showMessage(message)
        self.thread=QThread(self);self.worker=Task(operation,stream=progress_callback is not None);self.worker.moveToThread(self.thread)
        if progress_callback:self.worker.progress.connect(progress_callback)
        self.thread.started.connect(self.worker.run)
        self.worker.finished.connect(callback);self.worker.failed.connect(self._error)
        self.worker.finished.connect(self.thread.quit);self.worker.failed.connect(self.thread.quit)
        self.worker.finished.connect(self.worker.deleteLater);self.worker.failed.connect(self.worker.deleteLater)
        self.thread.finished.connect(self._task_done);self.thread.start()

    def _task_done(self):
        self.thread.deleteLater();self.thread=None;self.worker=None;self.loading=False;self.progress.hide();self._update_actions()
        self.statusBar().showMessage('Klar')

    def _update_actions(self):
        if not hasattr(self,'excel_button'):return
        busy=self.loading or (hasattr(self,'settings_panel') and self.settings_panel.busy)
        self.import_button.setEnabled(not busy);self.settings_button.setEnabled(not busy);self.analysis_button.setEnabled(not busy)
        self.igv_button.setEnabled(not busy);self.open_igv_button.setEnabled(self.current_variant is not None and not busy)
        count=len(self.variant_model.selected_rows()) if hasattr(self,'variant_model') else 0
        self.excel_button.setText(f'Eksporter Excel ({count})' if count else 'Eksporter Excel')
        self.lookup_button.setText(f'Søk i databaser ({count})' if count else 'Søk i databaser')
        self.excel_button.setEnabled(bool(count) and not busy)
        self.lookup_button.setEnabled(bool(count) and bool(self.settings.providers) and not busy)
        self.retry_images_button.setEnabled(self.current_variant is not None and bool(self.lookup_results.get(allele_key(self.current_variant),[])) and not busy)
        for control in (self.variant_table,self.sample_filter,self.status_filter,self.search,self.mark_visible_button,self.clear_marks_button):control.setEnabled(not busy)

    def _error(self,message):
        self.log_event(message)
        self.statusBar().showMessage(message);QMessageBox.warning(self,APP_NAME,message)

    def closeEvent(self,event):
        if self.thread is not None or self.settings_panel.busy or self._export is not None:
            self.statusBar().showMessage('Vent til operasjonen er ferdig.');event.ignore();return
        self.read_viewer.shutdown()
        if hasattr(self.database_browser,'shutdown'):self.database_browser.shutdown()
        super().closeEvent(event)
