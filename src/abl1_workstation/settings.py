"""Local preferences and accounts backed by Windows Credential Manager."""
import json
from pathlib import Path
from PyQt6.QtCore import QObject,QThread,QTimer,pyqtSignal
from PyQt6.QtWidgets import (QCheckBox,QFileDialog,QFormLayout,QGridLayout,QHBoxLayout,
                             QLabel,QLineEdit,QPushButton,QVBoxLayout,QWidget)
from .report import PROVIDER_NAMES
from .domain import resource_root
from .ui_common import label
from .credentials import CredentialStore,CredentialStoreError

HOMES={'clinvar':'https://www.ncbi.nlm.nih.gov/clinvar/',
       'oncokb':'https://www.oncokb.org/',
       'franklin':'https://franklin.genoox.com/', 'mtbp':'https://mtbp.org/'}
PORTALS=('franklin','oncokb','mtbp')


class Settings:
    def __init__(self,folder):
        self.path=Path(folder)/'settings.json'
        reference=resource_root()/'reference/chr9.fa'
        self.providers=['clinvar'];pruned=False
        self.reference=str(reference) if reference.is_file() else ''
        try:
            if self.path.exists() and self.path.stat().st_size<16000:
                data=json.loads(self.path.read_text(encoding='utf-8'))
                if isinstance(data,dict):
                    providers=data.get('providers')
                    if isinstance(providers,list):
                        self.providers=[p for p in providers if isinstance(p,str) and p in HOMES]
                        pruned=self.providers!=providers
                    if isinstance(data.get('reference'),str):self.reference=data['reference'] or self.reference
        except (OSError,ValueError,TypeError):pass
        if not self.reference or not Path(self.reference).is_file() or not Path(self.reference+'.fai').is_file():
            from .reference_bundle import bundled_reference
            prepared=bundled_reference(resource_root(),folder)
            if prepared:self.reference=str(prepared)
        if pruned:
            try:self.save()
            except OSError:pass

    def save(self):
        self.path.parent.mkdir(parents=True,exist_ok=True)
        temporary=self.path.with_suffix('.tmp')
        temporary.write_text(json.dumps({'providers':self.providers,'reference':self.reference},ensure_ascii=False),encoding='utf-8')
        temporary.replace(self.path)


class SourceTask(QObject):
    done=pyqtSignal(object)
    def __init__(self,operation):super().__init__();self.operation=operation
    def run(self):
        try:self.done.emit(self.operation())
        except RuntimeError as error:self.done.emit({'error':str(error)[:1000]})
        except Exception:self.done.emit({'error':'Kilden kunne ikke åpnes. Prøv igjen eller kontroller Edge-oppsettet.'})


