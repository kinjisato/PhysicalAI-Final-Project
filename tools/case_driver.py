"""Sequential host driver; only input text and ID cross into the runtime."""
from pathlib import Path
import argparse,json,os,subprocess,sys,uuid
import manage
from evaluate_cases import evaluate
ROOT=Path(__file__).resolve().parents[1]
def ordered(inputs):
 ids=['T02','T01','T03','T04','T05','T06','T07']+[f'P2{x}{n}' for x in 'ABCDE' for n in range(1,4)]+['N01','N02','N03','P3B9','P3B10','P3B11']
 assert set(ids)==set(inputs);return ids

def main(argv=None):
 p=argparse.ArgumentParser();group=p.add_mutually_exclusive_group(required=True);group.add_argument('--case');group.add_argument('--all',action='store_true');a=p.parse_args(argv)
 inputs={x['case_id']:x for x in json.loads((ROOT/'cases/inputs_28.json').read_text())};selected=ordered(inputs) if a.all else [a.case]
 if any(x not in inputs for x in selected):raise ValueError('Unknown case ID')
 _,_,out=manage.settings();out.mkdir(parents=True,exist_ok=True);lock=out/'BATCH.lock';fd=os.open(lock,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600);os.close(fd)
 batch=out/'batches'/uuid.uuid4().hex;batch.mkdir(parents=True,exist_ok=False);results=[];halt=None
 try:
  for case_id in selected:
   if halt:
    results.append({'case_id':case_id,'instruction':inputs[case_id]['instruction'],'result':'NOT_RUN','reason':halt,'new_Qwen_calls':0,'task_goals':0});continue
   before=set((out/'sessions').glob('*/SESSION_SUMMARY.json'));print(json.dumps({'event':'BATCH_CASE_BEGIN','case_id':case_id},ensure_ascii=False),flush=True)
   with (batch/(case_id+'.stdout')).open('w') as stdout,(batch/(case_id+'.stderr')).open('w') as stderr:
    run=subprocess.run([sys.executable,'-B',str(ROOT/'tools/manage.py'),'run','--request-id',case_id,'--text',inputs[case_id]['instruction']],stdout=stdout,stderr=stderr)
   new=set((out/'sessions').glob('*/SESSION_SUMMARY.json'))-before
   if len(new)!=1:
    row={'case_id':case_id,'instruction':inputs[case_id]['instruction'],'result':'NOT_RUN','reason':'Runtime did not produce exactly one new summary; inspect driver logs','new_Qwen_calls':0,'task_goals':0,'continue_allowed':False};halt=row['reason']
   else:
    f=new.pop();summary=json.loads(f.read_text());assert summary['case_id']==case_id and summary['instruction']==inputs[case_id]['instruction'];row=evaluate(case_id,summary,f.parent)
    if run.returncode!=0 or not row['continue_allowed']:halt='Stopped after '+case_id+': '+str(row.get('critical') or row.get('reason'))
   results.append(row);(batch/'RESULTS.json').write_text(json.dumps(results,ensure_ascii=False,indent=2)+'\n');print(json.dumps({'event':'BATCH_CASE_END','case_id':case_id,'result':row['result'],'task_goals':row['task_goals'],'halt':halt},ensure_ascii=False),flush=True)
   if halt:
    subprocess.run([sys.executable,'-B',str(ROOT/'tools/manage.py'),'stop'],check=False)
  (batch/'RESULTS.json').write_text(json.dumps(results,ensure_ascii=False,indent=2)+'\n');print(json.dumps({'event':'BATCH_END','batch':str(batch),'completed':sum(x['result']!='NOT_RUN' for x in results),'halt':halt}),flush=True)
  return 3 if halt else 0
 finally:lock.unlink()
if __name__=='__main__':raise SystemExit(main())
