# Task: Recover a hydration solver that loses oscillations

## Background

The read-only inputs `/app/assets/defective_solver.py` and `/app/assets/defective_force_model.py` implement a deliberately defective sixth-order hydration-pressure solver; run the first with an output directory to inspect its force curve. The physical conventions are those of the underlying task: natural boundary condition `P1''=0` and variational pressure `Pi = -dU/dL_A/epsilon0`.

## Task

Diagnose and minimally repair the injected defect so the oscillatory sharp pressure is recovered. The submission must execute a real solver — reporting fixed numbers is not sufficient.

## Requirements

- Environment: use the container Python on `PATH`. Preinstalled packages include matplotlib, MDAnalysis, NumPy, pillow, SciPy. Do not install additional packages or fetch dependencies from the network.

- Write `final/fixed_solver.py`, `final/force_model.py`, `final/diagnosis.md`, `final/force_fixed.csv`, and `final/recovery.json`.
- The submitted solver must accept a workspace directory as its first positional argument, read `CASE007_P0` and `CASE007_ALPHA` from its environment, and write `final/force_fixed.csv` under that workspace.
- `recovery.json` must record `natural_boundary` as `P1''=0` and `pressure_definition` as `-dU/dL_A/epsilon0`; `diagnosis.md` must identify both the wrongly substituted first-derivative condition and the corrected second-derivative one.
- The full 2–20 Å pressure curve at the public parameters is compared against an independently evaluated reference, and the submitted program is re-run at several other `P0`/`alpha` values that are not disclosed in advance. Each re-run must be genuinely recomputed from the requested parameters — outputs that ignore the parameters, reuse the public-parameter curve, or reproduce the original defect will not pass.

### Input and deliverable details

- Inputs: `/app/assets/defective_solver.py`, `/app/assets/defective_force_model.py` (read-only)
- Outputs: `final/fixed_solver.py`, `final/force_model.py`, `final/diagnosis.md`, `final/force_fixed.csv`, `final/recovery.json`

Preserve the 181-point distance grid from 2 to 20 Å in 0.1 Å steps. The distance tolerance is 1e-9 Å; pressure comparisons use relative tolerance 2e-5 and absolute tolerance 1e-3 Pa.

## Files

Public input files:

| File path | Description |
| --- | --- |
| `/app/assets/defective_solver.py` | Supplied calculation or helper tool. |
| `/app/assets/defective_force_model.py` | Supplied calculation or helper tool. |

| Path | Contents |
| --- | --- |
| `/app/final` | Required result; use the contents and format specified above. |
