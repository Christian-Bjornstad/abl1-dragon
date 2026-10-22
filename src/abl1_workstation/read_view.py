"""Native read evidence tabs, isolated from newly imported VCF sessions.

Packaged IGV/PNG evidence belongs only to the explicitly loaded pilot session.
Qt WebEngine is optional and is created only when that evidence is requested.
Its separate off-the-record profile permits bundled/local resources only.

Qt API references:
https://doc.qt.io/qt-6/qwebengineprofile.html#QWebEngineProfile
https://doc.qt.io/qt-6/qwebengineurlrequestinterceptor.html
https://doc.qt.io/qt-6/qwebenginedownloadrequest.html#downloadRequested
"""
from __future__ import annotations

from functools import partial
import json
from pathlib import Path
import re
import tempfile
from urllib.parse import urlsplit
import xml.etree.ElementTree as ET

from PyQt6.QtCore import QIODevice, QSaveFile, Qt, QUrl, QUrlQuery
from PyQt6.QtGui import QDesktopServices, QPixmap
from PyQt6.QtWidgets import (
    QComboBox, QFileDialog, QHBoxLayout, QLabel, QMessageBox, QPushButton,
    QScrollArea, QTabWidget, QVBoxLayout, QWidget,
)

MAX_SVG_BYTES = 20 * 1024 * 1024


def resource_root() -> Path:
    """Resolve the same installed/bundled resources as the native domain layer."""
    from .domain import resource_root as domain_resource_root
    return Path(domain_resource_root()).resolve()


def secure_asset(root: Path, relative: str) -> Path | None:
    """Only return an existing resource underneath root, including symlink checks."""
    if not isinstance(relative, str) or not relative or "\x00" in relative:
        return None
    if urlsplit(relative).scheme or Path(relative).is_absolute() or relative.startswith(("\\", "/")):
        return None
    try:
        resolved_root = Path(root).resolve()
        path = (resolved_root / relative).resolve()
        if path.is_relative_to(resolved_root) and path.is_file():
            return path
    except (OSError, ValueError, RuntimeError):
        pass
    return None


def allowed_url(url: str, root: Path) -> bool:
    """No external network origins; only embedded data and contained local files.

    QUrl performs percent decoding in toLocalFile(), so encoded traversal is
    checked against the resolved filesystem path, not merely its URL prefix.
    Network shares are deliberately rejected, including file://localhost.
    """
    try:
        parsed = QUrl(str(url))
        if not parsed.isValid():
            return False
        scheme = parsed.scheme().lower()
        if scheme in {"data", "blob", "qrc"}:
            return True
        if scheme == "about":
            return parsed.path() in {"blank", "srcdoc"}
        if scheme != "file" or parsed.host() or parsed.userInfo():
            return False
        local = Path(parsed.toLocalFile()).resolve()
        return local.is_relative_to(Path(root).resolve()) and local.is_file()
    except (OSError, ValueError, RuntimeError):
        return False


def locus_for_variant(variant: dict | None) -> str:
    """Use the selected genomic position; codon315 is always shown together."""
    fallback = "chr9:133748262-133748304"
    if not isinstance(variant, dict):
        return fallback
    chrom = str(variant.get("chrom") or variant.get("chr") or "chr9")
    if not re.fullmatch(r"(?:chr)?(?:[1-9]|1\d|2[0-2]|X|Y|M|MT)", chrom):
        return fallback
    if not chrom.startswith("chr"):
        chrom = "chr" + chrom
    try:
        position = int(variant.get("pos") or variant.get("position") or 0)
    except (ValueError, TypeError, OverflowError):
        return fallback
    if not 1 <= position <= 300_000_000:
        return fallback
    if chrom == "chr9" and 133748282 <= position <= 133748284:
        return fallback
    ref = variant.get("ref", "")
    length = len(ref) if isinstance(ref, str) and re.fullmatch(r"[ACGTNacgtn]+",ref) else 1
    return f"{chrom}:{max(1,position-20)}-{position+min(length,1000)-1+20}"


