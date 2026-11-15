import sys,unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from abl1_workstation.browser_evidence import classification_views


class ReadyTests(unittest.TestCase):
    def test_empty_container_is_not_ready_until_evidence_cards_have_text(self):
        class SlowPage:
            checks=0
            def evaluate(self,expression):
                self.checks+=1
                if '.map(' in expression:return ['Population Data'] if self.checks>4 else []
                # The Angular container exists immediately; categories arrive later.
                if 'gnx-result-category' in expression and 'innerText' in expression:return self.checks>4
                return True
        with patch('abl1_workstation.browser_evidence.activate',return_value=True),patch('abl1_workstation.browser_evidence.time.sleep'):
            page=SlowPage();views=classification_views(page,'ACMG Classification','gnx-result-page','gnx-result-page gnx-result-category')
            self.assertEqual(next(views),('ACMG Classification overview',None))
            self.assertGreater(page.checks,4)
            views.close()


if __name__=='__main__':unittest.main()
