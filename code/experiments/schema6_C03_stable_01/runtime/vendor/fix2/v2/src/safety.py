"""Deterministic, input-grounded vetoes. This module never supplies an execution route.

A closed set of target aliases and explicit unregistered colours is accepted. Other
references and uncovered grammar stop for clarification; an LLM cannot waive this.
"""
import re
import unicodedata

UNKNOWN_COLOURS=['赤色','赤','紫色','紫','白色','白','黒色','黒','ピンク','オレンジ','茶色','灰色','銀色','金色','水色']
UNSUPPORTED=re.compile(r'掴|つか[むんまめ]|把持|持ち上|運[ぶんべ搬]|搬送|移動|撮影|カメラ|異常.{0,8}判定|異常判定|判定')
AMBIGUOUS=re.compile(r'適当|どれか|どちらか|おまかせ|お任せ|ランダム|不明|わから|未指定|別の|もう一つ|例の|あっち|そっち|あれ|これ|それ|何か|どこか|好きな|全部|すべて|全て')
EXCLUSION=re.compile(r'不要|除外|飛ば|見なく|なくていい|ないで')

def target_hits(text,meta):
    aliases={a:k for k,o in meta['objects'].items() for a in o['aliases']}
    aliases.update({x:x.removesuffix('色') for x in UNKNOWN_COLOURS})
    pattern='|'.join((r'(?<![A-Za-z])'+re.escape(a)+r'(?![A-Za-z])') if a in 'ABC' else re.escape(a) for a in sorted(aliases,key=len,reverse=True))
    return [(m.start(),m.end(),aliases[m[0]]) for m in re.finditer(pattern,text)]


def source_policy(instruction,meta):
    text=unicodedata.normalize('NFKC',instruction).strip()
    if UNSUPPORTED.search(text):
        return {'status':'unsupported','reason':'把持・持ち上げ・運搬・移動・異常判定・撮影は未対応です。接近へ読み替えず、要求全体を停止します。'}
    if AMBIGUOUS.search(text):
        return {'status':'clarification_required','reason':'対象または順序を一意に確定できません。対象・順序を具体的に指定してください。'}
    if '\x00' in text:
        return {'status':'clarification_required','reason':'入力に未対応の制御文字があります。'}
    hits=target_hits(text,meta)
    if not hits:
        return {'status':'clarification_required','reason':'対象物の指定がありません。挨拶や雑談から訪問順序を生成しません。'}
    corrections=list(re.finditer(r'いや|訂正|やっぱり',text))
    if len(corrections)>1 or (corrections and len(target_hits(text[:corrections[0].start()],meta))>1):
        return {'status':'clarification_required','reason':'訂正が複数の対象や指示に及び一意に確定できません。訂正後の対象列を指定してください。'}
    # Literal lists are commands too, but a colour appearing in ordinary prose is not.
    residue=text
    for start,end,_ in reversed(hits):residue=residue[:start]+' \x00 '+residue[end:]
    if not re.search(r'点検|確認|見て|見る|チェック|近づ|伸ば|お願い',text):
        if re.search(r'\x00\s*(?:は|が)\s*\x00',residue):
            return {'status':'clarification_required','reason':'対象の説明だけでは訪問意図が不明です。接近する対象と順序を指定してください。'}
    # All remaining words must belong to the supported command grammar. Unknown
    # nouns/references/verbs are never interpreted as nonexistent objects to skip.
    words=['\x00','確認していただけますか','確認してください','点検してください','アームを伸ばして','アームを伸ばす',
           'チェックしてください','チェックして','チェックする','確認する','確認して','確認','点検する','点検して','点検',
           '近づいて','近づく','見てください','見て','見る','見','なくていい','ないで','不要','除外','飛ばして',
           '最初に','最初は','続いて','そのあと','その後','その次に','最後に','終わりに','次に','まず','最後','最初',
           'もう一度','再確認','再度','いや','訂正','やっぱり','だけ','この順で','順に','順で','順番で','順番に',
           'お願い','背の','対象物','対象','物','残り','うち','した','する','して','から','その','あと','後','前','先に',
           'を','の','に','へ','と','は','が','い','回','度']
    allowed='|'.join(re.escape(w) for w in sorted(words,key=len,reverse=True))
    residue=re.sub(allowed,'',residue)
    residue=re.sub(r'[\s、。，．,.!！?？:：;；→⇒/\-()（）0-9一二三四五六七八九十百千〇零]+','',residue)
    if residue:
        return {'status':'clarification_required','reason':'対応する対象・接近指示として確定できない表現があります。対象と動作を明確にしてください。'}
    return None


def source_sequence(instruction,meta,number):
    """Compile only a validation expectation. Never used as a robot command/fallback."""
    text=unicodedata.normalize('NFKC',instruction).strip()
    # A correction replaces the preceding incomplete request. More elaborate or
    # multiple corrections are intentionally left for clarification by the policy.
    corrections=list(re.finditer(r'いや|訂正|やっぱり',text))
    if corrections:text=text[corrections[-1].end():]
    hits=target_hits(text,meta)
    excluded=set()
    for i,(_,end,target) in enumerate(hits):
        tail=text[end:hits[i+1][0] if i+1<len(hits) else len(text)]
        if EXCLUSION.search(tail):excluded.add(target)
    relation= re.search(r'(前|後)に', text[hits[0][1]:hits[1][0]]) if len(hits)==2 else None
    if relation and not excluded and not re.search(r'[0-9一二三四五六七八九十]+\s*(回|度)',text):
        return [hits[1][2],hits[0][2]] if relation[1]=='前' else [hits[0][2],hits[1][2]]
    # Relations embedded in longer routes are not safely certified by this subset.
    if re.search(r'前に',text) or (len(hits)>2 and re.search(r'の後に',text)):
        raise ValueError('複合的な前後関係は確認が必要です。順番を対象名の列で指定してください。')
    result=[]
    for i,(_,end,target) in enumerate(hits):
        if target in excluded:continue
        tail=text[end:hits[i+1][0] if i+1<len(hits) else len(text)]
        count_hit=re.match(r'(?:を)?\s*([0-9一二三四五六七八九十百千〇零]+)\s*(回|度)',tail)
        count=number(count_hit[1]) if count_hit else 1
        if count<1 or count>10:raise ValueError('訪問回数は1〜10回です。切り詰めず拒否します。')
        result.extend([target]*count)
    # A target-less 'もう一度' after a visit is an additional request; when attached
    # to the next explicit target it already corresponds to that next occurrence.
    if hits and re.search(r'もう一度|再度|再確認',text[hits[-1][1]:]):
        tail=text[hits[-1][1]:]
        if re.search(r'(?:して|見て|確認[し。、、])[^。]*もう一度',tail):result.append(hits[-1][2])
    return result


def validate_grounding(requested,instruction,meta,number):
    policy=source_policy(instruction,meta)
    if policy:raise ValueError(policy['reason'])
    expected=source_sequence(instruction,meta,number)
    if requested!=expected:raise ValueError('入力の対象・順序・回数・除外・訂正とAI出力が一致しません。動作を停止します。')
