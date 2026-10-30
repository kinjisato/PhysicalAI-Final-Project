#!/usr/bin/env python3
"""Fetch the existing pinned robot dependency; no credentials or new model are used."""
import argparse,hashlib,io,json,tarfile,urllib.request
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
COMMIT='19c1d6069126cd27488bf1bbefd410704bfc515d'
p=argparse.ArgumentParser();p.add_argument('--output',type=Path,default=ROOT/'vendor/crane_plus_source.tar.gz');a=p.parse_args()
if a.output.exists():raise SystemExit('Preserve existing archive')
manifest=json.loads((ROOT/'vendor/source_manifest.json').read_text())
url='https://codeload.github.com/rt-net/crane_plus/tar.gz/'+COMMIT
with urllib.request.urlopen(url,timeout=60) as r:data=r.read()
found={}
with tarfile.open(fileobj=io.BytesIO(data),mode='r:gz') as source:
 for member in source:
  if not member.isfile() or '/' not in member.name:continue
  name=member.name.split('/',1)[1]
  if name in manifest:
   content=source.extractfile(member).read()
   if hashlib.sha256(content).hexdigest()!=manifest[name]['sha256']:raise SystemExit('Pinned source content mismatch')
   found[name]=content
if set(found)!=set(manifest):raise SystemExit('Pinned source file set mismatch')
a.output.parent.mkdir(parents=True,exist_ok=True)
with tarfile.open(a.output,'w:gz') as target:
 for name in sorted(found):
  entry=tarfile.TarInfo('crane_plus/'+name);entry.size=len(found[name]);entry.mode=manifest[name]['mode'];entry.mtime=0;entry.uid=entry.gid=0;entry.uname=entry.gname='';target.addfile(entry,io.BytesIO(found[name]))
print('Verified pinned dependency files:',len(found))
