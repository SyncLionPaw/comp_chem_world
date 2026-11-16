# Analyse temperature-dependent behaviour in archived short NPT trajectories

## Background

Six archived short NPT segments describe a 2,432-atom reline system at 323, 333, 343, 353, 363, and 373 K. They can show finite-window behaviour, but by themselves they establish neither equilibration, independent sampling, equilibrium precision, nor an equilibrium temperature response.

## Task

Audit the native records, recompute density and the finite-window diagnostics, state the limits of what the evidence supports, and derive the specified bounded sampling plan. This is local analysis only: do not run LAMMPS, create trajectories, use the network, or imply that the planned sampling was executed.

## Requirements

- Verify every file listed in `source-manifest.json`, then audit `native.in`, `native-runtime.json`, `log.lammps`, and `trajectory.lmp` at each temperature: settings, temperature, metal units, pressure target, timestep, run length, ordered row count and spacing, atom and type counts, and finiteness. Report any discrepancy instead of silently repairing the data.
- Recompute each frame density from the type masses and the orthogonal box volume, and compare it with the thermo values in g/cm³. The archived conversion factor and its SI equivalent are both acceptable, but only within the value and drift tolerances fixed by `output-contract.json`.
- Record, for every temperature, the recomputed density series together with its descriptive statistics and the source hashes, so that each reported number can be traced back to a native record.
- Keep finite-window drift distinct from stationarity, equilibration, correlation/ESS, equilibrium density precision, and equilibrium temperature response. Do not treat atoms or saved frames as independent replicates, and present any normal-theory interval as diagnostic with its assumptions stated.
- Derive the 12-unit sampling plan from the recomputed per-temperature triggers and report its stage-one and stage-two allocation. Treat those triggers as planning conventions for this exercise, not as physical convergence thresholds.
- Scope the `decision.json` claims to the fixed 11-row records and to the sampling design. Evaluate each property separately, distinguish an observed finite-window drift from any equilibrium inference, and explain the evidence limits; do not infer those properties from frame counts, short duration, or planned sampling. Mark every proposed unit `planned_only`, recompute after stage one before considering stage two, and leave a claim unresolved if the evidence is still insufficient at the cap.
- `report.md` must summarise the observations and limitations, reference both JSON files, name all six temperatures, and state that the sampling was planned, not executed.

## Files

Public input files:

| File path | Description |
| --- | --- |
| `/app/inputs/` | Native simulation records and source manifest. |
| `/app/output-contract.json` | Output and evidence conventions. |

Work under `/app/`; input and output paths below are relative to that directory.

Read `inputs/native/T*/`, `inputs/source-manifest.json`, and `output-contract.json`. Submit `audit.json`, `decision.json`, and `report.md`. `output-contract.json` defines the required fields, units, algorithms, tolerances, and the allocation policy.
