# Stationary solutions and finite-probe response spectra

## Background

The inputs provide the initial mesh, fixed-flux probes and numerical controls, coupled-model baseline, strong- and weak-start fields and metadata, thermochemistry, and transport, species and boundary parameters.

## Task

Construct stationary solutions at −0.50 and −1.70 V SHE and reconstruct all prescribed signed finite-probe response spectra.

## Requirements

See the listed output convention for output fields, numerical rules and scientific criteria.

- Construct stationary solutions at both −0.50 and −1.70 V SHE and execute every signed fixed-flux probe in `/app/inputs/controls.json`. Preserve failed controls and native histories; final roots, spectra and labels are not supplied.
- Use every prescribed full-domain nested mesh, both symmetric step sizes and the higher-precision finest stationary/probe repeats. Public initial guesses have only 21 nodes rounded to 0.1; use them only as starting guesses. Perform actual new solves and all audits; direct interpolation/copying does not satisfy the original equations.
- Reconstruct full/reduced finite-probe matrices under `/opt/co2-public/model-definition.md`. Classify relative to spectral radius one only when margin>10*Delta, with Delta from independently recomputed spectral spread, gradient-step and representation errors, excluding candidate tangent terms.
- Independently audit all seven original species equations, electrostatics, boundaries, field admissibility, source/element/charge conservation and stationary kinetic closure. Probe fields obey their own imposed flux and need not satisfy perturbed kinetic closure.
- Report mesh/step/precision sensitivity and retain actual starting states and final/probe fields. Small residuals alone do not establish continuum accuracy.
- Limit interpretation to the prescribed finite probes, model carbonate approximation and literal reservoir. Iteration spectra are not physical time stability or proof of root uniqueness, continuum existence, bulk-origin attraction, a full voltage domain, electrode termination or paper-exact reproduction.

- `/app/code/solve.py` must accept `--inputs PATH --output PATH` for independent isolated recomputation.

## Files

| Path | Description |
| --- | --- |
| `/app/inputs/` | Meshes, model parameters and solver controls. |
| `/opt/co2-public/output-contract.md` | Required outputs and submission format. |
| `/app/` | Submitted results and required execution evidence. |
