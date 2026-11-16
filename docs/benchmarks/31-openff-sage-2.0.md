# OpenFF Sage Small-Molecule Force Field

## Overview

This benchmark is based on the study "**Development and Benchmarking of Open Force Field 2.0.0: The Sage Small Molecule Force Field**" by Simon Boothroyd et al., published in *Journal of Chemical Theory and Computation* (2023).

The study develops and benchmarks the Open Force Field 2.0.0 Sage small-molecule force field. Molecular energetics and condensed-phase properties provide complementary tests of its parameterisation and predictive accuracy. The central question is how force-field development can improve the description of small molecules across conformational and bulk-property benchmarks.

**Reference:** Simon Boothroyd et al., *Journal of Chemical Theory and Computation*, 2023. DOI: [10.1021/acs.jctc.3c00039](https://doi.org/10.1021/acs.jctc.3c00039).

## Tasks

| Task | Description |
| --- | --- |
| Task 201 | Parameterise molecules with Sage and check molecular energy and force consistency. |
| Task 202 | Perform multi-start conformer minimisation and compare the resulting structures and energies. |
| Task 203 | Compute constrained relaxed molecular-mechanics torsion scans against quantum reference profiles. |
| Task 204 | Sample small-system liquid NPT trajectories and estimate liquid densities. |
| Task 205 | Analyse finite gas-phase MBAR reweighting and identifiability limits. |
| Task 206 | Refit Sage torsion parameters and evaluate performance on protected validation data. |
