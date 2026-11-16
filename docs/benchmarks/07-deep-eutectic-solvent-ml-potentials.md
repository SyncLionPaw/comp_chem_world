# Deep Eutectic Solvent ML Potentials

## Overview

This benchmark is based on the study "**Efficient Molecular Dynamics Simulations of Deep Eutectic Solvents with First-Principles Accuracy Using Machine Learning Interatomic Potentials**" by Omid Shayestehpour and Stefan Zahn, published in *Journal of Chemical Theory and Computation* (2023).

The study investigates reline, a choline-chloride/urea deep eutectic solvent, using machine-learned interatomic potentials trained on first-principles data. It examines structural and transport properties through molecular dynamics. The central question is whether efficient learned potentials can reproduce first-principles behaviour with defensible accuracy, sampling, and uncertainty.

**Reference:** Omid Shayestehpour and Stefan Zahn, *Journal of Chemical Theory and Computation*, 2023. DOI: [10.1021/acs.jctc.3c00944](https://doi.org/10.1021/acs.jctc.3c00944).

## Tasks

| Task | Description |
| --- | --- |
| Task 42 | Audit model errors on a small public DFT training and holdout dataset. |
| Task 43 | Analyse temperature-dependent behaviour in archived short NPT trajectories. |
| Task 44 | Audit historical CP2K, prediction, and execution records without launching new calculations. |
| Task 45 | Investigate molecular-centre-of-mass diffusion and its identifiability within a finite budget. |
| Task 46 | Investigate conductivity estimates with consistent temperature, units, and sampling evidence. |
| Task 47 | Compare transport observables and finite-size-corrected diffusion across six temperatures. |
| Task 48 | Independently assess the reliability and transferability of a reline potential. |

## Environment repair note (2026-11)

Task 042 now selects hashed PyTorch 2.8.0 CPU wheels for both Linux ARM64 and AMD64, avoiding unpinned CUDA dependencies. See [environment repairs and oracle checks](environment-repairs.md) before rerunning.
