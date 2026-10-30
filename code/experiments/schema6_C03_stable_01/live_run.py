"""Authorized simulation batch. Unchanged Qwen/schema6/C03 semantics; no reuse CLI."""
import argparse,copy,hashlib,json,math,os,signal,sys,time,traceback
from pathlib import Path
from unittest.mock import patch
EXP=Path(__file__).resolve().parent;CODE=EXP.parents[1];BASE=CODE.parent;OUT=BASE/'results'
sys.path[:0]=[str(EXP),str(EXP/'runtime/src')]
from io_guard import Writer,sha
from session_log import SessionLog
import sdf_guard
from persistent_rpc import Persistent,RPCError
import storage,mission,mission_adapter as adapter,executor,backend
from scene import frozen,metadata
from core import ARM,delta
PROTECTED=[CODE,Path('/workspace/pai_v3'),Path('/workspace/pai_v2'),Path('/workspace/pai_launcher'),Path('/workspace/PhysicalAI_V5_Integrated/minimal'),Path('/model-source')]
W=Writer(OUT,PROTECTED);ORIGINAL_FACTORY=executor.simulator;RPC=None;ACTIVE=None;STOP=False;SOURCE={};MODEL_DIGEST='357c53fb659c5076de1d65ccb0b397446227b71a42be9d1603d46168015c9e4b'
class CriticalSafety(RuntimeError):pass
def FACTORY():
 if RPC is None:raise CriticalSafety('Persistent read client not initialized')
 node=ORIGINAL_FACTORY()
 def live_scene():
  raw,receipt=RPC.acquire('SCENE');node.gz_raw=raw;node.gz_models={backend.one(x,'name'):x for x in backend.pbparse(raw).get('model',[])}
  if not node.gz_models:raise RPCError('Empty live Gazebo model set')
  return node.gz_models
 node.gazebo_scene=live_scene;return node
def progress(event,**data):print(json.dumps(dict(event=event,**data),ensure_ascii=False),flush=True)
def stopped():return STOP or (OUT/'STOP_REQUESTED').exists()
def signal_stop(signum,frame):
 global STOP
 STOP=True
 progress('STOP_SIGNAL',signal=signum)
def hashes_ok():
 pin=json.loads((BASE/'WORKER_PIN.json').read_text())
 if sha(BASE/'sdf_rpc_worker')!=pin['binary_sha256'] or sha(EXP/'sdf_rpc_worker.cpp')!=pin['source_sha256']:raise CriticalSafety('Owned worker binary/source mismatch')
 for name,h in SOURCE.items():
  if sha(CODE/name)!=h:raise CriticalSafety('Deployed source modified: '+name)
def resources():
 mem={x.split(':')[0]:int(x.split()[1])*1024 for x in Path('/proc/meminfo').read_text().splitlines() if x.startswith(('MemTotal:','MemAvailable:'))};disk=os.statvfs(OUT)
 if mem['MemAvailable']<750*1024**2 or disk.f_bavail*disk.f_frsize<2*1024**3:raise CriticalSafety('Insufficient available memory/disk')
 return dict(mem,disk_free_bytes=disk.f_bavail*disk.f_frsize,logical_cpus=os.cpu_count())
def check_model(full=False):
 import urllib.request
 with urllib.request.urlopen('http://127.0.0.1:11434/api/tags',timeout=3) as f:data=json.load(f)
 model=next((m for m in data['models'] if m['name']=='qwen2.5:3b'),None)
 if not model or model['digest']!=MODEL_DIGEST:raise CriticalSafety('Qwen model digest mismatch')
 if full:
  pin=json.loads((CODE/'MODEL_PIN.json').read_text());root=Path('/model-source/models');manifest=root/'manifests/registry.ollama.ai/library/qwen2.5/3b'
  if sha(manifest)!=pin['manifest_file_sha256']:raise CriticalSafety('Model manifest file hash mismatch')
  for blob in pin['blobs']:
   if sha(root/'blobs'/blob.replace(':','-'))!=blob.split(':')[1]:raise CriticalSafety('Model blob hash mismatch')
 return {k:model.get(k) for k in ['name','digest','size']}
