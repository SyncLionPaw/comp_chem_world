# Task: NewtonNet against DFT Hessians on four reaction geometries

## Background

Four transition-state geometries (IDs `001`, `079`, `205`, `024`) come with DFT
Cartesian Hessians computed at the same structures, and with a trained NewtonNet
checkpoint. Curvature-based analysis of reaction paths depends on how well the
model reproduces the reference vibrational structure, including the modes that
control a crossing.

## Task

Compute the full Cartesian Hessian of the fixed checkpoint at each geometry,
project out the rigid-body modes, and compare the resulting internal-mode spectra
with the DFT reference: eigenvalues, mode correspondence and overlaps. For ID
`001`, also quantify how the bonds respond to a controlled displacement along a
matched mode. State which conclusions the comparison supports about the model and
which part remains a limitation of the four-geometry scope.

## Requirements

- Environment: use the container Python on `PATH`. Preinstalled packages include ASE, JAX, matplotlib, NetworkX, NumPy, pandas, pillow, PyTorch, PyYAML, scikit-learn, SciPy, sympy. Do not install additional packages or fetch dependencies from the network.

- Follow `analysis_protocol.json`: rigid-body projection, near-degenerate
  clustering, subspace comparison, the two published mode-matching methods, the
  published near-degenerate relative thresholds and the frozen normalized
  displacement definition. Declare the method and threshold you use.
- Keep the packaged frame order. Report eigenvalues and responses at full
  precision; the comparison tolerances are tight.
  In `eigenpairs.csv`, use either same-index DFT eigenvalues or matched-index DFT eigenvalues, consistently within each geometry; `matched_dft_mode_index` and `abs_overlap` describe the matched pair.
- In `metadata.json`, declare the matching method, near-degenerate threshold, and
  ID `001` matched NewtonNet/DFT mode pair and permitted displacement step. Explain
  the scientific basis for the pair and step in `report.md`; rationale need not be
  duplicated in metadata.
- Report the complete internal-mode spectrum of every geometry, the matching
  method used, the selected mode pair and its evidence, and the limits of the
  four-geometry scope. Do not claim a general property of the model from these
  four systems.
- Stay within 8 Hessian calls and 40 energy/force evaluations.

### Input and deliverable details

Inputs are in `/app/assets`: the four geometries, the matching DFT Hessians, the
checkpoint, the model specification, `analysis_protocol.json` and
`output-contract.json`, which fixes file names, schemas, units, ordering, row
counts and the required report coverage.

Write to `/app/final` the four Hessian matrices, `metadata.json`,
`eigenpairs.csv`, `mode_comparison.csv` and `report.md`, as the contract
specifies.

Mode eigenvalues, overlaps, and bond responses use absolute comparison tolerances of 2e−5 eV/Å², 2e−5, and 2e−6 Å, respectively. Coordinate tolerance is 1e−9 Å, and the mode-matching tie tolerance is 1e−12.

## Files

Public input files:

| File path | Description |
| --- | --- |
| `/app/assets` | Supplied scientific input or resource; see the task requirements for format and units. |

| Path | Contents |
| --- | --- |
| `/app/final` | Required result; use the contents and format specified above. |
