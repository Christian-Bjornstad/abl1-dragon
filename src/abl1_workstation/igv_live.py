"""Local, per-run IGV viewer. No alignment or reference leaves loopback.

IGV reference API: https://igv.org/doc/igvjs/Reference-Genome/
CRAM header layout: https://samtools.github.io/hts-specs/CRAMv3.pdf
"""
from __future__ import annotations

from dataclasses import dataclass
import gzip
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import io
import json
import os
from pathlib import Path
import re
import secrets
import struct
import threading
from urllib.parse import urlsplit
import zlib

from PyQt6.QtCore import QObject, Qt, QUrl, pyqtSignal
from PyQt6.QtWidgets import QFileDialog, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

HG19_CHR9_LENGTH = 141213431
HG19_CHR9_MD5 = '3e273117f15e0a400f01055d9f393768'
_MAX_HEADER = 8 * 1024 * 1024
_RESOURCE_NAME = re.compile(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,100}\Z')


def _identity(stat) -> tuple:
    return stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns


@dataclass(frozen=True)
class _File:
    selected: Path
    resolved: Path
    identity: tuple

    @classmethod
    def register(cls, path):
        selected = Path(os.path.abspath(path))
        resolved = selected.resolve(strict=True)
        if not resolved.is_file():
            raise ValueError('Den valgte filen finnes ikke')
        return cls(selected, resolved, _identity(resolved.stat()))

    def open(self):
        # Pin both the selected symlink target and the actual opened file identity.
        if self.selected.resolve(strict=True) != self.resolved:
            raise ValueError('Filen er endret')
        stream = self.resolved.open('rb')
        if _identity(os.fstat(stream.fileno())) != self.identity:
            stream.close()
            raise ValueError('Filen er endret')
        return stream


