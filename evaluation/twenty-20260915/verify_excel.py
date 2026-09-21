"""Read-only source verification independent of application ingestion and generated SQL."""
import hashlib,json,sqlite3,sys
from collections import Counter
from pathlib import Path
import openpyxl
source=Path(sys.argv[1]); target=Path(sys.argv[2]); out=Path(__file__).parent
book=openpyxl.load_workbook(source,read_only=True,data_only=True)
sheet=book.active;sheet.reset_dimensions(); iterator=sheet.iter_rows(values_only=True);headers=next(iterator); raw=[dict(zip(headers,r)) for r in iterator if r[0] is not None]
def val(v):
 if v is None:return None
 if isinstance(v,float) and v.is_integer():v=int(v)
 return str(v).strip() or None
def attended(r,event):return val(r.get(event))=='1'
t='4月28日【主题大会】';m='4月28日【音乐节】'
checks={'registrations':len(raw),'O01':sum(r['品牌']=='CHERY' for r in raw),'O02':sum(r['品牌']=='CHERY' and attended(r,t) for r in raw),'O03':sum(r['品牌']=='EXEED' and attended(r,t) for r in raw),'O04':sum(r['邀请国家'] in ['英国','UK'] for r in raw),'O08':sum(attended(r,t) and attended(r,m) for r in raw),'N01':sum(r['品牌']=='O&J' and (attended(r,t) or attended(r,m)) for r in raw),'N02':sum(r['品牌']=='O&J' and attended(r,t) and not attended(r,m) for r in raw),'N05':sum(val(r['所在公司名']) is None for r in raw),'N06':sum(attended(r,'4月26日icar品牌伙伴峰会') for r in raw)}
manifest=json.loads((out/'manifest.json').read_text());expected={c['id']:c.get('expected_rows') for c in manifest['cases']}
scalar_matches={k:v==expected[k][0][0] for k,v in checks.items() if k in expected}
conn=sqlite3.connect(target.as_uri()+'?mode=ro',uri=True)
fields={'registration_id':'序号/No.','full_name':'全名【与护照上的顺序保持一致】','brand':'品牌','country':'邀请国家','company_name':'所在公司名','job_title':'职务','inbound_flight_no':'入境航班号'}
actual={r[0]:r for r in conn.execute('SELECT '+','.join(fields)+' FROM registrations WHERE snapshot_id=?',(manifest['snapshot'],))}
errors=[]
for r in raw:
 wanted=tuple(val(r[h]) for h in fields.values()); got=actual.get(wanted[0]);
 if got is None or tuple(val(v) for v in got)!=wanted:errors.append({'registration_id':wanted[0],'fields':[f for i,f in enumerate(fields) if got is None or got[i]!=wanted[i]]})
source_answers={k:[[v]] for k,v in checks.items() if k in expected}
source_answers['O05']=sorted([[h[len('4月26日'):]] for h in headers[24:] if h.startswith('4月26日') and any(r['品牌']=='CHERY' and attended(r,h) for r in raw)])
source_answers['O06']=[[val(r['序号/No.']),val(r['全名【与护照上的顺序保持一致】'])] for r in sorted(raw,key=lambda r:val(r['序号/No.'])) if attended(r,t)]
source_answers['N03']=[list(x) for x in sorted(Counter(r['邀请国家'] for r in raw if r['品牌']=='O&J').items(),key=lambda x:(-x[1],x[0] or ""))[:5]]
source_answers['N04']=[[round(100*sum(r['品牌']=='CHERY' and r['签证是否办毕']=='是' for r in raw)/checks['O01'],2)]]
source_answers['N07']=[[val(r[h]) for h in ['序号/No.','全名【与护照上的顺序保持一致】','所在公司名','职务','入境航班号']] for r in sorted((r for r in raw if r['品牌']=='CHERY'),key=lambda r:val(r['序号/No.']))[:5]]
source_answers['N08']=sorted([[h[len('4月27日'):],sum(attended(r,h) for r in raw)] for h in headers[24:] if h.startswith('4月27日')])
source_answers['N09']=[[val(r['全名【与护照上的顺序保持一致】']),val(r['所在公司名'])] for r in raw if r['邀请国家']=='格陵兰']
source_answers['N10']=[[s,sum(r['品牌']=='CHERY' and val(r['签证是否办毕'])==v for r in raw)] for s,v in [('completed','是'),('not_required','无需办理'),('unknown',None)]]
source_matches={k:[[val(x) for x in row] for row in v]==[[val(x) for x in row] for row in expected[k]] for k,v in source_answers.items()}
result={'source_answer_matches_sql_oracle':source_matches,'all_17_answerable_references_verified_against_excel':len(source_matches)==17 and all(source_matches.values()),'source_name':source.name,'source_sha256':hashlib.sha256(source.read_bytes()).hexdigest(),'record_count':len(raw),'source_field_count':len(headers),'scalar_checks':checks,'scalar_matches':scalar_matches,'all_registration_fields_compared':list(fields),'registration_field_mismatches':errors,'chery_visa_raw_distribution':dict(Counter(str(r['签证是否办毕']) for r in raw if r['品牌']=='CHERY'))}
(out/'source-verification.json').write_text(json.dumps(result,ensure_ascii=False,indent=2))
print(json.dumps(result,ensure_ascii=False,indent=2))
