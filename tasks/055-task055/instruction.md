# Compare angularly weighted scattering rates and resolve forward-scattering integration

## Background

In elastic, speed-preserving scattering, the lifetime rate and momentum-relaxation rate have different angular weights; a forward peak can affect the stability of numerical integration.

## Task

Given the screening parameters and kernel, design an angular integration and grid-refinement method, compare the SERTA and MRTA rates, and assess the forward-scattering trend.

## Requirements

- Environment: use the container Python on `PATH`. Preinstalled packages include NumPy. Do not install additional packages or fetch dependencies from the network.

- Cover all five input values of `a`; submit `results.json` and `quadratures.json` for each.
- For each `a`, provide at least two distinct quadrature grids with increasing resolution. Each must have at least 8 distinct nodes in `[-1,1]`, strictly positive weights summing to 2, and no more than 200000 nodes.
- On every grid, the first- and second-moment errors must each be at most `1e-3`; the relative change in each of the two rates between the final two grids must be at most `1e-3`.
- Final rates must be reproducible from the submitted quadrature values (`rtol=1e-10`) and agree with the closed-form rates (relative error at most `3e-4`). All values must be finite; `rate_ratio=mrta_rate/serta_rate`.
- Submit fields as specified in `environment/assets/public/output-contract.md`. The integration results must be generated from this task's kernel and inputs; do not substitute external values or fabricated run records for the calculation.

## Files

Public input files:

| File path | Description |
| --- | --- |
| `/app/environment/assets/author/inputs/elastic-angular.json` | Scattering kernel, parameters and rate definitions |
| `/app/environment/assets/public/output-contract.md` | Public submission contract |

The working directory is `/app`. Inputs are in `environment/assets/author/inputs/elastic-angular.json`; write outputs to `/app/final/`. This task uses equal-speed elastic scattering and `u=cos(theta)`; the parameters, kernel, and rate definitions are in the input file.

**Deliverables**

| Path | Contents |
| --- | --- |
| `/app/final/results.json` | Scattering rates and ratios |
| `/app/final/quadratures.json` | Numerical quadrature results |
