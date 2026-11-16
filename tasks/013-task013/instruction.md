# Crack-tip first crossings and experimental comparability

## Background

Public parameters and a registered 12-column geometry support conditional crack-tip predictions. Hill Poisson ratio, relaxation volume, width convention, interpolation and inferred energetic reference are model assumptions. Experimental/theoretical observations are comparators, not model outputs.

## Task

Predict the earliest admissible cleavage/emission crossings for six alloys, test sensitivities and agreement with observations, and bound a separate Ni comparison without inventing Ni energy parameters.

## Requirements

- Environment: use the container Python on `PATH`. Preinstalled packages include NumPy. Do not install additional packages or fetch dependencies from the network.

- Recompute bulk closure, site occupation, coverage, fracture-energy/entropy contributions and critical intensities from supplied sources using the distributed-energy model for both bulk and local occupancy. Keep the inferred energy reference conditional; convert USF mJ/m² to J/m². Emission branches use mean−sigma_A and mean, never mean+sigma_A.
- Cover 28 conditions, seven scenarios (50 Å² baseline; 30/70 Å² area sensitivities) and the 301-point Kapp=0…3 MPa√m display grid. Refine beyond that grid for all earlier crossings and tangencies; a sign-change scan alone is insufficient. Restrict no-root claims to [0,3].
- Supply complete residual, derivative and endpoint enclosures over a continuous, nonoverlapping partition; establish root existence/uniqueness and exclude roots elsewhere. Bind each root to exactly one certificate; refine interval width to ≤1e-8 MPa√m. Retain the prescribed 192/384/768 quadrature comparison. This is a fixed-quadrature numerical certificate, not an IEEE directed-rounding proof.
- Negative fracture/effective USF energy invalidates a branch; do not clip it into a crossing. Separate source-reading uncertainty, ensemble spread, model sensitivity and numerical error. Assess event ordering only over supported branches; do not tune roots to source classes.
- Compare experimental and theoretical classes separately. For Ni, convert mass ppm to atomic ppm with masses Ni/H `58.6934/1.00794`, round interval endpoints outward to 0.1, preserve charging versus test temperature, fugacity versus pressure, and lattice versus trapped/total H. Do not pair replicates or invent an intensity threshold outside the available parameter domain.
- Report `eta=mu−Ebar−EZP` in eV relative to the common zero-stress reference.
- Use the public `/app/assets/task13_task_spec.json` as the exact scenario/output/certificate contract. Submit under `/app/final/` `forward_curves.csv`, `first_crossings.csv`, `source_comparison.csv`, `ni_comparison.csv`, `prediction_limits.json`, executable `calculation_source.py,model.py,interval_audit.py`, run metadata, and `interval-audit/first_root_interval_certificates.csv` plus `root_quadrature_convergence.csv`. The spec also gives allowed IDs, enum values, certificate fields and provenance; retain its public source-comparison inputs and limits.

## Files

Public input files:

| File path | Description |
| --- | --- |
| `/app/assets/` | Alloy data, source records and task conventions. |

Inputs include parameter/coordinate tables, Fig. 3 observations and Wada Ni records under `/app/assets/`; outputs and generated certificate subdirectory belong under `/app/final/`.