class _Server(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = False
    block_on_close = False
    request_queue_size = 16

    def __init__(self, owner):
        self.owner = owner
        self.slots = threading.BoundedSemaphore(12)
        super().__init__(('127.0.0.1', 0), _Handler)

    def get_request(self):
        connection, address = super().get_request()
        connection.settimeout(10)
        return connection, address

    def process_request(self, request, client_address):
        if not self.slots.acquire(blocking=False):
            self.shutdown_request(request)
            return
        try:
            super().process_request(request, client_address)
        except BaseException:
            self.slots.release()
            raise

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            self.slots.release()

    def handle_error(self, request, client_address):
        # Broken pipes/timeouts must not print clinical resource URLs or tokens.
        pass


class _Handler(BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'
    server_version = 'LocalIGV'
    sys_version = ''

    def log_message(self, *_):
        pass

    def _headers(self, status, length=0, mime='application/octet-stream', extra=None):
        self.send_response(status)
        self.send_header('Content-Length', str(length))
        self.send_header('Content-Type', mime)
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Referrer-Policy', 'no-referrer')
        self.send_header('Cross-Origin-Resource-Policy', 'same-origin')
        self.send_header('X-Frame-Options', 'DENY')
        self.send_header('Content-Security-Policy', "default-src 'none'; script-src 'self' 'wasm-unsafe-eval'; "
                         "style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; "
                         "connect-src 'self'; worker-src 'self' blob:; font-src 'self' data:; "
                         "base-uri 'none'; form-action 'none'; frame-ancestors 'none'")
        if extra:
            for key, value in extra.items():
                self.send_header(key, value)
        self.send_header('Connection', 'close')
        self.end_headers()
        self.close_connection = True

    def _serve(self, head=False):
        owner = self.server.owner
        host = f'127.0.0.1:{owner.port}'
        if self.headers.get_all('Host') != [host] or self.headers.get('Origin', 'http://' + host) != 'http://' + host:
            self._headers(403)
            return
        name = owner.name_for_path(self.path)
        if name is None or not owner.active:
            self._headers(404)
            return
        resource = owner.resources[name]
        try:
            stream = resource.open() if isinstance(resource, _File) else io.BytesIO(resource)
        except (OSError, ValueError, RuntimeError):
            self._headers(409)
            return
        with stream:
            size = resource.identity[2] if isinstance(resource, _File) else len(resource)
            start, end, status = 0, size - 1, 200
            ranges = self.headers.get_all('Range', [])
            if ranges:
                match = re.fullmatch(r'bytes=(\d{0,20})-(\d{0,20})', ranges[0]) if len(ranges) == 1 else None
                try:
                    if match is None or not any(match.groups()):
                        raise ValueError
                    first, last = match.groups()
                    if first:
                        start = int(first)
                        end = min(int(last), size - 1) if last else size - 1
                    else:
                        suffix = int(last)
                        if suffix <= 0:
                            raise ValueError
                        start = max(0, size - suffix)
                    if start >= size or start > end:
                        raise ValueError
                    status = 206
                except ValueError:
                    self._headers(416, extra={'Content-Range': f'bytes */{size}'})
                    return
            count = max(0, end - start + 1)
            extra = {'Accept-Ranges': 'bytes'}
            if status == 206:
                extra['Content-Range'] = f'bytes {start}-{end}/{size}'
            mime = {'js': 'text/javascript', 'json': 'application/json', 'html': 'text/html',
                    'css': 'text/css'}.get(name.rsplit('.', 1)[-1], 'application/octet-stream')
            self._headers(status, count, mime, extra)
            if not head:
                stream.seek(start)
                while count and owner.active:
                    data = stream.read(min(count, 256 * 1024))
                    if not data:
                        break
                    self.wfile.write(data)
                    count -= len(data)

    def do_GET(self):
        self._serve()

    def do_HEAD(self):
        self._serve(head=True)

    def do_POST(self):
        self._headers(405, extra={'Allow': 'GET, HEAD'})

    do_PUT = do_DELETE = do_PATCH = do_OPTIONS = do_POST


class LoopbackFileServer:
    """Revocable, capability-URL server over an explicit, immutable file list."""

    def __init__(self, resources: dict[str, Path | bytes]):
        if not resources or any(not _RESOURCE_NAME.fullmatch(name) for name in resources):
            raise ValueError('Ugyldig ressursnavn')
        self.resources = {name: value if isinstance(value, bytes) else _File.register(value)
                          for name, value in resources.items()}
        self.token = secrets.token_urlsafe(32)
        self.active = False
        self._server = _Server(self)
        self.port = self._server.server_address[1]
        self._thread = None

    def path(self, name: str) -> str:
        return f'/{self.token}/{name}'

    def url(self, name: str) -> str:
        return f'http://127.0.0.1:{self.port}{self.path(name)}'

    def name_for_path(self, path):
        prefix = f'/{self.token}/'
        if not isinstance(path, str) or not path.startswith(prefix):
            return None
        name = path[len(prefix):]
        return name if name in self.resources and _RESOURCE_NAME.fullmatch(name) else None

    def start(self):
        if self._thread is not None:
            raise RuntimeError('Serveren er allerede startet')
        self.active = True
        self._thread = threading.Thread(target=self._server.serve_forever,
                                        kwargs={'poll_interval': 0.05}, daemon=True, name='local-igv')
        self._thread.start()
        return self

    def shutdown(self):
        was_active, self.active = self.active, False
        if was_active:
            self._server.shutdown()
        self._server.server_close()
        if self._thread is not None and self._thread is not threading.current_thread():
            self._thread.join(timeout=2)


def viewer_url_allowed(url: str, server: LoopbackFileServer | None) -> bool:
    try:
        parsed = urlsplit(url)
        if parsed.scheme == 'about':
            return url in ('about:blank', 'about:srcdoc')
        if parsed.scheme in ('data', 'blob'):
            return True
        return (server is not None and server.active and parsed.scheme == 'http'
                and parsed.netloc == f'127.0.0.1:{server.port}' and not parsed.query and not parsed.fragment
                and server.name_for_path(parsed.path) is not None)
    except (ValueError, TypeError):
        return False


@dataclass(frozen=True)
class ReferenceInfo:
    fasta: Path
    index: Path
    chromosome: str
    length: int
    offset: int
    line_bases: int
    line_width: int


def inspect_reference(fasta) -> ReferenceInfo:
    """Check FAI structure and hg19 chr9 length; sequence MD5 is checked separately."""
    try:
        if fasta is None:
            raise ValueError('Velg en lokal hg19 FASTA-referanse med .fai')
        fasta = Path(fasta).resolve(strict=True)
        index = Path(str(fasta) + '.fai').resolve(strict=True)
        if not fasta.is_file() or not index.is_file() or index.stat().st_size > 5 * 1024 * 1024:
            raise ValueError('FASTA eller FASTA-indeks er ugyldig')
        candidates = []
        for line in index.read_text(encoding='ascii').splitlines():
            fields = line.split('\t')
            if fields and fields[0] in ('chr9', '9'):
                if len(fields) < 5:
                    raise ValueError('Ugyldig FASTA-indeks')
                length, offset, bases, width = map(int, fields[1:5])
                candidates.append(ReferenceInfo(fasta, index, fields[0], length, offset, bases, width))
        if len(candidates) != 1:
            raise ValueError('Referansen må ha én chr9 eller 9')
        reference = candidates[0]
        if reference.length != HG19_CHR9_LENGTH:
            raise ValueError('Referansen er ikke hg19/GRCh37: feil lengde på kromosom 9')
        if reference.offset < 0 or reference.line_bases <= 0 or not reference.line_bases <= reference.line_width <= reference.line_bases + 2:
            raise ValueError('Ugyldig FASTA-indeks')
        span = ((reference.length - 1) // reference.line_bases * reference.line_width
                + (reference.length - 1) % reference.line_bases + 1)
        if reference.offset + span > fasta.stat().st_size:
            raise ValueError('FASTA-indeksen passer ikke til referansefilen')
        return reference
    except (OSError, UnicodeError, TypeError, OverflowError) as error:
        raise ValueError('Lokal hg19 FASTA og tilhørende .fai kunne ikke leses') from error


def verify_reference(reference: ReferenceInfo, cancel: threading.Event | None = None) -> str:
    """Hash the actual chr9 sequence; filesystem timestamps can miss rewrites."""
    fasta = _File.register(reference.fasta)
    index = _File.register(reference.index)
    remaining = ((reference.length - 1) // reference.line_bases * reference.line_width
                 + (reference.length - 1) % reference.line_bases + 1)
    digest, bases = hashlib.md5(), 0
    with fasta.open() as stream:
        stream.seek(reference.offset)
        while remaining:
            if cancel is not None and cancel.is_set():
                raise InterruptedError
            chunk = stream.read(min(1024 * 1024, remaining))
            if not chunk:
                raise ValueError('Referansefilen er avkortet')
            remaining -= len(chunk)
            sequence = chunk.translate(None, b'\r\n').upper()
            digest.update(sequence)
            bases += len(sequence)
        if _identity(os.fstat(stream.fileno())) != fasta.identity:
            raise ValueError('Referansefilen ble endret under kontrollen')
    if bases != reference.length or digest.hexdigest() != HG19_CHR9_MD5:
        raise ValueError('Referansesekvensen på kromosom 9 er ikke hg19/GRCh37 (MD5)')
    with index.open():
        pass
    return digest.hexdigest()


def _read_exact(stream, count):
    data = stream.read(count)
    if len(data) != count:
        raise ValueError('Alignment-filen har en ufullstendig header')
    return data


def _integer(stream, long=False):
    first = _read_exact(stream, 1)[0]
    if not long and first >= 0xF0:
        tail = _read_exact(stream, 4)
        return ((first & 15) << 28) | (tail[0] << 20) | (tail[1] << 12) | (tail[2] << 4) | (tail[3] & 15)
    count, mask = 0, 128
    while first & mask and mask:
        count += 1
        mask >>= 1
    if not long and count > 3:
        raise ValueError('Ugyldig CRAM-header')
    value = first & (mask - 1) if mask else 0
    for byte in _read_exact(stream, count):
        value = (value << 8) | byte
    return value


def _cram_sam_header(path):
    with path.open('rb') as stream:
        definition = _read_exact(stream, 26)
        if definition[:4] != b'CRAM' or definition[4:6] not in (b'\x03\x00', b'\x03\x01'):
            raise ValueError('IGV-viseren krever CRAM 3.0 eller 3.1')
        container_start = stream.tell()
        container_size = struct.unpack('<i', _read_exact(stream, 4))[0]
        if not 0 < container_size <= 2 * _MAX_HEADER:
            raise ValueError('CRAM-headeren er for stor eller ugyldig')
        for _ in range(4):
            _integer(stream)
        _integer(stream, long=True)
        _integer(stream, long=True)
        block_count = _integer(stream)
        landmarks = _integer(stream)
        if not 1 <= block_count <= 1000 or not 0 <= landmarks <= 1000:
            raise ValueError('Ugyldig CRAM-header')
        for _ in range(landmarks):
            _integer(stream)
        container_end = stream.tell()
        checksum = struct.unpack('<I', _read_exact(stream, 4))[0]
        stream.seek(container_start)
        if zlib.crc32(_read_exact(stream, container_end - container_start)) != checksum:
            raise ValueError('CRAM-headerens kontrollsum er feil')
        stream.seek(container_end + 4)
        block_start = stream.tell()
        method, content_type = _read_exact(stream, 2)
        _integer(stream)
        compressed, raw = _integer(stream), _integer(stream)
        if method not in (0, 1) or content_type != 0 or not 4 <= raw <= _MAX_HEADER or not 0 < compressed <= _MAX_HEADER:
            raise ValueError('CRAM-headerblokken støttes ikke')
        payload = _read_exact(stream, compressed)
        block_end = stream.tell()
        checksum = struct.unpack('<I', _read_exact(stream, 4))[0]
        stream.seek(block_start)
        if zlib.crc32(_read_exact(stream, block_end - block_start)) != checksum:
            raise ValueError('CRAM-headerblokkens kontrollsum er feil')
        if method == 1:
            # Limit decompressed output even when the declared raw size is forged.
            with gzip.GzipFile(fileobj=io.BytesIO(payload)) as compressed_stream:
                payload = compressed_stream.read(_MAX_HEADER + 1)
        if len(payload) != raw:
            raise ValueError('Ugyldig CRAM-headerblokk')
        length = struct.unpack('<i', payload[:4])[0]
        if not 0 <= length <= len(payload) - 4:
            raise ValueError('Ugyldig SAM-header i CRAM')
        return payload[4:4 + length].decode('utf-8')


def _check_sam_reference(text, sample):
    references = []
    samples = set()
    for line in text.splitlines():
        if line.startswith('@RG\t'):
            fields = dict(field.split(':', 1) for field in line.split('\t')[1:] if ':' in field)
            if fields.get('SM'):
                samples.add(fields['SM'])
        if line.startswith('@SQ\t'):
            fields = dict(field.split(':', 1) for field in line.split('\t')[1:] if ':' in field)
            if fields.get('SN') in ('chr9', '9'):
                references.append(fields)
    if len(references) != 1 or references[0].get('LN') != str(HG19_CHR9_LENGTH):
        raise ValueError('Alignment-filen er ikke kartlagt mot hg19/GRCh37 kromosom 9')
    if references[0].get('M5', HG19_CHR9_MD5).lower() != HG19_CHR9_MD5:
        raise ValueError('Alignment-filens referanse-MD5 er ikke hg19/GRCh37')
    if samples != {str(sample)}:
        raise ValueError('BAM/CRAM-headeren må angi nøyaktig den valgte prøven i @RG SM')


def inspect_alignment(alignment):
    try:
        path = Path(alignment.path).resolve(strict=True)
        index = Path(alignment.index).resolve(strict=True)
        kind = str(alignment.kind).lower()
        if not path.is_file() or not index.is_file() or not index.stat().st_size:
            raise ValueError('Alignment-filen eller indeksen mangler')
        if kind == 'cram':
            _check_sam_reference(_cram_sam_header(path), alignment.sample)
        elif kind == 'bam':
            with gzip.open(path, 'rb') as stream:
                if _read_exact(stream, 4) != b'BAM\x01':
                    raise ValueError('Ugyldig BAM-fil')
                length = struct.unpack('<i', _read_exact(stream, 4))[0]
                if not 0 < length <= _MAX_HEADER:
                    raise ValueError('BAM-headeren er for stor eller ugyldig')
                _check_sam_reference(_read_exact(stream, length).decode('utf-8'), alignment.sample)
        else:
            raise ValueError('Velg en BAM- eller CRAM-fil med indeks')
        return path, index, kind
    except (OSError, AttributeError, TypeError, UnicodeError, struct.error, EOFError, zlib.error) as error:
        raise ValueError('BAM/CRAM og tilhørende indeks kunne ikke leses') from error


class _ReferenceSignals(QObject):
    finished = pyqtSignal(int, object, object)


class LiveIgvWidget(QWidget):
    """View the selected run's exact alignment, after local reference validation."""
    message=pyqtSignal(str)

    def __init__(self, parent=None, *, enable_webengine=True):
        super().__init__(parent)
        self.enable_webengine = enable_webengine
        self.server = None
        self.current_alignment = None
        self.reference_md5 = None
        self.web_view = self.web_profile = self.web_page = self.web_interceptor = None
        self._generation = 0
        self._cancel = threading.Event()
        self._signals = _ReferenceSignals(self)
        self._signals.finished.connect(self._reference_finished)
        self._pending = None
        self.status_label = QLabel('Velg en variant med BAM eller CRAM.')
        self.status_label.setWordWrap(True)
        self.save_image_button = QPushButton('Lagre bilde')
        self.save_image_button.setEnabled(False)
        self.save_image_button.clicked.connect(self._save_image)
        header = QHBoxLayout()
        header.addWidget(self.status_label, 1)
        header.addWidget(self.save_image_button)
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(0, 0, 0, 0)
        self.layout.addLayout(header)
        self.empty_space=QWidget(self)
        self.layout.addWidget(self.empty_space,1)

    def clear(self):
        self._generation += 1
        self._cancel.set()
        self._cancel = threading.Event()
        self._pending = None
        self.current_alignment = None
        self.reference_md5 = None
        self.save_image_button.setEnabled(False)
        self.empty_space.show()
        if self.web_view is not None:
            self.web_view.stop()
            self.web_view.setUrl(QUrl('about:blank'))
            self.web_view.hide()
        if self.server is not None:
            self.server.shutdown()
            self.server = None
        self.status_label.setText('Velg en variant med BAM eller CRAM.')

    def show_alignment(self, alignment, reference_fasta, variant=None):
        self.clear()
        if alignment is None:
            self.status_label.setText('BAM/CRAM med indeks finnes ikke for denne prøven.')
            return
        if not self.enable_webengine:
            self.status_label.setText('IGV-viseren er deaktivert i denne kjøringen.')
            return
        try:
            if variant is not None:
                position=variant.get('pos')
                if (str(variant.get('chrom','')).removeprefix('chr')!='9'
                        or isinstance(position,bool) or not isinstance(position,int) or not 1<=position<=HG19_CHR9_LENGTH):
                    raise ValueError('IGV: valgt posisjon er ikke støttet (hg19 kromosom 9).')
            reference = inspect_reference(reference_fasta)
            if variant and variant.get('sample') and str(variant['sample']) != str(alignment.sample):
                raise ValueError('Valgt variant og alignment tilhører ulike prøver')
            if not self._create_webengine():
                return
        except ValueError as error:
            self.status_label.setText(str(error))
            return
        self.status_label.setText('Kontrollerer hg19-referanse og alignment …')
        self._pending = alignment, reference, variant
        generation, cancel, signals = self._generation, self._cancel, self._signals

        def verify():
            result, error = None, None
            try:
                paths = inspect_alignment(alignment)
                result = paths, verify_reference(reference, cancel)
            except (ValueError, OSError, InterruptedError) as caught:
                error = str(caught) or 'Avbrutt'
            try:
                signals.finished.emit(generation, result, error)
            except RuntimeError:
                pass  # The widget was destroyed while a read was finishing.

        threading.Thread(target=verify, daemon=True, name='igv-reference-check').start()

    def _reference_finished(self, generation, result, error):
        if generation != self._generation or self._pending is None:
            return
        alignment, reference, variant = self._pending
        self._pending = None
        if error:
            self.status_label.setText(error)
            self.message.emit('IGV: '+error)
            return
        from .domain import resource_root
        from .read_view import locus_for_variant
        path, index, kind = result[0]
        assets = Path(resource_root()) / 'assets' / 'igv'
        try:
            resources = {name: assets / name for name in ('viewer.html', 'viewer.js', 'igv-3.8.9.min.js','cytoband.txt','abl1.bed','protein.bed')}
            resources.update({f'alignment.{kind}': path, f'alignment.{kind}.index': index,
                              'reference.fa': reference.fasta, 'reference.fa.fai': reference.index})
            server = LoopbackFileServer(resources)
            locus = locus_for_variant(variant)
            if reference.chromosome == '9':
                locus = locus.removeprefix('chr')
            config = {'sample': str(alignment.sample), 'kind': kind, 'locus': locus,
                      'chromosome': reference.chromosome, 'alignment': f'alignment.{kind}',
                      'index': f'alignment.{kind}.index'}
            position=int(variant.get('pos',133748283)) if variant else 133748283
            config['widerLocus']=reference.chromosome+':'+str(max(1,position-100))+'-'+str(position+100)
            server.resources['config.json'] = json.dumps(config, ensure_ascii=True).encode('utf-8')
            server.start()
        except (OSError, ValueError, RuntimeError) as caught:
            if 'server' in locals():
                server.shutdown()
            self.status_label.setText(f'IGV kunne ikke startes: {caught}')
            self.message.emit('IGV kunne ikke startes.')
            return
        self.server, self.current_alignment = server, alignment
        self.reference_md5 = result[1]
        self.status_label.setText(f'{alignment.sample} · {locus} · hg19 MD5 kontrollert')
        self.empty_space.hide()
        self.web_view.show()
        self.web_view.setUrl(QUrl(server.url('viewer.html')))

    def _create_webengine(self):
        if self.web_view is not None:
            return True
        try:
            from PyQt6.QtWebEngineCore import QWebEnginePage, QWebEngineProfile, QWebEngineSettings, QWebEngineUrlRequestInterceptor
            from PyQt6.QtWebEngineWidgets import QWebEngineView
        except (ImportError, RuntimeError):
            self.status_label.setText('Installer IGV-komponenten med INSTALLER.cmd og start programmet på nytt.')
            return False
        widget = self

        class LocalRequests(QWebEngineUrlRequestInterceptor):
            def interceptRequest(self, info):
                if not viewer_url_allowed(info.requestUrl().toString(), widget.server):
                    info.block(True)

        class LocalPage(QWebEnginePage):
            def acceptNavigationRequest(self, url, navigation_type, is_main_frame):
                return viewer_url_allowed(url.toString(), widget.server)

            def createWindow(self, window_type):
                return None

            def chooseFiles(self, mode, old_files, accepted_types):
                return []

        self.web_view = QWebEngineView(self)
        self.web_view.setContextMenuPolicy(Qt.ContextMenuPolicy.NoContextMenu)
        self.web_profile = QWebEngineProfile(self)
        self.web_profile.setHttpCacheType(QWebEngineProfile.HttpCacheType.NoCache)
        self.web_profile.setPersistentCookiesPolicy(QWebEngineProfile.PersistentCookiesPolicy.NoPersistentCookies)
        self.web_interceptor = LocalRequests(self.web_profile)
        self.web_profile.setUrlRequestInterceptor(self.web_interceptor)
        self.web_profile.downloadRequested.connect(lambda request: request.cancel())
        self.web_page = LocalPage(self.web_profile, self.web_view)
        self.web_view.setPage(self.web_page)
        settings = self.web_page.settings()
        attrs = QWebEngineSettings.WebAttribute
        for name in ('LocalContentCanAccessRemoteUrls', 'LocalContentCanAccessFileUrls', 'DnsPrefetchEnabled',
                     'JavascriptCanOpenWindows', 'JavascriptCanAccessClipboard', 'JavascriptCanPaste',
                     'LocalStorageEnabled', 'HyperlinkAuditingEnabled', 'FullScreenSupportEnabled',
                     'ScreenCaptureEnabled', 'PluginsEnabled', 'PdfViewerEnabled'):
            attribute = getattr(attrs, name, None)
            if attribute is not None:
                settings.setAttribute(attribute, False)
        settings.setUnknownUrlSchemePolicy(QWebEngineSettings.UnknownUrlSchemePolicy.DisallowUnknownUrlSchemes)
        self.web_view.titleChanged.connect(self._title_changed)
        self.web_view.loadFinished.connect(self._load_finished)
        self.layout.insertWidget(1, self.web_view, 1)
        self.web_view.hide()
        return True

    def _title_changed(self, title):
        if self.server is None:
            return
        if self.web_view.url().toString()!=self.server.url('viewer.html'):return
        self.save_image_button.setEnabled(title == 'ABL1_IGV_READY')
        if title=='ABL1_IGV_READY' and self.current_alignment:
            self.message.emit('IGV klar for '+str(self.current_alignment.sample)+'.')
        if title.startswith('ABL1_IGV_ERROR'):
            self.status_label.setText('IGV kunne ikke lese alignment-filen. Se feilen i viseren.')
            self.message.emit('IGV kunne ikke lese alignment-filen.')

    def _load_finished(self, success):
        if self.server is not None and not success:
            self.status_label.setText('IGV kunne ikke lastes.')

    def _save_image(self):
        if self.server is None or self.web_view is None or not self.save_image_button.isEnabled():
            return
        path, _ = QFileDialog.getSaveFileName(self, 'Lagre IGV-bilde', 'IGV.png', 'PNG (*.png)')
        if path:
            self.capture_png(path,lambda saved,error:self.status_label.setText(error or 'IGV-bilde lagret.'))

    def capture_png(self,path,callback):
        """Capture all rendered tracks; callback is scoped to this exact load."""
        generation=self._generation
        if not self.server or not self.web_view or not self.save_image_button.isEnabled():
            callback(None,'IGV er ikke ferdig lastet.');return
        def render(svg):
            if generation!=self._generation:callback(None,'Valgt variant ble endret.');return
            try:
                from PyQt6.QtSvg import QSvgRenderer
                from PyQt6.QtGui import QImage,QPainter
                if not isinstance(svg,str) or not svg.startswith('<svg') or len(svg)>30_000_000:raise ValueError('IGV-bildet kunne ikke leses.')
                renderer=QSvgRenderer(svg.encode());size=renderer.defaultSize()
                if not renderer.isValid() or size.width()<100 or size.height()<100 or size.width()*size.height()>32_000_000:
                    raise ValueError('IGV-bildet har ugyldig størrelse.')
                image=QImage(size,QImage.Format.Format_ARGB32);image.fill(Qt.GlobalColor.white)
                painter=QPainter(image);renderer.render(painter);painter.end()
                if not image.save(str(path),'PNG'):raise ValueError('IGV-bildet kunne ikke lagres.')
                callback(str(path),None)
            except (ValueError,RuntimeError) as error:callback(None,str(error))
        self.web_page.runJavaScript('window.dragonBrowser ? window.dragonBrowser.toSVG() : null',render)

    def shutdown(self):
        self.clear()

    def closeEvent(self, event):
        self.shutdown()
        super().closeEvent(event)
