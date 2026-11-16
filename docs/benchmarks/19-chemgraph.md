# ChemGraph

## Overview

This benchmark is based on the study "**ChemGraph as an agentic framework for computational chemistry workflows**" by Thang D. Pham, Aditya Tanikanti and Murat Keçeli, published in *Communications Chemistry* (2026).

The study introduces ChemGraph, an agentic framework connecting natural-language requests with computational-chemistry tools. Its workflows combine cheminformatics, structure generation, geometry optimisation, vibrational analysis, and thermochemistry. The central question is whether an agent can select and chain these tools correctly to deliver chemically consistent molecular and reaction properties.

**Reference:** Thang D. Pham, Aditya Tanikanti and Murat Keçeli, *Communications Chemistry*, 2026. DOI: [10.1038/s42004-025-01776-9](https://doi.org/10.1038/s42004-025-01776-9).

## Tasks

| Task | Description |
| --- | --- |
| Task 120 | Convert molecular names into canonical SMILES. |
| Task 121 | Generate reproducible three-dimensional structures from molecular names. |
| Task 122 | Optimise name-specified molecular structures with GFN2-xTB. |
| Task 123 | Calculate molecular vibrational frequencies from a Hessian. |
| Task 124 | Compute molecular thermochemistry with consistent symmetry and spin conventions. |
| Task 125 | Write an optimised structure to a molecule-specific coordinate file. |
| Task 126 | Generate reproducible three-dimensional structures from SMILES. |
| Task 127 | Optimise SMILES-specified molecular structures with GFN2-xTB. |
| Task 128 | Calculate vibrational frequencies for SMILES-specified molecules. |
| Task 129 | Compute thermochemistry for SMILES-specified molecules. |
| Task 130 | Export SMILES-derived optimised coordinates with the required naming convention. |
| Task 131 | Compute reaction enthalpies from consistent species-level calculations. |
| Task 132 | Compute reaction Gibbs free energies with consistent thermal and spin contributions. |