_shell=backend.shell
def readonly_cli(argv,*a,**k):
 if argv[:3]==['ros2','node','list']:argv=argv+['--no-daemon']
 return _shell(argv,*a,**k)
backend.shell=readonly_cli
def pause_fallback(reason):
 global STOP
 STOP=True
 try:
  answer=_shell(['ign','service','-s','/world/default/control','--reqtype','ignition.msgs.WorldControl','--reptype','ignition.msgs.Boolean','--timeout','3000','--req','pause: true'])
  progress('EMERGENCY_GAZEBO_PAUSE',reason=reason,response=answer.strip());return 'data: true' in answer
 except Exception as exc:progress('EMERGENCY_PAUSE_FAILED',reason=str(exc));return False
def wait(node,future,timeout,check=None):
 import rclpy
 end=time.monotonic()+timeout
 while not future.done() and time.monotonic()<end:
  rclpy.spin_once(node,timeout_sec=.05)
  if check:check()
 if not future.done():raise TimeoutError('ROS future timed out')
 return future.result()
def hold(node,seconds=1.):
 import rclpy
 first=node.current();samples=[];end=time.monotonic()+seconds
 while time.monotonic()<end:
  rclpy.spin_once(node,timeout_sec=.05)
  if node.js is not None:samples.append({n:float(dict(zip(node.js.name,node.js.position))[n]) for n in ARM})
 last=node.current();error=max([delta(first,x) for x in samples+[last]] or [float('inf')])
 return {'first':first,'last':last,'max_drift_rad':error,'samples':len(samples),'PASS':len(samples)>=5 and error<=.003}
def cancel_hold(node,handle):
 answer=wait(node,handle.cancel_goal_async(),3);ids=[bytes(g.goal_id.uuid).hex() for g in answer.goals_canceling];wanted=bytes(handle.goal_id.uuid).hex();result=wait(node,handle.get_result_async(),5);held=hold(node)
 return {'return_code':int(answer.return_code),'goals_canceling':ids,'goal_uuid':wanted,'action_status':int(result.status),'hold':held,'PASS':int(answer.return_code)==0 and wanted in ids and int(result.status)==5 and held['PASS']}

