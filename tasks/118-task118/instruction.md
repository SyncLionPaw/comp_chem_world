# Task: Compare fixed-composition stacking stability from deposited GGA relaxation outputs

## Background

`environment/assets/configurations.yaml` lists six deposited GGA relaxation outputs — `POSCAR`, `CONTCAR`, `INCAR`, `KPOINTS`, `OUTCAR`, and `OSZICAR` for each — covering three same-composition P-3m1 / R-3m stacking pairs: TiS2, LiTiS2, and NaTiS2.

## Task

Compare the P and R stackings of each pair from the deposited final energies, and state the evidence limits of that comparison.

## Requirements

Parse the native logs in the local container; do not launch VASP or rerun DFT. Normalize each structure by its Ti count, one Ti per TiS2 formula unit. The primary energy is the final OUTCAR free energy `TOTEN`; OUTCAR `energy(sigma->0)` and the final OSZICAR `E0` are cross-checks and must agree with it within 1e-5 eV. Report `E_stack = TOTEN / n_Ti` in eV per Ti and `delta_R_minus_P = E_R − E_P`; a positive delta means P lies lower in this deposited set. Report a definite ordering only when `|delta|` exceeds 1e-3 eV/Ti, otherwise `within_dead_zone`. The comparison tolerance 1e-5 eV/Ti reflects printed precision, not a physical DFT uncertainty.

Check each configuration separately for sampling conditions (KPOINTS and cell records), final electronic convergence (compare the final OSZICAR electronic-iteration `dE` and `d eps` with that file's `EDIFF`), ionic relaxation completion, normal VASP termination, and any early NELM limit. The three pairs are the entire comparison: signed differences do not establish a convex hull or global polymorph stability, and the 33-phase hull remains outside this task.

### Input and deliverable details

Write `/app/final/stacking.json` containing:

- `configurations`: an entry for each of the six public configuration IDs `TiS2-P`, `TiS2-R`, `LiTiS2-P`, `LiTiS2-R`, `NaTiS2-P`, and `NaTiS2-R`, with integer `n_atoms`, `n_Ti`, and `n_formula_units`, numeric `final_TOTEN_eV` and `energy_per_formula_unit_eV`, and boolean `final_electronic_converged`, `ionic_relaxation_complete`, `normal_end`, and `early_scf_limit_hit`.
- `pairs`: exactly `TiS2`, `LiTiS2`, and `NaTiS2`, each with numeric `P_eV_per_Ti`, `R_eV_per_Ti`, and `delta_R_minus_P_eV_per_Ti`, the string `ordering` (`P_lower`, `R_lower`, or `within_dead_zone`), and the boolean `early_scf_limit_hit` of the R stacking.
- `all_electronic_steps_converged` (boolean) and `hull_or_global_stability_claim` (fixed `false`).
- `methods` and `limitations`, using the fixed values below unchanged.

Booleans must not substitute for numbers.

`methods` must contain exactly: `energy_source` = `final OUTCAR free energy TOTEN, cross-checked against energy(sigma->0) and final OSZICAR E0`; `normalization` = `one Ti atom equals one TiS2 formula unit; divide by N_Ti`; `delta_definition` = `E_R_per_Ti - E_P_per_Ti`; `energy_tolerance_eV_per_Ti` = 1e-5; `delta_tolerance_eV_per_Ti` = 1e-5; `ordering_dead_zone_eV_per_Ti` = 1e-3; `tolerance_meaning` = `printed-value comparison precision only; not a physical DFT uncertainty`.

`limitations` must contain exactly these six statements, unchanged:

- `Only the three available same-composition P/R pairs are compared.`
- `The deposited KPOINTS files carry the same 4×4×4 grid label, while the cells have different sizes; k-point density convergence is not established.`
- `No Mg or Na0.5TiS2 pair is included.`
- `No formation energies, convex hull, or global stability result is calculated.`
- `Final ionic relaxation completion is checked separately from electronic convergence of every SCF step. NaTiS2-R has an early SCF step that reached NELM=100 without meeting EDIFF; later ionic steps converged.`
- `Therefore this result does not claim that every electronic step converged, nor that either stacking is a global ground state.`

Generate `/app/final/report.md` from `/app/final/stacking.json` with the provided renderer so the two agree:

```text
python environment/assets/render_report.py /app/final/stacking.json /app/final/report.md
```

## Files

Public input files:

| File path | Description |
| --- | --- |
| `environment/assets/configurations.yaml` | Supplied data, parameters or method documentation; see the task requirements. |

| Path | Contents |
| --- | --- |
| `/app/final/stacking.json` | Required result; use the contents and format specified above. |
| `/app/final/report.md` | Required result; use the contents and format specified above. |
