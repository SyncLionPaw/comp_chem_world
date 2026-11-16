# Scalable Constant-pH Molecular Dynamics

## Overview

This benchmark is based on the study "**Scalable Constant pH Molecular Dynamics in GROMACS**" by Noora Aho et al., published in *Journal of Chemical Theory and Computation* (2022).

The study develops scalable constant-pH molecular dynamics within GROMACS to sample protonation equilibria alongside molecular motion. Titration behaviour and computational performance provide complementary measures of the approach. The central question is how to make coupled protonation and conformational sampling accurate and computationally scalable.

**Reference:** Noora Aho et al., *Journal of Chemical Theory and Computation*, 2022. DOI: [10.1021/acs.jctc.2c00516](https://doi.org/10.1021/acs.jctc.2c00516).

## Tasks

| Task | Description |
| --- | --- |
| Task 220 | Run tripeptide constant-pH titrations and estimate pKa values with uncertainty. |
| Task 221 | Run fixed-pH tripeptide simulations and analyse lambda distributions and protonation populations. |
| Task 222 | Run protein multisite constant-pH titrations and assess site-specific pKa agreement with experiment. |
| Task 223 | Validate coarse-grained Martini constant-pH molecular dynamics. |
| Task 224 | Compare the performance and scaling of conventional and constant-pH molecular dynamics. |
| Task 225 | Fit Henderson–Hasselbalch titration curves from supplied lambda trajectories. |
