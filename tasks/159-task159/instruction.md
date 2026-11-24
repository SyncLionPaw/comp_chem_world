# Task: Compare finite-cell quartz/coesite Gibbs free energies at a fixed state and quantify uncertainty

## Background

At 600 K and 20,000 bar, compare the finite-cell Gibbs free energies of alpha-quartz (576 atoms) and coesite (384 atoms) with the packaged SiOx YACE Hamiltonian. Report the supported sign and uncertainty of ΔG = G_coesite − G_alpha, or report `unresolved`. This is a single-state, finite-cell comparison; do not infer a phase boundary or thermodynamic-limit ordering.

## Task

Create source-traceable evidence for the comparison and its uncertainty. Preserve forward and backward directions separately. This study has four baseline directions (B), four independent-seed repeat directions (R), and four directions for one adaptively selected check: duration (D) or size (S). Use independent seeds and snapshots for repeats. A duration check must share its baseline snapshot and seed. Freeze the selection rule and comparison criterion before running the selected check.

The 12-hour active-computation allowance includes preparation of the independent reference after your outputs are fixed. You do not need to regenerate that reference; leave allowance for its preparation and count the source-supported active intervals specified below.

## Requirements

- Environment: use the container Python on `PATH`. Preinstalled packages include NumPy, PyYAML, SciPy. Do not install additional packages or fetch dependencies from the network.

Use the exact packaged Hamiltonian, source-bound inputs, executable, software, and invocation interface. The public computation configuration is available at `/app/inputs/candidate-runtime/candidate-scope.json` and `/app/inputs/candidate-runtime/native_inputs/input-template*.json`. They define the role-specific sampling, including 20,000 switching steps per direction for B/R/S and 40,000 for D. Keep the declared temperature, pressure, cell, potential, and sampling conditions source-bound; do not substitute a different protocol.

If using HPC computing resources, consult `hpc`.

This computation is limited to 12 direction attempts, including failures and retries, and no more than 484,000 actual or conservatively reserved MD steps. Shared equilibration is limited to 20,000 steps per phase and is counted once per shared setup. Active computation is limited to 12 hours per independent evaluation. Count sourced active intervals; exclude queue time only when independent scheduler records show it does not overlap active work. These are ceilings, not a promise of convergence. If required compute is unavailable, report `NOT_RUN`; never fabricate run evidence.

Demonstrate native stability, fixed-cell statistical adequacy, volume and triclinic face-height/cutoff safety, correct Einstein-reference and PV normalization, and calibrated uncertainty. Keep unmeasured systematic terms explicitly `UNKNOWN`, never zero. Do not claim that combined uncertainty controls unmeasured errors. Report the finite-cell conclusion with its limitations or report `unresolved`.

## Files

Public input files:

| File path | Description |
| --- | --- |
| `/app/inputs/candidate-runtime/candidate-scope.json` | Public scope, method and runtime identity inputs. |
| `/app/inputs/candidate-runtime/native_inputs/input-template*.json` | Role-specific native sampling templates. |

Write all results under `/app/outputs/`.

| Path | Required contents |
| --- | --- |
| `gibbs_free_energy.csv` | One row per direction/repeat, using exactly `phase,T_K,P_bar,G_eV_per_atom,replicate,direction,cell_atoms,equilibration_steps,switching_steps,window_start,window_end,uncertainty_eV_per_atom,status,reason`. |
| `delta_g.csv` | Baseline comparison with exactly `T_K,P_bar,G_coesite_minus_G_alpha_eV_per_atom,repeat_uncertainty_eV_per_atom,direction_uncertainty_eV_per_atom,switching_uncertainty_eV_per_atom,finite_size_uncertainty_eV_per_atom,combined_uncertainty_eV_per_atom,decision,reason`; `decision` is `same_sign_resolved` or `unresolved`. Give a nonempty reason. |
| `error_budget.csv` | At least `quantity,estimate_eV_per_atom,status,reason`, with distinct `repeat`, `direction`, `switching`, and `finite_size` entries. Additional scientific columns are allowed; unknown estimates are not numeric zero. |
| `allocation_log.json`, `summary.json` | The allocation log records the initial rationale, adaptive observations and choice, rejected alternatives, remaining budgets, and stop reason. The summary includes `temperature_scope_K:[600]`, `pressure_scope_bar:[20000]`, `phase_boundary_claim:false`, `total_md_steps`, and `total_atom_steps`, plus status, Hamiltonian/software/element identity, direction/retry counts, active/queue time, resource use, conclusion, evidence, and limitations. Totals must match native evidence. |
| `native_inputs/`, `integration_runs/`, `figures/` | Preserve raw native inputs, logs, source records, and at least one figure. Preserve service-generated scheduler receipts, `outputs-manifest.json`, and `native-event-ledger.json` unchanged. |
| `campaign-evidence.json` | Use schema `case06-single-state-v2-campaign-evidence/v2` and protocol `single-state-v2`; preserve the runtime-generated bindings and source evidence. Each attempted direction must trace to its shared setup and forward/backward source segments. |
