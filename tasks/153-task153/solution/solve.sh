#!/usr/bin/env bash
# Oracle reference solution for task 153. Real execution against the public inputs;
# no precomputed answers. The solver is embedded so the task keeps a single
# solution entrypoint.
set -euo pipefail

exec python3 - "$@" <<'PY'
#!/usr/bin/env python3
import argparse,csv,json,os
from pathlib import Path
LABELS=("CYS A 145","4WI A 401","Sum")
def main():
 a=argparse.ArgumentParser(); a.add_argument('--input-dir'); a.add_argument('--output-dir'); x=a.parse_args(); default_assets=Path(os.environ.get('SOLUTION_ASSETS','/app/assets'))
 src=Path(x.input_dir or os.environ.get('INPUT_DIR') or default_assets); out=Path(x.output_dir or os.environ.get('OUTPUT_DIR') or '.')
 with (src/'occupancy_sweep.csv').open(newline='') as f: rows=list(csv.reader(f))
 cols=rows[1][1:]; vals={r[0]:[float(v) for v in r[1:]] for r in rows[2:]}; ratios=cols[:-1]
 vectors={r:[vals['CYS A 145'][i],vals['4WI A 401'][i]] for i,r in enumerate(ratios)}
 def tied_min(v):
  m=min(v.values()); return {'value':m,'ratios':[r for r in ratios if v[r]==m]}
 component={k:{r:vals[k][i] for i,r in enumerate(ratios)} for k in LABELS[:2]}
 mins={k:tied_min(v) for k,v in component.items()}; joint={r:vals['Sum'][i] for i,r in enumerate(ratios)}
 # Pareto: minimization in the two observed component scores.
 pareto=[r for r in ratios if not any(q!=r and all(vectors[q][j]<=vectors[r][j] for j in range(2)) and any(vectors[q][j]<vectors[r][j] for j in range(2)) for q in ratios)]
 # Linear scalarization parameter w in [0,1], component-1 weight; preserve every tie at knots.
 knots={0.0,1.0}
 for r in ratios:
  for q in ratios:
   da=vectors[r][0]-vectors[q][0]; db=vectors[r][1]-vectors[q][1]; den=da-db
   if den and 0<=-db/den<=1: knots.add(round(-db/den,12))
 knots=sorted(knots); raw=[]
 for lo,hi in zip(knots,knots[1:]):
  w=(lo+hi)/2; scores={r:w*vectors[r][0]+(1-w)*vectors[r][1] for r in ratios}; m=min(scores.values()); raw.append((lo,hi,[r for r in ratios if abs(scores[r]-m)<1e-9]))
 intervals=[]
 for lo,hi,win in raw:
  if intervals and intervals[-1]['ratios']==win: intervals[-1]['weight_interval'][1]=hi
  else: intervals.append({'weight_interval':[lo,hi],'ratios':win})
 switches=[]
 for w in sorted({0.0,1.0,*[it['weight_interval'][1] for it in intervals[:-1]]}):
  scores={r:w*vectors[r][0]+(1-w)*vectors[r][1] for r in ratios}; m=min(scores.values()); ties=[r for r in ratios if abs(scores[r]-m)<1e-9]
  if len(ties)>1: switches.append({'weight':w,'ratios':ties,'score':m})
 # Component display bounds are +/-0.05; derive Sum from the same component perturbations.
 eps=.05; robust=[]; possible=[]
 for r in ratios:
  for q in ratios:
   if r==q: continue
   upper=[vectors[r][j]+eps for j in range(2)]; lower=[vectors[q][j]-eps for j in range(2)]
   if all(upper[j]<=lower[j]+1e-12 for j in range(2)) and any(upper[j]<lower[j]-1e-12 for j in range(2)): robust.append([r,q])
   lower_r=[vectors[r][j]-eps for j in range(2)]; upper_q=[vectors[q][j]+eps for j in range(2)]
   if all(lower_r[j]<=upper_q[j]+1e-12 for j in range(2)) and any(lower_r[j]<upper_q[j]-1e-12 for j in range(2)): possible.append([r,q])
 d={'schema_version':'case04-m7-sweep/v2','task_version':'2.0','evaluation_scope':'m7_finite_data_robust_multiobjective_diagnosis','source':{'columns':cols,'rows':[{'label':k,'values':vals[k]} for k in LABELS]},'component_extrema':mins,'joint_extrema':tied_min(joint),'pareto_ratios':pareto,'scalarization':{'weight_definition':'w in [0,1] multiplies CYS A 145; (1-w) multiplies 4WI A 401','switch_points':switches,'open_intervals':intervals},'rounding_robustness':{'component_half_width':eps,'sum_is_derived_from_components':True,'robust_dominance_pairs':robust,'possible_dominance_pairs':possible,'interpretation':'component perturbations are shared through Sum; Sum is not an independent observation'}}
 out.mkdir(parents=True,exist_ok=True); (out/'diagnosis.json').write_text(json.dumps(d,indent=2)+'\n'); (out/'report.md').write_text('# M7 finite-sweep decision analysis\n\nThe structured result reports extrema, ties, the two-objective Pareto set, and every linear scalarization switch over the declared normalized weight domain. A recommendation is conditional on the selected component weight; the supplied data do not establish physical occupancy or mechanism.\n\nEach displayed component is treated as bounded by ±0.05. The Sum is derived from those component perturbations, so it is not assigned an independent error source. Robust dominance requires one candidate to be no worse at the upper bound in both components than the other at its lower bound, with a strict inequality in at least one; possible dominance uses the corresponding lower/upper bounds.\n')
if __name__=='__main__': main()

PY
