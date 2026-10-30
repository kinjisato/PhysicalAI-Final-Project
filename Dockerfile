ARG OLLAMA_IMAGE=ollama/ollama@sha256:5c6707fcf2e1a30cffe2ecb7e315584fc87747c389327e4bc711c4959aa1eecc
ARG BASE_IMAGE=airobotbook/ros2-desktop-ai-robot-book-humble@sha256:b58ec74c019aacd9ce4818fa25fc5a9e0a1f22f8c9cd1f5260994bf15cd9eb63
FROM --platform=linux/amd64 ${OLLAMA_IMAGE} AS ollama_source
FROM --platform=linux/amd64 ${BASE_IMAGE}
USER root
SHELL ["/bin/bash", "-c"]
COPY --from=ollama_source /bin/ollama /usr/local/bin/ollama
RUN --mount=from=ollama_source,source=/usr/lib/ollama,target=/tmp/ollama_source_lib,readonly \
    set -euo pipefail; mkdir -p /usr/lib/ollama; \
    find /tmp/ollama_source_lib -mindepth 1 -maxdepth 1 ! -type d -exec cp -a {} /usr/lib/ollama/ \; ; \
    for p in /tmp/ollama_source_lib/cpu*; do [[ ! -e "$p" ]] || cp -a "$p" /usr/lib/ollama/; done; \
    ln -sfn /usr/lib/ollama /usr/local/lib/ollama; test -x /usr/local/lib/ollama/llama-server
# Restore the desktop shipped in the public parent image; do not install another GUI.
RUN echo '8d1bd9a18213c57f1ecfb1d066d7a1932efcfab6f8ce3a7fb8b3ae5a62b68341  /entrypoint.sh' | sha256sum -c - && \
    test -f /usr/lib/novnc/vnc.html && \
    for p in mate-session marco mate-panel caja terminator fcitx vncserver supervisord websockify; do command -v "$p"; done
ENV LD_LIBRARY_PATH=/usr/local/lib/ollama IGN_FUEL_CACHE_PATH=/opt/pai_resources/fuel
ADD .cache/vendor/crane_plus_source.tar.gz /opt/pai_ws/src/
RUN source /opt/ros/humble/setup.bash && \
    for p in /home/*/airobot_ws/install/setup.bash; do [[ ! -f "$p" ]] || source "$p"; done && \
    cd /opt/pai_ws && colcon build --packages-up-to crane_plus_gazebo crane_plus_moveit_config
COPY code /opt/pai_release/code
COPY tools /opt/pai_release/tools
COPY tests /opt/pai_release/tests
COPY cases /opt/pai_release/cases
COPY docker /opt/pai_release/docker
COPY PUBLIC_MANIFEST.json /opt/pai_release/
COPY Dockerfile Dockerfile.gui-overlay .dockerignore .gitignore .env.example README.md LICENSE_STATUS.md compose.yaml compose.model-bind.yaml compose.model-volume.yaml compose.gui.yaml /opt/pai_release/
COPY docs/ /opt/pai_release/docs/
COPY licenses/ /opt/pai_release/licenses/
COPY .cache/fuel/ /opt/pai_resources/fuel/
RUN python3 -B /opt/pai_release/tools/verify_source.py && \
    mkdir -p /opt/pai_runtime && \
    g++ /opt/pai_release/code/experiments/schema6_C03_stable_01/sdf_rpc_worker.cpp \
        -o /opt/pai_runtime/sdf_rpc_worker \
        $(pkg-config --cflags --libs ignition-transport11 ignition-msgs8) && \
    python3 /opt/pai_release/tools/worker_pin.py /opt/pai_runtime
RUN mkdir -p /validation/bootstrap /validation/sessions /validation/baseline /validation/environment
ENTRYPOINT ["/bin/bash", "/opt/pai_release/tools/container_bootstrap.sh"]
