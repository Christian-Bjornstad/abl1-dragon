"""Synthetic pages and local locks only; no real profile, browser or account."""
import json
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from abl1_workstation import lookup_browser as browser_module
from abl1_workstation.lookup_browser import PortalBrowser, _EdgeContext

V = {'assembly': 'GRCh37', 'chrom': '9', 'pos': 133748283, 'ref': 'C', 'alt': 'T'}
URL = 'https://www.ncbi.nlm.nih.gov/clinvar/variation/12624/'
PAGE = {'url': URL, 'text': 'NC_000009.11:g.133748283C>T', 'ready_state': 'complete'}


class Page:
    def __init__(self, snapshots):
        self.snapshots = iter(snapshots)
        self.current = {}
        self.captures = 0
        self.navigations = []

    def snapshot(self):
        self.current = next(self.snapshots, self.current)
        return self.current

    def is_alive(self): return True
    def navigate(self, url): self.navigations.append(url)
    def close(self): pass

    def capture_png(self, path):
        self.captures += 1
        Path(path).write_bytes(b'\x89PNG\r\n\x1a\nsynthetic')


class RecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name).resolve()
        self.browser = PortalBrowser(self.root)

    def tearDown(self):
        self.browser.close()
        self.temp.cleanup()

    def result(self):
        return {'status': 'found', 'identity': dict(V), 'url': URL,
                'summary': 'API result retained', 'screenshot_error': 'previous failure'}

    def test_clinvar_accession_hgvs_is_exact_for_chromosome_build_and_allele(self):
        self.assertTrue(self.browser._public_identity('clinvar', V, PAGE))
        for text in ('NC_000009.12:g.133748283C>T', 'NC_000019.11:g.133748283C>T',
                     'NC_000009.11:g.133748283C>TG', '19:g.133748283C>T'):
            self.assertFalse(self.browser._public_identity('clinvar', V, {**PAGE, 'text': text}), text)

    def test_retry_waits_for_ready_page_and_clears_previous_capture_error_without_navigating(self):
        page = Page([{**PAGE, 'ready_state': 'loading'}, PAGE, PAGE, PAGE])
        self.browser._contexts['clinvar'] = page
        with patch.object(browser_module.time, 'sleep'):
            result = self.browser.recapture_result('clinvar', V, self.result())
        self.assertTrue(Path(result['screenshot']).is_file())
        self.assertEqual(page.captures, 1)
        self.assertEqual(page.navigations, [])
        self.assertNotIn('screenshot_error', result)
        self.assertEqual(result['summary'], 'API result retained')

    def test_retry_refuses_result_from_another_selected_allele(self):
        page = Page([PAGE])
        self.browser._contexts['clinvar'] = page
        result = self.browser.recapture_result('clinvar', {**V, 'alt': 'G'}, self.result())
        self.assertNotIn('screenshot', result)
        self.assertEqual(result['screenshot_reason'], 'identity_mismatch')
        self.assertEqual(page.captures, 0)

    def test_retry_closed_window_returns_recovery_instruction_without_launching(self):
        self.browser._context_factory = Mock(side_effect=AssertionError('must not launch'))
        result = self.browser.recapture_result('clinvar', V, self.result())
        self.assertEqual(result['screenshot_reason'], 'window_closed')
        self.assertIn('screenshot_error', result)

    def test_retry_captcha_stops_without_capture_and_preserves_api_classification(self):
        page = Page([{**PAGE, 'text': PAGE['text'] + '\nVerify you are human CAPTCHA'}])
        self.browser._contexts['clinvar'] = page
        with patch.object(browser_module.time, 'sleep'):
            result = self.browser.recapture_result('clinvar', V, {**self.result(), 'classification': 'Pathogenic'})
        self.assertEqual(result['screenshot_reason'], 'manual_check_required')
        self.assertEqual(result['classification'], 'Pathogenic')
        self.assertEqual(page.captures, 0)

    def test_manual_login_resume_parses_current_portal_result_and_captures_without_navigation(self):
        url = 'https://www.oncokb.org/hgvsg/9:g.133748283C%3ET?refGenome=GRCh37'
        ready = {'url': url, 'text': 'GRCh37\n9:g.133748283C>T\nOncogenicity\nOncogenic\nProtected by reCAPTCHA'}
        page = Page([ready, ready, ready])
        self.browser._contexts['oncokb'] = page
        original = {**self.result(), 'status': 'login_required', 'url': url}
        result = self.browser.recapture_result('oncokb', V, original)
        self.assertEqual(result['status'], 'found')
        self.assertEqual(result['classification'], 'Oncogenic')
        self.assertTrue(result['identity_verified'])
        self.assertTrue(Path(result['screenshot']).is_file())
        self.assertEqual(page.navigations, [])

    def test_passive_recaptcha_footer_allows_public_capture_but_active_challenge_does_not(self):
        for challenge in (False, True):
            page = Page([{**PAGE, 'text': PAGE['text'] + '\nProtected by reCAPTCHA', 'challenge_visible': challenge}])
            result = self.browser._capture('clinvar', V, page, self.result())
            if challenge:
                self.assertEqual(result['screenshot_reason'], 'manual_check_required')
                self.assertEqual(page.captures, 0)
            else:
                self.assertTrue(Path(result['screenshot']).is_file())

    def test_unfinished_manual_login_preserves_original_portal_status(self):
        page = Page([{'url': 'https://www.oncokb.org/login', 'password_visible': True}])
        self.browser._contexts['oncokb'] = page
        original = {**self.result(), 'status': 'login_required', 'classification': ''}
        result = self.browser.recapture_result('oncokb', V, original)
        self.assertEqual(result['status'], 'login_required')
        self.assertEqual(result['classification'], '')
        self.assertEqual(result['screenshot_reason'], 'login_required')
        self.assertEqual(page.captures, 0)

    def test_page_changed_before_capture_never_writes_picture(self):
        page = Page([{'url': URL, 'text': 'another allele'}])
        result = self.browser._capture('clinvar', V, page, self.result())
        self.assertIn('screenshot_error', result)
        self.assertEqual(page.captures, 0)
        self.assertEqual(list(self.root.rglob('*.png')), [])

    def test_page_changed_after_capture_discards_written_picture(self):
        page = Page([PAGE, {**PAGE, 'text': 'NC_000009.11:g.133748283C>G'}])
        result = self.browser._capture('clinvar', V, page, self.result())
        self.assertEqual(result['screenshot_reason'], 'identity_mismatch')
        self.assertEqual(page.captures, 1)
        self.assertEqual(list(self.root.rglob('*.png')), [])

    def test_initial_public_capture_rejects_result_from_another_allele_without_launching(self):
        self.browser._context_factory = Mock(side_effect=AssertionError('must not launch'))
        result = self.browser.capture_result('clinvar', {**V, 'alt': 'G'}, self.result())
        self.assertEqual(result['screenshot_reason'], 'identity_mismatch')

    def test_stale_session_reattaches_only_the_owned_target_before_retry(self):
        context = _EdgeContext.__new__(_EdgeContext)
        context.profile = self.root / 'PortalProfiler' / 'oncokb'
        context._target = 'owned'; context._session = 'stale'
        connection = Mock(); context._connection = connection
        def call(method, params=None, **kwargs):
            if method == 'Runtime.evaluate':
                if kwargs['session_id'] == 'stale':
                    raise browser_module._BrowserTargetClosed('detached')
                return {'result': {'value': 'recovered'}}
            if method == 'Target.getTargets':
                return {'targetInfos': [{'type': 'page', 'targetId': 'owned', 'url': 'https://www.oncokb.org/login'}]}
            if method == 'Target.attachToTarget': return {'sessionId': 'fresh'}
            return {}
        connection.call.side_effect = call
        self.assertEqual(context.evaluate('1'), 'recovered')
        self.assertEqual(context._session, 'fresh')

    def test_cdp_detached_session_error_is_classified_for_owned_target_recovery(self):
        connection = browser_module._WebSocketConnection.__new__(browser_module._WebSocketConnection)
        connection._lock = threading.Lock(); connection._counter = 0
        connection._socket = Mock()
        connection._timeout_error = TimeoutError
        connection._connection_error = OSError
        connection._closed_error = ConnectionError
        connection._socket.recv.return_value = json.dumps({'id': 1, 'error': {'code': -32001, 'message': 'Session with given id not found.'}})
        with self.assertRaises(browser_module._BrowserTargetClosed):
            connection.call('Runtime.evaluate', {'expression': '1'}, session_id='detached')

    def test_explicit_open_recovers_missing_owned_tab_without_claiming_unrelated_page(self):
        context = _EdgeContext.__new__(_EdgeContext)
        context.profile = self.root / 'PortalProfiler' / 'clinvar'
        context._target = 'closed-tab'; context._session = 'closed-session'
        context.close = Mock()
        calls = []
        def call(method, params=None, **kwargs):
            calls.append((method, params))
            if method == 'Target.getTargets':
                return {'targetInfos': [{'type': 'page', 'targetId': 'unrelated', 'url': 'edge://newtab/'}]}
            if method == 'Target.createTarget': return {'targetId': 'new-owned-tab'}
            if method == 'Target.attachToTarget': return {'sessionId': 'new-session'}
            return {}
        context._connection = Mock(); context._connection.call.side_effect = call
        self.browser._contexts['clinvar'] = context
        self.browser.edge = Mock()
        self.browser.edge.diagnostics.return_value = {}
        self.browser.edge.executable_path.return_value = self.root / 'msedge.exe'
        with patch.object(browser_module, 'debugging_policy', return_value=None):
            self.browser.open_url(URL)
        self.assertEqual(context._target, 'new-owned-tab')
        self.assertIn(('Target.createTarget', {'url': 'about:blank'}), calls)
        self.assertIn(('Page.navigate', {'url': URL}), calls)
        self.assertNotIn(('Target.attachToTarget', {'targetId': 'unrelated', 'flatten': True}), calls)

    def test_os_profile_lease_reuses_abandoned_file_but_rejects_concurrent_owner(self):
        self.root.joinpath('.abl1-portal.lock').write_text('crashed-owner')
        lease = browser_module._acquire_profile_lease(self.root)
        try:
            with self.assertRaises(RuntimeError): browser_module._acquire_profile_lease(self.root)
        finally: lease.close()
        recovered = browser_module._acquire_profile_lease(self.root)
        recovered.close()
        self.assertTrue(self.root.joinpath('.abl1-portal.lock').is_file())

    def test_only_refused_stale_marker_is_removed_without_attaching(self):
        marker = self.root / 'DevToolsActivePort'
        data = '12345\n/devtools/browser/12345678-abcd-1234-abcd-123456789012\n'
        for failure in (TimeoutError('uncertain'), None, ConnectionRefusedError('closed')):
            marker.write_text(data)
            transport = Mock()
            with patch('socket.create_connection', side_effect=failure, return_value=transport):
                if isinstance(failure, ConnectionRefusedError):
                    browser_module._clear_stale_endpoint(self.root)
                    self.assertFalse(marker.exists())
                else:
                    with self.assertRaises(RuntimeError): browser_module._clear_stale_endpoint(self.root)
                    self.assertEqual(marker.read_text(), data)

    @unittest.skipUnless(sys.platform == 'win32', 'Windows owned Edge launcher')
    def test_owned_launch_disables_browser_account_sync_without_changing_site_security(self):
        process = Mock(); process.poll.return_value = 23
        with patch.object(browser_module.subprocess, 'Popen', return_value=process) as launch:
            with self.assertRaises(RuntimeError):
                _EdgeContext(self.root / 'msedge.exe', self.root / 'PortalProfiler' / 'oncokb')
        args = launch.call_args.args[0]
        self.assertIn('--disable-sync', args)
        features = next(arg for arg in args if arg.startswith('--disable-features=')).split('=', 1)[1].split(',')
        self.assertIn('msImplicitSignin', features)
        self.assertNotIn('--ignore-certificate-errors', args)
        self.assertNotIn('--disable-web-security', args)


