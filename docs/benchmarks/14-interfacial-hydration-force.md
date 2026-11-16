# Interfacial Hydration Force

## Overview

This benchmark is based on the study "**The Dramatic Effect of Water Structure on Hydration Forces and the Electrical Double Layer**" by Jonathan G. Hedley, Hélène Berthoumieux and Alexei A. Kornyshev, published in *The Journal of Physical Chemistry C* (2023).

The study investigates how molecular water structure affects hydration forces and the electrical double layer. Molecular-dynamics response data inform a non-local dielectric model, boundary-value calculations, and electrostatic observables. The central question is how microscopic water correlations connect oscillatory and monotonic interfacial forces with measurable electrical response.

**Reference:** Jonathan G. Hedley, Hélène Berthoumieux and Alexei A. Kornyshev, *The Journal of Physical Chemistry C*, 2023. DOI: [10.1021/acs.jpcc.3c00262](https://doi.org/10.1021/acs.jpcc.3c00262).

## Tasks

| Task | Description |
| --- | --- |
| Task 88 | Compute bulk dielectric response and uncertainty from a new SPC/E production trajectory. |
| Task 89 | Infer a two-mode dielectric kernel from five supplied response targets. |
| Task 90 | Calculate hydration pressure using the specified variational boundaries and roughness convention. |
| Task 91 | Solve the coupled Poisson–Fermi electrical-double-layer model. |
| Task 92 | Analyse differential capacitance and Parsons–Zobel concentration relationships. |
| Task 93 | Repair a defective hydration-force solver that suppresses oscillations. |
| Task 94 | Reconstruct longitudinal dielectric response from a supplied SPC/E trajectory sample. |
| Task 95 | Evaluate scientific evidence for oscillatory versus monotonic mica hydration forces. |
