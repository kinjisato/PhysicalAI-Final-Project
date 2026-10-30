"""Closed JSON Schema and semantic checks. A failed interpretation never gets a replacement route."""
import json
import re
import unicodedata
from collections import Counter
from core import ROOT, order
from safety import source_policy, source_sequence, validate_grounding, UNKNOWN_COLOURS, UNSUPPORTED

MAX_VISITS=10
STATUSES=['ready','clarification_required','unsupported','no_valid_targets','error']
def array(item,limit=40):return {'type':'array','maxItems':limit,'items':item}
def string(limit=300):return {'type':'string','minLength':1,'maxLength':limit}
def obj(properties):return {'type':'object','additionalProperties':False,'properties':properties,'required':list(properties)}
COUNT={'type':'integer','minimum':1,'maximum':10000}
SCHEMA=obj({'requested_targets':array(string(40),128),
 'execution_order':array({'type':'string','enum':['A','B','C']},MAX_VISITS),
 'skipped_targets':array(obj({'target':string(40),'reason':{'type':'string','enum':['not_registered']}}),128),
 'status':{'type':'string','enum':STATUSES},'reason':string(500)})
LLM_SCHEMA=obj({'requested_targets':array({'type':'string','enum':['A','B','C']+UNKNOWN_COLOURS},128),'status':{'type':'string','enum':STATUSES},'reason':string(500)})


def schema_check(value,schema,path='$'):
 """Validate the closed schema's explicitly supported JSON Schema keywords, with no dependencies."""
 allowed={'type','additionalProperties','properties','required','items','maxItems','minItems','prefixItems','minLength','maxLength','minimum','maximum','enum'}
 if set(schema)-allowed:raise ValueError('Unsupported schema keyword')
 kinds={'object':dict,'array':list,'string':str,'integer':int}
 typ=schema['type']
 if type(value) is not kinds[typ]:raise ValueError(path+': wrong JSON type '+typ)
 if 'enum' in schema and value not in schema['enum']:raise ValueError(path+': not in enum')
 if typ=='object':
  if set(schema['required'])-set(value):raise ValueError(path+': missing required fields')
  if schema.get('additionalProperties') is False and set(value)-set(schema['properties']):raise ValueError(path+': unexpected fields')
  for k,v in value.items():schema_check(v,schema['properties'][k],path+'.'+k)
 elif typ=='array':
  if not schema.get('minItems',0)<=len(value)<=schema.get('maxItems',100000):raise ValueError(path+': invalid array length')
  prefix=schema.get('prefixItems',[])
  if not isinstance(prefix,list):raise ValueError('prefixItems must be an array')
  for i,v in enumerate(value):
   if i<len(prefix):schema_check(v,prefix[i],path+f'[{i}]')
   elif 'items' in schema:schema_check(v,schema['items'],path+f'[{i}]')
 elif typ=='string':
  if not schema.get('minLength',0)<=len(value)<=schema.get('maxLength',100000):raise ValueError(path+': invalid string length')
 elif typ=='integer' and not schema.get('minimum',-100000)<=value<=schema.get('maximum',100000):raise ValueError(path+': integer out of range')


def strict_json(raw):
 def pairs(items):
  result={}
  for k,v in items:
   if k in result:raise ValueError('Duplicate JSON key: '+k)
   result[k]=v
  return result
 return json.loads(raw,object_pairs_hook=pairs)


def norm(text):return unicodedata.normalize('NFKC',text).strip()


