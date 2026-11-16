# Low-energy hydrogen occupation and finite-spectrum sampling

## Background

For six alloys, the supplied absorption model gives an energy distribution `n(x)=exp(−x²)/sqrt(pi)` and `E=Ebar+sigma*x`; its energy standard deviation is `sigma/sqrt(2)`. It does not provide a complete site-resolved DFT spectrum.

## Task

At fixed bulk concentration and temperature, solve the chemical-potential offset, quantify low-energy-tail enrichment of occupied hydrogen, and assess finite hypothetical-spectrum bias and uncertainty.

## Requirements

- Environment: use the container Python on `PATH`. Preinstalled packages include NumPy, SciPy. Do not install additional packages or fetch dependencies from the network.

- Cover all six alloys at 300/400 K and bulk fractions `1e-6,1e-5,1e-4,1e-3,0.0026,0.0058`. Report offsets relative to `Ebar`, closure residual, root uniqueness and occupation bounds; do not claim an unsupported absolute DFT chemical potential.
- For tail masses `q=0.001,0.01,0.05`, report available-site fraction, occupied fraction, enrichment and occupied mean energy. Keep site fraction distinct from the fraction of hydrogen occupied in the tail.
- For hypothetical IID spectra of 25/50/100 sites, use 512 replicates per condition and the exact reproducible sampling stream in `/app/assets/task10_task_spec.json`. Report 5th/50th/95th quantiles, exact tail-absence probability and half-batch Monte Carlo diagnostics. These synthetic spectra are not recovered site energies.
- Establish normalization, energy-reference translation invariance and physical limits. Keep integration/root error below effects discussed. Include the specified 512/1024-point quadrature-refinement diagnostic even if another stable main solver is used. Explain width and rare-tail effects; means alone do not determine enrichment.
- Use `/app/assets/absorption_distribution_fig2a.csv` and provenance. In `/app/final/`, submit `concentration_closure.csv` (72 rows), `tail_enrichment.csv` (216), `finite_sampling.csv` (648), `inference.json`, executable `calculation_source.py` and run record. The public spec supplies exact column contracts, grid and random stream; separate deterministic numerical error from sampling uncertainty.

## Files

Public input files:

| File path | Description |
| --- | --- |
| `/app/assets/` | Alloy data, source records and task conventions. |

Inputs are under `/app/assets/`; outputs go under `/app/final/`.
