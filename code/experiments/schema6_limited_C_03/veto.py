"""Independent vetoes: verify AI intent claims; never return a replacement route."""
import re,unicodedata
from collections import Counter
from scene import UNKNOWN,metadata
BANNED=re.compile(r'掴|つか[むんまめ]|把持|持ち上|運[ぶんべ搬]|搬送|移動|撮影|カメラ|異常.{0,8}判定|異常判定|判定')
AMBIGUOUS=re.compile(r'適当|何か|どれか|どちらか|おまかせ|お任せ|ランダム|不明|わから|未指定|別の|もう一つ|例の|あっち|そっち|あれ|これ|それ|どこか|好きな|たぶん|かもしれ|なくはない|ないわけ')
NEGATIVE=re.compile(r'不要|除外|飛ば|見なく|なくていい|ないで|やめ|無視|対象外')
class AuditError(ValueError):pass
_NAME_IDS={o['aliases'][1]:k for k,o in metadata()['objects'].items()}
def canonical(x):
 name=x.removesuffix('色') if x not in ('茶色','灰色','銀色','金色','水色') else x
 return _NAME_IDS.get(name,name)
def number(s):
 if s.isdecimal():return int(s)
 digits={'一':1,'二':2,'三':3,'四':4,'五':5,'六':6,'七':7,'八':8,'九':9,'〇':0,'零':0};units={'十':10,'百':100,'千':1000};total=current=0
 for c in s:
  if c in digits:current=digits[c]
  elif c in units:total+=(current or 1)*units[c];current=0
  else:raise AuditError('Unsupported number')
 return total+current
def references(text,meta):
 aliases={x:k for k,v in meta['objects'].items() for x in v['aliases']}
 for x in UNKNOWN:
  aliases[x]=canonical(x)
  if not x.endswith('色'):aliases[x+'色']=canonical(x)
 pattern='|'.join(r'(?<![A-Za-z])'+re.escape(x)+r'(?![A-Za-z])' if x in ('A','B','C') else re.escape(x) for x in sorted(aliases,key=len,reverse=True))
 return [(m.start(),m.end(),aliases[m[0]],m[0]) for m in re.finditer(pattern,text)]
