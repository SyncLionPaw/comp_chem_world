# Task: Evaluate ACE active-learning label efficiency across diverse Si–O environments

## Background

A transferable Si–O potential must describe crystalline, disordered, high-pressure, mixed-composition and surface environments. The supplied geometries span six domains and have published DFT labels available through a controlled query service. This study evaluates label-efficient ACE learning using those existing labels; no new DFT calculation is required.

## Task

Build a three-member ACE committee from 12 seed labels, then conduct two active-learning rounds of six new labels each. Retrain all three members after each release: 24 labels and nine genuine fits in total. Determine whether the final committee improves energy and force predictions. The operational criterion requires at least 5% pooled improvement for both metrics and at least 5% at the lower 95% confidence bound. Within any domain, each metric may worsen by at most 25%.

## Requirements

- Environment: use the container Python on `PATH`. Preinstalled packages include ASE, NumPy, pandas, PyYAML, scikit-learn, SciPy. Do not install additional packages or fetch dependencies from the network.

- Use `/app/inputs/v2/geometry-manifest.json`: two seed structures and 20 pool structures per domain, 132 geometries total. Use only the structures listed in this manifest. Preserve atom order, species and cells. Only labels returned for the requested geometries may enter training; held-out values and evaluation results must not influence training, selection or stopping.
- At each round, rank the entire fixed pool using the preceding committee's force disagreement: the square root of the mean sample variance over all atomic Cartesian force components, with sample variance taken across the three members (`ddof=1`). Within each domain, choose the highest-ranked unqueried structure; break ties by ascending structure ID. Select one per domain, list domains alphabetically in the request, and retain the complete ranking, including previously queried entries marked ineligible. Register the selection before requesting labels. A committee with zero disagreement throughout the eligible pool is inadequate.
- Use the supplied ACE backend/template and three distinct seeds per stage, `7000 + 100*r + 17*m`, with stage `r=0,1,2` and member `m=1,2,3`. Fit on the cumulative released labels in release order. Keep the seed-only reference set fixed: determine the Si/O elemental energy offsets from those seed labels by least squares and do not refit the offsets using later or held-out labels. Save reloadable model checkpoints, native fit logs and exact training membership. Each fit has a 1,800-second ceiling; the whole trial has a 12-hour active-time limit. The trial-local trusted service records active time and isolated fit receipts.
- Compare stages 0 and 2 using total-energy-per-atom RMSE and force-component RMSE on the independent 80-frame, 16-source-file, six-domain evaluation. Quantify uncertainty by resampling source-file clusters within domains while retaining the specified frame weighting and fixed surface cluster. This comparison does not establish trajectory-family independence or guarantee convergence. Explain uncertainty and unsupported extrapolation.
- Obtain the released labels and register selections through the trial-local controlled query service, and preserve its returned records. Fitting is dispatched through the same trusted service to a task-provided isolated worker. No new DFT calculation or user-managed HPC allocation is part of this task. Do not substitute fabricated labels or execution records if the service or worker is unavailable; report the limitation.

## Files

Public input files:

| File path | Description |
| --- | --- |
| `/app/inputs/v2/geometry-manifest.json` | Geometry manifest for the six-domain structures. |
| `inputs/` | Directory of supplied inputs and resources. |

Use the supplied `inputs/` and write results under `/app/outputs/`. Energies use eV and forces use eV/Å. Preserve service-generated receipts and bindings as returned.

| Path | Required contents |
| --- | --- |
| `labels/{seed,round-1,round-2}.extxyz`, `oracle-query-receipts.jsonl` | Unaltered releases and query receipts. Each training frame retains `queried_id`, `dft_energy`, and ordered `dft_forces`. |
| `training/round-{0,1,2}.extxyz`, matching `.ids`, `training/seed-only-reference.extxyz` | Cumulative released frames and one ID per line in matching order; keep the seed-only reference fixed. |
| `models/round-{r}/member-{m}/` | Native `potential.yaml`, `potential.yace`, `manifest.json`, and `trusted-fit-binding.json`. Each `committee.json` uses `case07-v2-committee/v1` and records `round`, `training_sha256`, and three members with `seed`, `model_yace`, `model_sha256`, `backend_manifest_sha256`, and `training_sha256`. Preserve each fit's service receipt and native input/output records under `fit-evidence/round-{r}/member-{m}/`. |
| `selections/round-{1,2}.json` and matching `.request.json` | Selection has `round`, `pool_sha256`, and the complete `ranked` list with `id`, `geometry_sha256`, `force_disagreement_eV_per_A`, and `eligible_for_selection`. The request has `phase` (`round-1` or `round-2`) and six selected `ids` in domain order. |
| `active-budget-receipt.json`, `stop_decision.json`, `provenance.json` | Preserve the service-generated budget, lineage, receipt identities and independent-attempt bindings unchanged. The latter two use `case07-v2-stop-decision/v1` and `case07-v2-provenance/v1`; records cover 12+6+6 labels, zero new DFT attempts, all frozen committees, and this attempt's active time, distinct from earlier source runs. |
| `/app/case07-artifacts/trusted` | Required trusted result. |
