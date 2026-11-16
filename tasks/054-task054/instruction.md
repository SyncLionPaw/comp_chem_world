# Task: Evidence-linked diagnosis of frozen DeepVES records

## Background

Analyze two ordered, anonymized traces (`run-A.csv`, `run-B.csv`), their metadata, and `NeuralNetworkVes.cpp`. A uses a nonperiodic coordinate and natural energy units (`kBT`, T=1); B uses periodic angles in radians, kJ/mol, and T=300 K. Keep trace names anonymous. `ala2_ref/COLVAR` is out of scope.

Only one finite trace is available per system; actual per-run PLUMED ARG settings and complete physical inputs are unavailable. Report descriptive associations only. The records cannot identify CV completeness, causality, or cross-system rate rankings.

## Task

Create `/app/statistics.json`, `/app/analysis-contract.json`, `/app/diagnosis.md`, and `/app/intervention.md`. Use supplied assets and `statistics_builder.py` to compute the complete statistics layout. Record all scientific conclusions and supporting evidence in `analysis-contract.json`; this structured analysis is the authoritative record of findings. The diagnosis and intervention are explanatory reading aids with flexible wording and layout. Submit both as nonempty UTF-8 text; the optional `render_contract.py` can generate them. Do not simulate or present new MD evidence.

## Requirements

- Environment: use the container Python on `PATH`. Preinstalled packages include NumPy. Do not install additional packages or fetch dependencies from the network.

Read CSV columns `time,cv1,cv2,bias,force2,kl,lrscale`; require finite values and uniform time spacing. Preserve row order, hashes, units, frames, missingness, and time range. Cite zero-based data rows (CSV line = index + 2). The first `lrscale < 5e-5` row is the logged boundary; static analysis begins on the next calculation and fixed-bias analysis uses only later samples. Report adjacent equal-duration pre/post windows and a late-post window with inclusive endpoints.

Detect 20-frame continuous-dwell events: A cores are `cv1 <= -0.5`/`cv1 >= +0.5`; B cores are `sin(cv1) < -0.5`/`sin(cv1) > +0.5`, so branch-cut crossings are not events. Detect events over the full window before assigning them to equal-time blocks `(left,right]`. Report intervals for 5, 10, and 20 time blocks using two-sided Student-t critical values (`df=blocks-1`). These describe within-trace variation; event rates are operational proxies, not validated transition rates or independent-seed uncertainty.

For A use native-unit `beta=1`; for B use `beta=1/(RT)`, `R=0.00831446261815324 kJ mol^-1 K^-1`. Reweight only samples strictly after the boundary using stable `exp(beta*bias-max(beta*bias))` weights and global normalization; report Kish ESS separately. For hemisphere probability `p=sum(wI)/sum(w)`, use delete-block `p_b=(sum(wI)-block_sum(wI))/(sum(w)-block_sum(w))` and `SE=sqrt((B-1)/B * sum((p_b-mean(p_b))^2))`; label equal-block heterogeneity.

Use FFT autocovariance with lag denominator `n-k`, initial positive pairs `rho[1]+rho[2]`, `rho[3]+rho[4]`, …, maximum lag `min(4000,floor(n/4))`, and stop at the first nonpositive pair; report `g=max(1,1+2*sum(rho[k]))`. Compute separate diagnostics for weights, CV state, hemisphere, weighted-state residual, and periodic sine/cosine. Constant series have `g=1` and a flag; cap reach is truncated. Constant weights may have `g=1`; constant states/residuals and truncated estimates do not establish resolvable observable ESS. For periodic coordinates report circular sine/cosine means, resultant, and `SD=sqrt(-2 log(R))` (null near zero resultant), never a linear angle mean. Recompute one sensitivity per run with threshold 0.3–0.8, integer dwell 10–100 frames, window scale 0.75–1.0, changing at least one from `0.5/20/1.0`; report start/end/count/rate for pre-freeze, post-freeze, and late-post.

