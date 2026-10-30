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
    files=sorted((ROOT/'src').glob('*.py'))+[ROOT/'config/seeds.json']
    return digest({str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in files})


def plan_route(node, sequence, targets, home, start):
    current=start.copy();stages=[]
    for label in sequence+['Home']:
        goal=home if label=='Home' else targets[label]['goal_joint_rad']
        node.is_valid(goal)
        info,final,traj=node.plan_segment(current,goal)
        check=node.validate_trajectory(traj)
        if label!='Home':check_endpoint(node.fk_pose(final),targets[label])
        stages.append({'target':label,'start_joint_rad':current,'plan':info,'validation':check})
        current=final
    return stages


def prepare(node, report):
    from rclpy.serialization import serialize_message,deserialize_message
    from moveit_msgs.msg import PlanningScene
    seeds=json.loads((ROOT/'config/seeds.json').read_text())
    evidence=(ROOT/'evidence/v511_execution.json').read_bytes()
    old=json.loads(evidence)
    if hashlib.sha256(evidence).hexdigest()!=seeds['source_execution_sha256'] or old.get('success') is not True or old.get('commands_sent')!=7:
        raise RuntimeError('V5.11 seven-trajectory source proof missing/mismatched')
    home=seeds['home'];initial=node.current()
    if delta(initial,home)>.05:raise RuntimeError('Start is not near the recorded V5.11 Home')
    targets={}
    for label,s in seeds['targets'].items():
        fk=node.fk_pose(s['q'])  # Collision-check only in the proposed final scene, below.
        targets[label]=derive_target(label,fk,s['q'],s['source_stage'],s['factor'],s['gap_m'],s['size_m'],s['rgba'])
    check_layout(targets);report['targets']=targets;report['home_joint_rad']=home
    report['tcp_definition']=seeds['tcp']
    # Save the exact prior MoveIt scene; dry-run failure restores it before leaving.
    previous=node.scene_snapshot()
    backup=ROOT/'evidence/scene_before_prepare.cdr'
    if not backup.exists():backup.write_bytes(serialize_message(previous))
    gz_before=node.gazebo_scene()
    save(ROOT/'evidence/gazebo_models_before_prepare.json',{'models':list(gz_before)})
    (ROOT/'evidence/gazebo_scene_before_prepare.pbtxt').write_text(node.gz_raw)
    new_present={t['model'] for t in targets.values()}&set(gz_before)
    prior_path=ROOT/'results/layout_manifest.json'
    prior=json.loads(prior_path.read_text()) if prior_path.exists() else {}
    if not prior and new_present:
        # Recover a committed layout if preparation stopped during later evidence writing.
        progress=ROOT/'results/preflight_in_progress.json'
        prior=json.loads(progress.read_text()) if progress.exists() else {}
    if new_present:
        if not same_layout(targets,prior.get('targets',{})) or len(prior.get('routes',[]))!=6 or not all(r['success'] for r in prior['routes']):
            raise RuntimeError('Unrecognized existing final models; preserve them and stop')
        targets=prior['targets']  # Preserve the exact committed box poses; ignore floating-point FK roundoff.
        report['targets']=targets
    placed=False
    try:
        node.set_objects(targets,remove=OLD_MODELS)
        report['moveit_scene']=node.confirm_scene(targets);node.is_valid(initial)
        for seq in PERMUTATIONS:
            row={'order':seq,'success':False};report['routes'].append(row)
            try:
                print('PLAN '+''.join(seq),flush=True)
                row['stages']=plan_route(node,seq,targets,home,initial);row['success']=True
            except Exception as exc:
                row['error']=str(exc)
            save(ROOT/'results/preflight_in_progress.json',public(report))
        if not all(r['success'] for r in report['routes']):
            raise RuntimeError('At least one of six routes failed; no new Gazebo targets spawned')
        # Commit world changes only after ALL six complete routes passed MoveIt.
        report['removed_gazebo_models']=node.remove_old_gazebo()
        for t in targets.values():
            if t['model'] not in new_present:node.spawn(t)
        placed=True
        report['gazebo']=node.confirm_gazebo(targets)
        report['static_geometry']=node.verify_static_geometry(targets)
        report['moveit_scene']=node.confirm_scene(targets)
        report['gazebo_tool_sync']=node.gazebo_tool_pose(node.fk_pose(node.current()))
        report['layout_sha256']=digest(targets);report['source_code_sha256']=code_hash()
        report['world_from_base']=node.world_from_base
        report['success']=True
        save(ROOT/'results/layout_manifest.json',{'targets':targets,'routes':report['routes'],'layout_sha256':report['layout_sha256']})
    finally:
        if not placed:
            # Restore all original collision objects; original Gazebo entities remain untouched on planning failure.
            node.set_objects({},remove=[t['model'] for t in targets.values()]+['minimal_support_table'])
            previous.is_diff=True;previous.robot_state.is_diff=True
            from moveit_msgs.srv import ApplyPlanningScene
            if not node.call(node.apply,ApplyPlanningScene.Request(scene=previous)).success:
                raise RuntimeError('Failed to restore previous MoveIt scene')


