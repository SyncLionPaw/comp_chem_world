# Ai2-Kit AI Accelerated Ab Initio Workflows

## Overview

This benchmark draws on the preprint "**Ai2-Kit: Streamlining AI-Accelerated Ab Initio Workflows for Complex Chemical Systems**" by Sheng Bi et al., available on *arXiv* (2026).

The work investigates reproducible workflows that connect first-principles calculations, machine-learned potentials, molecular dynamics, and HPC orchestration. The central question is how these components can be assembled into reusable workflows for complex chemical systems. This benchmark applies those ideas to water preparation, fresh calculations, fixed-trajectory analysis, and independent potential development.

**Reference:** Sheng Bi et al., *arXiv*, 2026. DOI: [10.48550/arXiv.2607.00613](https://doi.org/10.48550/arXiv.2607.00613).

## Tasks

| Task | Description |
| --- | --- |
| Task 179 | Generate an isolated water molecule with a chemically valid geometry. |
| Task 180 | Run three fresh periodic-water CP2K labelling calculations. |
| Task 181 | Run new water MLMD trajectories with a fixed DeepMD committee. |
| Task 182 | Analyse oxygen structure in supplied historical water trajectories. |
| Task 183 | Quantify static hydrogen-bond networks and tetrahedral order. |
| Task 184 | Diagnose the displacement information available in wrapped water trajectories. |
| Task 185 | Independently construct and evaluate a water potential using Ai2-Kit. |
