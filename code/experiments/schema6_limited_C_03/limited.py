"""C03: immutable Qwen semantics, two-pass agreement, then independent vetoes.
No source-to-plan producer, unknown-name recovery, executor or inference path.
"""
import copy,json,re,sys,unicodedata
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'inputs/schema6/src'))
import mission as legacy
import veto as independent

class Uncovered(ValueError):pass

def normalized(text):
 if type(text) is not str or not 1<=len(text)<=2000 or '\x00' in text:raise Uncovered('Invalid instruction')
 return unicodedata.normalize('NFKC',text).strip()

def colour_aliases(meta):
 # Spatial descriptions stay on Qwen/legacy audit; no geometry parser added.
 result={}
 for key,obj in meta['objects'].items():
  for word in obj['aliases'][:4]:result[word]=key
 for word in meta['unknown_colours']:
  result[word]=word
  if not word.endswith('色'):result[word+'色']=word
 return result

def source_veto(text):
 if independent.BANNED.search(text):return 'unsupported'
 if independent.AMBIGUOUS.search(text) or '以外' in text:return 'clarification_required'
 if re.search(r'(?:[-−][0-9]+|[0-9]+[./／][0-9]+)\s*(?:回|度)',text):return 'clarification_required'
 for number in re.findall(r'[0-9一二三四五六七八九十百千〇零]+(?=\s*(?:回|度))',text):
  if not re.fullmatch(NUM,number):return 'clarification_required'
 return None

NUM=r'(?:[0-9]{1,6}|[一二三四五六七八九]?十[一二三四五六七八九]?|[〇零一二三四五六七八九])'
ORDER_CONNECTOR=re.compile(r'その(?:あと|後)(?:に|で)?')
PREFIX=rf'(?:最初に|最初は|まず|続いて|{ORDER_CONNECTOR.pattern}|その次に|最後に|終わりに|次に)?'
def normalize_plan(plan,meta):
 p=copy.deepcopy(plan)
 if type(p) is not dict or set(p)!=set(legacy.SCHEMA['required']):raise Uncovered('Closed schema6 envelope required')
 if p['status'] not in ['ready','unsupported','clarification_required'] or type(p['reason']) is not str or not 1<=len(p['reason'])<=80:raise Uncovered('Invalid status/reason')
 if type(p['targets']) is not list or len(p['targets'])>128 or any(type(x) is not str or not 1<=len(x)<=40 for x in p['targets']):raise Uncovered('Invalid targets envelope')
 aliases=colour_aliases(meta);canonical={k:o['aliases'][1] for k,o in meta['objects'].items()};changes=[]
 for i,x in enumerate(p['targets']):
  word=unicodedata.normalize('NFKC',x).strip()
  if word not in aliases:raise Uncovered('Uncertified target name: '+word)
  value=aliases[word];name=canonical.get(value,value)
  if x!=name:changes.append({'index':i,'before':x,'after':name,'basis':'frozen scene colour alias'})
  p['targets'][i]=name
 legacy.check_plan(p)
 return p,changes

def verifier_text(text,meta):
 """Independent lexical equivalents; no producer facts/plan supplied here."""
 text=ORDER_CONNECTOR.sub('そのあと',normalized(text)).replace('から始めて','から').replace('見た後','見てから')
 # A different, closed regex admits only explicit count/list utterances with
 # omitted mission verb. It cannot erase unknown words or partial clauses.
 names='|'.join(re.escape(x) for x in sorted(colour_aliases(meta),key=len,reverse=True))
 item=rf'{PREFIX}(?:{names})(?:を)?{NUM}(?:回|度)'
 if re.fullmatch(rf'{item}(?:[\s、,]*(?:と)?[\s、,]*{item})*[。.!！]?',text):text+='点検して'
 return text

def nonexecution(status,code,reason):
 return {'status':status,'visits':[],'skipped':[],'excluded':[],'reason':reason,'reason_code':code}

