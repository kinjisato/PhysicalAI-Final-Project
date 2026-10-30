"""Audited MoveIt service/action adapter derived from V5.11's V4/V5 adapters.
No legacy module imports, no IK/layout search, no gripper command publisher.
"""
import json
import math
import re
import subprocess
import time
import xml.etree.ElementTree as ET

import rclpy
from rclpy.action import ActionClient
from rclpy.node import Node
from sensor_msgs.msg import JointState
from rosgraph_msgs.msg import Clock
from control_msgs.action import FollowJointTrajectory
from geometry_msgs.msg import Pose
from moveit_msgs.msg import (CollisionObject, PlanningScene, PlanningSceneComponents,
                             RobotState, MotionPlanRequest, Constraints, JointConstraint, ObjectColor, AllowedCollisionEntry)
from moveit_msgs.srv import (ApplyPlanningScene, GetPlanningScene, GetPositionFK,
                             GetStateValidity, GetMotionPlan)
from controller_manager_msgs.srv import ListControllers
from rcl_interfaces.srv import GetParameters
from shape_msgs.msg import SolidPrimitive
from core import ARM, BASE, TIP, PREFIX, LIMITS, OLD_MODELS, delta, joints, ignition_messages


def shell(args, timeout=18):
    result = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
    if result.returncode:
        raise RuntimeError('Command failed '+str(args[:5])+': '+result.stderr[-500:])
    return result.stdout


def pbparse(s):
    """Read Ignition CLI protobuf text without importing nonportable msgs bindings."""
    tokens = re.findall(r'"(?:\\.|[^"\\])*"|[{}:]|[^\s{}:]+', s)
    def block(i):
        result = {}
        while i < len(tokens) and tokens[i] != '}':
            key=tokens[i]; i+=1
            if tokens[i] == '{': value,i=block(i+1)
            elif tokens[i] == ':':
                raw=tokens[i+1];i+=2
                if raw.startswith('"'): value=json.loads(raw)
                elif raw in ('true','false'): value=raw=='true'
                else:
                    try:value=float(raw)
                    except ValueError:value=raw
            else:raise ValueError('Unexpected protobuf token')
            result.setdefault(key,[]).append(value)
        return result,i+1
    return block(0)[0]


def one(obj, key, default=None):
    return obj.get(key,[default])[0]


def pbpose(obj):
    p=one(obj,'position',{}); q=one(obj,'orientation',{})
    return {'xyz':[one(p,k,0.) for k in ('x','y','z')],
            'quat_xyzw':[one(q,k,0. if k!='w' else 1.) for k in ('x','y','z','w')]}


def pose_msg(p):
    return {'xyz':[p.position.x,p.position.y,p.position.z],
            'quat_xyzw':[p.orientation.x,p.orientation.y,p.orientation.z,p.orientation.w]}


def make_pose(xyz, yaw=0.):
    p=Pose();p.position.x,p.position.y,p.position.z=map(float,xyz)
    p.orientation.z=math.sin(yaw/2);p.orientation.w=math.cos(yaw/2)
    return p


def rotate(q,v):
    x,y,z,w=q; vx,vy,vz=v
    return [(1-2*(y*y+z*z))*vx+2*(x*y-z*w)*vy+2*(x*z+y*w)*vz,
            2*(x*y+z*w)*vx+(1-2*(x*x+z*z))*vy+2*(y*z-x*w)*vz,
            2*(x*z-y*w)*vx+2*(y*z+x*w)*vy+(1-2*(x*x+y*y))*vz]