class GoalGate:
 def __init__(self,log):self.log=log;self.sent=0;self.accepted=0;self.succeeded=0;self.authorized=False;self.failure=None;self.sdf=sdf_guard.Reader(W,log.root/'evidence',RPC)
 def execute(self,node,traj):
  global ACTIVE
  if not self.authorized or not self.log.active or self.log.failed or stopped():raise CriticalSafety('Goal gate closed')
  hashes_ok();index=self.sent+1;handle=None;finished=False
  try:
   # Commit the intent before touching ROS; a failed write cannot send a goal.
   W.json(self.log.root/f'evidence/goal_{index:02d}_intent.json',{'session_id':self.log.session_id,'joint_names':list(traj.joint_names),'points':len(traj.points),'trajectory':[{ 'positions':list(p.positions),'time_ns':p.time_from_start.sec*10**9+p.time_from_start.nanosec} for p in traj.points],'created_utc':storage.utc()})
   if not node.trajectory_client.wait_for_server(timeout_sec=5):raise CriticalSafety('Action server unavailable')
   from control_msgs.action import FollowJointTrajectory
   goal=FollowJointTrajectory.Goal();goal.trajectory=traj;self.sent+=1
   handle=wait(node,node.trajectory_client.send_goal_async(goal),10)
   if not handle or not handle.accepted:raise CriticalSafety('Trajectory rejected')
   self.accepted+=1;ACTIVE=(node,handle);uuid=bytes(handle.goal_id.uuid).hex();W.json(self.log.root/f'evidence/goal_{index:02d}_accepted.json',{'goal_uuid':uuid,'created_utc':storage.utc()});progress('ROS_GOAL_ACCEPTED',case=self.log.root.name,index=index,uuid=uuid)
   future=handle.get_result_async();lower={n:min(float(p.positions[list(traj.joint_names).index(n)]) for p in traj.points)-.04 for n in ARM};upper={n:max(float(p.positions[list(traj.joint_names).index(n)]) for p in traj.points)+.04 for n in ARM};last_controller=time.monotonic();last_count=0;last_feedback=time.monotonic()
   def observe():
    nonlocal last_controller,last_count,last_feedback
    if stopped() or self.log.failed:raise CriticalSafety('Stop requested/log failed during goal')
    now=time.monotonic()
    if len(node.feedback)>last_count:last_count=len(node.feedback);last_feedback=now
    if now-last_feedback>2:raise CriticalSafety('Joint feedback became stale')
    if node.js is not None:
     q=dict(zip(node.js.name,node.js.position))
     if any(n not in q or not math.isfinite(q[n]) or q[n]<lower[n] or q[n]>upper[n] for n in ARM):raise CriticalSafety('Measured motion left trajectory envelope')
    if now-last_controller>1:node.controllers();last_controller=time.monotonic()
   result=wait(node,future,65,observe);finished=True;ACTIVE=None
   out={'action_status':int(result.status),'controller_error_code':int(result.result.error_code),'message':result.result.error_string,'goal_uuid':uuid}
   W.json(self.log.root/f'evidence/goal_{index:02d}_result.json',out)
   if out['action_status']!=4 or out['controller_error_code']!=0:raise CriticalSafety('Controller failed '+str(out))
   self.succeeded+=1;return out
  except Exception as exc:
   self.failure=type(exc).__name__+': '+str(exc)
   if handle is not None and handle.accepted and not finished:
    try:
     canceled=cancel_hold(node,handle);progress('ERROR_CANCEL_HOLD',result=canceled)
     try:W.json(self.log.root/f'evidence/goal_{index:02d}_error_cancel.json',canceled)
     except Exception:pass
     if not canceled['PASS']:pause_fallback(self.failure)
    except Exception as cancel_error:pause_fallback(self.failure+'; '+str(cancel_error))
   elif handle is None and self.sent:pause_fallback('Uncertain goal acceptance: '+self.failure)
   raise
  finally:ACTIVE=None
 def factory(self):
  node=FACTORY();node.verify_static_geometry=self.sdf.verify;node.execute=lambda traj:self.execute(node,traj);return node

def current_state():
 import rclpy
 rclpy.init();node=None
 try:
  node=FACTORY();guard=node.guard();q=node.current();err=delta(q,frozen()['home_joint_rad'])
  if err>.05:raise CriticalSafety('Home unknown/outside initial tolerance')
  return {'guard':guard,'joint_rad':q,'Home_error_rad':err}
 finally:
  if node:node.destroy_node()
  rclpy.shutdown()