def verify_proposal(text,proposal,meta):
 """Read-only audit. Can reject, bind IDs and skip known unregistered names."""
 text=normalized(text);p,_=normalize_plan(proposal,meta);veto=source_veto(text)
 if veto:
  return nonexecution(veto,'unsupported_operation' if veto=='unsupported' else 'ambiguous_source','この操作には対応していません' if veto=='unsupported' else '指示の対象または順序を確認してください')
 if p['status']!='ready':return nonexecution('clarification_required','model_nonready','指示の理解結果を確認してください')
 try:a=independent.inspect_intent(verifier_text(text,meta),p,meta)
 except independent.AuditError as exc:
  code=str(exc);reason={'count_mismatch':'点検回数を確認してください','target_mismatch':'点検対象を確認してください','order_mismatch':'点検順序を確認してください','Spatial selection differs from scene facts':'点検順序または空間指定を確認してください'}.get(code,'指示の内容を確認してください。独立監査で正しさを確認できませんでした')
  return nonexecution('clarification_required',code,reason)
 if a['status']!='ready':return nonexecution(a['status'],'visit_limit' if a['status']=='error' else 'audit_unverifiable',a['reason'])
 bound=[independent.canonical(x) for x in p['targets']]
 visits=[x for x in bound if x in meta['objects']];skipped=[x for x in bound if x not in meta['objects']]
 if len(visits)>10:return nonexecution('error','visit_limit','訪問上限10回を超えています')
 return {'status':'ready' if visits else 'no_valid_targets','visits':visits,'skipped':skipped,'excluded':a.get('excluded',[]),'reason':p['reason'] if visits else '登録された対象がありません','reason_code':'verified' if visits else 'no_valid_targets'}

def decide(calls,text,meta):
 """Schema -> meaning-preserving aliases -> exact pair agreement -> audit."""
 record={'decision':None,'route':'none','changes':[],'call_checks':[],'normalized_plans':[],'errors':[],'motion_authorized':False,'Qwen_calls':0,'actual_ROS_commands':0,'planned_ROS_visits':0}
 def finish(decision):
  record['decision']=decision;record['planned_ROS_visits']=len(decision['visits']) if decision['status']=='ready' else 0
  assert decision['status']=='ready' or not decision['visits']
  return record
 try:
  text=normalized(text)
  if len(calls)!=2 or any(c.get('model')!=legacy.MODEL or c.get('done') is not True or c.get('error') for c in calls):return finish(nonexecution('error','incomplete_inference','2回の推論が完了していません'))
  for i,call in enumerate(calls):
   check={'index':i,'schema_valid':False,'normalization_valid':False,'raw':None};record['call_checks'].append(check)
   try:
    p=legacy.strict_json(call['raw_response']);check['raw']=copy.deepcopy(p)
    # Validate each original schema envelope before any alias normalization.
    if type(p) is not dict or set(p)!=set(legacy.SCHEMA['required']):raise Uncovered('Closed schema6 envelope required')
    if type(p['status']) is not str or p['status'] not in legacy.SCHEMA['properties']['status']['enum'] or type(p['reason']) is not str or not 1<=len(p['reason'])<=80:raise Uncovered('Invalid status/reason')
    if type(p['targets']) is not list or len(p['targets'])>128 or any(type(x) is not str or not 1<=len(x)<=40 for x in p['targets']):raise Uncovered('Invalid targets envelope')
    check['schema_valid']=True;p,aliases=normalize_plan(p,meta);check['normalization_valid']=True;record['normalized_plans'].append(p)
    if aliases:record['changes'].append({'call':i,'aliases':aliases})
   except Exception as exc:check['error']=type(exc).__name__+': '+str(exc);record['errors'].append(check['error'])
  if not all(c['schema_valid'] and c['normalization_valid'] for c in record['call_checks']):return finish(nonexecution('clarification_required','unresolved_target' if all(c['schema_valid'] for c in record['call_checks']) else 'invalid_schema','点検対象を確認してください' if all(c['schema_valid'] for c in record['call_checks']) else '回答の形式を確認できませんでした。指示を確認してください'))
  plans=record['normalized_plans'];signature=lambda p:(p['status'],p['targets'])
  if signature(plans[0])!=signature(plans[1]):return finish(nonexecution('clarification_required','two_pass_disagreement','指示の理解結果が一致しませんでした'))
  record['route']='Qwen_aliases_only_then_audit' if record['changes'] else 'Qwen_unchanged_then_audit'
  decision=verify_proposal(text,plans[0],meta)
  # No repair is possible: executable visits are a projection of Qwen targets.
  if decision['status']=='ready':
   expected=[independent.canonical(x) for x in plans[0]['targets'] if independent.canonical(x) in meta['objects']]
   assert decision['visits']==expected,'Audit changed Qwen semantics'
  return finish(decision)
 except Exception as exc:
  record['errors'].append(type(exc).__name__+': '+str(exc));return finish(nonexecution('error','unexpected_error','詳細ログを確認してください'))
