# Task: Quantify static hydrogen-bond networks and tetrahedral order in water

## Background

The inputs are two historical, nonblind 300 K periodic-water trajectories. Each has 201 frames at 50 fs spacing, 64 O and 128 H atoms, and a 12.4 Å cubic cell; type 1 is O and type 2 is H. No simulation, DFT, training, or inference is required.

Follow the descriptions below for inputs and available resources; independently acquire materials where required.

## Task

Reconstruct the O–H mapping from geometry and quantify the static hydrogen-bond network and local tetrahedral order.

## Requirements

- Environment: use the container Python on `PATH`; required scientific packages are preinstalled. Do not install additional packages or fetch dependencies from the network.

For every frame, assign each H to its nearest O using orthorhombic MIC. Accept a mapping only if every nearest O–H distance is <1.25 Å, every nearest/second-nearest distance gap is >0.20 Å, and every O receives exactly two H atoms. Report diagnostics for all frames and fail closed if any gate fails.

A directed donor–H–acceptor bond requires distinct O atoms, r(O_d,O_a) < 3.5 Å, and an angle <30° between MIC vectors O_d→H and O_d→O_a. Record directed bonds; for the graph, deduplicate each O pair into one undirected edge and report per-frame degree histograms and connected-component sizes.

For each O in each frame, calculate q = 1 − (3/8) Σ_(j<k) (cos ψ_jk + 1/3)^2 over its four nearest other O atoms using MIC vectors. Break ties at the fourth neighbor by ascending O ID. Preserve negative values. Report all per-O q values and per-frame count, mean, population standard deviation (ddof=0), minimum, median, and maximum.

### Input and deliverable details

Inputs are the two trajectories listed in environment/assets/public-inputs-v2/trajectory-manifest.json. Submit final/relabel/network-analysis.json with source hashes, mapping rule and framewise diagnostics, directed bonds, undirected graph summaries, per-O q values, per-frame q summaries, and interpretation limits. Complete output fields and shapes are in the public output schema at environment/assets/public-docs-v2/output-schema-v2.md.

## Files

Public input files:

| File path | Description |
| --- | --- |
| `/app/environment/assets/public-inputs-v2/` | Two archived water trajectories and associated input data. |
| `/app/environment/assets/public-docs-v2/` | Data definitions and analysis conventions. |

| Path | Contents |
| --- | --- |
| `/app/final` | Required result; use the contents and format specified above. |
