"""User-controlled database handoff to a dedicated external Edge profile."""
from __future__ import annotations

from pathlib import Path
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (QApplication, QComboBox, QFileDialog, QHBoxLayout,
                            QLabel, QLineEdit, QPushButton, QVBoxLayout, QWidget)
from .evidence import provider_url


class DatabasePanel(QWidget):
    opened = pyqtSignal(str)

    def __init__(self, edge, providers, parent=None):
        super().__init__(parent)
        self.edge = edge
        self.catalogue = {p['id']: p for p in providers}
        self.variant = None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        row = QHBoxLayout()
        self.providers = QComboBox()
        self.providers.setAccessibleName('Database i Edge')
        for p in providers: self.providers.addItem(p['name'], p['id'])
        row.addWidget(self.providers, 1)
        self.login_button = QPushButton('Åpne / logg inn i Edge')
        self.query_button = QPushButton('Åpne variantoppslag')
        self.copy_button = QPushButton('Kopier søketekst')
        for button in (self.login_button, self.query_button, self.copy_button): row.addWidget(button)
        layout.addLayout(row)
        self.access = QLabel()
        self.access.setTextFormat(Qt.TextFormat.PlainText)
        self.access.setWordWrap(True)
        layout.addWidget(self.access)
        self.search_text = QLineEdit()
        self.search_text.setReadOnly(True)
        self.search_text.setAccessibleName('Eksakt allel for manuelt databasesøk')
        self.search_text.setPlaceholderText('Velg en variant for søketekst')
        layout.addWidget(self.search_text)
        footer = QHBoxLayout()
        self.status = QLabel('')
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        self.status.setWordWrap(True)
        footer.addWidget(self.status, 1)
        choose = QPushButton('Velg Edge.exe')
        choose.clicked.connect(self.choose_edge)
        footer.addWidget(choose)
        check = QPushButton('Kontroller oppsett')
        check.clicked.connect(self.check_setup)
        footer.addWidget(check)
        layout.addLayout(footer)
        self.providers.currentIndexChanged.connect(self._refresh)
        self.login_button.clicked.connect(self.open_home)
        self.query_button.clicked.connect(self.open_query)
        self.copy_button.clicked.connect(lambda: QApplication.clipboard().setText(self.search_text.text()))
        self._refresh()
        self.status.setText('Logg inn manuelt i Edge ved behov. Innlogging er ikke kontrollert av appen.')

    def set_variant(self, variant):
        self.variant = dict(variant) if variant else None
        self._refresh()

    def _refresh(self):
        provider = self.catalogue.get(self.providers.currentData(), {})
        self.access.setText(provider.get('access', ''))
        v = self.variant
        text = ''
        if v:
            text = f"GRCh37 · {v.get('chrom')}:{v.get('pos')} {v.get('ref')}>{v.get('alt')}"
            if v.get('cdna'): text += ' · NM_005157.6:' + v['cdna']
            if v.get('protein_snv_alone'): text += ' · ' + v['protein_snv_alone']
        self.search_text.setText(text)
        self.query_button.setEnabled(bool(v))
        self.copy_button.setEnabled(bool(v))

    def open_home(self):
        self.open_url(self.catalogue[self.providers.currentData()]['home'])

    def open_query(self):
        if self.variant:
            self.open_url(provider_url(self.catalogue[self.providers.currentData()], self.variant))

    def open_url(self, url):
        try:
            if not url: raise ValueError('Ingen oppslagsadresse for valgt kilde.')
            self.edge.open_url(str(url))
        except (OSError, ValueError, RuntimeError) as error:
            self.status.setText('Kunne ikke åpne Edge: ' + str(error))
            return False
        self.status.setText('Åpning forespurt i Edge. Logg inn ved behov; innlogging og kildetreff er ikke kontrollert av appen.')
        self.opened.emit(str(url))
        return True

    def check_setup(self):
        try:
            diagnostics = self.edge.diagnostics()
            executable = diagnostics.get('executable') or diagnostics.get('edge_path')
            warning = diagnostics.get('policy_warning') or diagnostics.get('warning') or diagnostics.get('error') or diagnostics.get('config_error')
            self.status.setText(('Edge: ' + str(executable) if executable else 'Edge ble ikke funnet. Velg Edge.exe.')
                                + '\nPlanlagt profil: ' + str(self.edge.profile_dir)
                                + ('\n' + str(warning) if warning else '')
                                + '\nInnlogging er ikke kontrollert. Arbeidsgiverpolicy må tillate egen profil.')
        except (OSError, ValueError) as error:
            self.status.setText('Oppsettskontroll feilet: ' + str(error))

    def choose_edge(self):
        name, _ = QFileDialog.getOpenFileName(self, 'Velg Microsoft Edge', '', 'Microsoft Edge (msedge.exe)')
        if name:
            try:
                self.edge.set_executable(Path(name))
                self.check_setup()
            except (OSError, ValueError) as error:
                self.status.setText('Kunne ikke lagre Edge-valget: ' + str(error))
