"""Fetch pinned public robot/Fuel inputs into ignored .cache only.
No weights, private logs, Docker operations or package installation.
"""
from pathlib import Path
import argparse,hashlib,io,json,subprocess,sys,urllib.request,zipfile
ROOT=Path(__file__).resolve().parents[1]
E=ROOT/'code/experiments/schema6_C03_stable_01'
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def main():
 p=argparse.ArgumentParser();p.add_argument('--fuel-only',action='store_true');a=p.parse_args()
 lock=json.loads((ROOT/'docker/dependencies.lock.json').read_text());pins=json.loads((ROOT/'docker/FUEL_PINS.json').read_text())['models'];cache=ROOT/'.cache';cache.mkdir(exist_ok=True)
 if not a.fuel_only:
  target=cache/'vendor/crane_plus_source.tar.gz';target.parent.mkdir(exist_ok=True)
  if not target.exists():subprocess.run([sys.executable,str(E/'runtime/vendor/fix2/environment/minimal/tools/fetch_vendor.py'),'--output',str(target)],check=True)
  # The build consumes only the 94 files whose content hashes match the pinned upstream manifest.
  import tarfile
  expected=json.loads((E/'runtime/vendor/fix2/environment/minimal/vendor/source_manifest.json').read_text());found={}
  with tarfile.open(target,'r:gz') as tar:
   for item in tar:
    if not item.isfile():continue
    name=item.name.split('/',1)[-1];data=tar.extractfile(item).read()
    if name not in expected or hashlib.sha256(data).hexdigest()!=expected[name]['sha256']:raise RuntimeError('Robot archive not exactly pinned')
    found[name]=True
  if set(found)!=set(expected):raise RuntimeError('Incomplete robot dependency')
 for model in lock['Fuel']:
  pin=pins[model['name']];dest=cache/'fuel'/pin['cache_relative'];expected=pin['files']
  if all((dest/n).is_file() and sha(dest/n) in {v['sha256'],v.get('formatting_variant',{}).get('sha256')} for n,v in expected.items()):continue
  with urllib.request.urlopen(model['url'],timeout=90) as response:data=response.read(32*1024*1024+1)
  if len(data)>32*1024*1024:raise RuntimeError('Fuel archive exceeds small-asset bound')
  with zipfile.ZipFile(io.BytesIO(data)) as archive:
   files={}
   for item in archive.infolist():
    if item.is_dir():continue
    path=Path(item.filename)
    if path.is_absolute() or '..' in path.parts:raise RuntimeError('Unsafe Fuel path')
    # Fuel archives may wrap files in one model-name directory.
    possibilities=[path.as_posix(),'/'.join(path.parts[1:])]
    name=next((n for n in possibilities if n in expected),None)
    if name is None:continue
    raw=archive.read(item)
    allowed={(expected[name]['sha256'],expected[name]['bytes'])}
    variant=expected[name].get('formatting_variant')
    if variant:allowed.add((variant['sha256'],variant['bytes']))
    if (hashlib.sha256(raw).hexdigest(),len(raw)) not in allowed:raise RuntimeError('Pinned Fuel file differs: '+model['name']+'/'+name)
    files[name]=raw
   if set(files)!=set(expected):raise RuntimeError('Fuel archive lacks pinned files: '+model['name'])
   for name,raw in files.items():
    out=dest/name;out.parent.mkdir(parents=True,exist_ok=True)
    if out.exists():
     if out.read_bytes()!=raw:raise RuntimeError('Do not overwrite mismatched Fuel cache')
    else:
     with out.open('xb') as f:f.write(raw)
 # Frozen world refers to the former Fuel hostname; alias verified assets without editing SDF.
 alias=cache/'fuel/fuel.ignitionrobotics.org'
 if not alias.exists():alias.symlink_to('fuel.gazebosim.org',target_is_directory=True)
 if not alias.is_symlink() or alias.readlink()!=Path('fuel.gazebosim.org'):raise RuntimeError('Unexpected Fuel hostname alias')
 print(json.dumps({'robot':'SKIPPED' if a.fuel_only else '94 pinned files verified','Fuel':'all pinned files verified','cache':'.cache (not published)'}))
if __name__=='__main__':main()