Compare freeze, orthogonal-coordinate, finite-sampling/correlation, and system-specific explanations, linking claims to evidence and retaining `not_identified` where mechanisms cannot be distinguished. Propose at least two matched interventions, each changing only CV definition or a preregistered freeze trigger. Match physical controls and paired starting states, account for serial correlation within seed, and preregister a same-run crossing-proxy-rate outcome, positive expected effect, minimum effect (zero or >=10% of expected effect but smaller than it), and paired 95% intervals for early and late windows. Support only if both signed interval lower bounds exceed expected effect; refute only if both signed interval upper bounds are below minimum effect; otherwise report inconclusive. Reversal, overlap, weak serial support, or too few seeds is inconclusive; mismatched controls, units, or exposure invalidate the design. Synthetic challenges test the rule only, not mechanism or simulation evidence.

### Input and deliverable details

Inputs under `environment/assets/`: `run-A.csv`, `run-B.csv`, `metadata.json`, `NeuralNetworkVes.cpp`, `statistics_builder.py`, `render_contract.py`. Required outputs are the four `/app/` files above. Use only the required contract fields below; optional descriptive metadata may be omitted and unknown keys are invalid.

| Object | Required fields |
|---|---|
| Root | `source_behavior,claims,hypotheses,interventions,alternative_sensitivities` |
| `source_behavior` | `source_sha256,comparison,threshold,condition_line,optimizer_guard_line,optimizer_step_line,static_branch_line,grid_read_line,lr_decay_line` |
| Claim | `id,kind,scope,evidence,assertion,inference`; scope=`run_id,window,observable,unit`; evidence=`input_sha256,run_id,window,metric_ref,operator,value,row_start,row_end,time_start,time_end`; assertion=`left,operator,right` |
| Hypothesis | `id,mechanism,status,evidence_claim_ids,competes_with,measurement_ref,prediction`; prediction=`intervention_id,change_factor,observable_ref,direction,discriminating_outcome` |
| Intervention | `id,run_id,controls,arms,cv_plan,freeze_criterion,paired_seed_ids,freeze_rule,window_rule,primary_metric_ref,estimand,uncertainty,prediction` |
| Sensitivity | `id,run_id,event_core_threshold,dwell_frames,window_scale,windows`; `windows.{pre_freeze,post_freeze,late_post}` each contains `start,end,count,rate` |

Provide >=3 claims, >=2 interventions, and exactly one sensitivity per run. IDs are unique per list and match `[A-Za-z0-9][A-Za-z0-9._-]{0,63}`. Claim kind=`observation`; inference=`observed/compatible/not_identified/refuted`. Runs=`run-A.csv/run-B.csv/source`; windows=`pre_freeze/post_freeze/late_post/strict_static/source/pre_post` (`pre_post` only for claim scope, citing both component windows). `scope.observable` names the asserted metric; each claim has nonempty evidence for its primary metric. Use `correlation_g.<observable>` for correlation factors. `right` is a finite number or `{metric_ref:...}`; operators=`eq/lt/le/gt/ge`. Evidence must match computed metrics, hashes, units, and exact row/time bounds; strict-static trajectory rows start at marker+1. Tolerances: evidence `rtol=1e-6/atol=1e-10`; hypothesis measurements/sensitivities `rtol=2e-6/atol=1e-10`.

`source_behavior` uses comparison `<` and threshold `5e-5`. Locators are positive 1-based line numbers or matching source-line text after whitespace and trailing `//` comment normalization. They identify the threshold condition setting `static_bias`, dynamic `if (!static_bias)` guard, optimizer step, `} else {` after the unique `//if static bias:` marker, static-branch bias/derivative evaluation at current CV using the initialized grid (not grid-file creation/loading), and learning-rate scaling update. Source evidence cites source SHA and the whole source with `row_start,row_end,time_start,time_end` all null; include all six locators. Canonical claim metrics: `source_behavior.threshold`; `runs.<run>.windows.{pre_freeze,post_freeze}.crossing_proxy_rate_per_time`; `runs.<run>.windows.pre_freeze.cv2_sd`; and `runs.<run>.reweight.correlation_g.<observable>`, where numeric observables are `weights,cv1,cv2,hemisphere_state,weighted_cv1_residual` (B also has `sin_cv1,cos_cv1`). Units: `optimizer-scale`; `1/<time unit>`; A=`native-CV-unit`/B=`radians`; `dimensionless`, respectively.

