"""Pure offline checks for the distribution/UI wrapper. Not a Docker runtime test."""
from pathlib import Path
import os,sys,unittest
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
import manage
class Distribution(unittest.TestCase):
 def test_default_output_is_ignored(self):
  with patch.dict(os.environ,{'PAI_CONTAINER':'pai_github_all_clean_test','PAI_PROJECT':'pai_github_all_clean_test'},clear=True):
   self.assertEqual(manage.settings()[2],ROOT/'validation/pai_github_all_clean_test')
 def test_reject_in_tree_custom_output(self):
  with patch.dict(os.environ,{'PAI_CONTAINER':'pai_github_all_clean_test','PAI_PROJECT':'pai_github_all_clean_test','PAI_VALIDATION':str(ROOT/'validation_manual_20261029')},clear=True):
   with self.assertRaisesRegex(RuntimeError,'outside repository'):
    manage.settings()
 def test_external_output_allowed(self):
  with patch.dict(os.environ,{'PAI_CONTAINER':'pai_github_all_clean_test','PAI_PROJECT':'pai_github_all_clean_test','PAI_VALIDATION':str(ROOT.parent/'manual-results')},clear=True):
   self.assertEqual(manage.settings()[2],ROOT.parent/'manual-results')
 def test_gui_override_is_explicit(self):
  with patch.dict(os.environ,{'PAI_CONTAINER':'pai_github_all_clean_test','PAI_PROJECT':'pai_github_all_clean_test','PAI_GUI':'1'},clear=True):
   args,_=manage.compose();self.assertIn(str(ROOT/'compose.gui.yaml'),args)
  with patch.dict(os.environ,{'PAI_CONTAINER':'pai_github_all_clean_test','PAI_PROJECT':'pai_github_all_clean_test'},clear=True):
   args,_=manage.compose();self.assertNotIn(str(ROOT/'compose.gui.yaml'),args)
 def test_loopback_web_novnc_and_no_control_change(self):
  config=(ROOT/'compose.yaml').read_text()
  self.assertIn('127.0.0.1:${PAI_WEB_PORT:-6080}:80',config)
  self.assertNotIn('internal: true',config)
  self.assertIn('USER: ubuntu',config)
  self.assertNotIn('privileged:',config)
if __name__=='__main__':unittest.main()
