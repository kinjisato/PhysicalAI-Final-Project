"""Input-only orchestration. Semantic audit, goal gate and execution stay frozen."""
from pathlib import Path
import argparse,contextlib,json,os,re,signal,subprocess,sys,time,traceback,uuid
from unittest.mock import patch
PUBLIC=Path(os.environ.get('PAI_PUBLIC_ROOT',str(Path(__file__).resolve().parents[1])))
EXP=PUBLIC/'code/experiments/schema6_C03_stable_01'
OUTPUT=Path(os.environ.get('PAI_OUTPUT','/validation'))
RUNTIME=Path(os.environ.get('PAI_RUNTIME','/opt/pai_runtime'))

def validate_input(text,request_id):
 if type(text) is not str or not text.strip() or len(text)>2000 or '\x00' in text:raise ValueError('Instruction must contain 1..2000 characters, no NUL')
 if not re.fullmatch('[A-Za-z0-9_-]{1,40}',request_id):raise ValueError('Invalid request ID')
 return text

@contextlib.contextmanager
def exclusive_request(path):
 path=Path(path);fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
 with os.fdopen(fd,'w') as f:f.write(str(os.getpid()))
 try:yield
 finally:path.unlink()

def forbid_test_data_reads(root):
 # The model/audit/trajectory process has no permission to open test or case tables.
 denied=[(root/'tests').resolve(),(root/'cases').resolve()]
 def check(event,args):
  if event!='open' or not isinstance(args[0],(str,bytes,os.PathLike)):return
  p=Path(os.fsdecode(args[0])).resolve()
  if any(p==d or d in p.parents for d in denied):raise PermissionError('Test/case table forbidden in inference process')
 sys.addaudithook(check)

def original_runner():
 if os.environ.get('ROS_DOMAIN_ID')!='42' or os.environ.get('PAI_MINIMAL_SIM')!='1' or os.environ.get('ROS_LOCALHOST_ONLY')!='1':raise RuntimeError('Explicit isolated Gazebo-only environment required')
 sys.path.insert(0,str(EXP));import live_run as L
 L.BASE=RUNTIME;L.OUT=OUTPUT/'sessions'/uuid.uuid4().hex;L.OUT.mkdir(parents=True,mode=0o700,exist_ok=False)
 L.W=L.Writer(L.OUT,L.PROTECTED);L.SOURCE=json.loads((PUBLIC/'code/SOURCE_MANIFEST.json').read_text());L.hashes_ok()
 signal.signal(signal.SIGINT,L.signal_stop);signal.signal(signal.SIGTERM,L.signal_stop)
 return L

def check_model_wait(L):
 deadline=time.monotonic()+60
 while True:
  try:return L.check_model(full=True)
  except Exception as exc:
   if time.monotonic()>=deadline or 'digest mismatch' in str(exc) or 'hash mismatch' in str(exc):raise
   time.sleep(1)

