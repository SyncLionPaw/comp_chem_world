#!/usr/bin/env python3
# L1 Deliverables: Check required deliverables for completeness and parseability (including submission.json).
# L2 Execution: No separate execution attestation is implied by checks of submitted results.
# L3 Science: Review of Functional Group Identification Results and Failure Explanations.
"""Terminal-state verification for task 87 (public aggregate reconciliation)."""
import hashlib, json, os, sys
from pathlib import Path

app = Path(os.environ['APP']); tests = Path(os.environ['TESTS']); logs = Path(os.environ['LOGS'])
os.environ['IR_PACKAGE_ROOT'] = str(app)
os.environ['IR_REFERENCE_ROOT'] = str(tests)

INPUT_HASHES = {'SOURCES.yaml': 'c0287683bf3b27d5899515e4b1a2d4edc519da930190fddf44fa344a71e6ae0a', 'figure4_structure_topk.csv': 'cbc7d74acccafb2b37999d283e69c24600d105f3ee05c2ebab096fc28072a519', 'figure5_group_metrics.csv': 'a06ebf12df982afb11d2f2e824d5549c7fa486147f13339dc7354c9cd3dcb1a9', 'figure6_error_over_under.csv': 'bf17893cf7f846256ccb1a3b00c9b8c3453515dfad3c417d3ad7a8cdf13e8408', 'official_main_article.pdf': '4c6442973a4a52bfe43e3cff2d198a8c097d9b233e6425a70eced077b056f6d9', 'official_supplementary_data.xlsx': '026f82ba924f46574d446fd99659f60b38ad1411bfd211b3549345a18175642a', 'official_supplementary_information.pdf': '2d97d6d00d4d2fbf1324a1f2ee0ed59d79e91b5e839bfe1bf666547195526d2d'}

import os, csv, hashlib, json, math, sys
from pathlib import Path
HERE=Path(os.environ.get('IR_PACKAGE_ROOT', str(Path(__file__).resolve().parents[1])))
IN=HERE/'assets'
def _load_refs():
 import json as _j, os as _o
 cands=[]
 r=_o.environ.get('IR_REFERENCE_ROOT')
 if r: cands.append(Path(r)/'refs.json')
 cands.append(Path(__file__).resolve().parent/'refs.json')
 for c in cands:
  if c.is_file():
   return _j.loads(c.read_text(encoding='utf-8'))
 raise Infra('missing or unreadable tests/refs.json')
HASHES=_load_refs()['input_sha256']
class Infra(Exception): pass
class Science(Exception): pass

def read_csv(name):
 p=IN/name
 if not p.is_file() or p.stat().st_size==0: raise Infra(f'missing or empty input: {name}')
 if hashlib.sha256(p.read_bytes()).hexdigest()!=HASHES[name]: raise Infra(f'source hash mismatch: {name}')
 try:
  with p.open(newline='',encoding='utf-8-sig') as f: return list(csv.reader(f))
 except Exception as e: raise Infra(f'cannot parse {name}: {e}')
def validate_sources():
 for name,expected in HASHES.items():
  p=IN/name
  if not p.is_file() or p.stat().st_size==0:raise Infra(f'missing or empty source input: {name}')
  h=hashlib.sha256()
  with p.open('rb') as f:
   for block in iter(lambda:f.read(1024*1024),b''):h.update(block)
  if h.hexdigest()!=expected:raise Infra(f'source hash mismatch: {name}')
def finite(v):
 try:return math.isfinite(float(v))
 except (ValueError,TypeError):return False
def near(a,b,tol=0.00000051): return abs(float(a)-float(b))<=tol
def need(cond,msg):
 if not cond: raise Science(msg)
def num(value, label):
 if not finite(value): raise Science(f'{label} must be finite numeric')
 return float(value)
def source_table_counts(rows):
 if not isinstance(rows,list): raise Science('category_counts must be a list')
 return {(str(x.get('source_id')),x.get('count')) for x in rows if isinstance(x,dict)}
