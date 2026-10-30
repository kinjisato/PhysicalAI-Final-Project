#!/usr/bin/env bash
# Use the unmodified public parent's Ubuntu/MATE/VNC/Supervisor entrypoint.
set -eo pipefail
export PAI_PUBLIC_ROOT="${PAI_PUBLIC_ROOT:-/opt/pai_release}"
export PAI_RUNTIME="${PAI_RUNTIME:-/opt/pai_runtime}"
export PAI_OUTPUT="${PAI_OUTPUT:-/validation}"
mkdir -p "$PAI_RUNTIME" "$PAI_OUTPUT/bootstrap"
# Preserve the previous boot logs when the user explicitly resumes this container.
if find "$PAI_OUTPUT/bootstrap" -type f -print -quit | grep -q .; then
  archive="$PAI_OUTPUT/boots/$(date -u +%Y%m%dT%H%M%S)-$$"
  mkdir -p "$archive"
  cp -a "$PAI_OUTPUT/bootstrap/." "$archive/"
fi
python3 -B "$PAI_PUBLIC_ROOT/tools/verify_source.py"
echo '8d1bd9a18213c57f1ecfb1d066d7a1932efcfab6f8ce3a7fb8b3ae5a62b68341  /entrypoint.sh' | sha256sum -c -
# The original entrypoint generates its own supervisord.conf. Add one program;
# retain its vnc, noVNC, mate-session, marco and Japanese IME unchanged.
cat > /etc/supervisor/conf.d/pai-runtime.conf <<CONF
[program:pai-runtime]
command=/bin/bash $PAI_PUBLIC_ROOT/tools/runtime_bootstrap.sh
autostart=true
autorestart=false
startsecs=0
stopasgroup=true
killasgroup=true
stopwaitsecs=20
stdout_logfile=$PAI_OUTPUT/bootstrap/runtime.log
stdout_logfile_maxbytes=4MB
stdout_logfile_backups=1
stderr_logfile=$PAI_OUTPUT/bootstrap/runtime.stderr
stderr_logfile_maxbytes=1MB
stderr_logfile_backups=1
CONF
mkdir -p /home/ubuntu/.config/autostart
cat > /home/ubuntu/.config/autostart/pai-command.desktop <<DESKTOP
[Desktop Entry]
Type=Application
Name=Physical AI Japanese Command
Exec=terminator --no-dbus -T Physical-AI -x sudo -E /bin/bash $PAI_PUBLIC_ROOT/tools/desktop_shell.sh gui
X-MATE-Autostart-enabled=true
DESKTOP
mkdir -p /home/ubuntu/Desktop
for mode in gui shell; do
cat > "/home/ubuntu/Desktop/pai-$mode.desktop" <<DESKTOP
[Desktop Entry]
Type=Application
Name=Physical AI $mode
Exec=terminator --no-dbus -x sudo -E /bin/bash $PAI_PUBLIC_ROOT/tools/desktop_shell.sh $mode
Icon=utilities-terminal
Terminal=false
DESKTOP
chmod +x "/home/ubuntu/Desktop/pai-$mode.desktop"
done
chown ubuntu:ubuntu /home/ubuntu/.config/autostart/pai-command.desktop /home/ubuntu/Desktop/pai-*.desktop
exec /entrypoint.sh
