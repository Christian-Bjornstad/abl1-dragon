"""Synthetic browser snapshots and loopback transport mocks; no browser launch."""
from pathlib import Path
import json
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from abl1_workstation.lookup import canonical_identity
from abl1_workstation.lookup_browser import PortalBrowser, parse_portal_snapshot, login_status, _WebSocketConnection, _EdgeContext, _owned_endpoint, _initial_target

V={'assembly':'GRCh37','chrom':'9','pos':133748283,'ref':'C','alt':'T','cdna':'c.944C>T','protein_snv_alone':'p.T315I'}


class PortalParserTests(unittest.TestCase):
    def test_login_state_requires_visible_authenticated_controls(self):
        base={'url':'https://franklin.genoox.com/clinical-db/home','text':'Franklin','password_visible':False}
        self.assertEqual(login_status('franklin',base)['status'],'unknown')
        self.assertEqual(login_status('franklin',{**base,'logout_visible':True})['status'],'logged_in')
        self.assertEqual(login_status('franklin',{**base,'password_visible':True,'logout_visible':True})['status'],'logged_out')
        self.assertEqual(login_status('franklin',{**base,'url':'https://evil.invalid/','logout_visible':True})['status'],'unknown')
        self.assertEqual(login_status('franklin',{**base,'franklin_search':True})['status'],'logged_in')
        self.assertEqual(login_status('franklin',{**base,'franklin_search':True,'url':'https://franklin.genoox.com/login'})['status'],'logged_out')
    def snapshot(self,body,url='https://franklin.genoox.com/clinical-db/variant/snp/chr9-133748283-C-T'):
        return {'url':url,'text':body,'password_visible':False}
    def test_franklin_exact_allele_and_build_retrieves_computed_classification(self):
        result=parse_portal_snapshot('franklin',V,self.snapshot('GRCh37 chr9-133748283-C-T\nSuggested classification\nPathogenic\nOncogenicity\nLikely oncogenic'))
        self.assertEqual(result['status'],'found');self.assertIn('Pathogenic',result['classification'])
        self.assertEqual(result['identity'],canonical_identity(V))
        self.assertIn('Suggested classification: Pathogenic',result['classification'])
        self.assertIn('Oncogenicity: Likely oncogenic',result['classification'])
        self.assertEqual(result['classifications']['Oncogenicity']['description'],'Likely oncogenic')
    def test_login_home_or_empty_spa_is_not_a_success(self):
        for snapshot in ({'url':'https://franklin.genoox.com/login','text':'Sign in','password_visible':True},
                         self.snapshot('Welcome to Franklin',url='https://franklin.genoox.com/clinical-db/home'),
                         self.snapshot('GRCh37 chr9-133748283-C-T')):
            result=parse_portal_snapshot('franklin',V,snapshot)
            self.assertNotEqual(result['status'],'found')
        snapshot=self.snapshot('GRCh37 chr9-133748283-C-T\nOncogenicity\nLoading assessment')
        self.assertNotEqual(parse_portal_snapshot('franklin',V,snapshot)['status'],'found')
    def test_snv_and_multibase_alleles_never_share_evidence(self):
        snapshot=self.snapshot('GRCh37 chr9-133748283-C-T\nSuggested classification\nPathogenic')
        self.assertNotEqual(parse_portal_snapshot('franklin',dict(V,ref='CT',alt='TG'),snapshot)['status'],'found')
        self.assertNotEqual(parse_portal_snapshot('franklin',V,self.snapshot('GRCh38 chr9-133748283-C-T\nSuggested classification\nPathogenic'))['status'],'found')
    def test_oncokb_requires_resolved_query_identity_and_classification(self):
        snapshot={'url':'https://www.oncokb.org/hgvsg/9:g.133748283C%3ET?refGenome=GRCh37',
                  'text':'GRCh37\n9:g.133748283C>T\nOncogenicity\nOncogenic\nResistance level\nR1','password_visible':False}
        result=parse_portal_snapshot('oncokb',V,snapshot)
        self.assertEqual(result['status'],'found');self.assertEqual(result['classification'],'Oncogenic')
        snapshot['url']='https://www.oncokb.org/gene/ABL1'
        snapshot['text']='ABL1 Oncogenic'
        self.assertNotEqual(parse_portal_snapshot('oncokb',V,snapshot)['status'],'found')
    def test_wrong_host_and_access_blocks_do_not_become_found(self):
        for snapshot in (self.snapshot('GRCh37 chr9-133748283-C-T Suggested classification Pathogenic',url='https://evil.invalid/'),
                         self.snapshot('Your subscription has expired'),self.snapshot('Access denied CAPTCHA')):
            self.assertNotEqual(parse_portal_snapshot('franklin',V,snapshot)['status'],'found')

    def test_classification_legends_and_unlabelled_badges_are_not_results(self):
        for body in ('GRCh37 chr9-133748283-C-T\nSuggested classification\nPathogenic\nLikely pathogenic\nBenign',
                     'GRCh37 chr9-133748283-C-T\nSuggested classification\nLoading\nLegend: Pathogenic Benign VUS',
                     'GRCh37 chr9-133748283-C-T\nOncogenicity\nLoading\nOncogenic'):
            self.assertNotEqual(parse_portal_snapshot('franklin',V,self.snapshot(body))['status'],'found')

    def test_evidence_legend_levels_do_not_inherit_into_result(self):
        body='GRCh37 chr9-133748283-C-T\nSuggested classification\nPathogenic\nLegend levels: R1 R2 1A 2A\nEvidence level\nLoading'
        result=parse_portal_snapshot('franklin',V,self.snapshot(body))
        self.assertEqual(result['status'],'found');self.assertEqual(result['evidence_level'],'')
        self.assertNotIn('Legend',result['summary'])

    def test_wrong_page_negative_does_not_claim_selected_allele_absence(self):
        snapshot=self.snapshot('No matching variant',url='https://franklin.genoox.com/clinical-db/home')
        self.assertEqual(parse_portal_snapshot('franklin',V,snapshot)['status'],'error')


