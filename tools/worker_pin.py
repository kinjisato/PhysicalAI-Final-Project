"""Record the locally compiled worker, not a platform-specific shipped binary."""
from pathlib import Path
import hashlib,json,sys,os
root=Path(os.environ.get('PAI_PUBLIC_ROOT',str(Path(__file__).resolve().parents[1])))
folder=Path(sys.argv[1]);binary=folder/'sdf_rpc_worker';src=root/'code/experiments/schema6_C03_stable_01/sdf_rpc_worker.cpp'
pin={'binary_sha256':hashlib.sha256(binary.read_bytes()).hexdigest(),'source_sha256':hashlib.sha256(src.read_bytes()).hexdigest()}
p=folder/'WORKER_PIN.json'
if p.exists():
 if json.loads(p.read_text())!=pin:raise SystemExit('Worker pin mismatch; preserve existing file and stop')
else:p.write_text(json.dumps(pin,indent=2)+'\n')
print(json.dumps(pin))
