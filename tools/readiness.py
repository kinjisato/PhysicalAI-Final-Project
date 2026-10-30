"""Readiness tied to this container init process, including container restarts."""
import json, os, sys, datetime
from pathlib import Path
runtime = Path(os.environ.get('PAI_RUNTIME', '/opt/pai_runtime'))
p = runtime / 'READY.json'
boot = Path('/proc/sys/kernel/random/boot_id').read_text().strip()
# The VM boot ID alone cannot distinguish docker stop/start of one container.
init_start = Path('/proc/1/stat').read_text().rsplit(')', 1)[1].split()[19]
identity = {'container': os.uname().nodename, 'vm_boot': boot, 'init_start': init_start}
action = sys.argv[1]
if action == 'begin':
    if p.exists():
        old = json.loads(p.read_text())
        if all(old.get(k) == v for k, v in identity.items()):
            raise SystemExit('Runtime already prepared during this container start')
        archive = runtime / ('READY.previous.' + str(old.get('init_start', 'legacy')) + '.json')
        if archive.exists(): raise SystemExit('Previous readiness archive already exists')
        p.rename(archive)
elif action == 'write':
    with p.open('x') as f:
        json.dump({**identity, 'ready_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
                   'prepare': 'PASS', 'motion_authorized': False}, f)
else:
    d = json.loads(p.read_text())
    if any(d.get(k) != v for k, v in identity.items()): raise SystemExit('Stale readiness marker')
    print(json.dumps(d))