def stop_probe():
 """Fixed diagnostic only: explicit Phase B low-speed 0.02rad cancellation test."""
 import rclpy
 from control_msgs.action import FollowJointTrajectory
 from trajectory_msgs.msg import JointTrajectory,JointTrajectoryPoint
 log=SessionLog(W,'stop_probe');node=None;handle=None;result={};outcome='failed'
 try:
  rclpy.init();node=FACTORY();guard=node.guard();scene=frozen();node.confirm_scene(scene['targets']);node.confirm_gazebo(scene['targets']);q=node.current()
  if delta(q,scene['home_joint_rad'])>.05:raise CriticalSafety('Stop probe must start at Home')
  services=_shell(['ign','service','-l']).splitlines()
  if '/world/default/control' not in services:raise CriticalSafety('Independent Gazebo pause fallback missing')
  trajectory=JointTrajectory();trajectory.joint_names=list(ARM)
  for sec,offset in [(0,0.),(8,.02)]:
   point=JointTrajectoryPoint();point.positions=[q[n]+(offset if i==0 else 0.) for i,n in enumerate(ARM)];point.velocities=[0.]*len(ARM);point.accelerations=[0.]*len(ARM);point.time_from_start.sec=sec;trajectory.points.append(point)
  valid=node.validate_trajectory(trajectory);log.update(log.report_path,{'phase':'before_short_slow_stop_probe','guard':guard,'start':q,'joint1_offset_rad':.02,'duration_s':8,'collision_validation':valid,'independent_fallback':'Gazebo /world/default/control pause'})
  if not node.trajectory_client.wait_for_server(timeout_sec=5):raise CriticalSafety('Stop action unavailable')
  goal=FollowJointTrajectory.Goal();goal.trajectory=trajectory;handle=wait(node,node.trajectory_client.send_goal_async(goal),10)
  if not handle.accepted:raise CriticalSafety('Stop probe rejected')
  start=time.monotonic()
  while time.monotonic()-start<2:rclpy.spin_once(node,timeout_sec=.05)
  moving=node.current();depart=delta(q,moving);canceled=cancel_hold(node,handle);handle=None
  result={'guard':guard,'start':q,'before_cancel':moving,'observed_departure_rad':depart,'joint1_goal_offset_rad':.02,'duration_s':8,'cancel':canceled,'actual_diagnostic_goals':1,'no_return_goal_sent':True}
  if depart<.0002 or not canceled['PASS']:raise CriticalSafety('Cancel/hold not demonstrated')
  result['Home_error_rad']=delta(canceled['hold']['last'],scene['home_joint_rad'])
  if result['Home_error_rad']>.05:raise CriticalSafety('Post-cancel state outside allowed Home region')
  result['status']='PASS';log.update(log.report_path,result);outcome='PASS';progress('STOP_PROBE_PASS',departure=depart,hold_drift=canceled['hold']['max_drift_rad'],home_error=result['Home_error_rad'])
 except Exception:
  if handle is not None and handle.accepted:
   try:cancel_hold(node,handle)
   except Exception:pass
  pause_fallback('Stop probe failed');raise
 finally:
  if node:node.destroy_node()
  if rclpy.ok():rclpy.shutdown()
  log.seal(outcome)
 return result

def revalidate_stop_proof():
 import rclpy
 prior=json.loads((EXP/'REUSED_STOP_RESULT.json').read_text())
 if prior.get('status')!='PASS' or not prior['cancel']['PASS'] or prior['cancel']['action_status']!=5:raise CriticalSafety('Prior cancellation proof invalid')
 rclpy.init();node=None
 try:
  node=FACTORY();guard=node.guard();held=hold(node);error=delta(held['last'],frozen()['home_joint_rad'])
  cancel='/crane_plus_arm_controller/follow_joint_trajectory/_action/cancel_goal'
  if not held['PASS'] or error>.05 or not node.trajectory_client.wait_for_server(timeout_sec=5) or cancel not in [n for n,t in node.get_service_names_and_types()] or '/world/default/control' not in _shell(['ign','service','-l']).splitlines():raise CriticalSafety('Current stop/hold prerequisites differ')
  result={'status':'PASS','reused_stop_test_sha256':sha(EXP/'REUSED_STOP_RESULT.json'),'prior_cancel_goal_uuid':prior['cancel']['goal_uuid'],'current_guard':guard,'current_hold':held,'Home_error_rad':error,'actual_diagnostic_goals':0,'previous_measured_cancel_reused':True}
  progress('STOP_PROOF_REVALIDATED',Home_error_rad=error,new_goals=0);return result
 finally:
  if node:node.destroy_node()
  rclpy.shutdown()

def matched(decision,case):
 return all(decision.get(k,[])==case['expected_'+k] for k in ['visits','skipped','excluded']) and decision['status']==case['expected_status']
def meaning_scores(doc,case):
 expected_status=case.get('expected_model_status','ready' if case['expected_status'] in ['ready','no_valid_targets','error'] else case['expected_status']);expected=case.get('expected_raw_targets')
 scores=[]
 for c in doc['schema6_evidence']['calls']:
  try:
   p=mission.strict_json(c['raw_response']);n,_=adapter.c03.normalize_plan(p,doc['metadata']);target_ok=True if expected is None else [adapter.c03.independent.canonical(x) for x in n['targets']]==[adapter.c03.independent.canonical(x) for x in expected];scores.append(n['status']==expected_status and target_ok)
  except Exception:scores.append(False)
 return scores

