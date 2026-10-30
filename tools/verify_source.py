"""No Docker/network/ROS. Verify public manifest, semantic core pins and syntax."""
from pathlib import Path
import ast,hashlib,json,sys
from ast_signature import signature
ROOT=Path(__file__).resolve().parents[1]
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def safe(name):
 p=ROOT/name
 if not p.is_file() or p.is_symlink() or ROOT not in p.resolve().parents:raise ValueError('Missing/unsafe public reference: '+name)
 return p
manifest=json.loads((ROOT/'PUBLIC_MANIFEST.json').read_text());files=manifest['files']
for name,h in files.items():
 p=safe(name)
 if sha(p)!=h:raise ValueError('Public source hash mismatch: '+name)
 if p.suffix=='.py':ast.parse(p.read_text(),filename=name)
 if p.suffix=='.json':json.loads(p.read_text())
actual={p.relative_to(ROOT).as_posix() for p in ROOT.rglob('*') if p.is_file() and not any(x in p.relative_to(ROOT).parts for x in ['.git','.cache','validation','__pycache__']) and p.name not in ['PUBLIC_MANIFEST.json','.env','.DS_Store'] and p.suffix!='.pyc'}
if actual!=set(files):raise ValueError('Unlisted/missing public files: '+str(sorted(actual^set(files))))
core=json.loads((ROOT/'docker/CORE_PINS.json').read_text())
for name,h in core['unchanged_files'].items():
 if sha(safe(name))!=h:raise ValueError('Frozen semantic/safety/trajectory file changed: '+name)
runner=ast.parse(safe(core['runner_file']).read_text());functions={n.name:signature(n) for n in runner.body if isinstance(n,(ast.FunctionDef,ast.ClassDef))}
if functions!=core['runner_function_AST_sha256']:raise ValueError('Original runner function/class logic changed')
for name,h in json.loads((ROOT/'code/SOURCE_MANIFEST.json').read_text()).items():
 if sha(safe('code/'+name))!=h:raise ValueError('Code manifest mismatch')
pin=json.loads((ROOT/'code/MODEL_PIN.json').read_text());expected=core['model_identity']
if {k:pin[k] for k in expected}!=expected:raise ValueError('Model identity changed')
if sha(safe('docker/qwen_manifest.json'))!=pin['manifest_file_sha256']:raise ValueError('Model wrapper descriptor differs')
required=['compose.yaml','Dockerfile','tools/container_bootstrap.sh','tools/simulation_cli.py','tools/manage.py','cases/inputs_28.json','tests/expected_28.json']
for name in required:safe(name)
cases=json.loads((ROOT/'cases/inputs_28.json').read_text());assert len(cases)==28 and len({x['case_id'] for x in cases})==28
assert set(json.loads((ROOT/'tests/expected_28.json').read_text()))=={x['case_id'] for x in cases}
print(json.dumps({'public_hashes':'PASS','entries':len(files),'frozen_core_files':len(core['unchanged_files']),'runner_function_logic':'UNCHANGED','model_identity':'UNCHANGED','syntax':'PASS','network_Docker_ROS_calls':0}))
