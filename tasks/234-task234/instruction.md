# Spatial Dipole Correlation Tensors and Needle-Like Order Diagnosis

## Background

Ferroelectric order in BaTiO3 leaves a spatial imprint: the correlation between dipole displacements in neighbouring unit cells. The supplied author trajectories give a 5x5x5 periodic grid of unit cells at 250 K under ambient pressure and under 30 GPa, so the spatial correlation tensor and its anisotropy can be measured directly from the recorded dipoles. A short-range descriptor cutoff does not by itself forbid longer effective coupling.

The ambient and 30 GPa trajectories contain 4947 and 3439 frames, respectively, with 125 cells per frame. The inputs also provide grid coordinates, reference cell and lattice constant, temperature and stress settings, a high-pressure cell-snapshot excerpt, and the author potential configuration with its descriptor cutoff.

## Task

Compute the full canonical spatial Pearson correlation tensor, its condensed projections, the pressure comparison and the moving-block bootstrap diagnostics from the supplied records, following the listed output convention.

Choose a component (0..2), spatial axis (0..2), displacement (1 or 2 lattice cells), an integer seed in 0..2^32-1 and a number of contiguous blocks (2..6). In `constructive_controls.json`, provide `spec` with `component`, `axis`, `distance_cells`, `seed`, `blocks`, and the matching `results` computed under `/app/public/autonomous_controls.py`, applying an independently generated spatial permutation in each frame, a periodic lattice translation and the contiguous-block comparisons.

## Requirements

- Use all raw frames of both trajectories, no truncation or chosen subset. The full original tensor and all displacements remain mandatory regardless of the exploratory choice.
- Report original, shuffled and translated correlations, the shuffle contrast, every block value, and the minimum and maximum.
- High-pressure distances stay in cell units because the short cell excerpt does not align with all dipole frames. Do not assign Angstrom distances to the high-pressure trajectory.
- The source range is the 5.5 Angstrom atom-centred descriptor cutoff; shared local environments can mediate longer effective coupling. The finite-grid fits and block intervals are descriptive; no asymptotic length, unique mechanism or causal pressure law is identified. `claim_scope` records those bounds and accompanies computed controls; it never substitutes for them.
-
- Use rtol 2e-6 and atol 2e-7 for scalar and tensor comparisons; use the specified bootstrap and interval tolerances.

- Include the boolean `needle_like_anisotropy_confirmed` in `spatial_correlation_results.json`: set it to `true` if and only if `axial_minus_radial_nn_ci95[0] > 0` and `axial_2cell_Cxx > 0`; otherwise set it to `false`. This records finite-record anisotropy and does not identify a unique mechanism or asymptotic length.

Submit the results according to the listed output convention.

## Files

| Path | Description |
| --- | --- |
| `/app/inputs/` | Dipole trajectories and system parameters. |
| `/app/final/` | Submitted results and required execution evidence. |
| `/app/canonical-protocol.md` | Calculation methods and result-submission requirements. |
