# Implement a flexible-boundary crack model for silicon

## Background

The Sinclair flexible-boundary model couples an atomistic crack core to an anisotropic Mode-I elastic field. Its region partition, hybrid energy, crack-tip closure and multilattice Cauchy–Born corrector must describe the same mechanical system. The model equations are given in `/app/spec.md`.

## Task

Implement the model with the Stillinger–Weber silicon potential and determine the lattice-trapping interval `[K₋, K₊]`, expressed as `K/K_G`. Both limits must be folds of one connected, force-balanced branch at the specified bond-centred lattice site. Below `K₋` the crack heals by one lattice period; above `K₊` it advances one period. The interval must bracket Griffith loading and be reproducible at equivalent bulk-like tip sites.

## Requirements

Implement the region construction, flexible-boundary coupling, hybrid energy, crack-tip generalized force, internal-shift corrector and its derivative yourself. Use SW for atomistic energies and forces. Do not import, vendor or transcribe `matscipy.fracture_mechanics`, `matscipy.cauchy_born` or their crack drivers, or reuse a task-specific published or online solution. Other permitted tools are listed in `/app/spec.md`.

Use the specified bond-centred registration and supply configurations that support independent consistency checks. Relaxed `C11/C12/C44` and `K_G` must agree with the reference within 3%. Validate atomistic forces against energy finite differences to relative error ≤0.5%, and limit continuum residual forces to 5×10⁻³ eV/Å. At the lowest and highest loads, crack-tip closure and the corrector derivative must agree with finite differences within 6%. The internal-shift corrector must reproduce the supplied held-out strains within 5% and give zero response on symmetry-forbidden strains. Determine each trapping limit within an absolute error of 0.04 in `K/K_G`. Definitions and reference conditions are given in `/app/spec.md`.

Bracket each fold on the correct side with load width ≤0.02 and report its midpoint. Establish the lattice-period healing or advance from the configurations. Blunting, reconstruction, bond softening and numerical non-convergence do not establish a fold.

## Files

**Inputs**

| Path | Contents |
| --- | --- |
| `/app/spec.md` | Model equations, definitions, permitted tools and necessary evidence conventions, including physical symbols and units. |
| `/app/data/` | SW and LEFM helpers, geometry, strain grids and loads. |

**Deliverables**

Submit JSON or NPZ data under `/app/out/` for elastic and cleavage properties, forces, crack-tip closure, internal shifts and both fold brackets. Include the configurations needed to reproduce the checks.

Follow the existing evidence conventions in `/app/spec.md`. Elastic constants use GPa, `K_G` uses GPa√Å, and trapping loads use `K/K_G`; explicitly declared equivalent units are handled as described there. The time budget is 28,800 s.
