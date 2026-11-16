# NewtonNet Hessian Transition States

## Overview

This benchmark is based on the study "**Analytical ab initio hessian from a deep learning potential for transition state optimization**" by Eric C.-Y. Yuan et al., published in *Nature Communications* (2024).

The study investigates analytical Hessians derived from the differentiable NewtonNet potential for transition-state optimisation. It compares full learned Hessians with quasi-Newton updates and density-functional references. The central question is whether inexpensive learned curvature information improves saddle-point convergence, robustness to initial guesses, and connection to the intended reaction endpoints.

**Reference:** Eric C.-Y. Yuan et al., *Nature Communications*, 2024. DOI: [10.1038/s41467-024-52481-5](https://doi.org/10.1038/s41467-024-52481-5).

## Tasks

| Task | Description |
| --- | --- |
| Task 138 | Check energy derivatives, Hessians, and unit consistency on a fixed NewtonNet potential. |
| Task 139 | Analyse curvature bias in paired predicted and DFT Hessian eigenvalues. |
| Task 140 | Compare NewtonNet and DFT Hessians at four fixed reaction geometries. |
| Task 141 | Compare full-Hessian and quasi-Newton saddle searches. |
| Task 142 | Assess saddle-search robustness to controlled perturbations of initial guesses. |
| Task 143 | Trace downhill paths in both directions and verify reactant/product endpoint identities. |