def run(submission):
 validate_sources()
 f4=read_csv('figure4_structure_topk.csv'); f5=read_csv('figure5_group_metrics.csv'); f6=read_csv('figure6_error_over_under.csv')
 for rows,name,nrow,ncol in [(f4,'Figure4',20,6),(f5,'Figure5',16,5),(f6,'Figure6',16,16)]:
  if len(rows)!=nrow or any(len(r)!=ncol for r in rows): raise Infra(f'{name} unexpected dimensions')
 if f4[0]!=['Functional Group','Count','Avg. HAC','Top 1%','Top 5%','Top 10%']: raise Infra('Figure4 header mismatch')
 if f5[0]!=['','count','Precision','Recall','F1']: raise Infra('Figure5 header mismatch')
 if f6[0][0]!='' or len(set(f6[0][1:]))!=15: raise Infra('Figure6 header mismatch')
 for rows in (f4[1:],f5[1:],f6[1:]):
  for row in rows:
   for v in row[1:]:
    if v!='' and not finite(v): raise Infra('non-finite source table value')
 # Cross-check source sheet topology and labels.
 n4=[r[0] for r in f4[1:]]; n5=[r[0] for r in f5[1:]]
 if len(set(n4))!=19 or len(set(n5))!=15 or n5!=[r[0] for r in f6[1:]]: raise Infra('source labels are duplicated or misaligned')
 try: sub=json.loads(Path(submission).read_text(encoding='utf-8'))
 except Exception as e: raise Science(f'invalid submission JSON: {e}')
 if not isinstance(sub,dict): raise Science('submission root must be an object')
 for key in ('summary','figure4_metrics','class_metrics','conditional_confusion','category_counts','cross_table_comparisons','error_relations','interpretations','limitations'):
  if key not in sub: raise Science(f'missing field: {key}')
 def map_rows(field,required_keys):
  arr=sub[field]
  need(isinstance(arr,list),f'{field} must be a list')
  m={}
  for row in arr:
   need(isinstance(row,dict),f'{field} rows must be objects')
   need(set(required_keys).issubset(row),f'{field} row missing fields')
   name=row.get('group')
   need(name not in m,f'duplicate {field} group')
   m[name]=row
  expected=set(n4) if field=='figure4_metrics' else set(groups)
  need(set(m)==expected,f'{field} must cover all source labels')
  return m
 # Expected numbers are recomputed only from source rows.
 data=[]
 for row in f5[1:]:
  name=row[0]
  try: data.append((name,int(row[1]),float(row[2]),float(row[3]),float(row[4])))
  except Exception as e: raise Infra(f'bad Figure5 cell in {name}: {e}')
 groups=[r[0] for r in data]; supports=[r[1] for r in data]
 macro=sum(r[4] for r in data)/len(data); weighted=sum(r[1]*r[4] for r in data)/sum(supports)
 summary=sub['summary']
 if not isinstance(summary,dict): raise Science('summary must be an object')
 need(summary.get('table6_class_count')==len(data),'reported Figure5 class count does not match source')
 need(summary.get('figure4_class_count')==len(n4),'reported Figure4 class count does not match source')
 need(near(num(summary.get('figure4_macro_top1_percent'),'figure4_macro_top1_percent'),sum(float(r[3]) for r in f4[1:])/len(f4[1:]),2e-6),'Figure4 macro top-1 does not match source')
 f4m=map_rows('figure4_metrics',('group','count','top1_percent','top5_percent','top10_percent'))
 for row in f4[1:]:
  got=f4m[row[0]]
  need(got['count']==int(row[1]) and all(near(num(got[k],k),float(v),2e-6) for k,v in [('top1_percent',row[3]),('top5_percent',row[4]),('top10_percent',row[5])]),f'Figure4 metrics mismatch for {row[0]}')
 need(near(num(summary.get('macro_f1'),'macro_f1'),macro,2e-6),'macro_f1 does not match source rows')
 need(near(num(summary.get('support_weighted_f1'),'weighted_f1'),weighted,2e-6),'support_weighted_f1 does not match source rows')
 # Each class row is checked independently; malformed containers return normal FAIL.
 cm=map_rows('class_metrics',('group','support','precision','recall','f1'))
 cf=map_rows('conditional_confusion',('group','tp','fp','fn'))
 for name,n,p,r,f in data:
  got=cm[name]
  need(got['support']==n and all(near(num(got[k],k),v) for k,v in [('precision',p),('recall',r),('f1',f)]),f'class metrics mismatch for {name}')
  c=cf[name]; tp,fp,fn=(c[k] for k in ('tp','fp','fn'))
  need(all(type(x) is int and x>=0 for x in (tp,fp,fn)),f'{name} TP/FP/FN must be nonnegative integers')
  # This is explicitly conditional on interpreting the displayed Count as positives.
  need(tp+fn==n,f'{name} counts fail conditional support identity')
  pp=tp/(tp+fp) if tp+fp else 0.; rr=tp/(tp+fn) if tp+fn else 0.; ff=2*pp*rr/(pp+rr) if pp+rr else 0.
  need(near(pp,p) and near(rr,r) and near(ff,f),f'{name} integers do not reproduce printed rounding')
 # Validate the stated support assumption before conditionally reconstructing counts.
 need(sub.get('conditional_support_assumption')=='figure5_displayed_count_assumed_positive_class_support','conditional confusion support assumption is missing or changed')
 # Validate exact official table row count declarations.
 cc=source_table_counts(sub['category_counts'])
 need(cc=={('si_section6_smarts',21),('si_table5',19),('si_table6',15)},'category count claims do not match distinct official source tables')
 # Verify at least two cross-table comparisons with different source counts.
 comp=sub['cross_table_comparisons']; need(isinstance(comp,list),'cross_table_comparisons must be a list')
 f4counts={r[0]:int(r[1]) for r in f4[1:]}; f5counts={r[0]:int(r[1]) for r in f5[1:]}
 expected_comps={(g,'si_table5',f4counts[g],'si_table6',f5counts[g]) for g in ('Tertiary Amine','Benzene')}
 need(expected_comps=={('Tertiary Amine','si_table5',507,'si_table6',420),('Benzene','si_table5',1376,'si_table6',1293)},'cross-table source rows disagree with reviewed source values')
 seen={(x.get('group'),x.get('source_a'),x.get('count_a'),x.get('source_b'),x.get('count_b')) for x in comp if isinstance(x,dict)}
 need(expected_comps.issubset(seen),'cross-table support comparisons are missing or inaccurate')
 # Figure6 target cells are read dynamically from source headers/rows and checked against claims.
 byrow={r[0]:dict(zip(f6[0][1:],r[1:])) for r in f6[1:]}
 targets=[('Secondary Amine','Amide'),('Secondary Amine','Primary Amine'),('Secondary Amine','Tertiary Amine')]
 er=sub['error_relations']; need(isinstance(er,list),'error_relations must be a list')
 em={(x.get('row_group'),x.get('column_group')):x for x in er if isinstance(x,dict)}
 for row,col in targets:
  need((row,col) in em,'required published error-composition cells not reported')
  v=float(byrow[row][col]); got=em[(row,col)]
  need(got.get('source')=='workbook:Figure6' and near(num(got.get('value'),'Figure6 value'),v,1e-9),'Figure6 evidence cell does not match official data')
  need(got.get('direction')==('overrepresented' if v>0 else 'underrepresented' if v<0 else 'neutral'),'Figure6 interpretation direction mismatch')
 # Mapped evidence claim schema, not freeform keywords.
 ints=sub['interpretations']; need(isinstance(ints,list),'interpretations must be a list')
 bycode={x.get('code'):x for x in ints if isinstance(x,dict)}
 need(set(bycode)=={'support_association','spectral_overlap_hypothesis','error_composition'},'interpretation codes must cover the three distinct evidence claims')
 low=bycode['support_association'].get('low_support_classes')
 need(isinstance(low,list),'support_association needs explicit class evidence')
 lowmap={x.get('group'):x for x in low if isinstance(x,dict)}
 expected_low={'Aldehyde':78,'Sulfide':83,'Amide':86,'Cyano':80}
 need(set(lowmap)==set(expected_low),'low-support evidence classes mismatch')
 srcmetrics={r[0]:(int(r[1]),float(r[4])) for r in data}
 for name,count in expected_low.items():
  x=lowmap[name]
  need(x.get('support')==count and srcmetrics[name][0]==count and near(num(x.get('f1'),'low-support F1'),srcmetrics[name][1]),f'low-support class evidence mismatch: {name}')
 counter=bycode['support_association'].get('counterexample')
 need(isinstance(counter,dict) and counter.get('group')=='Secondary Amine' and counter.get('support')==161 and near(num(counter.get('f1'),'counterexample F1'),srcmetrics['Secondary Amine'][1]),'support interpretation must include a high-support, lower-F1 counterexample')
 for code,x in bycode.items():
  need(x.get('causal_claim') is False,'aggregate evidence cannot be declared causal')
  need(isinstance(x.get('limits'),list) and {'aggregate_only','association_not_cause'}.issubset(set(x['limits'])),'each interpretation needs explicit aggregate and causal limits')
  refs=x.get('evidence_refs')
  need(isinstance(refs,list) and set(refs).issubset({'main_p7','si_table6','si_table5','si_section6','workbook_figure4','workbook_figure5','workbook_figure6'}),'evidence references must use source locations')
  expected_refs={'support_association':{'main_p7','si_table6','workbook_figure5'},'spectral_overlap_hypothesis':{'main_p7','si_table6'},'error_composition':{'main_p7','workbook_figure6'}}[code]
  need(expected_refs.issubset(set(refs)),f'{code} is missing its direct evidence sources')
 need({'main_p7','si_table6','workbook_figure5','workbook_figure6'}.issubset(set(bycode['support_association']['evidence_refs'])|set(bycode['spectral_overlap_hypothesis']['evidence_refs'])|set(bycode['error_composition']['evidence_refs'])),'interpretations lack precise official source references')
 need(set(bycode['spectral_overlap_hypothesis']['groups'])=={'Secondary Amine','Amide','Primary Amine','Tertiary Amine'},'spectral-overlap groups do not match cited published mechanism')
 need(bycode['spectral_overlap_hypothesis'].get('band_cm1')==[1200,1350],'spectral overlap band does not match stated main-text interval')
 need(bycode['error_composition'].get('figure6_semantics')=='relative_over_underrepresentation_in_errors_not_correlation','Figure6 meaning is not distinguished from correlation')
 lim=sub['limitations']; need(isinstance(lim,list),'limitations must be a list')
 need({'aggregate_not_sample_level','no_causal_identification','table5_table6_denominators_differ','conditional_confusion_only'}.issubset(set(lim)),'required evidence limits missing')
 followup=sub.get('follow_up')
 if followup is not None and not isinstance(followup,(dict,list,str)):raise Science('optional follow_up must be a structured or prose exploratory note')
 return {'status':'PASS','reward':1.0,'macro_f1_recomputed':round(macro,9),'count_weighted_f1_recomputed':round(weighted,9),'classes':15,'evidence':'official aggregate numeric and evidence-bound interpretation verified; no sample-level causal claim'}


def main():
    logs.mkdir(parents=True, exist_ok=True)
    report = logs / 'verification.json'; report.unlink(missing_ok=True)
    try:
        for name, digest in INPUT_HASHES.items():
            f = app / 'assets' / name
            if not f.is_file() or hashlib.sha256(f.read_bytes()).hexdigest() != digest:
                raise RuntimeError('missing/corrupt evaluation input: ' + name)
        result = run(str(app / 'final' / 'submission.json'))
        status = result.get('status'); value = result.get('reward')
        report.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
        print(json.dumps(result, ensure_ascii=False))
        return 0 if status == 'PASS' else 1
    except Science as exc:
        result = {'status': 'FAIL', 'reward': 0.0, 'reason': str(exc)}
        report.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
        print(json.dumps(result, ensure_ascii=False))
        return 1
    except Exception as exc:
        result = {'status': 'ERROR', 'reward': None, 'reason': str(exc)}
    report.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps(result, ensure_ascii=False))
    return 2


if __name__ == '__main__':
    raise SystemExit(main())
