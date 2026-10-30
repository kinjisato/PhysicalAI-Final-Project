#!/usr/bin/env python3
"""Prepare all six MoveIt routes, then execute the selected real AI order in Gazebo."""
import argparse
import datetime
import hashlib
import json
import os
import time
import traceback
from pathlib import Path

from core import ROOT, ARM, OLD_MODELS, PREFIX, PERMUTATIONS, check_layout, check_endpoint, delta, derive_target, digest, save, same_layout
from ai import validate_evidence


def utc():return datetime.datetime.now(datetime.timezone.utc).isoformat()


def code_hash():
    files=sorted((ROOT/'src').glob('*.py'))+sorted((ROOT/'config').glob('*.json'))
    return digest({str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in files})


def visit_stages(sequence):
    """Consecutive repeated visits require a real retreat and a fresh approach."""
    stages=[]
    for i,label in enumerate(sequence):
        if i and sequence[i-1]==label:stages.append({'target':'Home','role':'retreat','visit_index':None})
        stages.append({'target':label,'role':'visit','visit_index':i+1})
    stages.append({'target':'Home','role':'home','visit_index':None})
    return stages


def plan_route(node, sequence, targets, home, start):
    current=start.copy();stages=[]
    for descriptor in visit_stages(sequence):
        label=descriptor['target'];goal=home if label=='Home' else targets[label]['goal_joint_rad']
        node.is_valid(goal)
        info,final,traj=node.plan_segment(current,goal)
        check=node.validate_trajectory(traj)
        if label!='Home':
            check_endpoint(node.fk_pose(final),targets[label])
            if delta(current,final)<.005:raise RuntimeError('Visit would not physically approach the target')
        stages.append({**descriptor,'start_joint_rad':current,'plan':info,'validation':check})
        current=final
    return stages


def prepare(node, report):
    # V2 preparation is READ ONLY: never add/remove/relocate a world or collision object.
    frozen=json.loads((ROOT/'config/frozen_scene.json').read_text())
    targets=frozen['targets'];home=frozen['home_joint_rad']
    if digest(targets)!=frozen['layout_sha256']:raise RuntimeError('Frozen layout checksum mismatch')
    check_layout(targets)
    if node.world_from_base!=frozen['world_from_base']:raise RuntimeError('Gazebo base transform changed')
    initial=node.current()
    if delta(initial,home)>.05:raise RuntimeError('Start must be near the preserved Home')
    report['targets']=targets;report['home_joint_rad']=home
    report['world_from_base']=node.world_from_base;report['layout_sha256']=digest(targets)
    report['moveit_scene']=node.confirm_scene(targets);report['gazebo']=node.confirm_gazebo(targets)
    report['static_geometry']=node.verify_static_geometry(targets)
    report['gazebo_tool_sync']=node.gazebo_tool_pose(node.fk_pose(initial))
    for label,target in targets.items():check_endpoint(node.fk_pose(target['goal_joint_rad']),target)
    # Requested-route planning is performed during execute; skip all six permutations.
    report['routes'] = []
    report['source_code_sha256']=code_hash();report['success']=True


