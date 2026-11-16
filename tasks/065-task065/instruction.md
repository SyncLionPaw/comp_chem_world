# Task: Test G4 Hydration and Water-Bridge Mechanisms

## Background

Inputs include a source-bound 8,834-row G4 observation table and 64 real coordinate frames with explicit host, guest and water atom IDs and rotated boxes. The full record and coordinate excerpt have different coverage and must be analyzed in their stated scopes.

## Task

Join observations to native scalar/bias rows by time. Use coordinate-defined z/r geometry to test wet/dry and water-bridge hypotheses. For any proposed bridge, report the water O/H IDs, O–O distance, donor–H–acceptor angle and guest-Br contacts; assess geometric plausibility separately from causal interpretation.

## Requirements

- Environment: use the container Python on `PATH`. Preinstalled packages include NumPy. Do not install additional packages or fetch dependencies from the network.

For state labels use the full table's native z/r: bound-like z<0.8 nm and r≤0.45 nm; unbound-like z≥1.25 nm and r≤0.45 nm; otherwise intermediate. At 300 K use max-subtracted normalized log weights β·opes_bias_kJ_mol (not RCT), separately normalize burn-ins 0, 20,000 and 40,000 ps, and cover the full time range with 45 non-overlapping 4,000 ps blocks ending at `min(start+4000 ps,last_time+1 ps)`. Report weights, ESS and finite-sample block summaries; extra sensitivities may supplement these baselines.

Use the public atom map. The coordinate excerpt contains eight mapped host oxygens; the full trajectory provenance covers 32. Limit any no-bridge conclusion from the excerpt to that subset. Sparse biased samples from one trajectory are not equilibrium populations, rates or independent replicas. The block log-mass ratio is a conditional finite-sample proxy, not standard-state binding free energy. Report threshold sensitivity and evidence that could overturn the decision; if reweighting support is inadequate, report HOLD/not estimable.

## Files

Public input files:

| File path | Description |
| --- | --- |
| `/app/environment/assets/` | Public inputs and method resources |
| `/app/environment/assets/output-contract.json` | Submission format, evidence conventions and applicable tolerances |

**Deliverables**

| Path | Contents |
| --- | --- |
| `/app/coordinate-observables.csv` | Coordinate observables |
| `/app/geometry-evidence.csv` | Geometric evidence |
| `/app/state-hypotheses.json` | State hypotheses |
| `/app/mechanism-decision.md` | Mechanistic interpretation |
| `/app/state-analysis.json` | State analysis |
| `/app/state-frames.csv` | Frame assignments |
| `/app/state-blocks.csv` | Block estimates |
