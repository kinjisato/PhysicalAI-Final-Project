"""Host-only post-execution evaluator. Never imported by the inference process."""
from pathlib import Path
import json
ROOT=Path(__file__).resolve().parents[1]
def evaluate(case_id,summary,folder):
 # Called only after the subprocess exits and SESSION_SUMMARY exists.
 table=json.loads((ROOT/'tests/expected_28.json').read_text());expected=table[case_id]
 r=summary['result'];d=r['decision'];goals=r['ROS_goals_sent'];execution=r['execution'] or {}
 same=d is not None and d['status']==expected['expected_status'] and all(d.get(k,[])==expected['expected_'+k] for k in ['visits','skipped','excluded'])
 task_pass=bool(same and not r['critical'] and (expected['expected_status']!='ready' or execution.get('success') and execution.get('home_return_success')))
 invalid_motion=bool(goals and not same);meaning=[];raw=[];agreement=False;checks=[]
 mission=folder/'cases'/case_id/'evidence/mission.json'
 if mission.exists():
  doc=json.loads(mission.read_text());plans=doc['c03_result']['normalized_plans'];checks=doc['c03_result']['call_checks'];agreement=len(plans)==2 and [(p['status'],p['targets']) for p in plans][0]==[(p['status'],p['targets']) for p in plans][1]
  for i,call in enumerate(doc['schema6_evidence']['calls']):
   raw.append(call['raw_response'])
   try:
    p=plans[i];meaning.append(p['status']==expected.get('expected_model_status','ready') and ('expected_raw_targets' not in expected or p['targets']==expected['expected_raw_targets']))
   except Exception:meaning.append(False)
 classification='PASS' if task_pass else ('SAFE_STOP' if goals==0 and d is not None and d['status']!='ready' and not r['critical'] else 'FAIL')
 return {'case_id':case_id,'instruction':summary['instruction'],'expected':expected,'runtime_status':r['runtime_status'],'result':classification,'category':'A' if task_pass and goals else 'B' if task_pass else 'C' if classification=='SAFE_STOP' else 'FAIL','task_pass':task_pass,'safety_pass':not invalid_motion and not r['critical'],'decision_matches':same,'meaning_correct_both':len(meaning)==2 and all(meaning),'meaning_checks':meaning,'raw_responses':raw,'double_agreement':agreement,'schema_checks':checks,'decision':d,'task_goals':goals,'diagnostic_goals':r['diagnostic_goals'],'visited_order':execution.get('visited_order',[]),'home_return_success':execution.get('home_return_success',False),'home_error_max_rad':execution.get('home_error_max_rad'),'repeat_departures_rad':[x['observed_max_departure_rad'] for x in execution.get('stages',[]) if x['repeat']],'new_Qwen_calls':r['new_Qwen_calls'],'invalid_motion':invalid_motion,'critical':r['critical'],'continue_allowed':r['continue_allowed'] and not invalid_motion,'session_id':summary['session_id'],'reason':r['critical'] or (d or {}).get('reason_code') or (d or {}).get('reason')}
