"""Explicitly loaded runner-only I/O guard. No ambient preserve import or output."""
import hashlib,json,os
from pathlib import Path
class OutputRejected(ValueError):pass

def sha(path):
 h=hashlib.sha256()
 with Path(path).open('rb') as f:
  for b in iter(lambda:f.read(8*1024*1024),b''):h.update(b)
 return h.hexdigest()
def overlap(a,b):return a==b or a in b.parents or b in a.parents

class Writer:
 def __init__(self,root,protected):
  self.root=Path(root).resolve();self.protected=tuple(Path(p).resolve() for p in protected)
  if any(overlap(self.root,p) for p in self.protected):raise OutputRejected('Output root overlaps protected data')
 def path(self,path):
  p=Path(path);p=(p if p.is_absolute() else self.root/p).resolve()
  if p==self.root or self.root not in p.parents or any(p==q or q in p.parents for q in self.protected):raise OutputRejected('Write outside new output root or inside protected data: '+str(p))
  return p
 def bytes(self,path,data):
  p=self.path(path);p.parent.mkdir(parents=True,exist_ok=True);p=self.path(p)
  fd=os.open(p,os.O_WRONLY|os.O_CREAT|os.O_EXCL|getattr(os,'O_NOFOLLOW',0),0o600)
  with os.fdopen(fd,'wb') as f:f.write(data)
 def json(self,path,obj):self.bytes(path,(json.dumps(obj,ensure_ascii=False,indent=2,allow_nan=False)+'\n').encode())
 def text(self,path,value):self.bytes(path,value.encode())
 def new_case(self,path):
  p=self.path(path)
  if p.exists():raise OutputRejected('Existing case directory cannot be reused')
  p.parent.mkdir(parents=True,exist_ok=True);return p

class AssetAudit:
 def __init__(self,root,experiment):
  self.root=Path(root).resolve();self.exp=Path(experiment).resolve();g=json.loads((self.root/'results/G0.json').read_text());self.source=Path(g['source_root']);self.g0=g
  self.protected=[self.source,self.root/'inputs',self.root/'src',self.root/'tools',self.root/'tests',self.root/'heldout',self.root/'results',self.exp/'runtime',Path.home()/'.ollama/models']
  self.protected.extend(p for p in (self.root/'experiments').iterdir() if p.is_dir() and p.resolve()!=self.exp)
  files=set()
  for p in self.protected:
   if p==self.source or p==Path.home()/'.ollama/models':continue
   files.update(x.resolve() for x in p.rglob('*') if x.is_file() and not x.is_symlink() and '__pycache__' not in x.parts and '.git' not in x.parts)
  snap=json.loads((self.source.parent/'fix2_baselines/fix2_20261025/snapshot_manifest.json').read_text());self.required={self.source/k:v['sha256'] for k,v in snap.items()}
  self.required.update({self.root/k:v for k,v in g['input_hashes'].items()})
  vendor=json.loads((self.source/'v3/vendor/fix2_manifest.json').read_text());self.required.update({self.source/'v3/vendor/fix2'/k:v for k,v in vendor.items()})
  vr=self.source/'v3';runtime=[]
  for name in ['src','config','docker','vendor']:runtime.extend(p for p in (vr/name).rglob('*') if p.is_file() and '__pycache__' not in p.parts)
  runtime.extend(vr/n for n in ['host.py','command_inside.py','start_inspection.sh','stop_inspection.sh']);self.runtime_files=sorted(p for p in runtime if p.exists());files.update(self.runtime_files)
  model=json.loads((self.root/'results/G0_model.json').read_text());mroot=Path.home()/'.ollama/models';self.required[mroot/'manifests/registry.ollama.ai/library/qwen2.5/3b']=model['manifest_file_sha256']
  self.required.update({mroot/'blobs'/k.replace(':','-'):k.split(':')[1] for k in model['blobs']});files.update(self.required);self.files=sorted(files)
 def capture(self):
  values={str(p):sha(p) for p in self.files};bad=[str(p) for p,h in self.required.items() if values[str(p)]!=h]
  vr=self.source/'v3';runtime={str(p.relative_to(vr)):values[str(p)] for p in self.runtime_files};runtime_sha=hashlib.sha256(json.dumps(runtime,sort_keys=True,ensure_ascii=False,allow_nan=False).encode()).hexdigest()
  if runtime_sha!=self.g0['protected_runtime_sha256']:bad.append('official schema6 fingerprint')
  if bad:raise RuntimeError('Protected initial hash mismatch: '+str(bad))
  return {'status':'PASS','hashes':values,'official_schema6_sha256':runtime_sha,'files':len(values),'module_path':str(Path(__file__).resolve())}
 def verify(self,before):
  current=self.capture();bad=[p for p,h in before['hashes'].items() if current['hashes'].get(p)!=h]
  if bad:raise RuntimeError('Protected file changed: '+str(bad))
  return {'status':'PASS','verified_files':len(current['hashes']),'official_schema6_sha256':current['official_schema6_sha256'],'module_path':str(Path(__file__).resolve())}
