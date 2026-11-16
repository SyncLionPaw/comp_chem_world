# Task: Analyse CO2 structural fluctuations in water and potassium-containing interfacial trajectories

## Background

The four source molecular dynamics trajectories record structural fluctuations of neutral and reduced CO₂ at aqueous and K-containing interfaces. Bond lengths and angles describe geometry; by themselves, they cannot measure local charge or establish a reaction mechanism or causality.

## Task

Identify CO₂ in each trajectory, reconstruct how its bond lengths and angle change over time, and compare structural statistics between the two charge states. Explain which geometric conclusions are supported by these finite, time-correlated trajectories and which uncertainties remain unresolved.

## Requirements

- Environment: use the container Python on `PATH`. Preinstalled packages include ASE, matplotlib, NumPy, pillow, SciPy. Do not install additional packages or fetch dependencies from the network.

- Read only the four public trajectories in `/app/environment/assets/`. In the first frame of each system, identify one C and its two O atoms from elemental composition and spatial proximity, then keep those atom indices fixed. Use periodic-boundary minimum images for distances and angles.
- For each system, sample zero-based frames `range(1000, n_frames, 10)`. The columns in `geometry.csv` are `system,frame,co_short_A,co_long_A,oco_deg`; order systems as `water_CO2`, `water_CO2anion`, `2K_CO2`, `2K_CO2anion`, then order frames increasingly within each system. Bond lengths are in Å and angles in degrees.
- `summary.json` contains a `systems` mapping for the four systems. Each entry provides `n_frames`, `n_samples`, `co_short_mean_A`, `co_long_mean_A`, `oco_mean_deg`, `co_short_std_A`, `co_long_std_A`, `oco_std_deg`, and `block_means`. Split each system's samples in time order into five blocks using `numpy.array_split`. Each block may be represented as a three-number array `[mean short-bond length, mean long-bond length, mean bond angle]`, or as an object containing only `co_short_mean_A`, `co_long_mean_A`, and `oco_mean_deg`. Sort the two bond lengths within each frame; use `ddof=1` for standard deviations.
- `conclusions` provides five Boolean values: `water_reduction_bends`, `K_reduction_bends`, `K_anion_more_bent_than_water`, `water_reduction_elongates`, and `K_reduction_elongates`. Compare mean O–C–O angles to assess bending. Assess elongation by comparing the mean short bond in the reduced state with the mean long bond in the corresponding neutral state.
- `interpretation` provides four Boolean values: `geometry_directly_measures_electronic_charge`, `geometry_alone_proves_causal_mechanism`, `sample_std_is_SEM`, and `five_block_means_are_independent_CI`. Explain these judgments in light of the sampling and temporal correlation; do not treat frame-to-frame standard deviations or the range across five blocks as confidence intervals for the mean.
- The absolute differences between recomputed geometries and independent results must not exceed `1e-4 Å` for bond lengths or `1e-2°` for angles. Sample counts and conclusion fields must match their definitions exactly. These are computational consistency tolerances, not physical errors or confidence intervals.

### Input and deliverable details

- `/app/environment/assets/water_CO2/10ps.traj`
- `/app/environment/assets/water_CO2anion/10ps.traj`
- `/app/environment/assets/2K_CO2/10ps.traj`
- `/app/environment/assets/2K_CO2anion/10ps.traj`
- Use Python 3.12, ASE, and NumPy. Write `geometry.csv`, `summary.json`, an executable `analysis.py`, and `report.md` to `/app/final/`. `python analysis.py ASSET_DIR OUTPUT_DIR` must recompute the scientific data from the public trajectories and reproduce the two data files. The report must explain atom identification, PBC/minimum-image handling, sampling statistics, temporal correlation, and the scope of the conclusions.

Here `ASSET_DIR` is `/app/environment/assets/` and `OUTPUT_DIR` is `/app/final/`. Create `analysis.py` as part of your submission; no analysis script is supplied for this task.

## Files

Public input files:

| File path | Description |
| --- | --- |
| `/app/environment/assets/` | Directory of supplied inputs and resources. |
| `/app/environment/assets/water_CO2/10ps.traj` | Supplied scientific input or resource; see the task requirements for format and units. |
| `/app/environment/assets/water_CO2anion/10ps.traj` | Supplied scientific input or resource; see the task requirements for format and units. |
| `/app/environment/assets/2K_CO2/10ps.traj` | Supplied scientific input or resource; see the task requirements for format and units. |
| `/app/environment/assets/2K_CO2anion/10ps.traj` | Supplied scientific input or resource; see the task requirements for format and units. |

| Path | Contents |
| --- | --- |
| `/app/final` | Required result; use the contents and format specified above. |
