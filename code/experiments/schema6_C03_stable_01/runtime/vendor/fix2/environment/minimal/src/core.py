"""Pure contracts for the submission; metres in crane_plus_base unless stated."""
import hashlib
import itertools
import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ARM = ['crane_plus_joint1', 'crane_plus_joint2', 'crane_plus_joint3', 'crane_plus_joint4']
LIMITS = [(-2.61799, 2.61799), (-1.82474, 1.78372), (-2.55655, 2.45427), (-1.84009, 1.76836)]
TIP = 'crane_plus_link_endtip'
BASE = 'crane_plus_base'
PREFIX = 'pai_minimal_'
OLD_MODELS = ['wood_cube_5cm', 'pai_v5_site_right', 'pai_v5_site_center', 'pai_v5_site_left']
PERMUTATIONS = [list(p) for p in itertools.permutations('ABC')]


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False).encode()).hexdigest()


def save(path, value):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + '.tmp')
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf8')
    tmp.replace(path)


def joints(q):
    if not isinstance(q, dict) or set(q) != set(ARM):
        raise ValueError('Arm joint set must be exact')
    for n, (lo, hi) in zip(ARM, LIMITS):
        if isinstance(q[n], bool) or not isinstance(q[n], (float, int)) or not math.isfinite(q[n]) or not lo + .02 < q[n] < hi - .02:
            raise ValueError('Invalid joint or limit margin: ' + n)
    return q


def order(value):
    if not isinstance(value, list) or len(value) != 3 or set(value) != set('ABC'):
        raise ValueError('Order must visit A, B, C exactly once; ambiguous instructions stop')
    return value


def delta(a, b):
    return max(abs(a[n] - b[n]) for n in ARM)


def derive_target(label, fk, q, source, factor, gap, size, color):
    """Place a box OUTWARD from a verified FK endpoint. Its inward face is the target."""
    joints(q)
    x, y, z = fk['xyz']; r = math.hypot(x, y)
    if r < .02 or not .03 <= gap <= .05:
        raise ValueError('Invalid radial face / noncontact gap')
    u = [x / r, y / r]
    center = [x + u[0] * (gap + size[0] / 2), y + u[1] * (gap + size[0] / 2), z]
    return {'label': label, 'model': PREFIX + label, 'source_stage': source,
            'interpolation_from_home': factor, 'goal_joint_rad': q,
            'goal_pose_base': fk, 'center_base_m': center, 'yaw_rad': math.atan2(y, x),
            'size_m': size, 'rgba': color, 'standoff_m': gap,
            'horizontal_distance_m': math.hypot(*center[:2])}


def check_layout(targets):
    a, b, c = (targets[k] for k in 'ABC')
    if not a['center_base_m'][1] < b['center_base_m'][1] < c['center_base_m'][1]:
        raise ValueError('Right / center / left separation failed (+Y is left)')
    if not a['horizontal_distance_m'] + .015 < b['horizontal_distance_m'] or not b['horizontal_distance_m'] + .015 < c['horizontal_distance_m']:
        raise ValueError('Near / middle / far separation below 15 mm')
    if not a['center_base_m'][2] + .015 < c['center_base_m'][2] < b['center_base_m'][2] - .015:
        raise ValueError('Low / middle / high separation below 15 mm')
    return True


def face_error(xyz, target):
    """Inward face clearance and offset from its centre, expressed in box axes."""
    c = target['center_base_m']; yaw = target['yaw_rad']
    dx, dy = xyz[0] - c[0], xyz[1] - c[1]
    local_x = math.cos(yaw) * dx + math.sin(yaw) * dy
    local_y = -math.sin(yaw) * dx + math.cos(yaw) * dy
    return {'gap_m': -local_x - target['size_m'][0] / 2,
            'face_center_offset_m': math.hypot(local_y, xyz[2] - c[2])}


def check_endpoint(pose, target):
    e = face_error(pose['xyz'], target)
    if not .03 <= e['gap_m'] <= .05 or e['face_center_offset_m'] > .005:
        raise RuntimeError('Measured approach outside 30-50 mm gap / 5 mm centre tolerance: ' + str(e))
    # The full 4-DOF-derived orientation is retained, not an infeasible arbitrary 6D pose.
    qa, qb = pose['quat_xyzw'], target['goal_pose_base']['quat_xyzw']
    angle = 2 * math.acos(min(1., abs(sum(x*y for x,y in zip(qa,qb)))))
    if angle > .08:
        raise RuntimeError('Measured tool orientation differs by >0.08 rad')
    e['orientation_error_rad'] = angle
    return e


def ignition_messages(raw):
    """Ignition CLI may emit multiple callbacks despite --num=1. Parse complete messages."""
    decoder=json.JSONDecoder();messages=[];remaining=raw.lstrip()
    while remaining:
        message,end=decoder.raw_decode(remaining)
        if not isinstance(message,dict) or 'pose' not in message:raise ValueError('Unexpected Ignition pose message')
        messages.append(message);remaining=remaining[end:].lstrip()
    if not messages:raise ValueError('No Ignition pose messages')
    return messages


def same_layout(a,b):
    if set(a)!=set(b):return False
    for k,t in a.items():
        old=b[k]
        if any(t[f]!=old[f] for f in ('model','goal_joint_rad','size_m','rgba','standoff_m')):return False
        if math.dist(t['center_base_m'],old['center_base_m'])>1e-6:return False
        if abs(t['yaw_rad']-old['yaw_rad'])>1e-6:return False
        if math.dist(t['goal_pose_base']['xyz'],old['goal_pose_base']['xyz'])>1e-6:return False
    return True
