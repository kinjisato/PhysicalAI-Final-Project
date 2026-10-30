#!/usr/bin/env bash
# ROS/Qwen integration alongside the native desktop; no task goal on startup.
set -eo pipefail
export PAI_PUBLIC_ROOT="${PAI_PUBLIC_ROOT:-/opt/pai_release}"
export PAI_RUNTIME="${PAI_RUNTIME:-/opt/pai_runtime}"
export PAI_OUTPUT="${PAI_OUTPUT:-/validation}"
export ROS_DOMAIN_ID=42 ROS_LOCALHOST_ONLY=1 PAI_MINIMAL_SIM=1
export RMW_IMPLEMENTATION=rmw_cyclonedds_cpp PYTHONDONTWRITEBYTECODE=1
export DISPLAY=:0 XAUTHORITY=/home/ubuntu/.Xauthority
export LIBGL_ALWAYS_SOFTWARE=1 QT_X11_NO_MITSHM=1
export LANG=ja_JP.UTF-8 LC_ALL=ja_JP.UTF-8
export OLLAMA_HOST=127.0.0.1:11434
mkdir -p "$PAI_RUNTIME" "$PAI_OUTPUT/bootstrap" /tmp/pai_public_ollama
python3 -B "$PAI_PUBLIC_ROOT/tools/readiness.py" begin
if [[ ! -f "$PAI_RUNTIME/sdf_rpc_worker" ]]; then
  g++ "$PAI_PUBLIC_ROOT/code/experiments/schema6_C03_stable_01/sdf_rpc_worker.cpp" \
      -o "$PAI_RUNTIME/sdf_rpc_worker" \
      $(pkg-config --cflags --libs ignition-transport11 ignition-msgs8)
fi
python3 -B "$PAI_PUBLIC_ROOT/tools/worker_pin.py" "$PAI_RUNTIME"
source /opt/ros/humble/setup.bash
for p in /home/*/airobot_ws/install/setup.bash; do [[ ! -f "$p" ]] || source "$p"; done
source /opt/pai_ws/install/setup.bash
python3 -B "$PAI_PUBLIC_ROOT/tools/check_dependencies.py"
# Ollama 0.40.9 migrates a legacy manifest into manifests-v2 on first launch.
# Keep fetched weights RO; only the tiny registry index is writable.
model_runtime="$PAI_RUNTIME/ollama_models"
mkdir -p "$model_runtime/manifests/registry.ollama.ai/library/qwen2.5"
if [[ ! -L "$model_runtime/blobs" ]]; then ln -s /model-source/models/blobs "$model_runtime/blobs"; fi
cp /model-source/models/manifests/registry.ollama.ai/library/qwen2.5/3b \
   "$model_runtime/manifests/registry.ollama.ai/library/qwen2.5/3b"
# The frozen legacy descriptor wraps the real registry manifest as a layer.
# Reproduce the old store's v2 link to that exact (already fetched) manifest.
logical_digest=$(python3 -c 'import json; print(json.load(open("/opt/pai_release/code/MODEL_PIN.json"))["api_logical_digest"])')
v2="$model_runtime/manifests-v2/ollama.com/library/qwen2.5"
mkdir -p "$v2"
if [[ ! -e "$v2/3b" ]]; then
  ln -s "../../../../blobs/sha256-$logical_digest" "$v2/3b"
fi
[[ "$(sha256sum "$v2/3b" | cut -d ' ' -f 1)" == "$logical_digest" ]]
HOME=/tmp/pai_public_ollama OLLAMA_MODELS="$model_runtime" OLLAMA_NOPRUNE=1 \
  /usr/local/bin/ollama serve >"$PAI_OUTPUT/bootstrap/ollama.log" 2>&1 &
ollama_pid=$!
ros_pid=''
cleanup() {
  [[ -z "$ros_pid" ]] || kill -TERM "$ros_pid" 2>/dev/null || true
  kill -TERM "$ollama_pid" 2>/dev/null || true
}
trap cleanup EXIT
trap 'exit 143' INT TERM
for n in $(seq 1 120); do
  if xdpyinfo -display :0 >/dev/null 2>&1; then break; fi
  sleep .5
done
xdpyinfo -display :0 >/dev/null
cd /workspace/PhysicalAI_V5_Integrated/minimal
ros2 launch launch/minimal.launch.py >"$PAI_OUTPUT/bootstrap/ros.log" 2>&1 &
ros_pid=$!
if ! python3 -u /workspace/pai_launcher/prepare_inside.py >"$PAI_OUTPUT/bootstrap/scene.log" 2>&1; then
  echo 'Scene preparation failed; no Qwen/task trajectory was run' >&2
  exit 3
fi
if ! python3 -B "$PAI_PUBLIC_ROOT/tools/simulation_cli.py" prepare >"$PAI_OUTPUT/bootstrap/prepare.log" 2>&1; then
  echo 'C03 preparation failed; no task goal sent' >&2
  exit 4
fi
python3 -B "$PAI_PUBLIC_ROOT/tools/readiness.py" write
wait -n "$ros_pid" "$ollama_pid"
