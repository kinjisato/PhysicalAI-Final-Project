"""Real Ollama Qwen2.5 inference, strict order contract, no fallback."""
import argparse
import datetime
import json
import os
import urllib.request
from core import ROOT, digest, order, save

MODEL = 'qwen2.5:3b'
HEADER = '''Extract the visit order from the Japanese instruction below. Output JSON only.
Mapping: A=青色/青/右/近い/低い, B=黄色/黄/中央/中距離/高い, C=緑色/緑/左/遠い/中間の高さ.
Convert each mentioned object to its letter, keeping exactly the user's sequence.
Ignore Home (it means return home after visiting the objects).
Return {"order":["A","B","C"]} with the letters in the requested order.
If no complete sequence of three different objects is given, return {"order":[]}.
Japanese instruction:
'''


def validate_evidence(doc):
    if doc.get('schema') != 'minimal-ai-1' or doc.get('model') != MODEL or doc.get('done') is not True:
        raise ValueError('Unconfirmed Qwen inference')
    if doc.get('sha256') != digest({k:v for k,v in doc.items() if k != 'sha256'}):
        raise ValueError('Evidence checksum mismatch')
    if doc['request'].get('model') != MODEL or doc['request'].get('prompt') != HEADER + doc['instruction']:
        raise ValueError('Request provenance mismatch')
    raw = json.loads(doc['raw_response'])
    if set(raw) != {'order'} or order(raw['order']) != doc.get('order'):
        raise ValueError('Raw inference and action order differ')
    return doc['order']


def infer(text, host='http://127.0.0.1:11434'):
    if not isinstance(text, str) or not text.strip() or len(text) > 2000:
        raise ValueError('Empty or excessive instruction')
    text = text.strip()
    schema = {'type':'object', 'properties':{'order':{'type':'array','items':{'type':'string','enum':['A','B','C']}}}, 'required':['order'], 'additionalProperties':False}
    payload = {'model':MODEL, 'prompt':HEADER+text, 'stream':False,
               'format':schema, 'options':{'temperature':0, 'num_predict':100}}
    request = urllib.request.Request(host.rstrip('/')+'/api/generate',
                data=json.dumps(payload,ensure_ascii=False).encode(), headers={'Content-Type':'application/json'})
    with urllib.request.urlopen(request, timeout=120) as response:
        received = json.load(response)
    raw = json.loads(received['response'])
    if set(raw) != {'order'}:
        raise ValueError('Unexpected AI output fields')
    doc = {'schema':'minimal-ai-1', 'model':received.get('model'), 'done':received.get('done'),
           'instruction':text, 'order':order(raw['order']), 'request':payload,
           'raw_response':received['response'], 'endpoint':host.rstrip('/')+'/api/generate',
           'recorded_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),
           'eval_count':received.get('eval_count'), 'interpretation_source':'actual_ollama_no_fallback'}
    doc['sha256'] = digest(doc); validate_evidence(doc)
    return doc


if __name__ == '__main__':
    p=argparse.ArgumentParser();p.add_argument('--instruction',required=True)
    p.add_argument('--host',default=os.environ.get('PAI_OLLAMA_HOST','http://127.0.0.1:11434'))
    p.add_argument('--output',type=str,default=str(ROOT/'results/ai.json'));a=p.parse_args()
    try:
        d=infer(a.instruction,a.host);save(a.output,d);print(json.dumps({'order':d['order'],'evidence':a.output},ensure_ascii=False))
    except Exception as exc:
        p.exit(1,'AI解析失敗。動作しません: '+str(exc)+'\n')