class FakeEdge:
    def __init__(self,root):self.profile_dir=root/'EdgeProfil';self.path=root/'msedge.exe';self.path.write_bytes(b'fixture')
    def executable_path(self):return self.path
    def diagnostics(self):return {'executable':str(self.path),'warning':None}
    def set_executable(self,path):self.path=path
    def open_url(self,url):self.url=url


class PortalBrowserTests(unittest.TestCase):
    def test_closed_portal_window_reopens_with_same_profile_and_fresh_context(self):
        contexts=[]
        class Context:
            def __init__(self,*args):self.args=args;self.alive=True;self.closed=False;contexts.append(self)
            def is_alive(self):return self.alive
            def navigate(self,url):self.url=url
            def snapshot(self):return {}
            def close(self):self.closed=True
        browser=PortalBrowser(self.root,edge_browser=self.edge,context_factory=Context)
        with patch('abl1_workstation.lookup_browser.debugging_policy',return_value=None):
            browser.open_login('franklin');contexts[0].alive=False
            self.assertEqual(browser.status('franklin')['status'],'closed')
            browser.open_login('franklin')
        self.assertEqual(len(contexts),2);self.assertTrue(contexts[0].closed)
        self.assertEqual(contexts[0].args,contexts[1].args)
        browser.close()

    def test_status_never_launches_browser_and_rechecks_real_page_after_login(self):
        browser=PortalBrowser(self.root,edge_browser=self.edge,context_factory=unittest.mock.Mock())
        self.assertEqual(browser.status('franklin')['status'],'closed')
        browser._context_factory.assert_not_called()
        context=unittest.mock.Mock();context.is_alive.return_value=True
        context.snapshot.return_value={'url':'https://franklin.genoox.com/login','password_visible':True}
        browser._contexts['franklin']=context
        self.assertEqual(browser.status('franklin')['status'],'logged_out')
        context.snapshot.return_value={'url':'https://franklin.genoox.com/clinical-db/home','logout_visible':True}
        self.assertEqual(browser.status('franklin')['status'],'logged_in')
        browser.close()
    def setUp(self):self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);self.edge=FakeEdge(self.root)
    def tearDown(self):self.tmp.cleanup()
    def test_login_uses_own_provider_profile_and_does_not_mark_authenticated(self):
        contexts=[]
        class Context:
            def __init__(self,*args):self.args=args;self.urls=[];self.closed=False;contexts.append(self)
            def navigate(self,url):self.urls.append(url)
            def snapshot(self):return {}
            def close(self):self.closed=True
        browser=PortalBrowser(self.root,edge_browser=self.edge,context_factory=Context)
        with patch('abl1_workstation.lookup_browser.debugging_policy',return_value=None):browser.open_login('franklin')
        self.assertEqual(contexts[0].args[1],self.root/'PortalProfiler/franklin')
        self.assertIn('franklin.genoox.com',contexts[0].urls[0]);self.assertIsNone(browser.diagnostics()['authenticated'])
        browser.close();self.assertTrue(contexts[0].closed)
    def test_policy_block_prevents_process_creation_and_profile_creation(self):
        factory=unittest.mock.Mock();browser=PortalBrowser(self.root,edge_browser=self.edge,context_factory=factory)
        with patch('abl1_workstation.lookup_browser.debugging_policy',return_value='policy blocked'):
            with self.assertRaisesRegex(RuntimeError,'policy blocked'):browser.open_login('franklin')
        factory.assert_not_called();self.assertFalse((self.root/'PortalProfiler').exists())
    def test_mtbp_does_not_generate_or_delete_remote_reports(self):
        browser=PortalBrowser(self.root,edge_browser=self.edge,context_factory=unittest.mock.Mock())
        result=browser.lookup('mtbp',V)
        self.assertEqual(result['status'],'unsupported')
        browser._context_factory.assert_not_called()
    def test_loopback_socket_events_do_not_replace_response_or_use_proxy(self):
        fake_socket=unittest.mock.Mock();fake_socket.recv.side_effect=['{"method":"event"}','{"id":1,"result":{"ok":true}}']
        transport=unittest.mock.Mock();url='ws://127.0.0.1:12345/devtools/browser/12345678-abcd-1234-abcd-123456789012'
        with patch('socket.create_connection',return_value=transport) as connect,patch('websocket.create_connection',return_value=fake_socket) as websocket:
            connection=_WebSocketConnection(url,12345)
        connect.assert_called_once_with(('127.0.0.1',12345),timeout=10)
        self.assertIs(websocket.call_args.kwargs['socket'],transport);self.assertTrue(websocket.call_args.kwargs['suppress_origin'])
        result=connection.call('Test.method',{'value':1})
        self.assertEqual(result,{'ok':True});self.assertEqual(json.loads(fake_socket.send.call_args.args[0]),{'id':1,'method':'Test.method','params':{'value':1}})
        connection.close();fake_socket.close.assert_called_once()

    def test_arbitrary_or_mismatched_debug_endpoints_are_rejected_before_connection(self):
        with patch('socket.create_connection') as connect:
            for url in ('ws://evil.invalid:12345/devtools/browser/1234567890123456','ws://127.0.0.1:12346/devtools/browser/1234567890123456',
                        'ws://user@127.0.0.1:12345/devtools/browser/1234567890123456','ws://127.0.0.1:12345/devtools/page/1234567890123456'):
                with self.assertRaises(ValueError):_WebSocketConnection(url,12345)
            connect.assert_not_called()

    def test_stale_or_redirected_profile_endpoint_cannot_be_attached(self):
        profile=self.root/'provider';profile.mkdir();port_file=profile/'DevToolsActivePort'
        port_file.write_text('12345\n/devtools/browser/12345678-abcd-1234-abcd-123456789012\n')
        with self.assertRaises(ValueError):_owned_endpoint(profile,port_file,port_file.stat().st_mtime_ns+1)
        self.assertTrue(port_file.exists())

    def test_existing_owned_blank_tab_is_reused_instead_of_creating_another(self):
        connection=unittest.mock.Mock()
        connection.call.return_value={'targetInfos':[{'type':'page','targetId':'owned-blank','url':'about:blank'},
                                                     {'type':'browser','targetId':'browser-ui','url':'edge://newtab'}]}
        self.assertEqual(_initial_target(connection),'owned-blank')
        connection.call.assert_called_once_with('Target.getTargets')

    @unittest.skipUnless(sys.platform=='win32','Windows inherited browser handles')
    def test_failed_owned_edge_start_records_startup_diagnostic_and_releases_profile(self):
        class Process:
            def poll(self):return 23
            def wait(self,timeout=None):return 23
        def launch(*args,**kwargs):
            kwargs['stderr'].write(b'synthetic startup diagnostic\n')
            kwargs['stderr'].flush()
            return Process()
        profile=self.root/'PortalProfiler/franklin'
        with patch('abl1_workstation.lookup_browser.subprocess.Popen',side_effect=launch):
            with self.assertRaisesRegex(RuntimeError,'23'):_EdgeContext(self.edge.path,profile)
        self.assertFalse((profile/'.abl1-portal.lock').exists())
        log=self.root/'work/launcher-logs/edge-startup.log'
        self.assertIn('synthetic startup diagnostic',log.read_text(encoding='utf-8'))


if __name__=='__main__':unittest.main()
