import sys,tempfile,unittest
from pathlib import Path
from unittest.mock import Mock,patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from abl1_workstation.lookup_browser import PortalBrowser,login_status,_EdgeContext


class PortalLoginFlowTests(unittest.TestCase):
    def test_saved_oncokb_account_is_confirmed_before_variant_query(self):
        variant={'assembly':'GRCh37','chrom':'9','pos':133748283,'ref':'C','alt':'T'}
        with tempfile.TemporaryDirectory() as folder:
            browser=PortalBrowser(folder);context=Mock()
            context.snapshot.return_value={'url':'https://www.oncokb.org/hgvsg/9:g.133748283C%3ET?refGenome=GRCh37','text':'GRCh37\n9:g.133748283C>T\nOncogenicity\nOncogenic'}
            with patch.object(browser,'_context',return_value=context),patch.object(browser,'_has_saved_account',return_value=True),patch.object(browser,'status',return_value={'status':'unknown'}),patch.object(browser,'_saved_login',return_value=True) as login,patch.object(browser,'_wait_capture',side_effect=lambda p,v,c,r:r):
                result=browser.lookup('oncokb',variant)
            self.assertEqual(result['status'],'found');login.assert_called_once()
            self.assertEqual(context.navigate.call_args_list[0].args,('https://www.oncokb.org/login',))
            self.assertIn('/hgvsg/',context.navigate.call_args_list[1].args[0]);browser.close()
    def test_saved_oncokb_login_failure_cannot_silently_fall_back_to_public_result(self):
        variant={'assembly':'GRCh37','chrom':'9','pos':133748283,'ref':'C','alt':'T'}
        with tempfile.TemporaryDirectory() as folder:
            browser=PortalBrowser(folder);context=Mock()
            with patch.object(browser,'_context',return_value=context),patch.object(browser,'_has_saved_account',return_value=True),patch.object(browser,'status',return_value={'status':'unknown'}),patch.object(browser,'_saved_login',return_value=False):
                result=browser.lookup('oncokb',variant)
            self.assertEqual(result['status'],'login_required');context.navigate.assert_called_once_with('https://www.oncokb.org/login');browser.close()
    def test_submitted_credentials_are_not_reported_as_success_before_authentication(self):
        with tempfile.TemporaryDirectory() as folder:
            browser=PortalBrowser(folder);browser.credentials=Mock();browser.credentials.get.return_value=('synthetic@example.invalid','SYNTHETIC_ONLY')
            context=Mock();context.fill_login.return_value=True
            with patch.object(browser,'status',return_value={'status':'logged_out'}),patch('abl1_workstation.lookup_browser.time.sleep'):
                self.assertFalse(browser._saved_login('franklin',context))
            context.fill_login.assert_called_once();browser.close()
    def test_successful_login_is_waited_for_and_password_is_submitted_only_once(self):
        with tempfile.TemporaryDirectory() as folder:
            browser=PortalBrowser(folder);browser.credentials=Mock();browser.credentials.get.return_value=('synthetic@example.invalid','SYNTHETIC_ONLY')
            context=Mock();context.fill_login.return_value=True
            with patch.object(browser,'status',side_effect=[{'status':'logged_out'},{'status':'unknown'},{'status':'logged_in'}]),patch('abl1_workstation.lookup_browser.time.sleep'):
                self.assertTrue(browser._saved_login('oncokb',context))
            context.fill_login.assert_called_once();browser.close()
    def test_keycloak_route_is_explicit_login_even_before_password_input_renders(self):
        result=login_status('mtbp',{'url':'https://mtbp.org/keycloak/realms/MTBP/protocol/openid-connect/auth'})
        self.assertEqual(result['status'],'logged_out')
    def test_known_franklin_javascript_form_is_allowed_with_native_get_prevention(self):
        context=object.__new__(_EdgeContext);context.evaluate=Mock(return_value=False)
        context.fill_login('franklin','synthetic@example.invalid','SYNTHETIC_ONLY')
        expression=context.evaluate.call_args.args[0]
        self.assertIn('sign-in-form',expression)
        self.assertIn('preventDefault',expression)

if __name__=='__main__':unittest.main()