def inspect_intent(instruction,plan,meta):
 text=unicodedata.normalize('NFKC',instruction).strip()
 if BANNED.search(text):return {'status':'unsupported','reason':'把持・運搬・撮影・異常判定等は未対応'}
 if AMBIGUOUS.search(text) or '\x00' in text:return {'status':'clarification_required','reason':'対象または順序を一意に確認できない'}
 corrections=list(re.finditer(r'いや|訂正|やっぱり',text))
 if len(corrections)>1:return {'status':'clarification_required','reason':'複数訂正の範囲を確認できない'}
 active=text
 if corrections:
  mark=corrections[0];before=text[:mark.start()];after=text[mark.end():]
  if not NEGATIVE.search(after):
   if len(references(before,meta))>1:return {'status':'clarification_required','reason':'訂正対象が複数あり一意でない'}
   active=after
 hits=references(active,meta)
 # Spatial selection is checked directly against measured/frozen scene facts.
 selection=re.fullmatch(r'(?:対象を)?(近い|遠い|高い|低い)順に([0-9一二三四]+)(?:つ|個|対象)(?:を)?(?:点検して|確認して|見て|近づいて)',active)
 spatial=None
 if selection:
  count=number(selection[2]);field='distance_m' if selection[1] in ('近い','遠い') else 'height_m'
  if not 1<=count<=len(meta['objects']):return {'status':'error','reason':'空間選択の個数がシーン範囲外'}
  spatial=sorted(meta['objects'],key=lambda k:meta['objects'][k][field],reverse=selection[1] in ('遠い','高い'))[:count]
 if not hits and spatial is None:return {'status':'clarification_required','reason':'具体的な対象指定を確認できない'}
 if spatial is None:
  residue=active
  for start,end,_,_ in reversed(hits):residue=residue[:start]+' '+residue[end:]
  timing=['最初に','最初は','続いて','そのあと','その後','その次に','最後に','終わりに','次に','まず','最後','最初','この順で','順に','順で','順番で','順番に']
  literal=residue
  for word in sorted(timing,key=len,reverse=True):literal=literal.replace(word,'')
  literal=re.sub(r'[\s、。，．,.!！?？:：;；→⇒/と]+','',literal)
  if not re.search(r'点検|確認|見て|見る|チェック|近づ|伸ば|お願い',active) and literal:
   return {'status':'clarification_required','reason':'対象の説明だけでは訪問意図を確認できない'}
  words=timing+['確認していただけますか','確認してください','点検してください','アームを伸ばして','チェックしてください','チェックして','チェックする','確認した','確認して','確認する','確認し','確認','点検する','点検して','点検','近づいて','近づく','見てください','見て','見る','なくていい','ないで','不要','除外','飛ばして','飛ば','見なくていい','見なく','やめて','やめ','無視','対象外','もう一度','再確認','再度','いや','訂正','やっぱり','だけ','お願い','対象物','対象','残り','うち','した','する','して','から','あと','後','前','先に','を','の','に','へ','と','は','が','い','回','度']
  for word in sorted(words,key=len,reverse=True):residue=residue.replace(word,'')
  residue=re.sub(r'[\s、。，．,.!！?？:：;；→⇒/\-()（）0-9一二三四五六七八九十百千〇零]+','',residue)
  if residue:return {'status':'clarification_required','reason':'原文の対象/動作/関係を独立に確認できない'}

 # Non-ready plans never receive a replacement plan or permission to move.
 if plan['status']!='ready':return {'status':plan['status'],'reason':plan['reason']}
 targets=[canonical(x) for x in plan['targets']]
 if spatial is not None:
  if targets!=spatial:raise AuditError('Spatial selection differs from scene facts')
  return {'status':'ready','reason':'空間参照と計画が一致','excluded':[]}
 forbidden=set();groups=[]
 for i,(start,end,target,phrase) in enumerate(hits):
  tail=active[end:hits[i+1][0] if i+1<len(hits) else len(active)]
  if NEGATIVE.search(tail):forbidden.add(target)
  repeat=re.match(r'(?:を)?\s*([0-9一二三四五六七八九十百千〇零]+)\s*(?:回|度)',tail)
  count=number(repeat[1]) if repeat else 1
  if count<1 or count>10:return {'status':'error','reason':'回数は1〜10回。切り詰めない'}
  groups.append((target,count))
 groups=[g for g in groups if g[0] not in forbidden]
 if len(hits)==2 and re.search(r'前に',active[hits[0][1]:hits[1][0]]):groups=list(reversed(groups))
 elif re.search(r'前に',active):raise AuditError('Complex before relation cannot be independently certified')
 if hits and re.search(r'(?:して|見て|確認し).*もう一度',active[hits[-1][1]:]):groups.append((hits[-1][2],1))
 counts=Counter()
 for target,count in groups:counts[target]+=count
 if sum(n for k,n in counts.items() if k in meta['objects'])>10:return {'status':'error','reason':'訪問上限10回を超える。切り詰めない'}
 if set(targets)!=set(counts):raise AuditError('target_mismatch')
 if Counter(targets)!=counts:raise AuditError('count_mismatch')
 cursor=0
 for target,count in groups:
  if targets[cursor:cursor+count]!=[target]*count:raise AuditError('order_mismatch')
  cursor+=count
 # Reject target references that the lexical audit cannot certify, rather than inventing routes.
 if re.search(r'箱|ボトル|机|人|障害物|よりも|交互|逆順',active):raise AuditError('Uncertified target or relation')
 return {'status':'ready','reason':'対象・順序・回数・否定と独立監査が一致','excluded':sorted(forbidden)}
