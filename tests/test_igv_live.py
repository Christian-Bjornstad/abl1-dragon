"""Synthetic fixtures: real run resources stay outside the public repository."""
import hashlib
import gzip
from http.client import HTTPConnection
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from pathlib import Path
import sys
import struct
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import zlib

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from abl1_workstation.igv_live import (
    LoopbackFileServer, LiveIgvWidget, inspect_reference, verify_reference,
    viewer_url_allowed, inspect_alignment,
)


class LocalServerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.folder = Path(self.temp.name)
        self.file = self.folder / 'reads.bam'
        self.file.write_bytes(b'0123456789')
        self.server = LoopbackFileServer({'alignment.bam': self.file, 'config.json': b'{}'})
        self.server.start()

    def tearDown(self):
        self.server.shutdown()
        self.temp.cleanup()

    def request(self, path=None, headers=None, method='GET'):
        connection = HTTPConnection('127.0.0.1', self.server.port, timeout=3)
        connection.request(method, path or self.server.path('alignment.bam'), headers=headers or {})
        response = connection.getresponse()
        result = response.status, dict(response.getheaders()), response.read()
        connection.close()
        return result

    def test_full_head_and_ranges(self):
        code, headers, body = self.request()
        self.assertEqual((code, body), (200, b'0123456789'))
        self.assertEqual(headers['Accept-Ranges'], 'bytes')
        self.assertEqual(headers['Cache-Control'], 'no-store')
        self.assertNotIn('Access-Control-Allow-Origin', headers)
        self.assertEqual(self.request(method='HEAD')[2], b'')
        for value, expected in [('bytes=2-4', b'234'), ('bytes=7-', b'789'), ('bytes=-3', b'789'), ('bytes=8-99', b'89')]:
            with self.subTest(value=value):
                code, headers, body = self.request(headers={'Range': value})
                self.assertEqual((code, body), (206, expected))
                self.assertEqual(int(headers['Content-Length']), len(expected))

    def test_invalid_ranges_and_methods_do_not_return_data(self):
        for value in ['bytes=10-', 'bytes=-0', 'bytes=4-2', 'bytes=0-1,3-4', 'items=0-1', 'bytes=abc', 'bytes=999999999999999999999-']:
            with self.subTest(value=value):
                code, headers, body = self.request(headers={'Range': value})
                self.assertEqual(code, 416)
                self.assertEqual(headers['Content-Range'], 'bytes */10')
                self.assertEqual(body, b'')
        self.assertEqual(self.request(method='POST')[0], 405)

    def test_host_token_traversal_queries_and_unknown_files_rejected(self):
        self.assertEqual(self.request(headers={'Host': 'attacker.example'})[0], 403)
        self.assertEqual(self.request(headers={'Origin': 'https://attacker.example'})[0], 403)
        for path in ['/alignment.bam', '/bad/alignment.bam', self.server.path('../reads.bam'),
                     f'/{self.server.token}/%2e%2e/reads.bam', self.server.path('unknown'),
                     self.server.path('alignment.bam') + '?x=1', self.server.path('alignment.bam') + '/']:
            with self.subTest(path=path):
                self.assertIn(self.request(path)[0], (403, 404))

    def test_changed_or_replaced_file_is_not_served(self):
        self.file.write_bytes(b'private replacement')
        self.assertEqual(self.request()[0], 409)

    def test_symlink_swap_is_not_served(self):
        link = self.folder / 'link.bam'
        other = self.folder / 'other.bam'
        other.write_bytes(b'other secret')
        try:
            link.symlink_to(self.file)
        except OSError:
            self.skipTest('Windows symlink privileges unavailable')
        server = LoopbackFileServer({'alignment.bam': link})
        server.start()
        try:
            link.unlink()
            link.symlink_to(other)
            connection = HTTPConnection('127.0.0.1', server.port, timeout=3)
            connection.request('GET', server.path('alignment.bam'))
            response = connection.getresponse()
            self.assertEqual(response.status, 409)
            response.read()
            connection.close()
        finally:
            server.shutdown()

    def test_shutdown_revokes_endpoint_and_is_idempotent(self):
        port = self.server.port
        self.server.shutdown()
        self.server.shutdown()
        with self.assertRaises(OSError):
            connection = HTTPConnection('127.0.0.1', port, timeout=1)
            connection.request('GET', '/')

    def test_only_exact_server_urls_are_allowed(self):
        url = self.server.url('alignment.bam')
        self.assertTrue(viewer_url_allowed(url, self.server))
        for bad in [url.replace('127.0.0.1', 'localhost'), url + '?external=1',
                    url.replace(self.server.token, 'bad'), 'https://igv.org/', 'file:///C:/private.txt',
                    'http://127.0.0.1:1/', url.replace('/alignment.bam', '/%2e%2e')]:
            self.assertFalse(viewer_url_allowed(bad, self.server), bad)


class ReferenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.fasta = Path(self.temp.name) / 'reference.fa'
        self.fasta.write_bytes(b'>chr9\nACGT\nACGT\n')
        Path(str(self.fasta) + '.fai').write_text('chr9\t8\t6\t4\t5\n')
        self.length_patch = patch('abl1_workstation.igv_live.HG19_CHR9_LENGTH', 8)
        self.md5_patch = patch('abl1_workstation.igv_live.HG19_CHR9_MD5', hashlib.md5(b'ACGTACGT').hexdigest())
        self.length_patch.start()
        self.md5_patch.start()

    def tearDown(self):
        self.length_patch.stop()
        self.md5_patch.stop()
        self.temp.cleanup()

    def test_exact_reference_digest_is_verified_and_changed_sequence_rejected(self):
        reference = inspect_reference(self.fasta)
        self.assertEqual(reference.chromosome, 'chr9')
        self.assertEqual(verify_reference(reference), hashlib.md5(b'ACGTACGT').hexdigest())
        self.fasta.write_bytes(b'>chr9\nACGT\nACGA\n')
        with self.assertRaises(ValueError):
            verify_reference(inspect_reference(self.fasta))

    def test_changed_sequence_is_rejected_even_when_filesystem_timestamp_is_unchanged(self):
        reference=inspect_reference(self.fasta)
        verify_reference(reference)
        original=self.fasta.stat()
        self.fasta.write_bytes(b'>chr9\nACGT\nACGA\n')
        os.utime(self.fasta,ns=(original.st_atime_ns,original.st_mtime_ns))
        with self.assertRaises(ValueError):verify_reference(inspect_reference(self.fasta))

    def test_wrong_length_missing_index_duplicate_chromosome_and_short_fasta_rejected(self):
        index = Path(str(self.fasta) + '.fai')
        for value in ['chr9\t9\t6\t4\t5\n', 'chr9\t8\t6\t4\t5\n9\t8\t6\t4\t5\n',
                      'chr9\t8\t999\t4\t5\n', 'chr9\t8\t6\t4\t3\n']:
            index.write_text(value)
            with self.assertRaises(ValueError):
                inspect_reference(self.fasta)
        index.unlink()
        with self.assertRaises(ValueError):
            inspect_reference(self.fasta)

    def test_cancelled_reference_verification_does_not_cache_success(self):
        cancel = threading.Event()
        cancel.set()
        with self.assertRaises(InterruptedError):
            verify_reference(inspect_reference(self.fasta), cancel)


def _itf8(value):
    if value < 128:
        return bytes([value])
    if value < 16384:
        return bytes([0x80 | (value >> 8), value & 255])
    raise ValueError('Synthetic header field too large')


def _cram_header(text, compressed=False):
    raw = struct.pack('<i', len(text)) + text
    payload = gzip.compress(raw) if compressed else raw
    block = bytes([int(compressed), 0, 0]) + _itf8(len(payload)) + _itf8(len(raw)) + payload
    block += struct.pack('<I', zlib.crc32(block))
    container = struct.pack('<i', len(block)) + bytes([0, 0, 0, 0, 0, 0, 1, 0])
    container += struct.pack('<I', zlib.crc32(container))
    return b'CRAM\x03\x00' + bytes(20) + container + block


class AlignmentHeaderTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.folder = Path(self.temp.name)
        self.header = (b'@HD\tVN:1.6\tSO:coordinate\n@SQ\tSN:chr9\tLN:141213431\tM5:3e273117f15e0a400f01055d9f393768\n'
                       b'@RG\tID:synthetic\tSM:SYNTHETIC\n')

    def tearDown(self):
        self.temp.cleanup()

    def make_alignment(self, kind, content):
        path = self.folder / ('synthetic.' + kind)
        index = self.folder / ('synthetic.' + kind + '.index')
        path.write_bytes(content)
        index.write_bytes(b'synthetic index')
        return SimpleNamespace(sample='SYNTHETIC', path=path, index=index, kind=kind)

    def test_bam_header_checks_hg19_length_and_md5_without_pysam(self):
        payload = b'BAM\x01' + struct.pack('<i', len(self.header)) + self.header
        alignment = self.make_alignment('bam', gzip.compress(payload))
        self.assertEqual(inspect_alignment(alignment)[2], 'bam')
        for header in [self.header.replace(b'141213431', b'138394717'),
                       self.header.replace(b'3e273117f15e0a400f01055d9f393768', b'0' * 32)]:
            alignment.path.write_bytes(gzip.compress(b'BAM\x01' + struct.pack('<i', len(header)) + header))
            with self.assertRaises(ValueError):
                inspect_alignment(alignment)

    def test_raw_and_gzip_cram_headers_and_corrupt_checksum(self):
        for compressed in (False, True):
            alignment = self.make_alignment('cram', _cram_header(self.header, compressed))
            self.assertEqual(inspect_alignment(alignment)[2], 'cram')
            content = bytearray(alignment.path.read_bytes())
            content[-1] ^= 1
            alignment.path.write_bytes(content)
            with self.assertRaises(ValueError):
                inspect_alignment(alignment)

    def test_unknown_cram_version_and_wrong_reference_refused(self):
        alignment = self.make_alignment('cram', _cram_header(self.header.replace(b'141213431', b'138394717')))
        with self.assertRaises(ValueError):
            inspect_alignment(alignment)
        content = bytearray(_cram_header(self.header))
        content[4] = 4
        alignment.path.write_bytes(content)
        with self.assertRaises(ValueError):
            inspect_alignment(alignment)

    def test_wrong_missing_or_multiple_header_samples_are_refused(self):
        for header in [self.header.replace(b'SM:SYNTHETIC', b'SM:OTHER'),
                       self.header.replace(b'SM:SYNTHETIC', b'PL:ILLUMINA'),
                       self.header + b'@RG\tID:second\tSM:OTHER\n']:
            with self.subTest(header=header):
                alignment = self.make_alignment('cram', _cram_header(header))
                with self.assertRaisesRegex(ValueError, 'prøve'):
                    inspect_alignment(alignment)
                alignment = self.make_alignment('bam', gzip.compress(b'BAM\x01' + struct.pack('<i', len(header)) + header))
                with self.assertRaisesRegex(ValueError, 'prøve'):
                    inspect_alignment(alignment)