def metadata():
 scene=json.loads((ROOT/'config/frozen_scene.json').read_text());targets=scene['targets']
 positions=sorted(targets,key=lambda k:targets[k]['center_base_m'][1]);heights=sorted(targets,key=lambda k:targets[k]['center_base_m'][2]);distances=sorted(targets,key=lambda k:targets[k]['horizontal_distance_m'])
 aliases={'A':['A','青','青色','ブルー'],'B':['B','黄','黄色','イエロー'],'C':['C','緑','緑色','グリーン']}
 for keys,words in [(positions,[['右','右側'],['中央','真ん中','真中'],['左','左側']]),(heights,[['低い','低い対象','低所'],['中間の高さ','中間高さ'],['高い','高い対象','高所']]),(distances,[['近い','近い対象','一番近い','近距離'],['中距離'],['遠い','遠い対象','一番遠い','遠距離']])]:
  for key,values in zip(keys,words):aliases[key].extend(values)
 return {'layout_sha256':scene['layout_sha256'],'max_visits':MAX_VISITS,'objects':{k:{'aliases':aliases[k],'center_base_m':targets[k]['center_base_m'],'height_m':targets[k]['center_base_m'][2],'distance_m':targets[k]['horizontal_distance_m'],'rgba':targets[k]['rgba']} for k in 'ABC'}}


def resolve(value,meta):
 value=norm(value)
 for k,t in meta['objects'].items():
  if value in t['aliases']:return k
 return value.removesuffix('色')


def mentions(text):
 return re.findall(r'青色|青|黄色|黄|緑色|緑|赤色|赤|紫色|紫|白色|白|黒色|黒|ピンク|オレンジ|(?<![a-zA-Z])[ABC](?![a-zA-Z])',norm(text))


def clear_unsupported(text):
 return UNSUPPORTED.findall(norm(text))


def number(text):
 if text.isdecimal():return int(text)
 units={'十':10,'百':100,'千':1000};digits={'一':1,'二':2,'三':3,'四':4,'五':5,'六':6,'七':7,'八':8,'九':9,'〇':0,'零':0};total=current=0
 for ch in text:
  if ch in digits:current=digits[ch]
  elif ch in units:total+=(current or 1)*units[ch];current=0
  else:raise ValueError('Unrecognized repetition number')
 return total+current


def normalize(raw,instruction,meta):
 schema_check(raw,SCHEMA);t=norm(instruction)
 requested=[resolve(x,meta) for x in raw['requested_targets']]
 skips=[];expanded=[]
 for target in requested:
  if target in meta['objects']:expanded.append(target)
  else:
   if target in ['どれか','適当','対象','対象物','あれ','これ','それ','全部','すべて','全て','unknown','不明']:raise ValueError('Ambiguity cannot be skipped as nonexistent')
   if target not in {x.removesuffix('色') for x in UNKNOWN_COLOURS} or target not in t:raise ValueError('Unknown reference is not an explicitly named unregistered colour')
   skips.append({'target':target,'reason':'not_registered'})
 if [s['target'] for s in skips]!=[resolve(s['target'],meta) for s in raw['skipped_targets']]:raise ValueError('Skipped targets mismatch')
 status=raw['status'];reason=raw['reason']
 if clear_unsupported(t) and status!='unsupported':raise ValueError('Explicit unsupported action must stop the whole request')
 if len(expanded)>MAX_VISITS:
  if raw['execution_order']:raise ValueError('Excess visit count must not be truncated')
  status='error';reason=f'訪問回数{len(expanded)}回は上限{MAX_VISITS}回を超えます。切り詰めず拒否します。'
 if status=='ready':
  validate_grounding(requested,instruction,meta,number)
  order(raw['execution_order'])
  if raw['execution_order']!=expanded:raise ValueError('Execution sequence differs from filtered requested visits')
  # These checks can only reject AI results. They never construct a replacement route.
  aliases={a:k for k,o in meta['objects'].items() for a in o['aliases']}
  alias_pattern='|'.join(re.escape(a) for a in sorted(aliases,key=len,reverse=True))
  for hit in re.finditer('('+alias_pattern+r')(?:を)?\s*([0-9一二三四五六七八九十百千〇零]+)\s*(?:回|度)',t):
   count=number(hit[2]);target=aliases[hit[1]]
   if count>MAX_VISITS:raise ValueError('Explicit visit count exceeds limit; no truncation')
   if expanded.count(target)<count:raise ValueError('Explicit visit count omitted')
  if any(w in t for w in ['適当に','どれか']):raise ValueError('Explicit ambiguous target cannot become ready')
  for hit in re.finditer('('+alias_pattern+')(?:の)(前|後)に('+alias_pattern+')',t):
   first=aliases[hit[1]];second=aliases[hit[3]]
   if first not in expanded or second not in expanded:raise ValueError('Explicit before/after target omitted')
   a,b=(second,first) if hit[2]=='前' else (first,second)
   if a==b or expanded.index(a)>=expanded.index(b):raise ValueError('Explicit before/after relation contradicted')
  complex_terms=['前','後','回','度','もう','再確認','再度','いや','訂正','やっぱり','不要','除外','飛ば','見なく','なくて','ないで']
  if not any(w in t for w in complex_terms):
   stated=[resolve(x,meta) for x in re.findall(alias_pattern,t)]
   if stated and stated!=expanded:raise ValueError('Explicit target omitted or changed')
   unknown_stated=[resolve(x,meta) for x in mentions(t) if resolve(x,meta) not in meta['objects']]
   if unknown_stated and Counter(unknown_stated)!=Counter(x for x in requested if x not in meta['objects']):raise ValueError('Explicit nonexistent target omitted or changed')
 elif raw['execution_order']:raise ValueError('Non-ready execution sequence must be empty')
 if status=='no_valid_targets' and (expanded or not skips):raise ValueError('Invalid no-valid-targets status')
 return {'requested_targets':requested,'execution_order':raw['execution_order'] if status=='ready' else [],'skipped_targets':skips,'status':status,'reason':reason,'requested_valid_visits':len(expanded)}


