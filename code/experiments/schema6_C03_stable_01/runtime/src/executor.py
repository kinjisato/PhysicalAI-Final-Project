"""Simulation-only executor using frozen MoveIt contracts; no language repair."""
import copy,json,math,os,sys,time,traceback
from pathlib import Path
from storage import ROOT,digest,fingerprint,save,utc
from scene import frozen,metadata
from mission_adapter import validate
from feedback import settled_current
# Exact baseline backend/core copies; original Fix2 folders are never imported/written.
sys.path.insert(0,str(ROOT/'vendor/fix2/v2/src'))
from core import ARM,delta,check_endpoint

def simulator():
 import rclpy
 from backend import Simulator
 class Measured(Simulator):
  def __init__(self):self.feedback=[];super().__init__()
  def on_js(self,msg):
   super().on_js(msg)
   if set(ARM).issubset(msg.name):self.feedback.append({'monotonic':time.monotonic(),'joint_rad':{n:float(dict(zip(msg.name,msg.position))[n]) for n in ARM}})
 return Measured()
def prepare():
 import rclpy
 scene=frozen();rclpy.init();node=None
 try:
  node=simulator();guard=node.guard();node.confirm_scene(scene['targets']);node.confirm_gazebo(scene['targets']);node.verify_static_geometry(scene['targets'])
  if node.world_from_base!=scene['world_from_base']:raise RuntimeError('World transform mismatch')
  q=node.current()
  if delta(q,scene['home_joint_rad'])>.05:raise RuntimeError('Prepare requires Home')
  doc={'schema':'pai-v3-prepared-1','source_sha256':fingerprint(),'metadata_sha256':digest(metadata()),'layout_sha256':scene['layout_sha256'],'guard':guard,'prepared_utc':utc()}
  save(ROOT/'results/prepared.json',doc);return doc
 finally:
  if node is not None:node.destroy_node()
  rclpy.shutdown()
def join_trajectories(first,second):
 # Preserve segment timing/zero boundary velocities; one repeated visit is one action.
 if list(first.joint_names)!=list(second.joint_names):raise RuntimeError('Cannot merge different joints')
 for boundary in (first.points[-1],second.points[0]):
  if len(boundary.velocities)!=len(first.joint_names) or any(not math.isfinite(v) or abs(v)>1e-6 for v in boundary.velocities):raise RuntimeError('Repeat Home boundary must be at rest')
 result=copy.deepcopy(first);offset=first.points[-1].time_from_start.sec*1000000000+first.points[-1].time_from_start.nanosec
 for point in second.points:
  t=point.time_from_start.sec*1000000000+point.time_from_start.nanosec
  if t==0:
   if max(abs(a-b) for a,b in zip(point.positions,first.points[-1].positions))>.004:raise RuntimeError('Discontinuous trajectory join')
   continue
  q=copy.deepcopy(point);q.time_from_start.sec=(t+offset)//1000000000;q.time_from_start.nanosec=(t+offset)%1000000000;result.points.append(q)
 return result
def plan_stage(node,start,goal,repeat,home,target):
 if repeat:
  one,mid,first=node.plan_segment(start,home);node.validate_trajectory(first)
  two,end,second=node.plan_segment(mid,goal);node.validate_trajectory(second)
  traj=join_trajectories(first,second);plan={'repeat':True,'via':'Home','retreat_plan':one,'return_plan':two}
 else:plan,end,traj=node.plan_segment(start,goal)
 validation=node.validate_trajectory(traj)
 if target is not None:check_endpoint(node.fk_pose(end),target)
 return plan,end,traj,validation
def check_prepared(path=None):
 doc=json.loads((Path(path) if path else ROOT/'results/prepared.json').read_text())
 if doc.get('source_sha256')!=fingerprint():raise RuntimeError('Source hash mismatch; prepare v3 again')
 if doc.get('metadata_sha256')!=digest(metadata()) or doc.get('layout_sha256')!=frozen()['layout_sha256']:raise RuntimeError('Prepared scene mismatch')
 return doc
