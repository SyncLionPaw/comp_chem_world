# Task: Archived online VES trajectory analysis

## Background

The supplied Wolfe–Quapp record contains eight replicas, a bias-coefficient history, and saved trajectories. Saved frames (every 5,000 steps), optimizer updates (500 steps), and internal optimizer samples (50 steps) have different cadences. These records support historical analysis, not independent reconstruction of optimizer batches or a new convergence claim.

## Task

Implement `/app/solution/analyze.py --data-dir PATH --output PATH [--analysis-cutoff STEP]` to audit the recorded bias history and samples, reconstruct the post-cutoff free-energy profile, and assess its statistical support.

## Requirements

- Environment: use the container Python on `PATH`. Preinstalled packages include NumPy. Do not install additional packages or fetch dependencies from the network.

Validate complete coefficient versions, chronology, replica exposure, and each frame's recorded bias. Read frames by replica and step, independent of CSV row order. Default to the last complete recorded update; an explicit cutoff must be an integer saved by every replica and no earlier than that update. Use only steps strictly after the selected cutoff. Moving this boundary does not establish a new freeze.

Use the supplied `statistics_builder.py` definitions for the 60-bin finite-domain FES, existing and conservative ESS, observable autocorrelation, common-support delete-block uncertainty, window comparisons, and block/window sensitivity. Reweight stably with `exp(bias_x − max(bias_x))`; adding a constant to log weights must not change results. Adding a constant to every RBF coefficient is not a gauge transformation. Empty-bin FES and unresolved jackknife uncertainty are null, with the builder's status; poor conservative support does not erase a defined existing FES.

Assess supported bins using positive count, target mass ≥0.001, and conservative ESS ≥20. After subtracting the target-mass-weighted residual offset, require target-mass coverage ≥0.90, weighted RMSE ≤1.0 kBT, and ordinary absolute-error P95 ≤2.0 kBT. Report whether these conditions hold; insufficient support is a valid scientific finding. Do not claim production convergence, first eligible freeze, CV sufficiency, or fresh sampling. Do not run simulation or optimizer replay.

### Input and deliverable details

Read `run-protocol.json`, `bias-history.csv`, `trajectory.csv`, and `statistics_builder.py` under `/app/environment/assets/`. Write one finite JSON object to `--output`; use numbers rather than booleans for numerical results. Invalid CLI inputs must exit nonzero.

Use these required members; optional metadata can be omitted:

- `recorded_update_cutoff` and `cutoff`: `{step,bias_version}` for the last complete update and the selected analysis boundary, respectively.
- `history_audit`: `complete_updates` (including version zero), `parameter_count`, ascending paired `versions`/`update_steps`, and `last_complete_update:{step,bias_version}`.
- `sample_audit`: `trajectory_rows`, integer `replica_ids`, `per_replica` keyed by decimal replica ID with `{rows,first_step,last_step,strict_post_cutoff_rows}`, `optimizer_sample_interval_steps`, `optimizer_update_interval`, `saved_trajectory_stride`, and total `strict_post_cutoff_rows`.
- `fes_bins`: the builder's `reweighted_fes`; `legacy`, `conservative`, `support`, `windows`, and `sensitivity`: the corresponding `derived_diagnostics` members. In the latter groups rename `pre_freeze`, `post_freeze`, and `late_post` to `pre_analysis_cutoff`, `post_analysis_cutoff`, and `late_post_analysis_cutoff`.
- `instance_adequacy:{thresholds_met}`: the Boolean assessment above. If a `window_boundary` marker is included, use `"analysis_cutoff"` or the selected cutoff step.

## Files

Public input files:

| File path | Description |
| --- | --- |
| `/app/environment/assets/` | Directory of supplied inputs and resources. |

Submit `/app/solution/analyze.py`. Use the interface and output conventions above.
