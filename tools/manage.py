#!/usr/bin/env python3
"""Independent local Docker lifecycle. No rm/prune/down, no old container control."""
from pathlib import Path
import argparse,json,os,shutil,subprocess,sys,time
ROOT=Path(__file__).resolve().parents[1]
RESERVE=2*1024**3

def command(argv,check=True,capture=True):
 p=subprocess.run(argv,capture_output=capture,text=True)
 if check and p.returncode:raise RuntimeError((p.stderr or '')[-2500:] or 'Command failed: '+str(argv[:4]))
 return p

def docker(*args,**kw):return command(['docker',*args],**kw)

def settings():
 name=os.environ.get('PAI_CONTAINER','pai_github_all_desktop_20261029');project=os.environ.get('PAI_PROJECT','pai_github_all_desktop_20261029')
 if not name.startswith('pai_github_all_') or not project.startswith('pai_github_all_'):raise RuntimeError('Use independent pai_github_all_ names only')
 output=Path(os.environ.get('PAI_VALIDATION',str(ROOT/'validation'/name))).expanduser().resolve()
 # Prevent a custom result directory from becoming an unlisted public source file.
 if not (output==ROOT/'validation' or ROOT/'validation' in output.parents) and (ROOT==output or ROOT in output.parents):
  raise RuntimeError('PAI_VALIDATION must be outside repository, or use default repository/validation')
 return name,project,output

def compose(extra=None):
 name,project,out=settings();env=os.environ.copy();env.update(PAI_CONTAINER=name,PAI_PROJECT=project,PAI_VALIDATION=str(out))
 args=['docker','compose','--project-directory',str(ROOT),'-p',project,'-f',str(ROOT/'compose.yaml')]
 if os.environ.get('PAI_MODEL_VOLUME'):args+=['-f',str(ROOT/'compose.model-volume.yaml')]
 if os.environ.get('PAI_GUI')=='1':args+=['-f',str(ROOT/'compose.gui.yaml')]
 return args+(extra or []),env

def local_daemon():
 ctx=json.loads(docker('context','inspect').stdout)[0];endpoint=ctx['Endpoints']['docker']['Host']
 if not endpoint.startswith(('unix://','npipe://')):raise RuntimeError('Remote Docker endpoint refused; do not transmit this context externally')
 return endpoint

def budget(phase):
 free=shutil.disk_usage(ROOT).free;increment=(1024 if phase=='build' else 512)*1024**2
 report={'phase':phase,'host_free_bytes':free,'estimated_increment_bytes':increment,'reserved_after_increment_bytes':RESERVE,'decision':'GO' if free>=RESERVE+increment else 'NOT_RUN_CAPACITY','basis':'shared pinned image layers; no model copy; 2GiB host reserve; bounded logs; actual host monitor'}
 print(json.dumps(report),flush=True)
 if report['decision']!='GO':raise RuntimeError('Insufficient incremental disk budget; no runtime action started')
 return report

