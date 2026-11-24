# Task: Toluene ipso-BPR: dual-channel screening and saddle-point validation

## Background

Toluene ipso-bicyclic peroxy radical (ipso-BPR) can undergo ring opening through C1 or C2. The supplied evidence includes a native log for the ipso-BPR minimum, geometries for the BPR and both products, supplied scalar DFT/F12 energy and barrier references, and the supplied source’s Supporting Information. It does not include deposited saddle-point coordinates, Hessians, imaginary modes, scan points, search trajectories, or a guaranteed-convergent guess. Establish the atom mapping and starting structures from the supplied material. Reference energies are comparisons, not substitutes for new calculations or an uncertainty estimate.

## Task

Within one bounded attempt, use new calculations to screen both C1 and C2 and investigate at least one channel as a possible transition state. Choose the channel to refine from your observed screening evidence; explain why you stop work on the other and what remains unresolved. A validated channel does not establish a global pathway ranking.

## Requirements

- Environment: use the container Python on `PATH`; required scientific packages are preinstalled. Do not install additional packages or fetch dependencies from the network.

If using HPC, follow the `hpc` workflow: probe the authorized target, submit, wait for a terminal state, collect native outputs, and validate the scientific result.

First run a short trial with the chosen engine to estimate calculation cost. For each channel, calculate at least three distinct constrained-scan or path geometries, retaining a native energy or gradient result for each. Use these observations—such as topology, energy, convergence and cost—to select at least one channel for a new open-shell DFT saddle-point optimization and full vibrational analysis. For that saddle point, show that displacement along both signs of its actual imaginary mode, or an IRC initiated there, relaxes to the intended BPR and selected product. Optimize and analyze both endpoints at the same final DFT level. Independently optimizing supplied endpoint geometries does not establish a connection.

Calculate the new same-level DFT+ZPE barrier from the validated BPR and saddle-point outputs, and compare it with the supplied DFT+ZPE and published higher-level reference. Keep any proposed transfer correction separate and conditional, with its basis and limitations. State what the new calculation supports, its uncertainty and what it cannot establish. Discuss your atom mapping and reaction coordinates, method choice, interpretation of the imaginary mode, failed or abandoned work, stopping decision, and at least one reasonable coordinate or method you rejected. If no saddle point is validated, report the attempt as incomplete.

The complete attempt is limited to 8 hours of active wall time. Failed, retried, cancelled and terminated allocations count. Queue time may be excluded only for a documented pending interval with no running work; overlapping pending intervals count once. Waiting without such records counts toward the deadline.

Perform the calculations on HPC. Preserve native calculation files, job records, and actual resource usage. Follow the cluster’s current submission policy; report requested and measured resources separately, and do not replace missing measurements with requested values or zero.

Use a native open-shell DFT engine capable of saddle-point optimization, complete vibrational analysis and endpoint relaxation. A lower-cost method may guide guesses or screening but cannot replace final DFT validation. Freeze the engine version, final method and any rule for treating a small imaginary frequency as numerical noise during the trial. Preserve native inputs, outputs, geometries, frequencies or Hessians, actual connection trajectories, failures, commands, times, exit states and available resource evidence. Report spin diagnostics when available. Do not fabricate missing results or call failed points a screen.

### Input and deliverable details

Inputs are in `/app/assets/`: the Supporting Information, the toluene ipso-BPR native log, BPR/product skeleton geometries, scalar reference energies and their provenance.

Under `final/`, provide the six execution deliverables `ts_search_report.json`, `barriers.csv`, `native_outputs/`, `failures.md`, `resource_usage.csv`, and `execution-receipt.json`, plus `references_uncertainty.md` for the reference and uncertainty assessment. Any F12 transfer estimate must state its assumptions and limitations. The report must cover both channels, at least three screening records per channel, and the rationale for refinement or stopping; distinguish `validated`, `screened_unresolved` and `failed`. The barrier table has one row per channel, with new-level energy and barrier cells blank for an unvalidated channel. Keep the native calculation files, geometries and connection evidence in `native_outputs/`; retain failures and a per-job resource record. The public machine-readable contract is mounted at `/app/output-contract.json`, and the SSH/Slurm interface overview at `/app/environment/README.md`; consult them for the exact report fields, native-file bindings and receipt structure. Disclose missing execution or resource evidence and keep SSH credentials out of submitted files.

Use the existing `hpc` client from `/app` for Slurm work and retain all `.submit-job/*.json` state files unchanged in `final/native_outputs/slurm/`, including failed and cancelled jobs. Preserve the original calculation files and connect scientific stages to their job IDs.

## Files

Public input files:

| File path | Description |
| --- | --- |
| `/app/assets/` | Directory of supplied inputs and resources. |
| `/app/output-contract.json` | Supplied data, parameters or method documentation; see the task requirements. |
| `/app/environment/README.md` | Supplied data, parameters or method documentation; see the task requirements. |

| Path | Contents |
| --- | --- |
| `/app/final` | Required result; use the contents and format specified above. |
