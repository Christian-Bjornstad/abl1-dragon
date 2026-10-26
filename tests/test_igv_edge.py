import sys,tempfile,threading,unittest
from pathlib import Path
from unittest.mock import Mock,patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from abl1_workstation.igv_live import LoopbackFileServer
from abl1_workstation.igv_edge import EdgeIgv

class EdgeIgvTests(unittest.TestCase):
    def test_owned_edge_uses_only_current_local_view_and_can_return_svg(self):
        with tempfile.TemporaryDirectory() as folder:
            server=LoopbackFileServer({'viewer.html':b'<html></html>'}).start()
            edge=Mock();edge.diagnostics.return_value={};edge.executable_path.return_value=Path(folder)/'msedge.exe'
            context=Mock();context.evaluate.side_effect=['ABL1_IGV_READY','<svg>synthetic</svg>']
            factory=Mock(return_value=context)
            viewer=EdgeIgv(Path(folder),edge=edge,context_factory=factory)
            with patch('abl1_workstation.igv_edge.debugging_policy',return_value=None):
                viewer.open(server,threading.Event())
            self.assertEqual(context._page_call.call_args.args,('Page.navigate',{'url':server.url('viewer.html')}))
            self.assertEqual(viewer.svg(),'<svg>synthetic</svg>')
            self.assertEqual(factory.call_args.args[1],Path(folder).resolve()/'IgvEdge')
            viewer.close();context.close.assert_called_once();server.shutdown()

    def test_cancelled_view_closes_only_owned_context(self):
        with tempfile.TemporaryDirectory() as folder:
            server=LoopbackFileServer({'viewer.html':b'<html></html>'}).start()
            edge=Mock();edge.diagnostics.return_value={};edge.executable_path.return_value=Path(folder)/'msedge.exe'
            cancel=threading.Event();context=Mock()
            def factory(*args):cancel.set();return context
            viewer=EdgeIgv(Path(folder),edge=edge,context_factory=factory)
            with patch('abl1_workstation.igv_edge.debugging_policy',return_value=None):
                with self.assertRaises(InterruptedError):viewer.open(server,cancel)
            context._page_call.assert_not_called();context.close.assert_called_once();server.shutdown()

    def test_edge_policy_is_respected_without_launching(self):
        with tempfile.TemporaryDirectory() as folder:
            factory=Mock();edge=Mock();edge.diagnostics.return_value={'warning':'Policy blocked'}
            viewer=EdgeIgv(Path(folder),edge=edge,context_factory=factory)
            with self.assertRaisesRegex(RuntimeError,'Policy blocked'):viewer.open(None,threading.Event())
            factory.assert_not_called()
