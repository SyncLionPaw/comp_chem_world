# Task: curvature bias of predicted Hessian eigenvalues

## Background

Two anonymized data series of Hessian eigenvalues are supplied. Each row pairs a
DFT reference eigenvalue with the value predicted for the same mode, and each row
is labelled by reaction region (reactant, transition state or product). Only the
spectra are provided: no geometries, no model and no further provenance.

## Task

Quantify how the predicted positive eigenvalues differ from the DFT reference in
each series and region, and interpret what the pattern can and cannot support.
Treat the measured discrepancies as observations; if you propose a cause, state
it as a hypothesis with the control or test that would distinguish it from the
competing explanations.

## Requirements

- Use the metric identifiers, units and subset definition of
  `output-contract.json`; the reported diagnostics must follow them exactly.
- Sample counts and the RMSE cover all rows of a series/region group, while the
  median predicted-over-reference ratio and the mean signed bias are computed on
  the DFT eigenvalue > 10 kcal/mol/angstrom^2 subset only. Report full precision.
- Give at least two competing mechanisms that are distinguishable from each
  other, each with the evidence it rests on and a testable prediction that
  separates it from the alternatives.
- Separate observation from causal claim explicitly, and state the limits of what
  this dataset can establish.
- The scientific part of the assessment is an independent review of the exact
  content you submit, so the report and the decision file must be self-contained
  and auditable on their own.

### Input and deliverable details

Inputs are in `/app/assets`: `hessian_eigenvalues.csv` (one header row, the
paired eigenvalues) and `output-contract.json`, which fixes the deliverable
names, CSV columns, JSON structure and the interpretation requirements.

Write `diagnostics.csv`, `decision.json` and `report.md` to `/app/final`. The
report explains the observed pattern, the limits of inference and how the
proposed controls discriminate among the mechanisms.

## Files

Public input files:

| File path | Description |
| --- | --- |
| `/app/assets` | Supplied scientific input or resource; see the task requirements for format and units. |

| Path | Contents |
| --- | --- |
| `/app/final` | Required result; use the contents and format specified above. |