class NativeViewerTests(unittest.TestCase):
    def test_viewer_document_uses_registered_html_instead_of_http_navigation(self):
        from unittest.mock import Mock
        widget=LiveIgvWidget(enable_webengine=False)
        server=LoopbackFileServer({'viewer.html':b'<html><head></head><body>synthetic</body></html>'}).start()
        widget.server=server;widget.web_view=Mock()
        widget._load_viewer()
        widget.web_view.setUrl.assert_not_called()
        html,base=widget.web_view.setHtml.call_args.args
        self.assertIn('synthetic',html);self.assertEqual(base.toString(),server.url('viewer.html'))
        widget.web_view=None;widget.close()

    def loading_info(self,server,*,code=-102,status='LoadFailedStatus',url=None):
        return SimpleNamespace(status=lambda:SimpleNamespace(name=status),errorCode=lambda:code,
            errorDomain=lambda:SimpleNamespace(name='ConnectionErrorDomain'),
            url=lambda:__import__('PyQt6.QtCore',fromlist=['QUrl']).QUrl(url or server.url('viewer.html')))

    def test_failed_current_page_reports_code_without_leaking_capability_url(self):
        widget=LiveIgvWidget(enable_webengine=False)
        server=LoopbackFileServer({'viewer.html':b'<html></html>'}).start();widget.server=server
        widget.reference_md5='verified'
        messages=[];widget.message.connect(messages.append)
        widget._loading_changed(self.loading_info(server))
        self.assertIn('-102',widget.status_label.text())
        self.assertIn('ConnectionErrorDomain',messages[-1])
        self.assertIn('hg19-referansen er kontrollert',messages[-1])
        self.assertNotIn(server.token,messages[-1]);self.assertNotIn('http://',messages[-1])
        widget.close()

    def test_cancelled_old_or_blank_navigation_does_not_replace_reference_status(self):
        widget=LiveIgvWidget(enable_webengine=False)
        server=LoopbackFileServer({'viewer.html':b'<html></html>'}).start();widget.server=server
        for info in (self.loading_info(server,code=-3),self.loading_info(server,status='LoadStoppedStatus'),
                     self.loading_info(server,url='about:blank'),self.loading_info(server,url=server.url('viewer.html').replace(server.token,'old-token'))):
            widget.status_label.setText('Kontrollerer hg19-referanse og alignment …')
            widget._loading_changed(info)
            self.assertTrue(widget.status_label.text().startswith('Kontrollerer'))
        widget.close()

    def test_renderer_termination_has_a_distinct_actionable_message(self):
        widget=LiveIgvWidget(enable_webengine=False)
        server=LoopbackFileServer({'viewer.html':b'<html></html>'}).start();widget.server=server
        messages=[];widget.message.connect(messages.append)
        widget._renderer_terminated(SimpleNamespace(name='CrashedTerminationStatus'),7)
        self.assertIn('nettleserprosessen',widget.status_label.text())
        self.assertIn('7',messages[-1]);self.assertFalse(widget.save_image_button.isEnabled())
        widget.close()

    def test_active_view_can_use_the_full_content_height(self):
        from PyQt6.QtWidgets import QWidget
        widget=LiveIgvWidget(enable_webengine=False);widget.resize(900,600)
        view=QWidget(widget)
        widget.layout.insertWidget(1,view,1)
        widget.empty_space.hide()
        widget.show();self.app.processEvents()
        self.assertGreater(view.height(),widget.height()-100)
        widget.close()

    @classmethod
    def setUpClass(cls):
        from PyQt6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def test_missing_selection_clears_current_server_and_sample(self):
        widget = LiveIgvWidget(enable_webengine=False)
        widget.show_alignment(None, None, {'sample': 'DO NOT REUSE'})
        self.assertIsNone(widget.server)
        self.assertIsNone(widget.current_alignment)
        self.assertIsNone(widget.web_view)
        self.assertFalse(widget.save_image_button.isEnabled())
        widget.clear()
        widget.shutdown()
        widget.close()

    def test_assets_are_local_and_disable_remote_genome_services(self):
        script = (ROOT / 'assets/igv/viewer.js').read_text(encoding='utf-8')
        self.assertIn('loadDefaultGenomes: false', script)
        self.assertNotIn('https://', script)
        self.assertIn('textContent', script)
        self.assertTrue((ROOT / 'assets/igv/LICENSE.igv.txt').is_file())

    def test_unsupported_variant_contig_or_position_never_creates_webengine(self):
        alignment = SimpleNamespace(sample='SYNTHETIC')
        variants = [
            {'chrom': 'GL000207.1', 'pos': 133748283},
            {'chrom': 'chr1', 'pos': 133748283},
            {'chrom': 'chr9', 'pos': 0},
            {'chrom': '9', 'pos': 141213432},
            {'chrom': 'chr9', 'pos': True},
            {'chrom': 'chr9', 'pos': 1.5},
            {'chrom': 'chr9', 'pos': None},
            {},
        ]
        for variant in variants:
            with self.subTest(variant=variant):
                widget = LiveIgvWidget()
                with patch.object(widget, '_create_webengine') as create, patch('abl1_workstation.igv_live.inspect_reference') as reference:
                    widget.show_alignment(alignment, None, variant)
                create.assert_not_called()
                reference.assert_not_called()
                self.assertIn('ikke støttet', widget.status_label.text())
                self.assertIsNone(widget.server)
                self.assertIsNone(widget.current_alignment)
                widget.close()


if __name__ == '__main__':
    unittest.main()
