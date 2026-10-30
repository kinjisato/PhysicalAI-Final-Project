"""One owned, serial, read-only Ignition client; bounded pre-AI retries only."""
import json,os,selectors,subprocess,threading,time
from pathlib import Path
class RPCError(RuntimeError):pass
class TransportNoReply(RPCError):pass
class Persistent:
 def __init__(self,executable,writer,folder):
  self.executable=Path(executable);self.writer=writer;self.folder=Path(folder);self.pre_ai=True;self.context='readiness';self.sequence=0;self.lock=threading.Lock();self.buffer=b'';self.closed=False
  path=writer.path(self.folder/'worker.stderr');path.parent.mkdir(parents=True,exist_ok=True);self.stderr=path.open('xb',buffering=0)
  self.proc=subprocess.Popen([str(executable)],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=self.stderr,start_new_session=True,bufsize=0)
  try:
   ready=json.loads(self._line(8))
   if ready!={'event':'ready','service_listed':True}:raise RPCError('SDF service discovery not ready')
   writer.json(self.folder/'STARTED.json',{'pid':self.proc.pid,'command':[str(executable)],'ready':ready,'allowed_services':['/world/default/generate_world_sdf','/world/default/scene/info'],'scene_writes':False,'single_inflight':True})
  except Exception:self.close();raise
 def _line(self,timeout):
  deadline=time.monotonic()+timeout
  with selectors.DefaultSelector() as selector:
   selector.register(self.proc.stdout,selectors.EVENT_READ)
   while b'\n' not in self.buffer:
    remaining=deadline-time.monotonic()
    if remaining<=0 or not selector.select(remaining):raise RPCError('Worker process response deadline exceeded')
    part=os.read(self.proc.stdout.fileno(),65536)
    if not part:raise RPCError('Worker exited before complete response')
    self.buffer+=part
    if len(self.buffer)>4*1024*1024:raise RPCError('Worker response exceeds diagnostic bound')
  line,self.buffer=self.buffer.split(b'\n',1);return line.decode('utf-8')
 def request(self,kind):
  if kind not in ['GET','SCENE'] or self.closed:raise RPCError('Invalid/closed worker request')
  if not self.lock.acquire(blocking=False):raise RPCError('Concurrent Ignition request prohibited')
  self.sequence+=1;index=self.sequence;prefix=self.folder/f'rpc_{index:04d}';started=time.monotonic();offset=os.fstat(self.stderr.fileno()).st_size;record={'sequence':index,'kind':kind,'pid':self.proc.pid,'context':self.context,'pre_ai':self.pre_ai,'status':'FAIL'};raw_saved=False
  try:
   self.writer.json(str(prefix)+'_started.json',{'command':[str(self.executable)],'stdin':kind,'service':'/world/default/generate_world_sdf' if kind=='GET' else '/world/default/scene/info','RPC_timeout_ms':20000,'process_reply_timeout_seconds':25,'pre_ai':self.pre_ai,'pid':self.proc.pid})
   self.proc.stdin.write((kind+'\n').encode());self.proc.stdin.flush();raw=self._line(25);self.writer.text(str(prefix)+'.stdout',raw+'\n');raw_saved=True;data=json.loads(raw)
   if data.get('sequence')!=index:raise RPCError('Stale/out-of-order worker response')
   record.update(executed=data.get('executed'),result=data.get('result'),RPC_milliseconds=data.get('milliseconds'),stdout_bytes=len(raw.encode()),data_bytes=len(data.get('response',{}).get('data','').encode()))
   if data.get('executed') is not True or data.get('result') is not True:raise TransportNoReply('Ignition request did not produce a successful reply')
   text=data.get('response',{}).get('data')
   if not isinstance(text,str) or not text.strip():raise RPCError('Empty/malformed typed service response')
   record['status']='PASS';return text,record
  except Exception as exc:record['error']=type(exc).__name__+': '+str(exc);raise
  finally:
   try:
    if not raw_saved:self.writer.bytes(str(prefix)+'.stdout',self.buffer)
    self.stderr.flush();tail=Path(self.stderr.name).read_bytes()[offset:];self.writer.bytes(str(prefix)+'.stderr',tail);record.update(wall_seconds=time.monotonic()-started,stderr_bytes=len(tail));self.writer.json(str(prefix)+'_result.json',record)
   finally:self.lock.release()
 def acquire(self,kind):
  attempts=3 if self.pre_ai else 1
  for index in range(attempts):
   try:return self.request(kind)
   except TransportNoReply:
    if index+1>=attempts:raise
    time.sleep(.25)
  raise RPCError('Bounded acquisition exhausted')
 def close(self):
  if self.closed:return
  self.closed=True;graceful=False
  try:
   if self.proc.poll() is None:
    try:self.proc.stdin.write(b'QUIT\n');self.proc.stdin.flush();self.proc.stdin.close();self.proc.wait(timeout=3);graceful=True
    except (BrokenPipeError,subprocess.TimeoutExpired):
     self.proc.terminate()
     try:self.proc.wait(timeout=2)
     except subprocess.TimeoutExpired:self.proc.kill();self.proc.wait(timeout=2)
  finally:
   self.stderr.close();self.writer.json(self.folder/'CLOSED.json',{'pid':self.proc.pid,'returncode':self.proc.returncode,'requests':self.sequence,'graceful':graceful,'collected':self.proc.poll() is not None,'only_owned_process_touched':True})