def owned():
 name,_,out=settings();d=json.loads(docker('inspect',name).stdout)[0]
 if d['Name']!='/'+name or d['Config'].get('Labels',{}).get('pai.github.release')!='20261028':raise RuntimeError('Container identity/label mismatch')
 expected={'ROS_DOMAIN_ID':'42','ROS_LOCALHOST_ONLY':'1','PAI_MINIMAL_SIM':'1'};env=dict(x.split('=',1) for x in d['Config']['Env'] if '=' in x)
 if any(env.get(k)!=v for k,v in expected.items()):raise RuntimeError('Simulation/DDS isolation environment mismatch')
 if d['HostConfig']['NetworkMode']=='host':raise RuntimeError('Host networking forbidden')
 networks=list(d['NetworkSettings']['Networks'])
 if len(networks)!=1:raise RuntimeError('Exactly one isolated Docker bridge network required')
 net=json.loads(docker('network','inspect',networks[0]).stdout)[0]
 gui=True
 if net.get('Driver')!='bridge' or bool(net.get('Internal')):raise RuntimeError('Unexpected GUI/headless network isolation mode')
 published=d['HostConfig'].get('PortBindings') or {}
 if gui:
  web=published.get('80/tcp') or []
  expected_port=os.environ.get('PAI_WEB_PORT','6080')
  if len(web)!=1 or web[0].get('HostIp')!='127.0.0.1' or str(web[0].get('HostPort'))!=expected_port:raise RuntimeError('GUI noVNC not bound to requested loopback port')
  if any(k!='80/tcp' and v for k,v in published.items()):raise RuntimeError('Unexpected published port')
 elif any(published.values()):raise RuntimeError('Headless mode must not publish ports')
 expected_binds={
  '/opt/pai_release':ROOT,
  '/workspace/pai_v3':ROOT/'code/experiments/schema6_C03_stable_01/runtime',
  '/workspace/pai_v2':ROOT/'code/experiments/schema6_C03_stable_01/runtime/vendor/fix2/v2',
  '/workspace/pai_launcher':ROOT/'code/experiments/schema6_C03_stable_01/runtime/vendor/fix2/docker_run',
  '/workspace/PhysicalAI_V5_Integrated/minimal':ROOT/'code/experiments/schema6_C03_stable_01/runtime/vendor/fix2/environment/minimal',
  '/opt/pai_resources/fuel':ROOT/'.cache/fuel',
  '/validation':out,
  '/workspace/pai_v2/results':out/'baseline',
  '/workspace/PhysicalAI_V5_Integrated/minimal/results':out/'environment',
  '/model-source':ROOT/'.cache/model-root'
 }
 writable={'/validation','/workspace/pai_v2/results','/workspace/PhysicalAI_V5_Integrated/minimal/results'}
 for m in d['Mounts']:
  target=m['Destination']
  if target=='/model-source' and m['RW']:raise RuntimeError('Model must be read-only')
  if m['Type']=='bind':
   raw=m['Source'];raw=raw[len('/host_mnt'):] if raw.startswith('/host_mnt/') else raw
   src=Path(raw).resolve()
   if target not in expected_binds or src!=expected_binds[target].resolve():raise RuntimeError('Bind outside the explicit new-source/result contract: '+target)
   if bool(m['RW'])!=(target in writable):raise RuntimeError('Unexpected source/result mount mode')
  elif m['Type']=='volume':
   if target!='/model-source' or m.get('Name')!=os.environ.get('PAI_MODEL_VOLUME',''):raise RuntimeError('Unexpected shared volume')
  else:raise RuntimeError('Unexpected mount type')
 return d

def inside(args,capture=False):
 name,_,_=settings();owned()
 setup='source /opt/ros/humble/setup.bash; for p in /home/*/airobot_ws/install/setup.bash; do [[ ! -f "$p" ]] || source "$p"; done; source /opt/pai_ws/install/setup.bash; export ROS_DOMAIN_ID=42 ROS_LOCALHOST_ONLY=1 PAI_MINIMAL_SIM=1 RMW_IMPLEMENTATION=rmw_cyclonedds_cpp; exec "$@"'
 return command(['docker','exec',name,'/bin/bash','-lc',setup,'pai-public',*args],capture=capture)

def require_ready():
 name,_,_=settings();owned()
 probe=docker('exec',name,'python3','-B','/opt/pai_release/tools/readiness.py','read',check=False)
 if probe.returncode:
  raise RuntimeError('Container is not ready. Wait for up/start to finish before submitting a request')

def monitor(proc,action):
 name,_,out=settings();low=False
 while proc.poll() is None:
  if shutil.disk_usage(ROOT).free<RESERVE:
   low=True
   for p in (out/'sessions').glob('*'):
    if p.is_dir() and not (p/'SESSION_SUMMARY.json').exists():
     try:(p/'STOP_REQUESTED').write_text('Host disk reserve breached; cancel/hold, no automatic Home\n')
     except OSError:pass
   if action=='build':proc.terminate()
   else:
    # The original goal gate observes STOP_REQUESTED and cancels/holds first.
    deadline=time.monotonic()+12
    while proc.poll() is None and time.monotonic()<deadline:time.sleep(.2)
    if proc.poll() is None:owned();docker('stop','-t','15',name,check=False)
   break
  time.sleep(1)
 rc=proc.wait()
 if low:raise RuntimeError('Stopped at 2GiB host reserve; inspect current-session evidence, never auto-retry')
 return rc

