# Finite prediction assessment of twelve retained models

## Background

Compare finite prediction errors on the supplied recorded validation set.

The inputs include recorded validation labels and twelve retained prediction records.

## Task

Using the twenty recorded real public-validation frames and the twelve retained model prediction records in the supplied inputs, independently compute for every model its per-frame energy error and per-component force error over the full supplied frames, and report each model's force-component RMSE and per-atom energy MAE with their exact denominators (frames and force components). Select one of these two legal metrics and use it for the two final-round paired comparisons that share a trial: random minus adaptive for trial 6061 and for trial 6062, where a positive difference means the adaptive model is better on that metric. Derive each comparison's better arm from the computed difference, and state the combined direction across both trials. Declare applicability as exactly these twelve retained models on these twenty recorded frames with these denominators, and exclude the domain-100 and multicomponent-49 sets, which have stored residuals only and no independent prediction records.

## Requirements

This task concerns analysis of already recorded predictions. It does not establish execution of model inference, fitting, selection or blinded controls, and it makes no population or generalization claim.

Model and frame ordering are free. Recompute for full-frame, frame-subset and record-order-reversed inputs rather than echoing fixed answers. Explain the metric choice, comparisons, direction and limits in the report.

Use the supplied records only; no new simulation or model inference is required. The executable accepts `--inputs DIR --output DIR` and writes its outputs directly under DIR. Recompute for each supplied input, including the input variations described in the task specification. Use bundled Python dependencies (stdlib suffices), without network access.

- Submit the required results and evidence under `/app/results/` according to the listed output convention. The executable analysis entry point is `/app/results/run/analyze.py`.

## Files

| Path | Description |
| --- | --- |
| `/app/inputs/` | Validation labels and prediction records. |
| `/app/results/` | Submitted results and required execution evidence. |
| `/app/public/output-contract.json` | Required outputs and submission format. |