@unittest.skipUnless(shutil.which('node'), 'Synthetic JavaScript DOM requires Node')
class LoginScriptTests(unittest.TestCase):
    def run_form(self, *, form=True, method='get', disabled=False, host='www.oncokb.org', action_host='www.oncokb.org', captcha=False, passive=False):
        context = _EdgeContext.__new__(_EdgeContext)
        scripts = []
        context.evaluate = lambda expression: scripts.append(expression)
        context.fill_login('oncokb', 'synthetic@example.invalid', 'synthetic-secret')
        # This is an isolated fake DOM, not a real browser or login request.
        harness = r'''
const fs=require('fs'), input=JSON.parse(fs.readFileSync(0,'utf8'));
let clicks=0;
global.location={protocol:'https:',hostname:input.host,port:'',href:'https://'+input.host+'/login'};
global.getComputedStyle=()=>({visibility:'visible',display:'block',opacity:'1'});
global.Event=class {constructor(type){this.type=type;}};
global.HTMLInputElement=class {get value(){return this._value||''} set value(v){this._value=v}};
const make=()=>Object.assign(new HTMLInputElement(),{getBoundingClientRect:()=>({width:100,height:20}),dispatchEvent:()=>{setTimeout(()=>button.disabled=false,0)},getAttribute:()=>null});
const email=make(),password=make();
const button={type:'submit',innerText:'Sign in',disabled:input.disabled,formAction:'',getBoundingClientRect:()=>({width:100,height:20}),getAttribute:()=>null,click:()=>clicks++};
const container={innerText:input.captcha?'CAPTCHA':input.passive?'Sign in\nProtected by reCAPTCHA':'Sign in',method:input.method,action:'https://'+input.action_host+'/login',querySelector:s=>s.includes('checkbox')?null:s.includes('password')?password:null,querySelectorAll:s=>s.includes('button')?[button]:s.includes('password')?[password]:[email],addEventListener:()=>{}};
password.form=input.form?container:null;password.closest=()=>container;
global.document={querySelectorAll:s=>s.includes('iframe')?[]:s.includes('password')?[password]:s.includes('button')?[button]:[email]};
(async()=>{const result=await eval(input.script);console.log(JSON.stringify({result,clicks,email:email.value,password:password.value}));})().catch(e=>{console.error(e);process.exit(1)});
'''
        payload = dict(script=scripts[0], form=form, method=method, disabled=disabled,
                       host=host, action_host=action_host, captcha=captcha, passive=passive)
        completed = subprocess.run([shutil.which('node'), '-e', harness], input=json.dumps(payload),
                                   text=True, capture_output=True, timeout=10, check=True)
        return json.loads(completed.stdout)

    def test_oncokb_react_form_submits_after_controlled_inputs_enable_button(self):
        result = self.run_form(disabled=True)
        self.assertEqual(result, {'result': True, 'clicks': 1, 'email': 'synthetic@example.invalid', 'password': 'synthetic-secret'})

    def test_oncokb_formless_login_uses_bounded_container(self):
        result = self.run_form(form=False)
        self.assertTrue(result['result']); self.assertEqual(result['clicks'], 1)

    def test_passive_recaptcha_notice_does_not_block_saved_login_submission(self):
        result = self.run_form(passive=True)
        self.assertTrue(result['result']); self.assertEqual(result['clicks'], 1)

    def test_login_does_not_fill_or_submit_on_unsafe_destination_or_captcha(self):
        for options in ({'host': 'evil.invalid'}, {'action_host': 'evil.invalid'}, {'captcha': True}):
            with self.subTest(options=options):
                result = self.run_form(**options)
                self.assertFalse(result['result']); self.assertEqual(result['clicks'], 0)
                self.assertEqual(result['password'], '')


if __name__ == '__main__': unittest.main()
