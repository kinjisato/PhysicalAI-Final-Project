"""Offline boundaries; never represent these tests as real model/ROS execution."""
from pathlib import Path
import importlib.util,json,os,subprocess,sys,tempfile,unittest
R=Path(__file__).resolve().parents[1];sys.path.insert(0,str(R/'tools'))
import simulation_cli as runtime
class Checks(unittest.TestCase):
 def test_integrity(self):subprocess.run([sys.executable,'-B',str(R/'tools/verify_source.py')],check=True,capture_output=True)
 def test_invalid_text_before_ROS(self):
  for text in ['', '  ', 'a'*2001,'a\x00b']:
   with self.assertRaises(ValueError):runtime.validate_input(text,'USER')
 def test_exact_input_not_rewritten(self):self.assertEqual(runtime.validate_input(' 青、黄。\n','USER'),' 青、黄。\n')
 def test_no_expected_argument_or_import(self):
  import inspect,ast
  self.assertEqual(list(inspect.signature(runtime.run).parameters),['action','text','request_id','authorized'])
  t=ast.parse((R/'tools/simulation_cli.py').read_text());imports=[ast.unparse(x) for x in ast.walk(t) if isinstance(x,(ast.Import,ast.ImportFrom))]
  self.assertFalse(any('evaluate_cases' in x or 'case_driver' in x for x in imports));self.assertNotIn('L.run_case(', (R/'tools/simulation_cli.py').read_text())
 def test_lock_is_exclusive(self):
  with tempfile.TemporaryDirectory() as tmp:
   p=Path(tmp)/'lock'
   with runtime.exclusive_request(p):
    with self.assertRaises(FileExistsError):
     with runtime.exclusive_request(p):pass
   self.assertFalse(p.exists())
 def test_runtime_cannot_open_oracles(self):
  code='from pathlib import Path;import sys;sys.path.insert(0,sys.argv[1]);import simulation_cli as r;r.forbid_test_data_reads(Path(sys.argv[2]));Path(sys.argv[2],"tests/expected_28.json").read_text()'
  x=subprocess.run([sys.executable,'-B','-c',code,str(R/'tools'),str(R)],capture_output=True,text=True);self.assertNotEqual(x.returncode,0);self.assertIn('Test/case table forbidden',x.stderr)
 def test_protected_namespace(self):
  import manage
  from unittest.mock import patch
  with patch.dict(os.environ,{'PAI_CONTAINER':'pai_github_minimal_20261028_02'}):
   with self.assertRaises(RuntimeError):manage.settings()
if __name__=='__main__':unittest.main()
