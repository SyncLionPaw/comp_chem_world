# Finite NVE timestep convergence in goldene

## Background

Study finite-window timestep convergence in goldene using recorded observations.

The inputs contain fixed-cell NVE energy logs at 0.5, 1 and 2 fs. `request.json` specifies timestep order and the finite-window budget.

## Task

Analyze the three supplied real fixed-cell NVE logs for 1800 Au atoms over their observed 0.2 ps windows. Compute per-atom total-energy envelopes and OLS slopes, compare timestep halving, and select the largest supplied timestep meeting the request's finite-window energy-envelope budget. This task measures integrator diagnostics on existing observations. It does not assess production MD, 1 ns membrane stability, finite-temperature equilibrium or thermostat/barostat correctness.

## Requirements

Analyze all recorded rows, including the initial row, in the requested timestep order. Calculate the per-atom energy envelope, peak-to-peak range, OLS slope with an intercept, and observed convergence orders for adjacent timesteps. Select the largest supplied timestep within the budget, or report none. Do not extrapolate the short-window slope into a long-term drift bound or claim that these records establish 1 ns stability or equilibrium. Explain the observed order, choice and finite-window limitations in the report.

Use only the supplied records; no new simulation or model inference is required. The executable accepts `--inputs DIR --output DIR`, writes directly to the output directory, and recomputes for each input, including prefix windows and changed budgets. Use bundled Python dependencies without network access. Submit results and evidence according to the listed output convention.

## Files

| Path | Description |
| --- | --- |
| `/app/inputs/` | Supplied NVE energy records and analysis parameters. |
| `/app/results/` | Submitted results and required execution evidence. |
| `/app/public/output-contract.json` | Required outputs and submission format. |