class SettingsPanel(QWidget):
    changed=pyqtSignal()
    busyChanged=pyqtSignal(bool)
    def __init__(self,settings,browser,parent=None,*,credential_store=None):
        super().__init__(parent);self.settings=settings;self.browser=browser
        self.credentials=credential_store or CredentialStore(settings.path.parent)
        if hasattr(browser,'set_credentials'):browser.set_credentials(self.credentials)
        self.thread=None;self.worker=None
        layout=QVBoxLayout(self);layout.setContentsMargins(0,0,0,0);layout.setSpacing(18)
        layout.addWidget(label('Innstillinger','PageTitle'))
        form=QFormLayout();self.reference=QLineEdit(settings.reference)
        self.reference.setAccessibleName('GRCh37 FASTA');self.reference.editingFinished.connect(self._save)
        pick=QPushButton('Velg FASTA');pick.clicked.connect(self._pick_reference)
        row=QHBoxLayout();row.addWidget(self.reference,1);row.addWidget(pick)
        form.addRow('GRCh37 FASTA',row);layout.addLayout(form)
        grid=QGridLayout();grid.setHorizontalSpacing(20);grid.setVerticalSpacing(14)
        grid.addWidget(label('Database','CardTitle'),0,0);grid.addWidget(label('Innlogging','CardTitle'),0,1)
        grid.addWidget(label('E-post','CardTitle'),0,2);grid.addWidget(label('Passord','CardTitle'),0,3)
        self.enabled={};self.status_labels={};self.login_buttons={};self.emails={};self.passwords={}
        for i,(provider,name) in enumerate(PROVIDER_NAMES.items(),1):
            enabled=QCheckBox(name);enabled.setChecked(provider in settings.providers)
            enabled.toggled.connect(self._save);self.enabled[provider]=enabled;grid.addWidget(enabled,i,0)
            state=label('Ikke kontrollert' if provider in PORTALS else 'Åpen kilde')
            self.status_labels[provider]=state;grid.addWidget(state,i,1)
            login=QPushButton('Åpne / logg inn' if provider in PORTALS else 'Åpne')
            login.clicked.connect(lambda checked=False,p=provider:self.open_source(p))
            self.login_buttons[provider]=login;grid.addWidget(login,i,6)
            if provider in PORTALS:
                email=QLineEdit();email.setAccessibleName(name+' e-post');email.setPlaceholderText('E-post');email.setMaximumWidth(210)
                password=QLineEdit();password.setAccessibleName(name+' passord');password.setEchoMode(QLineEdit.EchoMode.Password)
                password.setMaximumWidth(170);password.setPlaceholderText('Passord')
                try:
                    account,secret=self.credentials.get(provider);email.setText(account)
                    if secret:password.setPlaceholderText('Lagret passord')
                except CredentialStoreError:pass
                self.emails[provider]=email;self.passwords[provider]=password
                grid.addWidget(email,i,2);grid.addWidget(password,i,3)
                save=QPushButton('Lagre');save.clicked.connect(lambda checked=False,p=provider:self.save_login(p));grid.addWidget(save,i,4)
                forget=QPushButton('Glem');forget.clicked.connect(lambda checked=False,p=provider:self.forget_login(p));grid.addWidget(forget,i,5)
        grid.setColumnStretch(1,1);layout.addLayout(grid)
        self.refresh_button=QPushButton('Kontroller innlogging');self.refresh_button.clicked.connect(self.refresh_status)
        refresh=QHBoxLayout();refresh.addWidget(self.refresh_button);refresh.addStretch();layout.addLayout(refresh)
        self.message=label('','Subtitle');layout.addWidget(self.message);layout.addStretch()
        self.timer=QTimer(self);self.timer.setInterval(6000);self.timer.timeout.connect(self.refresh_status)

    def save_login(self,provider):
        try:
            email=self.emails[provider].text().strip();password=self.passwords[provider].text()
            if not password:
                previous,secret=self.credentials.get(provider)
                if email==previous:password=secret
            self.credentials.save(provider,email,password)
            self.passwords[provider].clear();self.passwords[provider].setPlaceholderText('Lagret passord')
            self.message.setText(PROVIDER_NAMES[provider]+': innlogging lagret.')
            return True
        except (CredentialStoreError,ValueError) as error:self.message.setText(str(error));return False

    def forget_login(self,provider):
        try:
            self.credentials.delete(provider);self.emails[provider].clear();self.passwords[provider].clear()
            self.passwords[provider].setPlaceholderText('Passord');self.message.setText(PROVIDER_NAMES[provider]+': lagret innlogging fjernet.')
        except CredentialStoreError as error:self.message.setText(str(error))

    @property
    def busy(self):return self.thread is not None

    def _pick_reference(self):
        path,_=QFileDialog.getOpenFileName(self,'Velg GRCh37 FASTA','','FASTA (*.fa *.fasta *.fna)')
        if path:self.reference.setText(path);self._save()

    def _save(self,*args):
        self.settings.providers=[p for p,c in self.enabled.items() if c.isChecked()]
        self.settings.reference=self.reference.text().strip()
        try:self.settings.save();self.changed.emit()
        except OSError:self.message.setText('Innstillingene kunne ikke lagres.')

    def open_source(self,provider):
        if self.busy:return
        if provider in PORTALS:
            try:previous,_=self.credentials.get(provider)
            except CredentialStoreError:previous=''
            changed=self.emails[provider].text().strip()!=previous
            if (self.passwords[provider].text() or changed) and not self.save_login(provider):return
        self.enabled[provider].setChecked(True)
        self.status_labels[provider].setText('Åpner …')
        def operation():
            if provider in PORTALS and hasattr(self.browser,'open_login'):self.browser.open_login(provider)
            else:self.browser.open_url(HOMES[provider])
            return {provider:self.browser.status(provider)} if hasattr(self.browser,'status') else {}
        self._start(operation)

    def refresh_status(self):
        if self.busy or not self.isVisible():return
        def operation():
            return {p:self.browser.status(p) for p in PORTALS} if hasattr(self.browser,'status') else {}
        self._start(operation)

    def _start(self,operation):
        self.refresh_button.setEnabled(False)
        for button in self.login_buttons.values():button.setEnabled(False)
        self.thread=QThread(self);self.worker=SourceTask(operation);self.worker.moveToThread(self.thread)
        self.busyChanged.emit(True)
        self.thread.started.connect(self.worker.run);self.worker.done.connect(self._results)
        self.worker.done.connect(self.thread.quit);self.worker.done.connect(self.worker.deleteLater)
        self.thread.finished.connect(self._finished);self.thread.start()

    def _results(self,results):
        self.message.setText(results.get('error',''))
        if results.get('error'):
            for item in self.status_labels.values():
                if item.text()=='Åpner …':item.setText('Kunne ikke åpnes')
        for provider,result in results.items():
            if provider not in self.status_labels:continue
            state=result.get('status');item=self.status_labels[provider]
            item.setText(result.get('summary') or 'Ikke kontrollert')
            tooltip='Kontrollert: '+str(result.get('checked_at',''))
            if result.get('confirmed_at'):tooltip+='\nInnlogging bekreftet: '+str(result['confirmed_at'])
            item.setToolTip(tooltip)
            item.setProperty('sourceState',state)
            color='#3E6C4C' if state=='logged_in' else '#7150A1' if state=='last_confirmed' else '#6A6374'
            item.setStyleSheet('color:'+color+(' ;font-weight:600;' if state in ('logged_in','last_confirmed') else ';'))
            self.login_buttons[provider].setText('Åpne' if state in ('logged_in','last_confirmed') else 'Åpne / logg inn')

    def _finished(self):
        self.thread.deleteLater();self.thread=None;self.worker=None
        self.refresh_button.setEnabled(True)
        for button in self.login_buttons.values():button.setEnabled(True)
        self.busyChanged.emit(False)

    def showEvent(self,event):
        super().showEvent(event);self.timer.start();QTimer.singleShot(0,self.refresh_status)

    def hideEvent(self,event):
        self.timer.stop();super().hideEvent(event)