def signature(plan):
 return {k:plan[k] for k in ['status','execution_order','requested_targets','skipped_targets']}


def interpret(raw,instruction,meta):
 """Compile the AI's one ordered request list; ONLY nonexistent names are filtered.

 Execution and skip lists are computed, not guessed by a second text generation.
 The raw request order is never replaced or repaired.
 """
 schema_check(raw,generation_schema(instruction,meta))
 policy=source_policy(instruction,meta)
 if policy:
  return {'requested_targets':[],'execution_order':[],'skipped_targets':[],**policy,'requested_valid_visits':0}
 requested=[resolve(x,meta) for x in raw['requested_targets']]
 executable=[x for x in requested if x in meta['objects']]
 status=raw['status'];reason=raw['reason']
 if status=='ready' and len(executable)>MAX_VISITS:status='error';reason=f'訪問回数{len(executable)}回は上限10回を超えます。切り詰めず拒否します。'
 if status=='ready' and requested and not executable:status='no_valid_targets';reason='要求された対象物は全て未登録です。動作しません。'
 envelope={'requested_targets':requested,'execution_order':executable if status=='ready' else [],'skipped_targets':[{'target':x,'reason':'not_registered'} for x in requested if x not in meta['objects']],'status':status,'reason':reason}
 return normalize(envelope,instruction,meta)


def generation_schema(instruction,meta):
 """Constrain target set/count and only the positions of explicit unknown colours.

 Registered-target order is still generated by Qwen and independently audited.
 An invalid response is rejected, never replaced with the input audit's sequence.
 """
 schema=json.loads(json.dumps(LLM_SCHEMA))
 if source_policy(instruction,meta):return schema
 try:expected=source_sequence(instruction,meta,number)
 except ValueError:return schema
 registered=sorted({target for target in expected if target in meta['objects']})
 if 1<=len(expected)<=128 and sum(target in meta['objects'] for target in expected)<=MAX_VISITS:
  field=schema['properties']['requested_targets']
  field.update(minItems=len(expected),maxItems=len(expected),items={'type':'string','enum':sorted(set(expected))})
  if any(target not in meta['objects'] for target in expected):
   prefix=[]
   for target in expected:
    choices=registered if target in meta['objects'] else sorted({name for name in UNKNOWN_COLOURS if resolve(name,meta)==target})
    if not choices:return schema  # Do not guess a representation for an unsupported target.
    prefix.append({'type':'string','enum':choices})
   field.pop('items')  # Tuple decoding: avoid a generic items rule shadowing prefixItems.
   field['prefixItems']=prefix
 return schema