def execute(node,report,ai_path):
    if os.environ.get('PAI_MINIMAL_SIM')!='1':raise RuntimeError('Use the simulation-only launcher (PAI_MINIMAL_SIM=1)')
    prep=json.loads((ROOT/'results/preflight.json').read_text())
    if not prep.get('success') or len(prep.get('routes',[]))!=6 or not all(r['success'] for r in prep['routes']):
        raise RuntimeError('Successful six-order preparation required')
    if prep.get('source_code_sha256')!=code_hash():raise RuntimeError('Source/config changed; run prepare again')
    report['source_code_sha256']=code_hash();report['layout_sha256']=prep['layout_sha256']
    targets=prep['targets'];home=prep['home_joint_rad']
    if prep['layout_sha256']!=digest(targets):raise RuntimeError('Layout integrity mismatch')
    ai_doc=json.loads(Path(ai_path).read_text());sequence=validate_evidence(ai_doc)
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
    for label in sequence+['Home']:
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
        stage={'target':label,'plan':plan,'validation':validation,'started_utc':utc()};report['stages'].append(stage)
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
        if delta(before,final)>.015 and stage['observed_motion_rad']<.005:raise RuntimeError('No measured arm movement')
        measured=node.fk_pose(after);stage['measured_pose_base']=measured
        stage['gazebo_tool_sync']=node.gazebo_tool_pose(measured)
        if label!='Home':
            stage['face_check']=check_endpoint(measured,targets[label]);report['visited_order'].append(label)
        else:
            report['home_error_max_rad']=delta(after,home)
            if report['home_error_max_rad']>.025:raise RuntimeError('Did not return Home')
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
    report['success']=True


def public(report):return {k:v for k,v in report.items() if not k.startswith('_')}


def main():
    p=argparse.ArgumentParser();g=p.add_mutually_exclusive_group(required=True)
    g.add_argument('--inspect',action='store_true');g.add_argument('--prepare',action='store_true');g.add_argument('--execute',action='store_true')
    p.add_argument('--ai-file');p.add_argument('--output');a=p.parse_args()
    phase='execute' if a.execute else 'prepare' if a.prepare else 'inspect'
    output=Path(a.output) if a.output else ROOT/'results'/('preflight.json' if a.prepare else phase+'.json')
    report={'schema':'minimal-sim-1','phase':phase,'started_utc':utc(),'success':False,'commands_sent':0,'simulation_only':True,'routes':[],'stages':[],'_path':output}
    node=None
    import rclpy
    from backend import Simulator
    try:
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
        if rclpy.ok():rclpy.shutdown()
    print(json.dumps({'phase':phase,'success':report['success'],'commands_sent':report['commands_sent'],'error':report.get('error'),'output':str(output)},ensure_ascii=False),flush=True)
    return 0 if report['success'] else 1


if __name__=='__main__':raise SystemExit(main())
