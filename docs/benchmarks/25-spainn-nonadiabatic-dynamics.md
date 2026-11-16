# SPaiNN Nonadiabatic Dynamics

## Overview

This benchmark is based on the study "**SPaiNN: equivariant message passing for excited-state nonadiabatic molecular dynamics**" by Sascha Mausenberger et al., published in *Chemical Science* (2024).

The study introduces SPaiNN, an equivariant message-passing model for excited-state energies, forces, and nonadiabatic couplings. Learned electronic properties drive nonadiabatic molecular dynamics and the analysis of photochemical pathways. The central question is whether these models preserve the coupled electronic and geometric behaviour needed for reliable excited-state dynamics.

**Reference:** Sascha Mausenberger et al., *Chemical Science*, 2024. DOI: [10.1039/d4sc04164j](https://doi.org/10.1039/d4sc04164j).

## Tasks

| Task | Description |
| --- | --- |
| Task 162 | Audit the XAlkeneDB reference database, electronic-state conventions, and training inputs. |
| Task 163 | Analyse alkene conical-intersection geometries and surface-hopping evidence. |
| Task 164 | Assess bounded fine-tuning of a nonadiabatic-coupling head and its symmetry properties. |
| Task 165 | Evaluate an exploratory PaiNN/SHARC dynamics model and justify whether to continue. |
| Task 166 | Cross-check three-root state-averaged CASSCF properties for two fixed ethylene geometries. |