def run(action,text=None,request_id='USER',authorized=False):
 if action=='run':
  validate_input(text,request_id)
  if not authorized:raise ValueError('Use --authorize-simulation-and-stop-test')
 # Child reads source bytes for integrity only; it does not infer or plan.
 subprocess.run([sys.executable,'-B',str(PUBLIC/'tools/verify_source.py')],check=True)
 with exclusive_request(RUNTIME/'REQUEST.lock'):
  forbid_test_data_reads(PUBLIC)
  L=original_runner();log=L.SessionLog(L.W,'cases/'+request_id);gate=None
  doc=None;report=None;failure=None;stop=None;diagnostic_started=False;outcome='HOLD';prepared=None;after=None;sealed=None
  try:
   L.RPC=L.Persistent(RUNTIME/'sdf_rpc_worker',L.W,L.OUT/'transport');gate=L.GoalGate(log)
   L.W.json('ENVIRONMENT.json',{'resources':L.resources(),'model':check_model_wait(L),'container':os.uname().nodename,'source_manifest':L.SOURCE,'test_tables_forbidden':True,'payload_fields':['id','text'],'action':action})
   def save(path,obj):
    nonlocal prepared
    if Path(path)==L.storage.ROOT/'results/prepared.json':
     if prepared is not None:raise L.CriticalSafety('Repeated prepare write')
     prepared=obj;L.W.json(log.root/'evidence/prepared.json',obj)
    elif Path(path)==log.report_path:log.update(path,obj)
    else:raise L.CriticalSafety('Unexpected executor output path')
   with L.adapter.live_session(log.session_id,simulation_authorized=True),patch.object(L.executor,'save',side_effect=save),patch.object(L.executor,'simulator',side_effect=gate.factory):
    L.executor.prepare()
    if prepared is None:raise L.CriticalSafety('Fresh prepare required')
    if action=='prepare':outcome='PREPARED'
    else:
     L.RPC.pre_ai=False;L.RPC.context=request_id
     def recorder(i,event,call):
      L.W.json(log.root/f'evidence/call_{i+1}_{event}.json',call);L.progress('QWEN_'+event.upper(),id=request_id,call=i+1,seconds=call.get('wall_seconds'),error=call.get('error'))
     L.progress('CASE_BEGIN',id=request_id,instruction=text)
     doc=L.adapter.infer(text,recorder=recorder);L.W.json(log.root/'evidence/mission.json',doc)
     decision=doc['decision'];L.progress('C03_DECISION',id=request_id,decision=decision)
     if L.stopped():raise L.CriticalSafety('Stopped before handoff')
     if decision['status']=='ready':
      # New measurement for this request, after C03 permission and before task handoff.
      diagnostic_started=True;stop=L.stop_probe();proofdir=L.OUT/'fresh_stop';proofdir.mkdir()
      L.W.json(proofdir/'REUSED_STOP_RESULT.json',stop)
      with patch.object(L,'EXP',proofdir):proof=L.revalidate_stop_proof()
      proof['previous_measured_cancel_reused']=False;proof['proof_origin']='fresh_this_request';L.W.json('CURRENT_STOP_PROOF.json',proof)
      gate.authorized=True
      report=L.executor.execute(doc,log.report_path,log.root/'evidence/prepared.json');gate.authorized=False
      if not report.get('success'):raise L.CriticalSafety('ROS_EXECUTION_FAILURE: '+str(report.get('error')))
      if report['visited_order']!=decision['visits'] or gate.succeeded!=len(decision['visits'])+1:raise L.CriticalSafety('Physical order/goal count mismatch')
      outcome='EXECUTED'
     else:
      L.adapter.validate(doc);report={'status':decision['status'],'commands_sent':0,'visited_order':[],'success':False,'decision':decision};log.update(log.report_path,report)
      if decision.get('reason_code')=='unexpected_error':raise L.CriticalSafety('Unexpected C03 internal exception')
      if gate.sent:raise L.CriticalSafety('Nonready request sent a task goal')
      outcome='NONREADY'
     try:L.adapter.validate(doc)
     except ValueError:pass
     else:raise L.CriticalSafety('Used plan accepted twice')
   after=L.current_state();L.W.json(log.root/'evidence/post_state.json',after)
   if L.ACTIVE is not None:raise L.CriticalSafety('Active goal remains')
  except Exception as exc:
   if gate is not None:gate.authorized=False
   failure=type(exc).__name__+': '+str(exc);outcome='HOLD'
   L.progress('CRITICAL_STOP',id=request_id,reason=failure)
   try:L.W.json(log.root/'evidence/exception.json',{'error':failure,'traceback':traceback.format_exc()})
   except Exception:pass
  finally:
   if gate is not None:gate.authorized=False
   L.adapter.end_request();sealed=log.seal(outcome)
   if L.RPC is not None:L.RPC.close()
   try:L.hashes_ok()
   except Exception as exc:failure=failure or str(exc);outcome='HOLD'
   result={'id':request_id,'instruction':text,'runtime_status':outcome,'decision':None if doc is None else doc['decision'],'new_Qwen_calls':len(doc['schema6_evidence']['calls']) if doc else len(list((log.root/'evidence').glob('call_*_started.json'))),'ROS_goals_sent':gate.sent if gate else 0,'ROS_goals_accepted':gate.accepted if gate else 0,'ROS_goals_succeeded':gate.succeeded if gate else 0,'diagnostic_goals':int(stop['actual_diagnostic_goals']) if stop else ('UNKNOWN' if diagnostic_started else 0),'execution':report,'critical':failure,'post_state':after,'state_after':L.adapter.state(),'sealed':sealed,'continue_allowed':failure is None and after is not None and L.ACTIVE is None,'evaluation_not_performed_here':True}
   L.W.json(log.root/'RESULT.json',result);summary={'action':action,'case_id':request_id,'instruction':text,'session_id':L.OUT.name,'result':result,'production_adopted':False};L.W.json('SESSION_SUMMARY.json',summary)
   L.progress('SESSION_END',session_output=str(L.OUT),id=request_id,status=outcome,goals=result['ROS_goals_sent'],diagnostic_goals=result['diagnostic_goals'],failure=failure)
  return 0 if failure is None else 3

def main(argv=None):
 p=argparse.ArgumentParser();p.add_argument('action',choices=['prepare','run']);p.add_argument('--id',default='USER');p.add_argument('--authorize-simulation-and-stop-test',action='store_true');a=p.parse_args(argv)
 if a.action=='prepare':return run('prepare',request_id='PREPARE')
 payload=json.loads(sys.stdin.read(16384))
 if set(payload)!={'id','text'} or payload['id']!=a.id:raise ValueError('Input-only payload required')
 return run('run',payload['text'],payload['id'],a.authorize_simulation_and_stop_test)
if __name__=='__main__':raise SystemExit(main())
