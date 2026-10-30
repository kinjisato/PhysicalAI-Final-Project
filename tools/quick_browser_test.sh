#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
python3 -B tools/verify_source.py
: "${PAI_BASE_IMAGE:=pai-verify28:20261029}"
: "${PAI_IMAGE:=pai-github-browser-overlay:20261029}"
: "${PAI_PROJECT:=pai_github_all_browser_overlay_20261029}"
: "${PAI_CONTAINER:=$PAI_PROJECT}"
: "${PAI_MODEL_VOLUME:=pai_submission_ollama_models}"
: "${PAI_WEB_PORT:=6080}"
export PAI_IMAGE PAI_PROJECT PAI_CONTAINER PAI_MODEL_VOLUME PAI_WEB_PORT PAI_GUI=1
unset PAI_MODEL_BIND
# Don't accidentally collide with a running GUI session.
if docker container inspect "$PAI_CONTAINER" >/dev/null 2>&1; then
  echo "Container name already in use: $PAI_CONTAINER. Set new PAI_PROJECT and PAI_CONTAINER." >&2
  exit 3
fi
if docker ps --format '{{.Ports}}' | grep -q ":${PAI_WEB_PORT}->"; then
  echo "Port ${PAI_WEB_PORT} already allocated; set PAI_WEB_PORT to another value." >&2
  exit 4
fi
docker image inspect "$PAI_BASE_IMAGE" >/dev/null
docker build --platform linux/amd64 --pull=false --build-arg "BASE_IMAGE=$PAI_BASE_IMAGE" \
  -f Dockerfile.gui-overlay -t "$PAI_IMAGE" .
python3 -B tools/manage.py up
printf '\nBrowser URL: http://127.0.0.1:%s/vnc.html\n' "$PAI_WEB_PORT"