For these metrics, `scope.observable` normally uses the existing observable name (`threshold`, `crossing_proxy_rate_per_time`, `cv2_sd`, or `correlation_g.<observable>`). It may instead repeat the exact canonical metric reference in `assertion.left`; in that task the reference must match the declared `scope.run_id` and `scope.window` (including `source/source`, or the corresponding run and strict-static reweight window), and is interpreted as that metric's existing short observable name. Do not shorten arbitrary metric-reference suffixes.

Write `assertion.left`, every `evidence.metric_ref`, and any `right.metric_ref` as full canonical metric paths (for example, `runs.<run_id>.windows.<window>.<metric>` or `source_behavior.threshold`), never as short aliases. `assertion.left` explicitly selects the primary metric; for a `pre_post` scope, choose either the pre-freeze or post-freeze path. Do not infer the selected metric from `right` or the evidence list.

Hypotheses cover `freeze_removes_adaptation,orthogonal_slow_coordinate,finite_sampling_correlation,system_specific_dynamics`; use each identifier for both `id` and `mechanism`. Status=`compatible/not_identified`; `measurement_ref` is a nonempty map from metric refs to finite numbers. Prediction factor=`add_orthogonal_cv/delay_freeze`, direction=`increase/decrease/either` (matching the linked intervention's direction or `either`), outcome=`supports/weakens/remains_unresolved`. Link valid claim/hypothesis IDs and each prediction to its intervention's matching treatment factor and same-run primary metric. Freeze links source threshold to same-run pre/post rates; orthogonal-coordinate evidence includes `cv2_sd` and remains `not_identified`; finite-sampling cites correlation-limited or truncated support; system-specific evidence uses both runs and remains `not_identified`.

For interventions, `controls` has exactly `temperature,energy_unit,forcefield,initial_state_protocol,integrator_dt,target_distribution,exposure,output_interval`; temperature and energy unit match metadata. Set the other six fields to `matched`, meaning: same archived forcefield fingerprint and timestep with exact values resolved before execution; paired identical starting coordinates/velocities/checkpoint; same physical target/thermostat; equal simulation time per paired seed; same output interval. `arms` is an ordered baseline/treatment pair, each `{id,changed_variable,value}`; baseline=`{id:baseline,changed_variable:baseline,value:recover_source_configuration}`; treatment has `id=treatment` and changes only `cv_definition` or `freeze_rule`. Treatment values: A CV=`add_predeclared_orthogonal_cv2`; B CV=`add_predeclared_complementary_periodic_cv2`; freeze=`later_pre_registered_objective_gradient_trigger`. `cv_plan={baseline_status,coordinate_mapping,periodic_embedding,treatment_token}` uses `unidentified`, `cv2`, `none` (A)/`sin_cos` (B), and the treatment value.

`freeze_criterion={metric,operator,threshold,persistence_evaluations,baseline_time_fraction,treatment_time_fraction}` uses `relative_objective_gradient_norm`, `le`, threshold in (0,1), integer persistence >=3, and fractions in (0,1). CV-only uses equal fractions and `same_pre_registered_objective_gradient_rule`; freeze-only uses a later treatment fraction and `pre_registered_later_objective_gradient_rule`. Use >=3 unique nonempty paired seed IDs. `estimand={formula,unit,minimum_effect}` with formula=`paired_mean_delta`; `uncertainty={method,alpha,serial_block_rule,minimum_independent_seeds}` with `paired_t_interval`, 0.05, `block_within_seed_before_paired_seed_summary`, 3–30 seeds. Use `window_rule=equal_exposure_predefined_windows_with_late_sensitivity`, same-run crossing-proxy-rate primary metric, and prediction fields `direction,expected_effect,unit` with direction `increase/decrease`, positive effect, and matching rate unit.

## Files

Public input files:

| File path | Description |
| --- | --- |
| `/app/environment/assets/` | Anonymized traces, metadata, source code and analysis helpers. |

| Path | Contents |
| --- | --- |
| `/app/statistics.json` | Recomputed statistics and window diagnostics |
| `/app/analysis-contract.json` | Scientific claims and their evidence |
| `/app/diagnosis.md` | Diagnosis of both runs and their evidence limits |
| `/app/intervention.md` | Proposed paired intervention experiment |
