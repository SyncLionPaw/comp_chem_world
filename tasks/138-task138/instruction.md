# Task: derivative, Hessian, and unit consistency of a fixed potential

## Background

A trained NewtonNet checkpoint is provided for two transition-state geometries,
`001` (10 atoms) and `000` (16 atoms), together with the model specification and
the atomic coordinates. Energy, forces and the analytic Cartesian Hessian are
available from the same fixed potential. Before such a potential is used for
curvature-based work, its derivative relations and units have to be shown to be
self-consistent.

## Task

Assess whether the energy, forces and analytic Cartesian Hessian of this fixed
potential are mutually consistent and unit-correct for both geometries, and
report the numerical evidence. Reference relations: forces are the negative
gradient of the energy, each Hessian column is the negative coordinate
derivative of the force vector, the energy and forces are invariant under rigid
translation, and the Hessian transforms as `R H Rᵀ` (forces as `F Rᵀ`) under a
proper rigid rotation. Do not infer a scientific result from this description;
establish it from your own calculations.

## Requirements

- Environment: use the container Python on `PATH`. Preinstalled packages include ASE, JAX, matplotlib, NetworkX, NumPy, pandas, pillow, PyTorch, PyYAML, scikit-learn, SciPy, sympy. Do not install additional packages or fetch dependencies from the network.

- Compute analytic Hessians; finite differences are validation evidence and
  cannot replace them.
- Declare a validation plan before computing: the finite-difference step
  (5e-5, 1e-4 or 2e-4 angstrom), three distinct coordinate components per
  geometry covering x, y and z, a translation vector of length 0.05–0.20
  angstrom, and a proper rotation about z of 60, 90 or 120 degrees.
  `validation_plan.json` may include `rotated_coordinates_angstrom` keyed by geometry ID to make the exact rotated coordinates used for each rotated Hessian reproducible.
- Keep the packaged frame order and Cartesian coordinate order. Units are eV,
  eV/angstrom and eV/angstrom^2.
- Every analytic Hessian must be symmetric to 2e-5 eV/angstrom^2, and every
  reported residual must be reproducible from its stated definition at the
  precision the contract requires. Report residuals to full precision rather than
  rounded values.
- Log every model evaluation with the hash of the evaluated coordinates, and
  reuse a stored energy/force result when the coordinates repeat. Stay within
  4 Hessian calls and 40 energy/force evaluations.

### Input and deliverable details

Inputs are in `/app/assets`: the two geometries
(`case01_ts_geometries_001_000.extxyz`), the checkpoint, the model
specification, and `output-contract.json`, which fixes the file names, schemas,
field order, hashes and row counts.

Write the deliverables of the contract to `/app/final`: `validation_plan.json`,
`efh.json`, the four Hessian matrices, `diagnostics.csv`, `model_call_log.csv`
and `report.md`. The report states the checks performed, the meaning of each
residual and the observed results, including any inconsistency you find.

Numerical comparisons use absolute tolerances of 2e−8 for the reported energy and translation residuals, and 2e−7 for reported force–Hessian and rotation residuals, in their declared units. The finite-difference gradient comparison uses absolute/relative tolerances 2e−6/1e−5; the force–Hessian comparison uses 2e−4/1e−3.

## Files

Public input files:

| File path | Description |
| --- | --- |
| `/app/assets` | Supplied scientific input or resource; see the task requirements for format and units. |

| Path | Contents |
| --- | --- |
| `/app/final` | Required result; use the contents and format specified above. |
