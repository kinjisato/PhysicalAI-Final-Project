# Derived from crane_plus_gazebo/launch/crane_plus_with_table.launch.py
# Copyright 2022 RT Corporation. Licensed under Apache License 2.0.
# http://www.apache.org/licenses/LICENSE-2.0
from pathlib import Path
import os
from ament_index_python.packages import get_package_share_directory
from crane_plus_description.robot_description_loader import RobotDescriptionLoader
from launch import LaunchDescription
from launch.actions import ExecuteProcess,IncludeLaunchDescription
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch_ros.actions import Node,SetParameter


def generate_launch_description():
    root=Path(__file__).resolve().parents[1]
    env={'IGN_GAZEBO_SYSTEM_PLUGIN_PATH':os.environ['LD_LIBRARY_PATH'],
         'IGN_GAZEBO_RESOURCE_PATH':os.path.dirname(get_package_share_directory('crane_plus_description'))}
    sim=ExecuteProcess(cmd=['ign','gazebo','-s','-r',str(root/'worlds/minimal.sdf')],additional_env=env,output='screen')
    spawn=Node(package='ros_gz_sim',executable='create',arguments=['-topic','/robot_description','-name','crane_plus','-z','1.015','-allow_renaming','false'])
    loader=RobotDescriptionLoader();loader.use_gazebo='true';loader.use_ignition='true'
    loader.gz_control_config_package='crane_plus_control';loader.gz_control_config_file_path='config/crane_plus_controllers.yaml'
    moveit=IncludeLaunchDescription(PythonLaunchDescriptionSource([get_package_share_directory('crane_plus_moveit_config'),'/launch/run_move_group.launch.py']),launch_arguments={'loaded_description':loader.load(),'rviz_config_file':str(root/'config/minimal.rviz')}.items())
    controllers=[Node(package='controller_manager',executable='spawner',arguments=[name]) for name in ('joint_state_broadcaster','crane_plus_arm_controller','crane_plus_gripper_controller')]
    bridge=Node(package='ros_gz_bridge',executable='parameter_bridge',arguments=['/clock@rosgraph_msgs/msg/Clock[ignition.msgs.Clock'])
    return LaunchDescription([SetParameter(name='use_sim_time',value=True),sim,spawn,moveit,*controllers,bridge])