def run_case(case):
 log=SessionLog(W,'cases/'+case['id']);gate=GoalGate(log);doc=None;report=None;decision=None;critical=None;outcome='error';handoffs=0;begin=time.monotonic()
 try:
  RPC.pre_ai=True;RPC.context=case['id'];hashes_ok();resources();check_model();progress('CASE_BEGIN',id=case['id'],instruction=case['instruction'])
  prepared=None
  def save(path,obj):
   nonlocal prepared
   if Path(path)==storage.ROOT/'results/prepared.json':
    if prepared is not None:raise CriticalSafety('Prepare attempted overwrite')
    prepared=copy.deepcopy(obj);W.json(log.root/'evidence/prepared.json',obj)
   elif Path(path)==log.report_path:log.update(path,obj)
   else:raise CriticalSafety('Unexpected executor output path')
  with adapter.live_session(log.session_id,simulation_authorized=True),patch.object(executor,'save',side_effect=save),patch.object(executor,'simulator',side_effect=gate.factory):
   executor.prepare()
   if not prepared:raise CriticalSafety('Candidate-specific prepare missing')
   def recorder(i,event,call):
    W.json(log.root/f'evidence/call_{i+1}_{event}.json',call);progress('QWEN_'+event.upper(),id=case['id'],call=i+1,seconds=call.get('wall_seconds'),error=call.get('error'))
   RPC.pre_ai=False
   doc=adapter.infer(case['instruction'],recorder=recorder);W.json(log.root/'evidence/mission.json',doc);decision=doc['decision'];progress('C03_DECISION',id=case['id'],status=decision['status'],visits=decision['visits'],reason=decision.get('reason_code',decision.get('reason')))
   if stopped():raise CriticalSafety('Stopped before handoff')
   if decision['status']=='ready':
    # Evaluation oracle can stop an unsafe candidate; never supplies/fixes a plan.
    if not matched(decision,case):raise CriticalSafety('AUDIT_FALSE_ALLOW: original expected contract differs; no ROS sent')
    handoffs+=1;gate.authorized=True;report=executor.execute(doc,log.report_path,log.root/'evidence/prepared.json');gate.authorized=False
    if not report.get('success'):raise CriticalSafety('ROS_EXECUTION_FAILURE: '+str(report.get('error')))
    if report['visited_order']!=decision['visits'] or gate.succeeded!=len(decision['visits'])+1:raise CriticalSafety('Physical order/goal count mismatch')
   else:
    adapter.validate(doc);report={'status':decision['status'],'commands_sent':0,'visited_order':[],'success':False,'decision':decision};log.update(log.report_path,report)
    if decision.get('reason_code')=='unexpected_error':raise CriticalSafety('Unexpected C03 internal exception')
   try:adapter.validate(doc)
   except ValueError:reuse_rejected=True
   else:raise CriticalSafety('Used plan accepted twice')
   after=current_state();W.json(log.root/'evidence/post_state.json',after)
   if decision['status']!='ready' and (gate.sent or handoffs):raise CriticalSafety('Nonready plan reached ROS')
   outcome='complete' if decision['status']=='ready' else 'nonexecution'
 except Exception as exc:
  gate.authorized=False;critical=type(exc).__name__+': '+str(exc);outcome='HOLD';progress('CRITICAL_STOP',id=case['id'],reason=critical)
  try:W.json(log.root/'evidence/exception.json',{'error':critical,'traceback':traceback.format_exc()})
  except Exception:pass
 finally:
  adapter.end_request();seal=log.seal(outcome)
 result={'id':case['id'],'case':case,'decision':decision,'raw_responses':[c['raw_response'] for c in doc['schema6_evidence']['calls']] if doc else [],'schema_checks':doc['c03_result']['call_checks'] if doc else [],'normalized_plans':doc['c03_result']['normalized_plans'] if doc else [],'Qwen_meaning_correct':meaning_scores(doc,case) if doc else [],'double_agreement':bool(doc and len(doc['c03_result']['normalized_plans'])==2 and [(p['status'],p['targets']) for p in doc['c03_result']['normalized_plans']][0]==[(p['status'],p['targets']) for p in doc['c03_result']['normalized_plans']][1]),'new_Qwen_calls':len(doc['schema6_evidence']['calls']) if doc else sum(1 for _ in (log.root/'evidence').glob('call_*_started.json')),'handoff_count':handoffs,'ROS_goals_sent':gate.sent,'ROS_goals_accepted':gate.accepted,'ROS_goals_succeeded':gate.succeeded,'execution':report,'reused_plan_rejected':bool(doc and not adapter.state()['active_ticket']),'critical':critical,'task':'PASS' if not critical and matched(decision,case) and (decision['status']!='ready' or report.get('success')) else 'FAIL','safety':'FAIL' if critical else 'PASS','wall_seconds':time.monotonic()-begin,'sealed':seal,'state_after':adapter.state()}
 W.json(log.root/'RESULT.json',result);progress('CASE_DONE',id=case['id'],task=result['task'],safety=result['safety'],goals=gate.sent,seconds=round(result['wall_seconds'],1));return result

