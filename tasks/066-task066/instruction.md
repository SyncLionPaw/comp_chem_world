# Task: Estimate Apo-Cavity Hydration and Audit Bias Validity

## Background

The package provides sparse host-aligned coordinate excerpts from biased OAH/OAMe simulations, with explicit water IDs, rotated boxes, native times, and short contiguous COLVAR/bias windows. Coordinates and bias windows have different cadences and offsets.

## Task

Define a cavity around the public PLUMED axis and compare at least two geometric regions. Count waters and test boundary sensitivity. Reconcile coordinate times with the bias excerpts and provenance, then decide whether the evidence can support an unbiased hydration distribution; state what is missing if not.

## Requirements

- Environment: use the container Python on `PATH`. Preinstalled packages include NumPy. Do not install additional packages or fetch dependencies from the network.

For each declared region, state shape, center/axis, dimensions, volume, atom selection, PBC treatment and sensitivity. Report integer per-frame counts and a PBC-aware water O–O/H-angle graph with atom-level edges, connected components and cycle rank. Use the full mapped water IDs and preserve each host's distinct scope.

Label counts as sparse biased-sample frequencies, never equilibrium probabilities. The original alpha-shape parameters and machine-readable mask are unavailable; do not claim to reproduce that mask. OAMe XTC frames are 5 ps apart and its COLVAR is 0.5 ps; OAH XTC is 5 ps and its COLVAR starts at 1.5 ps with 2 ps cadence. A nearest-time bias is not necessarily the bias at that configuration; a final kernel or stable kernel count does not establish historical same-frame bias. Do not report unbiased P(n) without validated same-configuration historical weights.

## Files

Public input files:

| File path | Description |
| --- | --- |
| `/app/environment/assets/` | Public inputs and method resources |
| `/app/environment/assets/output-contract.json` | Submission format, evidence conventions and applicable tolerances |

**Deliverables**

| Path | Contents |
| --- | --- |
| `/app/cavity-definition.json` | Cavity definition |
| `/app/occupancy-region-sensitivity.csv` | Occupancy sensitivity |
| `/app/wire-geometry.csv` | Water-wire geometry |
| `/app/bias-validity-audit.json` | Bias validity audit |
| `/app/decision.md` | Scientific decision |
