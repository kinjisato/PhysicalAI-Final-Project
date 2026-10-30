#!/usr/bin/env python3
"""Restore the frozen Fix2 scene without old six-permutation route planning.

Scene-only setup: no trajectory planning or robot-motion commands are issued.
"""
import json
import os
import subprocess
import sys
import time
from pathlib import Path

BASE = Path('/workspace/PhysicalAI_V5_Integrated/minimal')
V2 = Path('/workspace/pai_v2')
FROZEN = V2 / 'config/frozen_scene.json'
NAMES = {'pai_minimal_A', 'pai_minimal_B', 'pai_minimal_C'}


def invoke(root, flag):
    env = os.environ.copy()
    env['PAI_MINIMAL_SIM'] = '1'
    result = subprocess.run([sys.executable, 'src/run.py', flag], cwd=root, env=env)
    if result.returncode:
        raise RuntimeError(f'{root.name} {flag} failed (exit={result.returncode})')


# Services, controller states and /clock are asynchronous.
for attempt in range(30):
    try:
        invoke(BASE, '--inspect')
        break
    except (RuntimeError, OSError):
        if attempt == 29:
            raise
        time.sleep(3)

sys.path.insert(0, str(BASE / 'src'))
from backend import Simulator
from core import check_layout, digest
import rclpy

frozen = json.loads(FROZEN.read_text())
targets = frozen['targets']
if set(targets) != {'A', 'B', 'C'}:
    raise RuntimeError('Frozen target membership mismatch')
if {t['model'] for t in targets.values()} != NAMES:
    raise RuntimeError('Frozen Gazebo model names mismatch')
if digest(targets) != frozen['layout_sha256']:
    raise RuntimeError('Frozen layout checksum mismatch')
check_layout(targets)

rclpy.init()
node = None
try:
    node = Simulator()
    node.guard()
    if node.world_from_base != frozen['world_from_base']:
        raise RuntimeError('Frozen base transform mismatch')
    models = set(node.gazebo_scene())
    present = models & NAMES
    if present and present != NAMES:
        raise RuntimeError('Partial target scene; stop without changing anything')
    if not present:
        print('Restoring the three frozen Fix2 targets WITHOUT six-route planning', flush=True)
        # Register identical target geometry in MoveIt before Gazebo spawn.
        # Never remove arbitrary preexisting Gazebo entities.
        node.set_objects(targets)
        node.confirm_scene(targets)
        for key in ('A', 'B', 'C'):
            node.spawn(targets[key])
    else:
        print('All three Gazebo entities already exist; preserving their poses', flush=True)
        # A fresh MoveIt process can have no collision objects despite Gazebo models existing.
        node.set_objects(targets)
    node.confirm_scene(targets)
    node.confirm_gazebo(targets)
    node.verify_static_geometry(targets)
finally:
    if node is not None:
        node.destroy_node()
    rclpy.shutdown()

# Fix2's --prepare performs read-only verification and NO six-route planning.
invoke(V2, '--prepare')
print('Frozen Fix2 scene verified. No robot movement commands sent.', flush=True)
