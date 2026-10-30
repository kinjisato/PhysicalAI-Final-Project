"""Session-owned mutable report; immutable evidence and sealed final result."""
import hashlib,json,os,secrets,stat
from pathlib import Path
class LogRejected(ValueError):pass
class SessionLog:
 def __init__(self,writer,path):
  self.writer=writer;self.root=writer.new_case(path);self.root.mkdir(mode=0o700) # atomic claim, existing/unclean session never reused
  self.session_id=secrets.token_hex(16);self.active=True;self.failed=False;self.version=0;self.owned=None
  self.lock=os.open(self.root/'SESSION.lock',os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600);os.write(self.lock,self.session_id.encode());os.fsync(self.lock)
  (self.root/'work').mkdir(mode=0o700);self.work=self.root/'work';self.fd=os.open(self.work,os.O_RDONLY|os.O_DIRECTORY|getattr(os,'O_NOFOLLOW',0));self.work_inode=os.fstat(self.fd).st_ino
  self.report_path=self.work/'execution.json';writer.json(self.root/'evidence/session.json',{'session_id':self.session_id,'mutable_report':'work/execution.json','reuse_forbidden':True})
 def _check(self):
  if not self.active or self.failed:raise LogRejected('Session closed or log failed')
  self.writer.path(self.report_path)
  if self.work.is_symlink() or self.work.stat().st_ino!=self.work_inode:raise LogRejected('Working directory changed')
  try:one=os.stat('execution.json',dir_fd=self.fd,follow_symlinks=False)
  except FileNotFoundError:
   if self.owned is not None:raise LogRejected('Owned report removed')
   return
  if not stat.S_ISREG(one.st_mode) or self.owned is None:raise LogRejected('Report is not a session-created regular file')
  raw=self.report_path.read_bytes()
  if (one.st_ino,hashlib.sha256(raw).hexdigest())!=self.owned:raise LogRejected('Owned report substituted')
 def update(self,path,obj,fault=None):
  # There is exactly one mutable pathname; no arbitrary existing file update.
  if Path(path).absolute()!=self.report_path.absolute():raise LogRejected('Only current session report may update')
  temp=None
  try:
   self._check();raw=(json.dumps(obj,ensure_ascii=False,indent=2,allow_nan=False)+'\n').encode();temp='.report-'+secrets.token_hex(8)+'.tmp'
   fd=os.open(temp,os.O_WRONLY|os.O_CREAT|os.O_EXCL|getattr(os,'O_NOFOLLOW',0),0o600,dir_fd=self.fd)
   with os.fdopen(fd,'wb') as f:
    f.write(raw);f.flush();os.fsync(f.fileno())
   if fault:fault('before_replace')
   self._check();os.replace(temp,'execution.json',src_dir_fd=self.fd,dst_dir_fd=self.fd);temp=None;self.version+=1
   info=os.stat('execution.json',dir_fd=self.fd,follow_symlinks=False);self.owned=(info.st_ino,hashlib.sha256(raw).hexdigest())
   self.writer.bytes(self.root/f'evidence/report_{self.version:04d}.json',raw)
  except Exception:
   self.failed=True;raise
  finally:
   if temp is not None:
    try:os.unlink(temp,dir_fd=self.fd)
    except FileNotFoundError:pass
 def seal(self,outcome):
  if not self.active:raise LogRejected('Session already sealed')
  self.active=False
  try:
   final=None
   if self.owned is not None:
    info=os.stat('execution.json',dir_fd=self.fd,follow_symlinks=False);raw=self.report_path.read_bytes()
    if not stat.S_ISREG(info.st_mode) or (info.st_ino,hashlib.sha256(raw).hexdigest())!=self.owned:raise LogRejected('Cannot seal substituted report')
    self.writer.bytes(self.root/'final/execution.json',raw);final=self.owned[1];os.chmod(self.report_path,0o400)
   evidence={str(p.relative_to(self.root)):hashlib.sha256(p.read_bytes()).hexdigest() for p in (self.root/'evidence').glob('*.json')}
   manifest={'session_id':self.session_id,'outcome':outcome,'log_failed':self.failed,'updates':self.version,'final_execution_sha256':final,'immutable_evidence':evidence,'closed':True};self.writer.json(self.root/'final/MANIFEST.json',manifest)
   for p in self.root.rglob('*'):
    if p.is_file() and not p.is_symlink():os.chmod(p,0o400)
   return manifest
  finally:os.close(self.fd);os.close(self.lock)
 def abandon(self):
  # Models abrupt process exit: leave the exclusive session directory/lock;
  # no recovery/reopen is permitted and no success manifest is fabricated.
  self.active=False;os.close(self.fd);os.close(self.lock)
