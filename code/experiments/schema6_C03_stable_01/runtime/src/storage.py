"""Immutable evidence and source fingerprints, separate from Fix2 results."""
import datetime,hashlib,json,os
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def utc():return datetime.datetime.now(datetime.timezone.utc).isoformat()
def digest(x):return hashlib.sha256(json.dumps(x,sort_keys=True,ensure_ascii=False,allow_nan=False).encode()).hexdigest()
def save(path,value):
 path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
 tmp=path.with_name(path.name+'.tmp');tmp.write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8');tmp.replace(path)
def strict_json(raw):
 def pairs(items):
  result={}
  for k,v in items:
   if k in result:raise ValueError('Duplicate JSON key: '+k)
   result[k]=v
  return result
 return json.loads(raw,object_pairs_hook=pairs)
def fingerprint():
 files=[]
 for name in ['src','config','docker','vendor']:
  files.extend(p for p in (ROOT/name).rglob('*') if p.is_file() and '__pycache__' not in p.parts)
 files.extend([ROOT/'host.py',ROOT/'command_inside.py',ROOT/'start_inspection.sh',ROOT/'stop_inspection.sh'])
 return digest({str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(files) if p.exists()})
