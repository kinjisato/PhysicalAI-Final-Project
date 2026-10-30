# Third-party components

The externally fetched `crane_plus` source dependency is RT Corporation's CRANE+ ROS 2 stack, commit `19c1d6069126cd27488bf1bbefd410704bfc515d`, Apache License 2.0. Its LICENSE and attribution remain in the upstream source. The source archive is not included in the public submission. The environment `launch/minimal.launch.py` is derived from its Gazebo launch file and retains attribution.

The Docker base is `airobotbook/ros2-desktop-ai-robot-book-humble`, pinned by digest in the repository root `Dockerfile`. ROS 2 Humble, MoveIt 2, Ignition Gazebo 6, RViz, Ollama and Qwen2.5 retain their respective licenses. Qwen model weights are not redistributed in this repository.

Fuel Table, Ground Plane, and Sun assets are fetched by the public fetch_dependencies.py using pinned version URLs/hashes; the frozen world retains its original resource URLs in `worlds/minimal.sdf`; those resources retain their own metadata/licenses. This project does not include camera inference, defect diagnosis, learned control, or gripper actions.
