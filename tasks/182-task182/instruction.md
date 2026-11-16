# Task: Analyze oxygen structure in fixed nonblind water trajectories

## Background

The inputs are two historical, nonblind 10 ps trajectories of 300 K periodic water. Each has 201 frames at 50 fs spacing, 64 O and 128 H atoms, and a 12.4 Å cubic cell; type 1 is O and type 2 is H. No new simulation or electronic-structure calculation is required.

Follow the descriptions below for inputs and available resources; independently acquire materials where required.

## Task

Calculate the O–O radial distribution function (RDF) and first-shell coordination for both trajectories.

## Requirements

- Environment: use the container Python on `PATH`; required scientific packages are preinstalled. Do not install additional packages or fetch dependencies from the network.

Use atom IDs and MIC distances. Compute each replica’s RDF with 0.05 Å bins through 6.2 Å, using distinct unordered O–O pairs and finite-N normalization:

    g(r) = H(r) V / (Nframes × N_O(N_O−1)/2 × shell_volume(r))

where shell_volume = 4π/3 × (r_outer³ − r_inner³) and N_O = 64. Report each full-trajectory RDF and descriptive segments 0 ≤ t ≤ 5.00 ps and 5.00 < t ≤ 10.00 ps. Pool both full trajectories to find the maximum-g bin centered in [2.40, 3.10] Å (lower-radius bin wins ties). Smooth the pooled RDF with a centered three-bin mean and report the first post-peak local minimum in [3.00, 4.00] Å that is no greater than its left neighbor and strictly below its right neighbor. Use the fixed 3.55 Å upper-edge cutoff for first-shell coordination, integrating with oxygen density (N_O−1)/V; integration through 6.2 Å is cumulative coordination. The segments and replicas are descriptive, not independent samples; do not claim independent standard errors, equilibration, or convergence.

### Input and deliverable details

Inputs are environment/assets/public-inputs-v2/trajectories/replica-00.lammpstrj and replica-01.lammpstrj; environment/assets/public-inputs-v2/trajectory-manifest.json records conditions and source hashes. Submit final/exploration/rdf-analysis.json with RDF arrays, peak and minimum, method and cutoff, full and segment first-shell coordination, source hashes, and interpretation limits. Complete output fields and shapes are in the [public output schema](environment/assets/public-docs-v2/output-schema-v2.md).

## Files

Public input files:

| File path | Description |
| --- | --- |
| `/app/environment/assets/public-inputs-v2/` | Two archived water trajectories and associated input data. |
| `/app/environment/assets/public-docs-v2/` | Data definitions and analysis conventions. |

| Path | Contents |
| --- | --- |
| `/app/final` | Required result; use the contents and format specified above. |
