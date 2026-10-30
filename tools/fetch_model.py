"""Fetch exact public registry blobs into a NEW ignored cache; no tag substitution.
Not invoked by build/up and not used when an existing read-only volume is selected.
"""
from pathlib import Path
import argparse,hashlib,json,urllib.request,os
ROOT=Path(__file__).resolve().parents[1]
def digest(p):
 h=hashlib.sha256()
 with p.open('rb') as f:
  for b in iter(lambda:f.read(1024*1024),b''):h.update(b)
 return h.hexdigest()
def main():
 p=argparse.ArgumentParser();p.add_argument('--accept-model-license',action='store_true');p.add_argument('--metadata-only',action='store_true',help='Fetch/verify small metadata only; never a complete model store');p.add_argument('--destination',type=Path,default=ROOT/'.cache/model-root/models');a=p.parse_args()
 if not a.accept_model_license:raise SystemExit('Read the Qwen2.5-3B license linked in docs/THIRD_PARTY_NOTICES.md, then pass --accept-model-license')
 dest=a.destination.resolve();forbidden=[Path.home()/'.ollama',Path('/model-source'),Path('/workspace')]
 if any(dest==x or x in dest.parents for x in forbidden):raise SystemExit('Refusing a protected/existing model store')
 pin=json.loads((ROOT/'code/MODEL_PIN.json').read_text());descriptor=ROOT/'docker/qwen_manifest.json'
 if digest(descriptor)!=pin['manifest_file_sha256']:raise SystemExit('Published wrapper manifest hash mismatch')
 dest.mkdir(parents=True,exist_ok=True);(dest/'blobs').mkdir(exist_ok=True)
 for name,info in pin['blobs'].items():
  if a.metadata_only and info['bytes']>1024*1024:continue
  h=name.split(':')[1];target=dest/'blobs'/name.replace(':','-')
  if target.exists():
   if digest(target)!=h or target.stat().st_size!=info['bytes']:raise SystemExit('Existing blob mismatch; do not overwrite')
   continue
  partial=target.with_suffix('.part')
  url='https://registry.ollama.ai/v2/library/qwen2.5/blobs/'+name
  request=urllib.request.Request(url,headers={'Accept':'application/vnd.docker.distribution.manifest.v2+json'})
  with urllib.request.urlopen(request,timeout=180) as src,partial.open('xb') as out:
   while True:
    block=src.read(1024*1024)
    if not block:break
    out.write(block)
  if digest(partial)!=h or partial.stat().st_size!=info['bytes']:raise SystemExit('Downloaded blob mismatch; preserve partial and stop')
  partial.rename(target)
 manifest=dest/'manifests/registry.ollama.ai/library/qwen2.5/3b';manifest.parent.mkdir(parents=True,exist_ok=True)
 if manifest.exists():
  if digest(manifest)!=pin['manifest_file_sha256']:raise SystemExit('Existing manifest mismatch; no overwrite')
 else:
  with manifest.open('xb') as f:f.write(descriptor.read_bytes())
 print(json.dumps({'model_store':str(dest),'status':'METADATA_ONLY_NOT_COMPLETE' if a.metadata_only else 'COMPLETE','blobs_verified':sum(not a.metadata_only or x['bytes']<=1024*1024 for x in pin['blobs'].values()),'manifest':'PASS','full_weight_fetch_verified':not a.metadata_only}))
if __name__=='__main__':main()