def execute(node,report,ai_path):
    if os.environ.get('PAI_MINIMAL_SIM')!='1':raise RuntimeError('Use the simulation-only launcher (PAI_MINIMAL_SIM=1)')
    prep=json.loads((ROOT/'results/preflight.json').read_text())
    if not prep.get('success'):
        raise RuntimeError('Successful scene preparation required')
    if prep.get('source_code_sha256')!=code_hash():raise RuntimeError('Source/config changed; run prepare again')
    report['source_code_sha256']=code_hash();report['layout_sha256']=prep['layout_sha256']
    targets=prep['targets'];home=prep['home_joint_rad']
    if prep['layout_sha256']!=digest(targets):raise RuntimeError('Layout integrity mismatch')
    ai_doc=json.loads(Path(ai_path).read_text());decision=validate_evidence(ai_doc)
    if decision['status']!='ready':raise RuntimeError('Non-ready AI decision cannot move')
    sequence=decision['execution_order']
    report['ai']=ai_doc;report['requested_order']=sequence.copy();report['visited_order']=[]
    if node.world_from_base!=prep['world_from_base']:raise RuntimeError('Gazebo base transform changed')
    node.confirm_scene(targets);report['initial_gazebo']=node.confirm_gazebo(targets)
    report['static_geometry']=node.verify_static_geometry(targets)
    before=node.current()
    if delta(before,home)>.05:raise RuntimeError('Robot must start near Home')
    report['initial_joint_rad']=before
    # Revalidate the whole requested contiguous route immediately before motion.
    report['full_route_preflight']=plan_route(node,sequence,targets,home,before)
    previous=before
    for descriptor in visit_stages(sequence):
        label=descriptor['target']
        report['active_target']=label
        save(ROOT/'results/status.json',{'time_utc':utc(),'instruction':ai_doc['instruction'],'order':sequence,'target':label,'phase':'moving','visited':report['visited_order']})
        node.confirm_scene(targets);node.confirm_gazebo(targets);node.controllers()
        before=node.current()
        if delta(before,previous)>.04:raise RuntimeError('Unexpected joint movement')
        goal=home if label=='Home' else targets[label]['goal_joint_rad']
        plan,final,traj=node.plan_segment(before,goal);validation=node.validate_trajectory(traj)
        if label!='Home':check_endpoint(node.fk_pose(final),targets[label])
        node.confirm_scene(targets);node.confirm_gazebo(targets)
        if delta(node.current(),before)>.025:raise RuntimeError('Robot moved during planning')
        stage={**descriptor,'plan':plan,'validation':validation,'started_utc':utc()};report['stages'].append(stage)
        print('EXECUTE '+label+' order='+''.join(sequence),flush=True)
        report['commands_sent']+=1;save(report['_path'],public(report))
        stage['execution']=node.execute(traj)
        # Allow fresh feedback after settling; no extra control command.
        deadline=time.monotonic()+.4
        while time.monotonic()<deadline:
            import rclpy
            rclpy.spin_once(node,timeout_sec=.05)
        after=node.current();stage['measured_joint_rad']=after
        stage['endpoint_error_rad']=delta(after,final)
        stage['observed_motion_rad']=delta(after,before)
        if stage['endpoint_error_rad']>.025:raise RuntimeError('Measured joint endpoint mismatch')
        if label!='Home' and stage['observed_motion_rad']<.005:raise RuntimeError('No measured arm movement')
        measured=node.fk_pose(after);stage['measured_pose_base']=measured
        stage['gazebo_tool_sync']=node.gazebo_tool_pose(measured)
        if label!='Home':
            stage['face_check']=check_endpoint(measured,targets[label]);report['visited_order'].append(label)
        else:
            stage['home_error_max_rad']=delta(after,home)
            if descriptor['role']=='home':report['home_error_max_rad']=stage['home_error_max_rad']
            if stage['home_error_max_rad']>.025:raise RuntimeError('Did not return Home')
        stage['gazebo']=node.confirm_gazebo(targets);node.confirm_scene(targets)
        stage['completed_utc']=utc();previous=after
        save(report['_path'],public(report))
        save(ROOT/'results/status.json',{'time_utc':utc(),'instruction':ai_doc['instruction'],'order':sequence,'target':label,'phase':'reached','visited':report['visited_order']})
        # Short noncontact dwell for the visible demonstration.
        deadline=time.monotonic()+1.
        while time.monotonic()<deadline:
            import rclpy
            rclpy.spin_once(node,timeout_sec=.1)
    if report['visited_order']!=sequence:raise RuntimeError('AI/actual order mismatch')
    report['visit_count']=len(report['visited_order'])
    report['final_gazebo']=node.confirm_gazebo(targets)
    report['home_return_success']=True
    report['success']=True


def public(report):return {k:v for k,v in report.items() if not k.startswith('_')}


def main():
    p=argparse.ArgumentParser();g=p.add_mutually_exclusive_group(required=True)
    g.add_argument('--inspect',action='store_true');g.add_argument('--prepare',action='store_true');g.add_argument('--execute',action='store_true')
    p.add_argument('--ai-file');p.add_argument('--output');a=p.parse_args()
    phase='execute' if a.execute else 'prepare' if a.prepare else 'inspect'
    output=Path(a.output) if a.output else ROOT/'results'/('preflight.json' if a.prepare else phase+'.json')
    report={'schema':'physical-ai-v2-sim-1','phase':phase,'started_utc':utc(),'success':False,'commands_sent':0,'simulation_only':True,'routes':[],'stages':[],'_path':output}
    # Reject non-ready or corrupt AI evidence before importing ROS or creating any controller clients.
    if a.execute:
        try:
            if not a.ai_file:raise ValueError('--ai-file required; no fallback order')
            ai_doc=json.loads(Path(a.ai_file).read_text());decision=validate_evidence(ai_doc)
            report['ai']=ai_doc;report['decision']=decision
            if decision['status']!='ready':
                report.update(safe_stop=True,status=decision['status'],reason=decision['reason'],completed_utc=utc())
                save(output,public(report));print(json.dumps(public(report),ensure_ascii=False));return 2
        except Exception as exc:
            report.update(safe_stop=True,status='error',error=str(exc),completed_utc=utc())
            save(output,public(report));print(str(exc));return 2
    node=None
    try:
        import rclpy
        from backend import Simulator
        rclpy.init();node=Simulator();report['guard']=node.guard()
        if a.inspect:
            report['current_joint_rad']=node.current();report['fk_pose']=node.fk_pose(report['current_joint_rad'])
            report['gazebo_tool_sync']=node.gazebo_tool_pose(report['fk_pose']);report['models']=list(node.gazebo_scene());report['success']=True
        elif a.prepare:prepare(node,report)
        else:
            if not a.ai_file:raise RuntimeError('--ai-file required; no default order')
            execute(node,report,a.ai_file)
    except Exception as exc:
        report['error']=str(exc);report['traceback']=traceback.format_exc();print(report['traceback'],flush=True)
    finally:
        report['completed_utc']=utc();save(output,public(report))
        if node is not None:node.destroy_node()
        if 'rclpy' in locals() and rclpy.ok():rclpy.shutdown()
    print(json.dumps({'phase':phase,'success':report['success'],'commands_sent':report['commands_sent'],'error':report.get('error'),'output':str(output)},ensure_ascii=False),flush=True)
    return 0 if report['success'] else 1


if __name__=='__main__':raise SystemExit(main())
