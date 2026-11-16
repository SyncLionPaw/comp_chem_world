#!/bin/bash
set -euo pipefail
oracle_dir=$(mktemp -d)
cleanup() { rm -rf -- "$oracle_dir"; }
trap cleanup EXIT
trap 'exit 129' HUP
trap 'exit 130' INT
trap 'exit 143' TERM

cat > "$oracle_dir/solve.py" <<'CCW_139_solve_py_fa8d73fe4108_END'
#!/usr/bin/env python3
"""Recompute public curvature diagnostics and write a cautious mechanism report."""
import csv, json, math, statistics
from collections import defaultdict
from pathlib import Path
src=Path('/app/assets/hessian_eigenvalues.csv'); out=Path('/app/final'); out.mkdir(parents=True,exist_ok=True)
groups=defaultdict(list)
with src.open(newline='',encoding='utf-8') as f:
    for row in csv.DictReader(f): groups[(row['series'],row['region'])].append((float(row['dft_eigenvalue']),float(row['predicted_eigenvalue'])))
rows=[]
for series in ('series_1','series_2'):
 for region in ('R','TS','P'):
    vals=groups[(series,region)]; positive=[(d,p) for d,p in vals if d>10.0]
    mid=f'{series}_{region.lower()}'
    rows.append({'metric_id':mid,'series':series,'region':region,'sample_count':len(vals),'rmse_kcal_mol_A2':math.sqrt(sum((p-d)**2 for d,p in vals)/len(vals)),'positive_eigenvalue_sample_count':len(positive),'median_pred_reference_ratio_dft_gt_10':statistics.median(p/d for d,p in positive),'mean_signed_bias_dft_gt_10':sum(p-d for d,p in positive)/len(positive)})
with (out/'diagnostics.csv').open('w',newline='') as f:
 w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
refs=[r['metric_id'] for r in rows]
obs=[{'claim':f"{r['metric_id']} has median predicted/reference ratio {r['median_pred_reference_ratio_dft_gt_10']:.6g} over the DFT-positive subset.",'metric_refs':[r['metric_id']]} for r in rows]
decision={'observations':obs,'causal_boundary':'These are associations in a small supplied table; they do not identify a unique cause.','hypotheses':[{'hypothesis_id':'coverage','mechanism':'The discrepancy is driven mainly by training-data coverage across structures and curvature regimes.','distinguishing_test':'Hold architecture, optimizer, and split fixed while adding matched training structures across the sparse curvature regime.','evidence_refs':refs,'predictions':'If coverage dominates, matched additions should reduce the series gap more than smoothness-only changes.'},{'hypothesis_id':'smoothness','mechanism':'The discrepancy is driven mainly by model smoothness or regularization, which attenuates high-curvature responses.','distinguishing_test':'Hold data, split, and training budget fixed while varying only the declared smoothness regularizer.','evidence_refs':refs,'predictions':'If smoothness dominates, the ratio should shift systematically with regularization while coverage-matched data remain fixed.'}]}
(out/'decision.json').write_text(json.dumps(decision,indent=2)+'\n')
(out/'report.md').write_text('# Curvature bias: observations and hypotheses\n\nThe six metric rows report RMSE over all supplied values and median prediction/reference ratios and mean signed bias on the strict DFT > 10 kcal mol^-1 A^-2 subset. '+', '.join(refs)+f" show the measured ratios across the six series/region combinations. This small supplied table establishes associations only; it cannot identify a unique cause. Two plausible explanations are limited training coverage and model smoothness or regularization. A controlled experiment should vary coverage while holding architecture, split and training settings fixed, then vary smoothness alone on a fixed dataset. A coverage effect predicts improvement concentrated in newly covered regimes; a smoothness effect predicts a systematic ratio shift when only regularization changes. Replicated matched splits and held-out structures are needed to distinguish them.\n")
CCW_139_solve_py_fa8d73fe4108_END
test "$(sha256sum "$oracle_dir/solve.py" | cut -d ' ' -f 1)" = "fa8d73fe4108ddde7843b8d1d5b064fbcf25ed9c8508e819375ce5c5a00d1858"

chmod 0444 "$oracle_dir"/*.py
python "$oracle_dir/solve.py"
