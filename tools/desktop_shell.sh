#!/usr/bin/env bash
set -eo pipefail
export PAI_PUBLIC_ROOT=/opt/pai_release PAI_RUNTIME=/opt/pai_runtime PAI_OUTPUT=/validation
export ROS_DOMAIN_ID=42 ROS_LOCALHOST_ONLY=1 PAI_MINIMAL_SIM=1 PAI_V3_TESTING=1
export RMW_IMPLEMENTATION=rmw_cyclonedds_cpp PYTHONDONTWRITEBYTECODE=1
export CYCLONEDDS_URI=file:///opt/pai_release/docker/cyclonedds.xml
export DISPLAY=:0 XAUTHORITY=/home/ubuntu/.Xauthority
export LANG=ja_JP.UTF-8 LC_ALL=ja_JP.UTF-8 OLLAMA_HOST=127.0.0.1:11434
export IGN_FUEL_CACHE_PATH=/opt/pai_resources/fuel
# sudo changes USER to root. Gazebo's default partition used USER=ubuntu
# at server startup; explicitly join that same partition from this terminal.
export IGN_PARTITION="$(hostname):ubuntu"
source /opt/ros/humble/setup.bash
source /home/ubuntu/airobot_ws/install/setup.bash
source /opt/pai_ws/install/setup.bash
cd "$PAI_PUBLIC_ROOT"
if [[ "${1:-gui}" == gui ]]; then
  echo 'Ubuntu / MATE — ROS・Qwenの準備完了を待っています。'
  until python3 -B tools/readiness.py read 2>/dev/null; do sleep 2; done
  python3 -B tools/gui_command.py || echo "安全停止または実行失敗。上の記録とvalidationログを確認してください。"
fi
exec bash --norc -i