def main():
 global SOURCE,RPC
 p=argparse.ArgumentParser();p.add_argument('--authorized-gazebo-batch',action='store_true');args=p.parse_args()
 if not args.authorized_gazebo_batch:raise RuntimeError('Explicit simulation authorization required')
 if os.environ.get('PAI_MINIMAL_SIM')!='1' or os.environ.get('ROS_DOMAIN_ID')!='42':raise RuntimeError('Expected simulation environment required')
 signal.signal(signal.SIGINT,signal_stop);signal.signal(signal.SIGTERM,signal_stop)
 OUT.mkdir(mode=0o700,exist_ok=False);W.json('RUN.lock',{'authorized_by_user':True,'resume_forbidden':True,'pid':os.getpid(),'created_utc':storage.utc()});SOURCE=json.loads((CODE/'SOURCE_MANIFEST.json').read_text());hashes_ok();cases=json.loads((EXP/'CASES.json').read_text());results=[];failure=None;stop=None
 try:
  RPC=Persistent(BASE/'sdf_rpc_worker',W,OUT/'transport')
  W.json('ENVIRONMENT.json',{'resources':resources(),'model':check_model(full=True),'initial':current_state(),'candidate_fingerprint':storage.fingerprint(),'source_manifest':SOURCE});progress('ENVIRONMENT_PASS')
  stop=revalidate_stop_proof();W.json('STOP_RESULT.json',stop)
  for case in cases:
   if stopped():raise CriticalSafety('External stop requested')
   result=run_case(case);results.append(result);hashes_ok()
   if result['critical']:raise CriticalSafety(result['critical'])
 except Exception as exc:
  failure=type(exc).__name__+': '+str(exc);progress('BATCH_HOLD',reason=failure)
  W.json('BATCH_EXCEPTION.json',{'error':failure,'traceback':traceback.format_exc()})
 finally:
  adapter.end_request()
  if RPC is not None:RPC.close()
  hashes_ok();summary={'status':'HOLD' if failure else 'COMPLETE','failure':failure,'stop_probe':stop,'completed':len(results),'planned':len(cases),'new_Qwen_calls':sum(x['new_Qwen_calls'] for x in results),'task_PASS':sum(x['task']=='PASS' for x in results),'task_FAIL':sum(x['task']=='FAIL' for x in results),'task_NOT_RUN':len(cases)-len(results),'task_ROS_goals_sent':sum(x['ROS_goals_sent'] for x in results),'diagnostic_ROS_goals_sent':stop.get('actual_diagnostic_goals',0) if stop else None,'results':results,'unrun':[c for c in cases if c['id'] not in [x['id'] for x in results]],'production_adopted':False};W.json('SUMMARY.json',summary)
  manifest={str(p.relative_to(OUT)):sha(p) for p in OUT.rglob('*') if p.is_file() and not p.is_symlink()};W.json('FINAL_MANIFEST.json',manifest);progress('BATCH_FINISHED',status=summary['status'],completed=len(results),task_PASS=summary['task_PASS'],task_FAIL=summary['task_FAIL'],new_Qwen_calls=summary['new_Qwen_calls'])
 return 1 if failure else 0
if __name__=='__main__':
 import runpy
 root=Path(os.environ.get('PAI_PUBLIC_ROOT',str(CODE.parent)))
 runpy.run_path(str(root/'tools/simulation_cli.py'),run_name='__main__')
