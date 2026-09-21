"""Offline comparison only. Does not call a model or modify business data."""
import hashlib,itertools,json,sqlite3,statistics
from pathlib import Path
HERE=Path(__file__).parent;ROOT=HERE.parents[1]
manifest=json.loads((HERE/'manifest.json').read_text());results=json.loads((HERE/'results.json').read_text());specs={c['id']:c for c in manifest['cases']}
def norm(x):
 if x is None or x=='':return None
 return x

def compare(actual,expected,kind):
 if kind in ('scalar','percentage'):
  return len(actual)==1 and any(isinstance(v,(int,float)) and abs(v-expected[0][0])<0.00001 for v in actual[0].values())
 if kind=='events':return sorted(r.get('event_name') for r in actual)==sorted(r[0] for r in expected)
 if kind=='detail_membership':
  allowed={r[0] for r in expected};ids=[r.get('registration_id') for r in actual]
  return len(ids)==10 and len(set(ids))==10 and set(ids)<=allowed
 if not expected:return actual==[]
 if len(actual)!=len(expected):return False
 cols=list(actual[0]);width=len(expected[0])
 aliases={'已完成':'completed','无需办理':'not_required','未知':'unknown'}
 for selected in itertools.permutations(cols,width):
  rows=[[norm(r[k]) for k in selected] for r in actual]
  if kind=='status_groups':
   rows=[[aliases.get(v,v) for v in r] for r in rows]
   if sorted(rows)==sorted(expected):return True
  elif rows==expected:return True
 return False

audit=sqlite3.connect(HERE/'audit.db');audit.row_factory=sqlite3.Row
traces={r['trace_id']:dict(r) for r in audit.execute('SELECT * FROM query_trace_requests')}
checked=[]
with sqlite3.connect((ROOT/'data/chery-excel.db').as_uri()+'?mode=ro',uri=True) as db:
 for rec in results['cases']:
  c=specs[rec['id']];p=rec.get('payload')or{};o=p.get('outcome')or{};q=p.get('query')or{};result=q.get('result');presentation=(p.get('presentation')or{}).get('answer')or{}
  if c['kind']=='clarification':
   behavior=q.get('status')=='clarification' and {v['candidate_id'] for v in (q.get('pending_choice')or{}).get('candidates',[])}=={'1410','1411'}
  elif c['kind']=='unavailable':
   behavior=not q and o.get('status') in ('unavailable','clarification') and '没有' in rec.get('text','') and '签到' in rec.get('text','')
  elif c['kind']=='rejected':behavior=o.get('status')=='rejected' and not q
  else:behavior=bool(result is not None and q.get('status')=='ok' and compare(result['rows'],c['expected_rows'],c['kind']))
  contract=behavior and (c['kind']!='unavailable' or (o.get('status')=='unavailable' and o.get('reason')=='data_missing'))
  replay=None
  if result is not None:
   sql=result['sql'];cur=db.execute(sql['sql'],sql['parameters']);cols=[x[0] for x in cur.description];replayed=[dict(zip(cols,r)) for r in cur.fetchall()]
   replay=replayed==result['rows']
  trace=traces.get(p.get('trace_id'));stage_rows=list(audit.execute('SELECT * FROM query_trace_stages WHERE trace_id=?',(p.get('trace_id'),)))
  audit_ok=bool(trace and not trace['logging_failed'] and stage_rows and all(s['finished_at'] is not None for s in stage_rows))
  narrative_ok=(presentation.get('narration_status')=='ok' if result and result['rows'] else True)
  item={'id':rec['id'],'question':rec['question'],'answerable':bool(c['reference_sql']),'answer_behavior_pass':behavior,'canonical_contract_pass':contract,'narration_completed':narrative_ok,'context_saved':p.get('context_saved',False),'sql_replay_equal':replay,'audit_complete':audit_ok,'strict_module_closure':bool(contract and narrative_ok and audit_ok and p.get('context_saved')),'seconds':rec['seconds'],'audit_model_calls':sum(s['stage']=='model_call' for s in stage_rows),'actual_rows':result['rows'] if result is not None else None,'narrative':presentation.get('narrative'),'outcome_status':o.get('status'),'outcome_reason':o.get('reason'),'query_status':q.get('status'),'trace_id':p.get('trace_id')}
  checked.append(item)
summary={'cases':len(checked),'answer_behavior_pass':sum(c['answer_behavior_pass'] for c in checked),'answerable_cases':sum(c['answerable'] for c in checked),'data_answer_pass':sum(c['answer_behavior_pass'] and c['answerable'] for c in checked),'canonical_contract_pass':sum(c['canonical_contract_pass'] for c in checked),'strict_module_closure':sum(c['strict_module_closure'] for c in checked),'audit_complete_cases':sum(c['audit_complete'] for c in checked),'context_saved_cases':sum(c['context_saved'] for c in checked),'audit_model_calls':sum(c['audit_model_calls'] for c in checked),'mean_seconds':statistics.mean(c['seconds'] for c in checked),'median_seconds':statistics.median(c['seconds'] for c in checked),'max_seconds':max(c['seconds'] for c in checked),'business_database_unchanged':hashlib.sha256((ROOT/'data/chery-excel.db').read_bytes()).hexdigest()==manifest['database_sha256'],'business_code_unchanged':all(hashlib.sha256((ROOT/p).read_bytes()).hexdigest()==sha for p,sha in manifest['code_sha256'].items()),'model_judge_calls':0,'note':'Narrative content requires manual review in report; narration_completed only checks technical completion.'}
(HERE/'scores.json').write_text(json.dumps({'summary':summary,'cases':checked},ensure_ascii=False,indent=2))
print(json.dumps(summary,ensure_ascii=False,indent=2))