def main(argv=None):
 p=argparse.ArgumentParser();p.add_argument('action',choices=['verify','fetch','build','up','start','prepare','run','cases','t02','reject','stop','logs','inspect','check']);p.add_argument('--text');p.add_argument('--request-id',default='USER');p.add_argument('--case');p.add_argument('--all',action='store_true');a=p.parse_args(argv)
 if a.action=='verify':return command([sys.executable,'-B',str(ROOT/'tools/verify_source.py')],capture=False).returncode
 if a.action=='fetch':return command([sys.executable,'-B',str(ROOT/'tools/fetch_dependencies.py')],capture=False).returncode
 if a.action in ['cases','t02']:
  local_daemon();require_ready()
  args=['--case',a.case or 'T02'] if a.action=='t02' or a.case else ['--all'] if a.all else []
  return command([sys.executable,'-B',str(ROOT/'tools/case_driver.py'),*args],capture=False).returncode
 if a.action=='reject':a.action='run';a.text='青を撮影して'
 if a.action=='run':
  from simulation_cli import validate_input
  validate_input(a.text,a.request_id)
 local_daemon();name,project,out=settings()
 if a.action=='build':
  budget('build');lock=json.loads((ROOT/'docker/dependencies.lock.json').read_text())
  for image in ['base_image','ollama_image']:docker('image','inspect',lock[image])
  command([sys.executable,'-B',str(ROOT/'tools/verify_source.py')],capture=False)
  proc=subprocess.Popen(['docker','build','--network=default','--pull=false','--platform','linux/amd64','-t',os.environ.get('PAI_IMAGE','pai-desktop:20261029'),str(ROOT)])
  return monitor(proc,'build')
 if a.action in ['up','start']:
  budget('up');command([sys.executable,'-B',str(ROOT/'tools/verify_source.py')],capture=False)
  exists=docker('inspect',name,check=False).returncode==0
  if exists and a.action=='up':raise RuntimeError('Existing container preserved. Use start for a stopped owned container, or a fresh PAI_CONTAINER/PAI_PROJECT')
  if exists:
   d=owned()
   if d['State']['Running']:raise RuntimeError('Container is already running; no restart performed')
  elif a.action!='up':raise RuntimeError('No existing container; use up')
  for sub in ['baseline','environment','sessions','bootstrap']:(out/sub).mkdir(parents=True,exist_ok=True)
  # Empty nested mountpoints are generated; Git need not track .gitkeep.
  for rel in ['code/experiments/schema6_C03_stable_01/runtime/vendor/fix2/v2/results','code/experiments/schema6_C03_stable_01/runtime/vendor/fix2/environment/minimal/results']:(ROOT/rel).mkdir(parents=True,exist_ok=True)
  args,env=compose(['up','-d','--no-build','--pull','never'])
  result=subprocess.run(['docker','start',name] if exists else args,env=env)
  if result.returncode:return result.returncode
  owned();deadline=time.monotonic()+300
  while time.monotonic()<deadline:
   if shutil.disk_usage(ROOT).free<RESERVE:docker('stop','-t','15',name);raise RuntimeError('Host reserve reached during startup; new container stopped')
   state=owned()
   if not state['State']['Running']:raise RuntimeError('New container exited during bootstrap; inspect logs/results')
   probe=docker('exec',name,'python3','/opt/pai_release/tools/readiness.py','read',check=False)
   if probe.returncode==0:print(probe.stdout);return 0
   time.sleep(2)
  owned();docker('stop','-t','15',name);raise RuntimeError('Readiness timeout; only the new container stopped')
 if a.action=='stop':owned();print(docker('stop','-t','20',name).stdout);return 0
 if a.action=='logs':owned();print(docker('logs','--tail','120',name).stdout);return 0
 if a.action in ['inspect','check']:
  d=owned();print(json.dumps({'container':name,'image':d['Image'],'state':d['State'],'network':'native MATE desktop, loopback HTTP port 80','ROS_LOCALHOST_ONLY':'1','model_RO':True},indent=2));return 0
 if a.action=='run':require_ready()
 budget(a.action)
 args=['python3','-B','/opt/pai_release/tools/simulation_cli.py',a.action]
 if a.action=='run':args+=['--id',a.request_id,'--authorize-simulation-and-stop-test']
 owned();setup='source /opt/ros/humble/setup.bash; for p in /home/*/airobot_ws/install/setup.bash; do [[ ! -f "$p" ]] || source "$p"; done; source /opt/pai_ws/install/setup.bash; export ROS_DOMAIN_ID=42 ROS_LOCALHOST_ONLY=1 PAI_MINIMAL_SIM=1 RMW_IMPLEMENTATION=rmw_cyclonedds_cpp; exec "$@"'
 proc=subprocess.Popen(['docker','exec','-i',name,'/bin/bash','-lc',setup,'pai-public',*args],stdin=subprocess.PIPE if a.action=='run' else subprocess.DEVNULL)
 if a.action=='run':proc.stdin.write(json.dumps({'id':a.request_id,'text':a.text},ensure_ascii=False).encode());proc.stdin.close()
 return monitor(proc,a.action)
if __name__=='__main__':
 try:raise SystemExit(main())
 except Exception as exc:print('Public workflow stopped: '+str(exc),file=sys.stderr);raise SystemExit(3)
