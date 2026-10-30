"""Read-only import, package and executable checks; no model call or ROS goal."""
import importlib,shutil,subprocess,json,os
from pathlib import Path
modules=['rclpy','control_msgs.action','trajectory_msgs.msg','sensor_msgs.msg','rosgraph_msgs.msg','moveit_msgs.srv','shape_msgs.msg','ament_index_python','crane_plus_description.robot_description_loader']
for name in modules:importlib.import_module(name)
for name in ['ign','g++','pkg-config','Xtigervnc','ros2','ollama']:
 if not shutil.which(name):raise SystemExit('Missing executable: '+name)
from ament_index_python.packages import get_package_share_directory
for name in ['crane_plus_description','crane_plus_control','crane_plus_moveit_config','ros_gz_sim','ros_gz_bridge','controller_manager']:
 get_package_share_directory(name)
root=Path(os.environ.get('PAI_PUBLIC_ROOT','/opt/pai_release'))
pin=json.loads((root/'code/MODEL_PIN.json').read_text())
model=Path('/model-source/models')
if not (model/'manifests/registry.ollama.ai/library/qwen2.5/3b').is_file():raise SystemExit('Pinned model manifest absent; do not auto-pull')
for name in pin['blobs']:
 if not (model/'blobs'/name.replace(':','-')).is_file():raise SystemExit('Pinned model blob absent: '+name)
print(json.dumps({'dependency_presence':'PASS','model_hash_check':'performed by simulation_cli before any action','ROS_goals':0}))

# Only explicitly hash-pinned Fuel files, including measured whitespace-only variants.
import hashlib
fuel=Path(os.environ.get('IGN_FUEL_CACHE_PATH','/opt/pai_resources/fuel'))
for model in json.loads((root/'docker/FUEL_PINS.json').read_text())['models'].values():
 for name,spec in model['files'].items():
  path=fuel/model['cache_relative']/name
  allowed={spec['sha256'],spec.get('formatting_variant',{}).get('sha256')}
  if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() not in allowed:raise SystemExit('Pinned Fuel cache missing/mismatch: '+name)
print(json.dumps({'Fuel_file_hashes':'PASS'}))
