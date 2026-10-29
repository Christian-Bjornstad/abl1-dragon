from pathlib import Path
import sys,unittest
from unittest.mock import Mock,patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from abl1_workstation.franklin_search import start_query,resolve_option

V={'assembly':'GRCh37','chrom':'9','pos':133748283,'ref':'C','alt':'T'}


class FranklinControlsTests(unittest.TestCase):
    def test_mode_selection_uses_real_mouse_events_before_submitting(self):
        context=Mock()
        with patch('abl1_workstation.franklin_search.dismiss_cookies') as dismiss,patch('abl1_workstation.franklin_search.evaluate',side_effect=[False,{'x':120,'y':80}]):
            self.assertFalse(start_query(context,V))
        dismiss.assert_called_once_with(context,'franklin')
        self.assertEqual([call.args[1]['type'] for call in context._page_call.call_args_list],['mousePressed','mouseReleased'])
    def test_ready_input_gets_native_enter_and_invalid_click_point_is_rejected(self):
        context=Mock()
        with patch('abl1_workstation.franklin_search.dismiss_cookies'),patch('abl1_workstation.franklin_search.evaluate',side_effect=[False,'ready']):
            self.assertTrue(start_query(context,V))
        self.assertEqual(context._page_call.call_args_list[0].args[1]['key'],'Enter')
        context.reset_mock()
        with patch('abl1_workstation.franklin_search.evaluate',return_value={'x':-1,'y':20}):
            self.assertFalse(resolve_option(context))
        context._page_call.assert_not_called()
    def test_selected_mode_ignores_text_from_open_dropdown_options(self):
        context=Mock()
        with patch('abl1_workstation.franklin_search.dismiss_cookies'),patch('abl1_workstation.franklin_search.evaluate',side_effect=[False,'waiting']) as evaluate:
            self.assertFalse(start_query(context,V))
        expression=evaluate.call_args.args[2]
        self.assertIn("querySelector('.mat-mdc-select-value')",expression)
        self.assertIn('===label.toLowerCase()',expression)
