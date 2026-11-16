# Task: Analyse occupancy refinement and its relation to an independent X-ray baseline

## Background

The supplied M7 sweep contains two component scores, CYS A 145 and 4WI A 401, both to be minimized. Their sum is derived; X-ray is a separate baseline, not an optimization candidate.

## Task

Assess trade-offs across all supplied ratios and how the preferred choice depends on component weights and display-rounding uncertainty. Limit conclusions to these finite scores, without inferring physical occupancy or mechanism.

## Requirements

Preserve all source rows, labels and values. Determine component and sum minima with all ties, the Pareto set, and the complete lower envelope and switches of w·CYS + (1−w)·4WI on the closed interval w ∈ [0,1].

Treat each candidate's displayed components as independently uncertain within closed ±0.05 intervals, deriving the sum from those same components. Report dominance that holds for every allowed perturbation and dominance possible for at least one. These bounds concern display rounding, not physical uncertainty.

### Input and deliverable details

Input: `/app/assets/occupancy_sweep.csv`. Submit `/app/diagnosis.json` with preserved source values and derived analyses, and `/app/report.md` with the conditional decision and its limits. Numerical conventions and output formats are defined in `/app/verification.md`.

## Files

Public input files:

| File path | Description |
| --- | --- |
| `/app/assets/occupancy_sweep.csv` | Supplied scientific input or resource; see the task requirements for format and units. |
| `/app/verification.md` | Supplied data, parameters or method documentation; see the task requirements. |

| Path | Contents |
| --- | --- |
| `/app/report.md` | Required result; use the contents and format specified above. |
| `/app/diagnosis.json` | Required result; use the contents and format specified above. |