def execute(doc,out,prepared_path=None,fault_after=None):
 report={'schema':'pai-v3-execution-1','success':False,'commands_sent':0,'visited_order':[],'stages':[],'started_utc':utc(),'source_sha256':fingerprint(),'mission_sha256':doc.get('sha256')};node=None
 try:
  decision=validate(doc);report['decision']=decision
  if decision['status']!='ready':report.update(safe_stop=True,status=decision['status'],reason=decision['reason']);return report
  check_prepared(prepared_path)
  if os.environ.get('PAI_MINIMAL_SIM')!='1':raise RuntimeError('Simulation-only environment required')
  if fault_after is not None and os.environ.get('PAI_V3_TESTING')!='1':raise RuntimeError('Fault injection disabled')
  import rclpy
  rclpy.init();node=simulator();report['guard']=node.guard();scene=frozen();targets=scene['targets'];home=scene['home_joint_rad'];sequence=decision['visits']
  if node.world_from_base!=scene['world_from_base']:raise RuntimeError('Scene transform differs')
  node.confirm_scene(targets);node.confirm_gazebo(targets);node.verify_static_geometry(targets);start=node.current()
  if delta(start,home)>.05:raise RuntimeError('Mission must start at Home')
  # Validate every requested stage before sending any command; no six-permutation planning.
  dry=[];current=start
  for i,label in enumerate(sequence+['Home']):
   repeat=i>0 and i<len(sequence) and sequence[i-1]==label
   plan,current,traj,valid=plan_stage(node,current,home if label=='Home' else targets[label]['goal_joint_rad'],repeat,home,None if label=='Home' else targets[label])
   dry.append({'target':label,'repeat':repeat,'plan':plan,'validation':valid})
  report['full_route_preflight']=dry;previous=start
  for i,label in enumerate(sequence+['Home']):
   if fault_after is not None and report['commands_sent']==fault_after:raise RuntimeError('INJECTED_ROS_FAILURE_AFTER_STAGE')
   node.confirm_scene(targets);node.confirm_gazebo(targets);node.controllers();before=node.current()
   if delta(before,previous)>.04:raise RuntimeError('Unexpected joint movement')
   repeat=i>0 and i<len(sequence) and sequence[i-1]==label
   goal=home if label=='Home' else targets[label]['goal_joint_rad']
   plan,end,traj,valid=plan_stage(node,before,goal,repeat,home,None if label=='Home' else targets[label])
   if delta(node.current(),before)>.025:raise RuntimeError('Robot moved during planning')
   stage={'target':label,'repeat':repeat,'plan':plan,'validation':valid,'started_utc':utc()};report['stages'].append(stage)
   node.feedback=[];report['commands_sent']+=1;save(out,report);stage['execution']=node.execute(traj);after,stage['settled_feedback']=settled_current(node)
   if delta(after,end)>.025:raise RuntimeError('Measured endpoint mismatch')
   stage['measured_joint_rad']=after;stage['feedback_samples']=node.feedback
   stage['observed_max_departure_rad']=max([delta(x['joint_rad'],before) for x in node.feedback] or [0.])
   if repeat and stage['observed_max_departure_rad']<.03:raise RuntimeError('Repeated visit did not physically depart and reapproach')
   measured=node.fk_pose(after);stage['gazebo_tool_sync']=node.gazebo_tool_pose(measured)
   if label!='Home':stage['face_check']=check_endpoint(measured,targets[label]);report['visited_order'].append(label)
   else:
    report['home_error_max_rad']=delta(after,home)
    if report['home_error_max_rad']>.025:raise RuntimeError('Home return mismatch')
   node.confirm_gazebo(targets);node.confirm_scene(targets);stage['completed_utc']=utc();previous=after;save(out,report)
   until=time.monotonic()+.5
   while time.monotonic()<until:rclpy.spin_once(node,timeout_sec=.05)
  if report['visited_order']!=sequence:raise RuntimeError('Actual visit order differs')
  report.update(success=True,home_return_success=True,status='complete')
 except Exception as e:
  report.update(error=str(e),traceback=traceback.format_exc(),safe_stop=report['commands_sent']==0,status='error',additional_commands_suppressed=True)
  if node is not None:
   try:
    first=node.current();time.sleep(.5);second=node.current();report['post_error_hold_joint_rad']=second;report['post_error_hold_delta_rad']=delta(first,second)
   except Exception as hold_error:report['hold_observation_error']=str(hold_error)
 finally:
  report['completed_utc']=utc();save(out,report)
  if node is not None:node.destroy_node();rclpy.shutdown()
 return report
def recover_home(out):
 import rclpy
 rclpy.init();node=None
 try:
  node=simulator();node.guard();scene=frozen();node.confirm_scene(scene['targets']);node.confirm_gazebo(scene['targets']);before=node.current();plan,end,traj,valid=plan_stage(node,before,scene['home_joint_rad'],False,scene['home_joint_rad'],None);execution=node.execute(traj);after,settled=settled_current(node)
  report={'recovery_only':True,'commands_sent':1,'execution':execution,'settled_feedback':settled,'home_error_max_rad':delta(after,scene['home_joint_rad']),'success':delta(after,scene['home_joint_rad'])<=.025,'created_utc':utc()};save(out,report);return report
 finally:
  if node is not None:node.destroy_node()
  rclpy.shutdown()