class Simulator(Node):
    def __init__(self):
        super().__init__('physical_ai_minimal')
        self.js=None;self.clock=None
        from core import ROOT
        self.tcp_offset=json.loads((ROOT/'config/seeds.json').read_text())['tcp']['offset_local_m']
        self.create_subscription(JointState,'/joint_states',self.on_js,10)
        self.create_subscription(Clock,'/clock',lambda x:setattr(self,'clock',x.clock),10)
        self.plan=self.create_client(GetMotionPlan,'/plan_kinematic_path')
        self.valid=self.create_client(GetStateValidity,'/check_state_validity')
        self.fk=self.create_client(GetPositionFK,'/compute_fk')
        self.scene=self.create_client(GetPlanningScene,'/get_planning_scene')
        self.apply=self.create_client(ApplyPlanningScene,'/apply_planning_scene')
        self.trajectory_client=ActionClient(self,FollowJointTrajectory,'/crane_plus_arm_controller/follow_joint_trajectory')

    def on_js(self,msg):
        if set(ARM).issubset(msg.name):self.js=msg

    def call(self,client,req,timeout=20):
        if not client.wait_for_service(timeout_sec=4):raise RuntimeError('Service unavailable '+client.srv_name)
        future=client.call_async(req);rclpy.spin_until_future_complete(self,future,timeout_sec=timeout)
        if not future.done() or future.result() is None:raise RuntimeError('Service failed/timed out '+client.srv_name)
        return future.result()

    def state(self,q):
        joints(q);s=RobotState();s.is_diff=False
        # Include passive gripper state in every collision query; it is never commanded.
        allq=dict(zip(self.js.name,self.js.position)) if self.js else {}
        allq.update(q);s.joint_state.name=list(allq);s.joint_state.position=[float(x) for x in allq.values()]
        return s

    def current(self,timeout=6):
        self.js=None;end=time.monotonic()+timeout
        while self.js is None and time.monotonic()<end:rclpy.spin_once(self,timeout_sec=.1)
        if self.js is None:raise RuntimeError('No fresh joint states')
        return joints({n:float(dict(zip(self.js.name,self.js.position))[n]) for n in ARM})

    def controllers(self):
        c=self.create_client(ListControllers,'/controller_manager/list_controllers')
        try:status={x.name:x.state for x in self.call(c,ListControllers.Request()).controller}
        finally:self.destroy_client(c)
        if any(status.get(x)!='active' for x in ('joint_state_broadcaster','crane_plus_arm_controller')):
            raise RuntimeError('Simulation controllers inactive: '+str(status))
        return status

    def guard(self):
        nodes=shell(['ros2','node','list']).splitlines()
        if '/gz_ros2_control' not in nodes or '/move_group' not in nodes:
            raise RuntimeError('Gazebo and MoveIt nodes required')
        for name in ('move_group',):
            c=self.create_client(GetParameters,'/'+name+'/get_parameters')
            try:r=self.call(c,GetParameters.Request(names=['use_sim_time']))
            finally:self.destroy_client(c)
            if not r.values or not r.values[0].bool_value:raise RuntimeError(name+' use_sim_time must be true')
        self.current();self.controllers()
        self.clock=None;end=time.monotonic()+5
        first=None
        while time.monotonic()<end:
            rclpy.spin_once(self,timeout_sec=.1)
            if self.clock:
                t=self.clock.sec+self.clock.nanosec/1e9
                if first is None:first=t
                elif t>first:break
        else:raise RuntimeError('Simulation clock is not advancing')
        description=shell(['ros2','param','get','/robot_state_publisher','robot_description'])
        xml=description[description.index('<robot'):]
        # Comments may precede <robot>; the required control plugin is in the XML.
        root=ET.fromstring(xml)
        plugin=root.find('./ros2_control/hardware/plugin')
        if plugin is None or plugin.text!='ign_ros2_control/IgnitionSystem':
            raise RuntimeError('Only IgnitionSystem simulation hardware is supported')
        for joint in ('base_link_to_world_joint','crane_plus_joint_base'):
            j=root.find("./joint[@name='"+joint+"']")
            if j is None or j.get('type')!='fixed':raise RuntimeError('Unexpected base chain')
            origin=j.find('origin')
            if origin is not None and any(abs(float(v))>1e-8 for k in ('xyz','rpy') for v in origin.get(k,'0 0 0').split()):
                raise RuntimeError('Nonidentity model-root to base unsupported')
        self.world='default'
        self.gazebo_scene()
        models=self.gz_models
        if 'crane_plus' not in models:raise RuntimeError('Gazebo robot missing')
        self.world_from_base=pbpose(one(models['crane_plus'],'pose',{}))
        q=self.world_from_base['quat_xyzw']
        if sum(abs(x) for x in q[:3])>1e-5:raise RuntimeError('Rotated robot root unsupported; no guessed transform')
        return {'hardware_plugin':plugin.text,'world_from_base':self.world_from_base,'controllers':self.controllers()}

    def fk_pose(self,q):
        req=GetPositionFK.Request();req.header.frame_id=BASE;req.fk_link_names=[TIP,'crane_plus_link_hand'];req.robot_state=self.state(q)
        r=self.call(self.fk,req)
        if r.error_code.val!=1 or len(r.pose_stamped)!=2:raise RuntimeError('MoveIt FK failed')
        reference=pose_msg(r.pose_stamped[0].pose);hand=pose_msg(r.pose_stamped[1].pose)
        offset=rotate(hand['quat_xyzw'],self.tcp_offset)
        return {'xyz':[a+b for a,b in zip(hand['xyz'],offset)],'quat_xyzw':hand['quat_xyzw'],
                'reference_link4':reference,'reference_hand':hand,'tcp_offset_hand_m':self.tcp_offset}

    def is_valid(self,q):
        req=GetStateValidity.Request();req.group_name='arm';req.robot_state=self.state(q)
        r=self.call(self.valid,req)
        if not r.valid:raise RuntimeError('MoveIt collision/invalid state: '+str([(x.contact_body_1,x.contact_body_2) for x in r.contacts[:5]]))
        return True

    def plan_segment(self,start,target):
        req=MotionPlanRequest();req.group_name='arm';req.start_state=self.state(start)
        req.allowed_planning_time=7.;req.num_planning_attempts=4
        req.max_velocity_scaling_factor=.10;req.max_acceleration_scaling_factor=.10
        c=Constraints()
        for n in ARM:
            j=JointConstraint();j.joint_name=n;j.position=float(target[n]);j.tolerance_above=.002;j.tolerance_below=.002;j.weight=1.;c.joint_constraints.append(j)
        req.goal_constraints=[c]
        r=self.call(self.plan,GetMotionPlan.Request(motion_plan_request=req)).motion_plan_response
        traj=r.trajectory.joint_trajectory
        if r.error_code.val!=1 or len(traj.points)<2:raise RuntimeError('MoveIt planning failure code='+str(r.error_code.val))
        names=list(traj.joint_names)
        if set(names)!=set(ARM):raise RuntimeError('Unexpected trajectory joints')
        final={n:float(traj.points[-1].positions[names.index(n)]) for n in ARM}
        if delta(final,target)>.004:raise RuntimeError('Planned endpoint does not match goal')
        report={'code':int(r.error_code.val),'points':len(traj.points),'planning_time_s':r.planning_time,'end_joint_rad':final}
        return report,final,traj

    def validate_trajectory(self,traj):
        names=list(traj.joint_names);last_t=-1.;previous=None;count=0
        for p in traj.points:
            t=p.time_from_start.sec+p.time_from_start.nanosec/1e9
            if t<=last_t:raise RuntimeError('Nonmonotonic trajectory')
            last_t=t;q={n:float(p.positions[names.index(n)]) for n in ARM};self.is_valid(q);count+=1
            if previous is not None:
                subdivisions=max(1,math.ceil(delta(q,previous)/.015))
                for i in range(1,subdivisions):
                    self.is_valid({n:previous[n]+(q[n]-previous[n])*i/subdivisions for n in ARM});count+=1
            previous=q
        if not 0 < last_t < 55:raise RuntimeError('Trajectory duration exceeds action budget')
        return {'collision_states_checked':count,'points':len(traj.points),'duration_s':last_t,'max_interpolation_step_rad':.015}

    def execute(self,traj):
        if not self.trajectory_client.wait_for_server(timeout_sec=5):raise RuntimeError('Arm action unavailable')
        g=FollowJointTrajectory.Goal();g.trajectory=traj
        f=self.trajectory_client.send_goal_async(g);rclpy.spin_until_future_complete(self,f,timeout_sec=10)
        if not f.done() or not f.result() or not f.result().accepted:raise RuntimeError('Trajectory rejected')
        h=f.result();f=h.get_result_async();rclpy.spin_until_future_complete(self,f,timeout_sec=65)
        if not f.done():
            cancel=h.cancel_goal_async();rclpy.spin_until_future_complete(self,cancel,timeout_sec=3)
            raise RuntimeError('Trajectory timeout, cancellation requested')
        r=f.result();out={'action_status':int(r.status),'controller_error_code':int(r.result.error_code),'message':r.result.error_string}
        if out['action_status']!=4 or out['controller_error_code']!=0:raise RuntimeError('Controller failed '+str(out))
        return out

    def scene_snapshot(self):
        req=GetPlanningScene.Request();req.components.components=PlanningSceneComponents.WORLD_OBJECT_GEOMETRY | PlanningSceneComponents.OBJECT_COLORS | PlanningSceneComponents.ALLOWED_COLLISION_MATRIX
        return self.call(self.scene,req).scene

    def set_objects(self,targets,remove=()):
        scene=PlanningScene();scene.is_diff=True;scene.robot_state.is_diff=True
        current_ids={ob.id for ob in self.scene_snapshot().world.collision_objects}
        for name in remove:
            if name not in current_ids:continue
            ob=CollisionObject();ob.id=name;ob.header.frame_id=BASE;ob.operation=CollisionObject.REMOVE;scene.world.collision_objects.append(ob)
        for target in targets.values():
            ob=CollisionObject();ob.id=target['model'];ob.header.frame_id=BASE;ob.operation=CollisionObject.ADD
            prim=SolidPrimitive();prim.type=SolidPrimitive.BOX;prim.dimensions=target['size_m']
            ob.primitives=[prim];ob.primitive_poses=[make_pose(target['center_base_m'],target['yaw_rad'])]
            scene.world.collision_objects.append(ob)
            color=ObjectColor();color.id=ob.id;color.color.r,color.color.g,color.color.b,color.color.a=map(float,target['rgba']);scene.object_colors.append(color)
        if targets:
            # Physical table: cached Table model has a 1.5 x 0.8 x 0.03 m top at z=1.0.
            # Validate its live visual geometry rather than assuming a clear floor.
            self.gazebo_scene();table=self.gz_models['Table']
            visual=next(v for link in table['link'] for v in link['visual'] if one(v,'name')=='visual1')
            size=one(one(one(visual,'geometry',{}),'box',{}),'size',{})
            sz=[one(size,k,0.) for k in ('x','y','z')]
            if max(abs(a-b) for a,b in zip(sz,[1.5,.8,.03]))>1e-5:raise RuntimeError('Unsupported table shape')
            rootpose=pbpose(one(table,'pose',{}));vpose=pbpose(one(visual,'pose',{}))
            center=[a+b-c for a,b,c in zip(rootpose['xyz'],vpose['xyz'],self.world_from_base['xyz'])]
            yaw=2*math.atan2(rootpose['quat_xyzw'][2],rootpose['quat_xyzw'][3])
            ob=CollisionObject();ob.id='minimal_support_table';ob.header.frame_id=BASE;ob.operation=CollisionObject.ADD
            prim=SolidPrimitive();prim.type=SolidPrimitive.BOX;prim.dimensions=sz
            ob.primitives=[prim];ob.primitive_poses=[make_pose(center,yaw)];scene.world.collision_objects.append(ob)
            color=ObjectColor();color.id=ob.id;color.color.r=.45;color.color.g=.48;color.color.b=.52;color.color.a=1.;scene.object_colors.append(color)
            acm=self.scene_snapshot().allowed_collision_matrix
            for name in ('minimal_support_table','crane_plus_base'):
                if name not in acm.entry_names:
                    acm.entry_names.append(name)
                    for row in acm.entry_values:row.enabled.append(False)
                    row=AllowedCollisionEntry();row.enabled=[False]*len(acm.entry_names);acm.entry_values.append(row)
            a=acm.entry_names.index('minimal_support_table');b=acm.entry_names.index('crane_plus_base')
            acm.entry_values[a].enabled[b]=True;acm.entry_values[b].enabled[a]=True
            scene.allowed_collision_matrix=acm
        if not self.call(self.apply,ApplyPlanningScene.Request(scene=scene)).success:raise RuntimeError('Scene apply rejected')

    def confirm_scene(self,targets):
        scene=self.scene_snapshot();found={o.id:o for o in scene.world.collision_objects}
        if set(found)&set(OLD_MODELS):raise RuntimeError('Legacy objects remain in MoveIt')
        if {k for k in found if k.startswith(PREFIX)} != {t['model'] for t in targets.values()}:raise RuntimeError('Unexpected final collision object membership')
        out={}
        for t in targets.values():
            ob=found[t['model']]
            if ob.header.frame_id not in (BASE,'world','base_link'):raise RuntimeError('Unknown planning scene frame')
            if len(ob.primitives)!=1 or len(ob.primitive_poses)!=1:raise RuntimeError('Unexpected shape')
            if max(abs(x-y) for x,y in zip(ob.primitives[0].dimensions,t['size_m']))>1e-6:raise RuntimeError('Scene dimensions mismatch')
            outer=pose_msg(ob.pose);inner=pose_msg(ob.primitive_poses[0]);v=rotate(outer['quat_xyzw'],inner['xyz'])
            xyz=[x+y for x,y in zip(outer['xyz'],v)]
            if math.dist(xyz,t['center_base_m'])>1e-5:raise RuntimeError('Scene position mismatch')
            # Multiply the normalized outer/inner yaw rotations (all target rotations are Z-only).
            a=outer['quat_xyzw'];b=inner['quat_xyzw']
            actual_yaw=2*math.atan2(a[3]*b[2]+a[2]*b[3],a[3]*b[3]-a[2]*b[2])
            if abs(math.atan2(math.sin(actual_yaw-t['yaw_rad']),math.cos(actual_yaw-t['yaw_rad'])))>1e-5:raise RuntimeError('Scene rotation mismatch')
            out[t['label']]={'center_base_m':xyz,'size_m':list(ob.primitives[0].dimensions),'yaw_rad':actual_yaw}
        return out

    def gazebo_scene(self):
        for attempt in range(3):
            s=shell(['ign','service','-s','/world/default/scene/info','--reqtype','ignition.msgs.Empty','--reptype','ignition.msgs.Scene','--timeout','8000','--req',''])
            self.gz_raw=s;self.gz_models={one(x,'name'):x for x in pbparse(s).get('model',[])}
            if self.gz_models:return self.gz_models
            print('Gazebo scene response empty; read-only retry '+str(attempt+1),flush=True)
        raise RuntimeError('No Gazebo models after 3 read-only attempts')

    def gz_service(self,op,request):
        reqtype='ignition.msgs.EntityFactory' if op=='create' else 'ignition.msgs.Entity'
        out=shell(['ign','service','-s','/world/default/'+op,'--reqtype',reqtype,'--reptype','ignition.msgs.Boolean','--timeout','8000','--req',request])
        if 'data: true' not in out:raise RuntimeError('Gazebo '+op+' rejected')

    def remove_old_gazebo(self):
        models=self.gazebo_scene();removed=[]
        for name in OLD_MODELS:
            if name in models:
                self.gz_service('remove','id: '+str(int(one(models[name],'id')))+', type: MODEL');removed.append(name)
        self.gazebo_scene()
        if set(OLD_MODELS)&set(self.gz_models):raise RuntimeError('Old Gazebo models remain')
        return removed

    def spawn(self,t):
        name=t['model'];size=' '.join(map(str,t['size_m']));rgba=' '.join(map(str,t['rgba']))
        xml=f'''<sdf version="1.6"><model name="{name}"><static>true</static><link name="body"><collision name="collision"><geometry><box><size>{size}</size></box></geometry></collision><visual name="visual"><geometry><box><size>{size}</size></box></geometry><material><ambient>{rgba}</ambient><diffuse>{rgba}</diffuse></material></visual></link></model></sdf>'''
        xyz=[x+y for x,y in zip(t['center_base_m'],self.world_from_base['xyz'])];p=make_pose(xyz,t['yaw_rad'])
        request='sdf: '+json.dumps(xml)+', name: '+json.dumps(name)+f', allow_renaming: false, pose: {{position: {{x: {xyz[0]}, y: {xyz[1]}, z: {xyz[2]}}}, orientation: {{z: {p.orientation.z}, w: {p.orientation.w}}}}}'
        self.gz_service('create',request)

    def confirm_gazebo(self,targets):
        models=self.gazebo_scene()
        expected={'ground_plane','Table','crane_plus'}|{t['model'] for t in targets.values()}
        if set(models)!=expected:raise RuntimeError('Unexpected Gazebo model membership '+str(sorted(set(models)^expected)))
        robot=pbpose(one(models['crane_plus'],'pose',{}))
        if math.dist(robot['xyz'],self.world_from_base['xyz'])>1e-5:raise RuntimeError('Robot base moved')
        out={}
        for t in targets.values():
            model=models[t['model']];p=pbpose(one(model,'pose',{}));xyz=[x-y for x,y in zip(p['xyz'],self.world_from_base['xyz'])]
            yaw=t['yaw_rad'];q=[0,0,math.sin(yaw/2),math.cos(yaw/2)]
            if math.dist(xyz,t['center_base_m'])>1e-5 or abs(sum(a*b for a,b in zip(q,p['quat_xyzw'])))<1-1e-8:raise RuntimeError('Gazebo pose mismatch '+t['label'])
            links=model.get('link',[])
            if len(links)!=1:raise RuntimeError('Unexpected Gazebo links')
            visuals=links[0].get('visual',[])
            if len(visuals)!=1:raise RuntimeError('Unexpected visuals')
            visual=visuals[0];box=one(one(visual,'geometry',{}),'box',{});sz=one(box,'size',{})
            actual=[one(sz,k,0) for k in ('x','y','z')]
            if max(abs(a-b) for a,b in zip(actual,t['size_m']))>1e-6:raise RuntimeError('Gazebo visual dimensions mismatch')
            mat=one(visual,'material',{});color=one(mat,'diffuse',{});rgba=[one(color,k,0.) for k in ('r','g','b','a')]
            if max(abs(a-b) for a,b in zip(rgba,t['rgba']))>1e-4:raise RuntimeError('Gazebo color mismatch '+t['label'])
            out[t['label']]={'center_world_m':p['xyz'],'center_base_m':xyz,'rgba':rgba,'size_m':actual}
        return out

    def verify_static_geometry(self,targets):
        import ast
        raw=shell(['ign','service','-s','/world/default/generate_world_sdf','--reqtype','ignition.msgs.SdfGeneratorConfig','--reptype','ignition.msgs.StringMsg','--timeout','8000','--req',''])
        encoded=raw[raw.index('"'):].strip();xml=ast.literal_eval(encoded)
        out={}
        for t in targets.values():
            # Gazebo exports the robot include as file://<urdf-string>, an invalid URI/XML placeholder.
            # Parse only each independently well-formed target model, leaving robot data untouched.
            match=re.search(r"<model name=['\"]"+re.escape(t['model'])+r"['\"]>.*?</model>",xml,re.S)
            m=ET.fromstring(match.group(0)) if match else None
            if m is None or m.findtext('static')!='true':raise RuntimeError('Target is not STATIC '+t['model'])
            collision=m.find('./link/collision/geometry/box/size')
            sizes=[float(x) for x in collision.text.split()] if collision is not None else []
            if len(sizes)!=3 or max(abs(a-b) for a,b in zip(sizes,t['size_m']))>1e-6:raise RuntimeError('Gazebo collision box mismatch')
            out[t['label']]={'static':True,'collision_size_m':sizes}
        return out

    def gazebo_tool_pose(self,expected):
        raw=shell(['ign','topic','-e','-n','1','-t','/world/default/pose/info','--json-output'])
        messages=ignition_messages(raw);msg=messages[-1];found={p.get('name'):p for p in msg['pose'] if p.get('name') in ('crane_plus_link4','crane_plus_link_hand')}
        if len(found)!=2:raise RuntimeError('Unique Gazebo link4 and hand poses required')
        def convert(p):return {'xyz':[p.get('position',{}).get(k,0.) for k in ('x','y','z')], 'quat_xyzw':[p.get('orientation',{}).get(k,1. if k=='w' else 0.) for k in ('x','y','z','w')]}
        link=convert(found['crane_plus_link4']);hand=convert(found['crane_plus_link_hand'])
        offset=rotate(hand['quat_xyzw'],self.tcp_offset);xyz=[a+b for a,b in zip(hand['xyz'],offset)]
        error=math.dist(xyz,expected['xyz']);link_error=math.dist(link['xyz'],expected['reference_link4']['xyz'])
        if max(error,link_error)>.005:raise RuntimeError('Gazebo actual tool and MoveIt FK disagree')
        return {'xyz_base_m':xyz,'xyz_world_m':[x+y for x,y in zip(xyz,self.world_from_base['xyz'])],
                'fk_error_m':error,'link4_fk_error_m':link_error,'messages_received':len(messages),'gazebo_stamp':msg.get('header',{}).get('stamp')}
