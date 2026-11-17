# Periodic Electrostatic-Potential Fidelity in Accessible Pore Volume

## Background

Atomic charge errors need not predict accessible-pore periodic potential errors.

Public inputs provide panel and charge data, geometry and mapping information, and the potential model and method conventions.

## Task

Compare full periodic pore fields for all four charge methods on the fixed four-MOF panel.

## Requirements

- Retain DDEC3, PQeq_GMP, EQeq_ox_exp and NO_Q, complete compatible assignments and source-row coupling at 5.1e-6 precision. Use conducting Ewald potentials in V, original charges with uniform background for residual net charge, and each field’s pore mean zero on the same geometry/mask. Pore exclusion is UFF_sigma/2+1.5 Å inclusive; retain isolated pockets and report connected volume separately. Use a 0.2 Å baseline plus an actual refinement or shift; distinguish padding and empty masks. Declare tau_V/tau_F and budgets, separate grid/Ewald/mapping uncertainty, and supply full-field witnesses, conservative bounds and periodic_field.py functions grid, pore_clearance, green_matrix. The legacy field ceiling is 1e-5 V; finite-grid sensitivity does not prove continuum convergence.
- Use only this case’s public inputs; retain required statuses, failures, units and reproducible evidence.
- Supply self-contained `periodic_field.py` and `accuracy.json` for field replay using the public inputs.
- For replay, `green_matrix` may optionally accept `apply_to=Q` (one column per charge model) and return `(G @ Q, proof)` directly. Otherwise it returns `(G, proof)`. Both forms must generate the same mean-zero fields for every accessible grid point.

- For mapping-sensitive methods, keep the required `conservative-pointwise-envelope` control in `mapping_method_bounds`; a separate stronger global-extremum result does not replace it.
- Submit the required artifacts according to the listed output contract.

## Files

| Path | Description |
| --- | --- |
| `/opt/qeq-public/` | Public data, models and calculation parameters. |
| `/opt/qeq-public/output-contract.yaml` | Required outputs and submission format. |
| `/app/outputs/` | Submitted results and required execution evidence. |
