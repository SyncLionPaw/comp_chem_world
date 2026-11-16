# Assessing short-prefix PaiNN/SHARC dynamics

## Background

The supplied butylene PaiNN checkpoint was selected by validation in a 30-minute exploratory profile and is not calibrated for production dynamics. The 40 S1 initial conditions come from public SHNITSEL A03 data after velocity/kinetic-energy filtering; they are neither Wigner samples nor newly generated trajectories. Low-gap coverage, phase continuity and out-of-domain risk remain to be assessed.

## Task

Preregister and execute one bounded diagnostic with at most two distinct supplied initial conditions. Use native trajectory evidence to assess the interface and sampled model risks and justify whether further investigation is supported.

## Requirements

- Environment: use the container Python on `PATH`. Preinstalled packages include ASE, h5py, matplotlib, NetworkX, NumPy, pillow, PyTorch, PyYAML, SciPy, sympy. Do not install additional packages or fetch dependencies from the network.

- Before execution, record the fixed model, selected conditions, resource plan, risk hypotheses, drift threshold and decision/stopping rules. Each condition runs for 5–10 fs with a 0.5 fs nuclear timestep, within a single-attempt wall-time cap of 300 s. Use the supplied CPU target; record actual software/resources and do not submit remote jobs.
- Use the fixed state dict, exported inference model, source, adapter and condition pool. Do not load a supplied replacement pickle. Inspect interface/data provenance and report energy, force and smooth-NAC shapes and units. Explain phase handling, low-gap behavior and OOD limits; smooth NACs are not derivative couplings. The public grid is diagnostic only, not training or tuning data.
- Execute the registered plan once. Do not retry, replace failed/censored conditions, add jobs or change the model, duration or threshold. Preserve conditions stopped before starting, including the triggering condition index. Keep inputs, native traces, termination status and resource evidence.
- Independently audit the complete 0…T grid, one-hot S1 initial population, finite and normalized populations, `Etot=Ekin+Epot`, drift and completion/censoring. A prefix ending before its planned endpoint is incomplete.
- Separate interface failures, numerical instability, energy drift, near-degenerate coupling/phase issues, surface-hop stability, OOD/data coverage and external failures. The drift threshold is diagnostic; without independent calibration, do not claim reliability or recommend continuation as a validated scientific result. One or two 5–10 fs prefixes cannot identify a 100 fs S1 lifetime, confidence interval or survival distribution. Leave the lifetime unestimated; an observed S1 occupancy integral must state its actual window and trajectory count.

## Files

Public input files:

| File path | Description |
| --- | --- |
| `/app/inputs/` | Database, pilot checkpoint, runtime assets and output contract. |

Inputs are under `/app/inputs/`: the 13,000-record `databases/03_3Sing_C4H8.db`, diagnostic `databases/06_3Sing_C4H8_grid.db`, `pilot-baseline/weights/painn_state_dict.pt`, `pilot-baseline/initial_conditions/a03_equiv_s1_40.json`, and `sharc-v3.0.0.zip` (SHARC 3.0).

Use `/app/inputs/output-contract.md` for the execution interface and result formats. Submit `/app/outputs/probe-plan.json`, `probe-result.json` and `decision.json`, with collected evidence in `/app/bench25-artifacts/`. In the decision, `s1_100fs_lifetime_fs` is null and `lifetime_identifiability` records its non-identifiability from a short prefix; report any observed area as `observed_prefix_s1_occupancy_integral_fs`. Explain unavailable execution or evidence without fabricating results.
