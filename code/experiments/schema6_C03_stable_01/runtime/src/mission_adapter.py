"""Quarantined C03 binding: original infer, immutable raw pair, session handoff.
Only the authorized simulation harness enables this module; no text-to-plan path.
"""
import contextlib,copy,hashlib,json,secrets,sys,os
from pathlib import Path
import mission as legacy
from storage import digest,fingerprint
EXPERIMENT=Path(__file__).resolve().parents[2]
C03=EXPERIMENT.parent/'schema6_limited_C_03'
sys.path.insert(0,str(C03))
import limited as c03
_PIN={name:hashlib.sha256((C03/name).read_bytes()).hexdigest() for name in ['limited.py','veto.py']}
_RUNTIME_SHA=fingerprint()
_enabled=False
_active=None
_session_id=None

def _check_sources():
 if fingerprint()!=_RUNTIME_SHA:raise ValueError('Isolated runtime changed')
 if any(hashlib.sha256((C03/n).read_bytes()).hexdigest()!=h for n,h in _PIN.items()):raise ValueError('C03 source changed')

def begin_request():
 global _active
 _active=None

def end_request():begin_request()

def state():
 return {'simulation_session_enabled':_enabled,'active_ticket':_active is not None,'cached_visits':[],'session_id':_session_id}

@contextlib.contextmanager
def live_session(session_id=None, simulation_authorized=False):
 if not simulation_authorized or os.environ.get("ROS_DOMAIN_ID")!="42" or os.environ.get("PAI_MINIMAL_SIM")!="1":raise ValueError("Explicit authorized simulation required")
 global _enabled,_session_id
 if _enabled:raise ValueError('Nested dryrun session forbidden')
 if session_id is not None and (not isinstance(session_id,str) or len(session_id)!=32 or any(c not in '0123456789abcdef' for c in session_id)):raise ValueError('Invalid session ID')
 begin_request();_enabled=True;_session_id=session_id or secrets.token_hex(16)
 try:yield
 finally:begin_request();_enabled=False;_session_id=None

def infer(instruction,**kwargs):
 global _active
 begin_request()
 if not _enabled or _session_id is None:raise ValueError('Authorized simulation harness required')
 if kwargs.get('single'):raise ValueError('Two independent Qwen calls required')
 _check_sources()
 # Unchanged schema6 inference builds the original prompts/requests and calls
 # its HTTP transport twice. The simulation harness forwards the unchanged requests to native Qwen.
 source=legacy.infer(instruction,**kwargs)
 result=c03.decide(source['calls'],source['instruction'],source['metadata'])
 doc={k:copy.deepcopy(source[k]) for k in ['schema','mode','model','instruction','metadata','source_sha256','ai_seconds']}
 doc.update(session_id=_session_id,schema6_evidence=copy.deepcopy(source),c03_result=result,decision=copy.deepcopy(result['decision']),c03_source_hashes=copy.deepcopy(_PIN),dryrun_only=False,simulation_only=True,inference_origin='fresh_container_Qwen',handoff_nonce=secrets.token_hex(16))
 doc['sha256']=digest(doc)
 _active={'nonce':doc['handoff_nonce'],'digest':doc['sha256'],'session_id':_session_id}
 return doc

def validate(doc):
 global _active
 ticket=_active;_active=None # consume before any validation/error; never retain a route
 if not _enabled or ticket is None:raise ValueError('No current unconsumed C03 handoff')
 _check_sources()
 if doc.get('session_id')!=_session_id or ticket.get('session_id')!=_session_id:raise ValueError('Session mismatch')
 if doc.get('handoff_nonce')!=ticket['nonce'] or doc.get('sha256')!=ticket['digest']:raise ValueError('Stale or substituted handoff')
 if doc['sha256']!=digest({k:v for k,v in doc.items() if k!='sha256'}):raise ValueError('C03 document checksum mismatch')
 if doc.get('c03_source_hashes')!=_PIN or (doc.get('dryrun_only') is not False or doc.get('simulation_only') is not True or doc.get('inference_origin')!='fresh_container_Qwen'):raise ValueError('Candidate provenance mismatch')
 source=doc['schema6_evidence']
 # Original validator checks both original requests, source, scene, checksum
 # and recomputed legacy evidence, even if its old audit was a false refusal.
 legacy.validate(source)
 for k in ['schema','mode','model','instruction','metadata','source_sha256','ai_seconds']:
  if doc.get(k)!=source.get(k):raise ValueError('Source evidence differs: '+k)
 result=c03.decide(source['calls'],source['instruction'],source['metadata'])
 if result!=doc.get('c03_result') or result['decision']!=doc.get('decision'):raise ValueError('C03 audit does not reproduce from raw responses')
 decision=copy.deepcopy(result['decision'])
 if decision['status']!='ready' and decision['visits']:raise ValueError('Nonready handoff contains visits')
 return decision