def validate_svg(payload: bytes) -> bool:
    """Accept a bounded static SVG, rejecting executable/external content."""
    if not isinstance(payload, bytes) or not 1 <= len(payload) <= MAX_SVG_BYTES:
        return False
    if b"<!DOCTYPE" in payload.upper() or b"<!ENTITY" in payload.upper():
        return False
    try:
        tree = ET.fromstring(payload)
    except (ET.ParseError, ValueError):
        return False
    if tree.tag.rsplit("}",1)[-1].lower() != "svg":
        return False
    for element in tree.iter():
        tag = str(element.tag).rsplit("}",1)[-1].lower()
        if tag in {"script", "foreignobject", "iframe", "object", "embed", "audio", "video", "style",
                   "animate", "animatemotion", "animatetransform", "set"}:
            return False
        for key, value in element.attrib.items():
            key = key.rsplit("}",1)[-1].lower()
            value = value.strip()
            # IGV's serializer emits literal static attributes. Escaped CSS or
            # comments could disguise an external url() or executable value.
            if "\\" in value or "/*" in value or "*/" in value:
                return False
            if key.startswith("on") or "javascript:" in value.lower() or "@import" in value.lower():
                return False
            if key in {"href", "src"} and not (value.startswith("#") or re.match(r"data:image/(?:png|jpeg|gif|webp|bmp);base64,",value,re.I)):
                return False
            for target in re.findall(r"url\(\s*['\"]?([^)'\"]+)", value, re.I):
                if not target.startswith("#"):
                    return False
    return True


def _app_root(root: Path) -> Path | None:
    for candidate in (root/"app",root):
        if secure_asset(candidate,"data/igv-manifest.json") is not None:
            return candidate.resolve()
    return None


