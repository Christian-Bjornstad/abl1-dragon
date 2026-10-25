import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from abl1_workstation.database_browser import EdgeBrowser, checked_url


class EdgeBrowserTests(unittest.TestCase):
    def test_cosmic_official_grch37_host_is_allowed_without_relaxing_host_checks(self):
        self.assertEqual(checked_url('https://grch37-cancer.sanger.ac.uk/cosmic/mutation/overview?id=123'),
                         'https://grch37-cancer.sanger.ac.uk/cosmic/mutation/overview?id=123')
        with self.assertRaises(ValueError):checked_url('https://grch37-cancer.sanger.ac.uk.evil.invalid/')
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(prefix='ABL1 Edge Å ');self.root=Path(self.tmp.name)
        self.exe=self.root/'Program Files/msedge.exe';self.exe.parent.mkdir();self.exe.write_bytes(b'test fixture')
        self.browser=EdgeBrowser(self.root/'app data',self.exe)
    def tearDown(self):self.tmp.cleanup()

    def test_invalid_urls_cannot_launch(self):
        with patch('abl1_workstation.database_browser.subprocess.Popen') as launch:
            for url in ['http://www.ncbi.nlm.nih.gov/', 'https://www.ncbi.nlm.nih.gov.evil.org/',
                        'https://x@www.ncbi.nlm.nih.gov/', 'https://www.ncbi.nlm.nih.gov:443/',
                        'https://www.ncbi.nlm.nih.gov/\r\n--arg', 'file:///C:/data',
                        'https://www.ncbi.nlm.nih.gov\\evil/', 'https://www.ncbi.nlm.nih.gov%2eevil/']:
                with self.subTest(url=url),self.assertRaises(ValueError):self.browser.open_url(url)
            launch.assert_not_called()

    def test_argv_uses_only_dedicated_profile_and_no_debug_port(self):
        with patch('abl1_workstation.database_browser.profile_policy',return_value={'configured':False,'error':None}),patch('abl1_workstation.database_browser.subprocess.Popen') as launch:
            self.browser.open_url('https://pubmed.ncbi.nlm.nih.gov/?term=ABL1%20T315I')
        args=launch.call_args.args[0]
        self.assertEqual(args[0],str(self.exe.resolve()))
        self.assertIn('--user-data-dir='+str(self.browser.profile_dir),args)
        self.assertFalse(launch.call_args.kwargs['shell'])
        self.assertFalse(any('remote-debug' in a for a in args))
        self.assertIsNone(self.browser.diagnostics()['authenticated'])

    def test_policy_override_or_unreadable_policy_blocks_launch(self):
        for policy in [{'configured':True,'error':None},{'configured':False,'error':'access denied'}]:
            with patch('abl1_workstation.database_browser.profile_policy',return_value=policy),patch('abl1_workstation.database_browser.subprocess.Popen') as launch:
                with self.assertRaises(RuntimeError):self.browser.open_url('https://mtbp.org/')
                launch.assert_not_called()
        self.assertFalse(self.browser.profile_dir.exists())

    def test_settings_roundtrip_does_not_create_profile(self):
        self.browser.set_executable(self.exe)
        restored=EdgeBrowser(self.root/'app data')
        self.assertEqual(restored.executable_path(),self.exe.resolve())
        self.assertEqual(set(json.loads(restored.settings.read_text())),{'executable'})
        self.assertFalse(restored.profile_dir.exists())

    def test_invalid_settings_do_not_silently_use_another_profile(self):
        self.browser.data_dir.mkdir();self.browser.settings.write_text('{bad json')
        restored=EdgeBrowser(self.browser.data_dir)
        self.assertIsNone(restored.executable_path());self.assertTrue(restored.config_error)

    def test_unicode_query_is_encoded_and_catalogue_hosts_are_all_allowed(self):
        self.assertIn('%C3%85',checked_url('https://pubmed.ncbi.nlm.nih.gov/?term=Å'))
        catalogue=json.loads((Path(__file__).resolve().parents[1]/'app/data/knowledge.json').read_text(encoding='utf-8'))
        from abl1_workstation.evidence import provider_url
        for provider in catalogue['providers']:
            checked_url(provider['home'])
            checked_url(provider_url(provider,{'chrom':'chr9','pos':133748283,'ref':'C','alt':'T','cdna':'c.944C>T','protein_snv_alone':'p.T315I'}))


if __name__=='__main__':unittest.main()
