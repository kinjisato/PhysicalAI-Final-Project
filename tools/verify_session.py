"""Read-only integrity checks, separate from expected-output evaluation."""
from pathlib import Path
import argparse,hashlib,json

def checksum(d):return hashlib.sha256(json.dumps({k:v for k,v in d.items() if k!='sha256'},sort_keys=True,ensure_ascii=False,allow_nan=False).encode()).hexdigest()
def main():
 p=argparse.ArgumentParser();p.add_argument('output',type=Path);a=p.parse_args();rows=[];uuids=[]
 for f in sorted((a.output/'sessions').glob('*/SESSION_SUMMARY.json')):
  s=json.loads(f.read_text());r=s['result']
  if s['action']!='run':continue
  case=f.parent/'cases'/s['case_id'];mf=case/'evidence/mission.json';row={'session_id':s['session_id'],'case_id':s['case_id'],'runtime_status':r['runtime_status'],'critical':r['critical'],'task_goals':r['ROS_goals_sent']}
  if mf.exists():
   d=json.loads(mf.read_text());source=d['schema6_evidence'];assert checksum(d)==d['sha256'] and checksum(source)==source['sha256'];assert source['instruction']==s['instruction'];assert len(source['calls'])==2
   for i,c in enumerate(source['calls']):assert c['request']['model']=='qwen2.5:3b' and c['request']['options']=={'temperature':0,'num_predict':1600,'num_ctx':8192,'seed':i}
   receipts=sorted((case/'evidence').glob('goal_*_accepted.json'));assert len(receipts)==r['ROS_goals_accepted'];assert not r['state_after']['active_ticket']
   if d['decision']['status']!='ready':assert r['ROS_goals_sent']==0
   if r['runtime_status']=='EXECUTED':
    e=r['execution'];assert e['success'] and e['home_return_success'] and e['home_error_max_rad']<=.025;assert e['visited_order']==d['decision']['visits'];assert r['ROS_goals_sent']==r['ROS_goals_succeeded']==len(d['decision']['visits'])+1
    assert [x['target'] for x in e['stages']]==d['decision']['visits']+['Home']
    for i,st in enumerate(e['stages'],1):
     accepted=json.loads((case/f'evidence/goal_{i:02d}_accepted.json').read_text());result=json.loads((case/f'evidence/goal_{i:02d}_result.json').read_text());assert accepted['goal_uuid']==result['goal_uuid']==st['execution']['goal_uuid'];assert result['action_status']==4 and result['controller_error_code']==0;uuids.append(accepted['goal_uuid'])
     if st['repeat']:assert st['observed_max_departure_rad']>=.03
    stop=json.loads((f.parent/'fresh_stop/REUSED_STOP_RESULT.json').read_text());assert stop['status']=='PASS' and stop['cancel']['PASS'] and stop['cancel']['action_status']==5 and stop['cancel']['goal_uuid'] not in uuids
   row['integrity']='PASS'
  else:row['integrity']='INCOMPLETE_NO_MISSION'
  rows.append(row)
 assert len(uuids)==len(set(uuids))
 print(json.dumps({'integrity_status':'PASS' if rows and all(x['integrity']=='PASS' for x in rows) else 'INCOMPLETE','requests':rows,'unique_task_UUIDs':len(uuids),'ROS_calls_from_verifier':0},ensure_ascii=False,indent=2))
 return 0 if rows and all(x['integrity']=='PASS' for x in rows) else 2
if __name__=='__main__':raise SystemExit(main())
