# Atomistic Simulation Benchmark

## Overview

This benchmark combines six independent tasks in atomistic modelling and scientific programming rather than reproducing a single study. It covers fracture, diffraction, conformer ensembles, geometric constraints, phonon transport, and battery energetics. Its conformer task uses MACE-OFF23, described in "**MACE-OFF: Short-Range Transferable Machine Learning Force Fields for Organic Molecules**" by Dávid Péter Kovács et al. in *Journal of the American Chemical Society* (2025). The central question is whether an agent can produce physically consistent, reproducible results across these distinct workflows.

**Task 110 model reference:** Dávid Péter Kovács et al., *Journal of the American Chemical Society*, 2025. DOI: [10.1021/jacs.4c07099](https://doi.org/10.1021/jacs.4c07099). This is the reference for the MACE-OFF23 potential used by Task 110 only; it is not the source of the benchmark as a whole. Task 113 uses the CHGNet potential.

## Tasks

| Task | Description |
| --- | --- |
| Task 108 | Implement silicon flexible-boundary crack mechanics and determine the lattice-trapping range. |
| Task 109 | Infer absolute phase fractions from multiphase powder diffraction and supporting measurements. |
| Task 110 | Generate MACE-OFF23 conformer ensembles and consistent Boltzmann populations. |
| Task 111 | Implement conformer generation subject to distance, angle, and signed-torsion restraints. |
| Task 112 | Calculate 3C-SiC lattice thermal conductivity from anharmonic force constants. |
| Task 113 | Calculate LiFePO4 intercalation voltage from consistently relaxed cathode and lithium references. |

## Environment repair note (2026-11)

Tasks 110, 112 and 113 now ship pinned local model caches with SHA-256 checks and Docker build steps that load the requested models without network access. Dependency downloads use uv retries and cache; build timeouts are 3600 seconds. The model names and scientific requirements are preserved. See [environment repairs, provenance and oracle checks](environment-repairs.md).
