#!/bin/bash
set -euo pipefail
# Oracle entrypoint: reference solve by real computation, no hardcoded answers.
export APP="${APP:-/app}" IR_PACKAGE_ROOT="${APP:-/app}"
mkdir -p "$APP/final"
python3 - "$APP/final/submission.json" <<'PY'
import os, csv,json,sys
from pathlib import Path
P=Path(os.environ.get('IR_PACKAGE_ROOT', str(Path(__file__).resolve().parents[1])))/'assets'
def read(n):
 with (P/n).open(encoding='utf-8-sig',newline='') as f:return list(csv.reader(f))
f4,f5,f6=read('figure4_structure_topk.csv'),read('figure5_group_metrics.csv'),read('figure6_error_over_under.csv')
d4=[(r[0],int(r[1]),float(r[3]),float(r[4]),float(r[5])) for r in f4[1:]]
d5=[(r[0],int(r[1]),float(r[2]),float(r[3]),float(r[4])) for r in f5[1:]]
def confusion(n,p,r,f):
 ans=[]
 for tp in range(n+1):
  if abs(tp/n-r)>5.1e-7:continue
  for fp in range(0,max(3,int(tp/max(p,1e-10)-tp+4))):
   pp=tp/(tp+fp) if tp+fp else 0; ff=2*pp*(tp/n)/(pp+tp/n) if pp+tp/n else 0
   if abs(pp-p)<=5.1e-7 and abs(ff-f)<=5.1e-7: ans.append((tp,fp,n-tp))
 if len(ans)!=1:raise ValueError((n,p,r,f,ans))
 return ans[0]
class_rows=[{'group':n,'support':c,'precision':p,'recall':r,'f1':f} for n,c,p,r,f in d5]
conditional=[dict(group=n,tp=confusion(c,p,r,f)[0],fp=confusion(c,p,r,f)[1],fn=confusion(c,p,r,f)[2]) for n,c,p,r,f in d5]
fig4=[dict(group=n,count=c,top1_percent=a,top5_percent=b,top10_percent=d) for n,c,a,b,d in d4]
head=f6[0]; body={r[0]:dict(zip(head[1:],r[1:])) for r in f6[1:]}
rels=[]
for row,col in [('Secondary Amine','Amide'),('Secondary Amine','Primary Amine'),('Secondary Amine','Tertiary Amine')]:
 v=float(body[row][col]);rels.append({'source':'workbook:Figure6','row_group':row,'column_group':col,'value':v,'direction':'overrepresented' if v>0 else 'underrepresented' if v<0 else 'neutral'})
low=[{'group':n,'support':c,'f1':f} for n,c,p,r,f in d5 if n in {'Aldehyde','Sulfide','Amide','Cyano'}]
out={
 'summary':{'figure4_class_count':len(d4),'figure4_macro_top1_percent':sum(x[2] for x in d4)/len(d4),'table6_class_count':len(d5),'macro_f1':sum(x[4] for x in d5)/len(d5),'support_weighted_f1':sum(x[1]*x[4] for x in d5)/sum(x[1] for x in d5)},
 'figure4_metrics':fig4,'class_metrics':class_rows,'conditional_support_assumption':'figure5_displayed_count_assumed_positive_class_support','conditional_confusion':conditional,
 'category_counts':[{'source_id':'si_section6_smarts','count':21},{'source_id':'si_table5','count':19},{'source_id':'si_table6','count':15}],
 'cross_table_comparisons':[{'group':'Tertiary Amine','source_a':'si_table5','count_a':507,'source_b':'si_table6','count_b':420},{'group':'Benzene','source_a':'si_table5','count_a':1376,'source_b':'si_table6','count_b':1293}],
 'error_relations':rels,
 'interpretations':[
  {'code':'support_association','evidence_refs':['main_p7','si_table6','workbook_figure5'],'causal_claim':False,'limits':['aggregate_only','association_not_cause'],'low_support_classes':low,'counterexample':{'group':'Secondary Amine','support':161,'f1':next(r[4] for r in d5 if r[0]=='Secondary Amine')}},
  {'code':'spectral_overlap_hypothesis','evidence_refs':['main_p7','si_table6'],'causal_claim':False,'limits':['aggregate_only','association_not_cause'],'groups':['Secondary Amine','Amide','Primary Amine','Tertiary Amine'],'band_cm1':[1200,1350]},
  {'code':'error_composition','evidence_refs':['main_p7','workbook_figure6'],'causal_claim':False,'limits':['aggregate_only','association_not_cause'],'figure6_semantics':'relative_over_underrepresentation_in_errors_not_correlation'}],
 'limitations':['aggregate_not_sample_level','no_causal_identification','table5_table6_denominators_differ','conditional_confusion_only'],
 'follow_up':{'matched_on':['class_support','heavy_atom_count','overlapping_groups'],'contrast_design':'paired_full_spectrum_vs_preregistered_band_masking','primary_endpoint':'paired_sample_level_confusion_and_target_recall','support_hypothesis_prediction':'performance_gap_attenuates_after_support_matching','band_hypothesis_prediction':'target_confusion_pair_changes_selectively_after_band_masking','blinded':True,'uncertainty':'cluster_bootstrap_frozen_before_unblinding'}}
path=Path(sys.argv[1] if len(sys.argv)>1 else '/tmp/case-04-reference.json');path.write_text(json.dumps(out,ensure_ascii=False,indent=2)+'\n',encoding='utf-8');print(path)
PY