class ReadViewer(QWidget):
    """Read evidence pane used by the native workstation main window."""

    def __init__(self, parent=None, enable_webengine: bool = True):
        super().__init__(parent)
        self.enable_webengine = bool(enable_webengine)
        self.report_path: Path | None = None
        self.web_view = None
        self.web_profile = None
        self.web_page = None
        self.web_interceptor = None
        self._resource_root = None
        self._session = None
        self._images = []
        self._pixmap = QPixmap()
        self._sample = ""
        self._locus = locus_for_variant(None)
        self._download_jobs = {}

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0,0,0,0)
        self.heading = QLabel("Lesningsgrunnlag")
        self.heading.setObjectName("readHeading")
        self.heading.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(self.heading)
        self.status_label = QLabel("Velg en prøve for å vise lesningsgrunnlaget.")
        self.status_label.setWordWrap(True)
        self.status_label.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(self.status_label)

        self.tabs = QTabWidget()
        self.igv_tab = QWidget()
        self.igv_layout = QVBoxLayout(self.igv_tab)
        toolbar = QHBoxLayout()
        self.open_report_button = QPushButton("Åpne lokal IGV-rapport")
        self.open_report_button.setEnabled(False)
        self.open_report_button.clicked.connect(self._open_report)
        toolbar.addWidget(self.open_report_button)
        toolbar.addStretch()
        self.igv_layout.addLayout(toolbar)
        self.igv_note = QLabel("IGV krever tilhørende CRAM/BAM og riktig referanse. VCF alene inneholder ikke lesningene.")
        self.igv_note.setWordWrap(True)
        self.igv_note.setTextFormat(Qt.TextFormat.PlainText)
        self.igv_layout.addWidget(self.igv_note)
        self.igv_layout.addStretch()
        self.tabs.addTab(self.igv_tab,"IGV")

        image_tab = QWidget()
        image_layout = QVBoxLayout(image_tab)
        self.image_selector = QComboBox()
        self.image_selector.setAccessibleName("Lesningsbilde")
        self.image_selector.currentIndexChanged.connect(self._show_image)
        image_layout.addWidget(self.image_selector)
        self.image_details = QLabel("")
        self.image_details.setTextFormat(Qt.TextFormat.PlainText)
        self.image_details.setWordWrap(True)
        image_layout.addWidget(self.image_details)
        self.image_scroll = QScrollArea()
        self.image_scroll.setWidgetResizable(True)
        self.image_label = QLabel()
        self.image_label.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignHCenter)
        self.image_label.setMinimumSize(240,180)
        self.image_scroll.setWidget(self.image_label)
        image_layout.addWidget(self.image_scroll,1)
        self.tabs.addTab(image_tab,"Bilder")
        layout.addWidget(self.tabs,1)
        self.tabs.currentChanged.connect(self._tab_changed)

    def set_context(self, session, variant: dict | None = None, sample: str | None = None):
        self._cancel_downloads()
        self._session = session
        self._sample = str(sample or (variant or {}).get("sample") or "DEMO-A")
        self._locus = locus_for_variant(variant)
        self.heading.setText(f"{self._sample} · lesningsgrunnlag")
        self.report_path = None
        self._images = []
        self.image_selector.clear()
        self._pixmap = QPixmap()
        self.image_label.clear()
        self.image_details.clear()
        self.open_report_button.setEnabled(False)
        if self.web_view is not None:
            self.web_view.stop()
            self.web_view.setUrl(QUrl("about:blank"))
            self.web_view.hide()

        # A matching sample label in an imported VCF never grants bundled evidence.
        if session is None or getattr(session,"is_pilot",False) is not True:
            message = ("Denne importen har ikke tilknyttet, kontrollert CRAM/BAM-lesningsgrunnlag. "
                       "VCF-resultater arver ikke pilotens IGV-rapporter eller bilder, selv når prøvenavnet er likt.")
            self.status_label.setText(message)
            self.igv_note.setText(message)
            self.igv_note.show()
            return
        try:
            self._resource_root = resource_root()
            app_root = _app_root(self._resource_root)
            if app_root is None:
                raise ValueError("Pakkens IGV-manifest finnes ikke")
            manifest_path = secure_asset(app_root,"data/igv-manifest.json")
            manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
            entry = manifest.get("samples",{}).get(self._sample)
            if not isinstance(entry,dict):
                raise ValueError("Ingen kontrollert pilotrapport for valgt prøve")
            self.report_path = secure_asset(app_root,entry.get("report",""))
            if self.report_path is None:
                raise ValueError("Pilotens IGV-rapport finnes ikke i ressurspakken")
            for image in entry.get("images",[]):
                if not isinstance(image,dict):
                    continue
                path = secure_asset(app_root,image.get("path",""))
                if path is not None and path.suffix.lower() == ".png":
                    self._images.append({**image,"resolved_path":path})
            self.image_selector.blockSignals(True)
            self.image_selector.addItems([str(image.get("label","Lesningsbilde")) for image in self._images])
            self.image_selector.blockSignals(False)
            self._show_image(0)
            self.open_report_button.setEnabled(True)
            self.status_label.setText(
                f"Kontrollert pilotgrunnlag · {self._locus}. Faktiske CRAM-utsnitt er pakket lokalt. "
                "Lesningsnavn er erstattet; PCR-duplikater er beholdt."
            )
            if self.enable_webengine and self.tabs.currentIndex() == 0:
                self._load_report()
            else:
                self.igv_note.setText("Lokal IGV-rapport er tilgjengelig. Velg «Åpne lokal IGV-rapport» for å åpne filen manuelt. "
                                      "Bildene kan vises direkte i Bilder-fanen.")
                self.igv_note.show()
        except (OSError,ValueError,TypeError,KeyError) as error:
            self.report_path = None
            self._images = []
            self.status_label.setText(f"Lesningsgrunnlaget kunne ikke lastes: {error}")
            self.igv_note.setText(self.status_label.text())
            self.igv_note.show()

    def _report_url(self) -> QUrl:
        if self.report_path is None:
            return QUrl("about:blank")
        url = QUrl.fromLocalFile(str(self.report_path))
        query = QUrlQuery()
        query.addQueryItem("locus",self._locus)
        url.setQuery(query)
        return url

    def _open_report(self):
        if self.report_path is not None and getattr(self._session,"is_pilot",False) is True:
            url = self._report_url()
            if allowed_url(url.toString(),self._resource_root):
                # Deliberately requires this explicit native button click.
                if not QDesktopServices.openUrl(url):
                    QMessageBox.information(self,"Lokal rapport",f"Åpne denne filen manuelt:\n{self.report_path}")

    def _tab_changed(self, index):
        if index == 0 and self.enable_webengine and self.report_path is not None:
            self._load_report()
        elif index == 1:
            self._scale_image()

    def _load_report(self):
        if not self.enable_webengine or self.report_path is None or getattr(self._session,"is_pilot",False) is not True:
            return
        if self.web_view is None and not self._create_webengine():
            return
        self.web_view.show()
        self.igv_note.hide()
        self.web_view.setUrl(self._report_url())

    def _create_webengine(self) -> bool:
        try:
            from PyQt6.QtWebEngineCore import QWebEnginePage, QWebEngineProfile, QWebEngineSettings, QWebEngineUrlRequestInterceptor
            from PyQt6.QtWebEngineWidgets import QWebEngineView
        except (ImportError,RuntimeError) as error:
            self.igv_note.setText("Den innebygde IGV-viseren er ikke tilgjengelig i denne installasjonen. "
                                  "Bildene fungerer fortsatt. Åpne lokal IGV-rapport manuelt ved behov.")
            self.igv_note.setToolTip(str(error))
            self.igv_note.show()
            return False

        permitted_root = self._resource_root

        class LocalRequests(QWebEngineUrlRequestInterceptor):
            def interceptRequest(self, info):
                if not allowed_url(info.requestUrl().toString(),permitted_root):
                    info.block(True)

        class LocalPage(QWebEnginePage):
            def acceptNavigationRequest(self, url, navigation_type, is_main_frame):
                return allowed_url(url.toString(),permitted_root)

            def createWindow(self, window_type):
                return None

            def chooseFiles(self, mode, old_files, accepted_types):
                return []

        self.web_view = QWebEngineView(self.igv_tab)
        self.web_view.setContextMenuPolicy(Qt.ContextMenuPolicy.NoContextMenu)
        # No storage name => a separate off-the-record profile, never a user browser profile.
        self.web_profile = QWebEngineProfile(self)
        self.web_profile.setHttpCacheType(QWebEngineProfile.HttpCacheType.NoCache)
        self.web_profile.setPersistentCookiesPolicy(QWebEngineProfile.PersistentCookiesPolicy.NoPersistentCookies)
        self.web_interceptor = LocalRequests(self.web_profile)
        self.web_profile.setUrlRequestInterceptor(self.web_interceptor)
        self.web_page = LocalPage(self.web_profile,self.web_view)
        self.web_view.setPage(self.web_page)
        settings = self.web_page.settings()
        attributes = QWebEngineSettings.WebAttribute
        for name in ("LocalContentCanAccessRemoteUrls","DnsPrefetchEnabled","JavascriptCanOpenWindows","JavascriptCanAccessClipboard",
                     "JavascriptCanPaste","LocalStorageEnabled","HyperlinkAuditingEnabled","FullScreenSupportEnabled",
                     "ScreenCaptureEnabled","PluginsEnabled","PdfViewerEnabled"):
            attribute = getattr(attributes,name,None)
            if attribute is not None:
                settings.setAttribute(attribute,False)
        settings.setAttribute(attributes.LocalContentCanAccessFileUrls,True)
        settings.setUnknownUrlSchemePolicy(QWebEngineSettings.UnknownUrlSchemePolicy.DisallowUnknownUrlSchemes)
        self.web_profile.downloadRequested.connect(self._download_requested)
        self.web_view.loadFinished.connect(self._load_finished)
        self.igv_layout.insertWidget(self.igv_layout.count()-1,self.web_view,1)
        return True

    def _load_finished(self, success):
        if self.report_path is not None and not success:
            self.igv_note.setText("IGV kunne ikke lastes inne i programmet. Bilder-fanen og den lokale rapportfilen er tilgjengelige.")
            self.igv_note.show()

    def _show_image(self,index):
        if not 0 <= index < len(self._images):
            self.image_label.clear()
            self.image_details.clear()
            return
        image = self._images[index]
        self._pixmap = QPixmap(str(image["resolved_path"]))
        evidence = image.get("evidence",{})
        reads = evidence.get("read_patterns_BQ30_MQ20",{})
        fragments = evidence.get("fragment_patterns_BQ30_MQ20",{})
        summarize = lambda counts: "; ".join(f"{base}: {count}" for base,count in counts.items()) or "ingen"
        self.image_details.setText(
            f"{image.get('locus','')}\n{image.get('method','CRAM-avledet egen rendering.')}\n"
            f"BQ≥30 / MQ≥20 · lesningsmønstre: {summarize(reads)} · fragmentobservasjoner: {summarize(fragments)}\n"
            "Fragmentobservasjoner er ikke uavhengige originalmolekyler eller validert VAF."
        )
        self._scale_image()

    def _scale_image(self):
        if not self._pixmap.isNull():
            width = max(240,self.image_scroll.viewport().width()-24)
            self.image_label.setPixmap(self._pixmap.scaledToWidth(width,Qt.TransformationMode.SmoothTransformation))

    def resizeEvent(self,event):
        super().resizeEvent(event)
        self._scale_image()

    def _download_requested(self, request):
        """Only SVG blobs from our own pilot page enter a temporary directory.

        The final user-selected file is written only after parsing/validation.
        Other download types, remote URLs and page-save operations are canceled.
        """
        suggested = request.suggestedFileName()
        source = request.url()
        accepted = (getattr(self._session,"is_pilot",False) is True and self.report_path is not None
                    and request.page() is self.web_page and not request.isSavePageDownload()
                    and request.mimeType().split(";",1)[0].lower() == "image/svg+xml"
                    and source.scheme().lower() in {"blob","data"}
                    and re.fullmatch(r"[A-Za-z0-9_-]+\.svg",suggested,re.I))
        if not accepted:
            request.cancel()
            return
        directory = tempfile.TemporaryDirectory(prefix="abl1-igv-svg-")
        identifier = request.id()
        self._download_jobs[identifier] = (request,directory,self._session)
        request.setDownloadDirectory(directory.name)
        request.setDownloadFileName("image.svg")
        request.receivedBytesChanged.connect(partial(self._download_progress,identifier))
        request.isFinishedChanged.connect(partial(self._download_finished,identifier))
        request.accept()

    def _download_progress(self,identifier):
        job = self._download_jobs.get(identifier)
        if job is not None and job[0].receivedBytes() > MAX_SVG_BYTES:
            job[0].cancel()

    def _download_finished(self,identifier):
        job = self._download_jobs.pop(identifier,None)
        if job is None:
            return
        request,directory,session = job
        try:
            from PyQt6.QtWebEngineCore import QWebEngineDownloadRequest
            if request.state() != QWebEngineDownloadRequest.DownloadState.DownloadCompleted or session is not self._session:
                return
            path = Path(directory.name)/"image.svg"
            if not path.is_file() or path.stat().st_size > MAX_SVG_BYTES:
                return
            payload = path.read_bytes()
            if not validate_svg(payload):
                QMessageBox.warning(self,"IGV-bilde","Bildet ble avvist fordi det ikke er en gyldig, selvstendig SVG.")
                return
            filename,_ = QFileDialog.getSaveFileName(self,"Lagre IGV-bilde",f"{self._sample}_IGV.svg","SVG-bilde (*.svg)")
            if not filename:
                return
            if not filename.lower().endswith(".svg"):
                filename += ".svg"
            output = QSaveFile(filename)
            if not output.open(QIODevice.OpenModeFlag.WriteOnly) or output.write(payload) != len(payload) or not output.commit():
                QMessageBox.warning(self,"IGV-bilde","Bildet kunne ikke lagres på valgt sted.")
        except (OSError,RuntimeError) as error:
            QMessageBox.warning(self,"IGV-bilde",f"Bildet kunne ikke lagres: {error}")
        finally:
            directory.cleanup()

    def _cancel_downloads(self):
        jobs = list(self._download_jobs.values())
        self._download_jobs.clear()
        for request,directory,_ in jobs:
            request.cancel()
            directory.cleanup()

    def closeEvent(self,event):
        self._cancel_downloads()
        if self.web_view is not None:
            self.web_view.stop()
        super().closeEvent(event)
