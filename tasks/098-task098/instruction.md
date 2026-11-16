# Task: MD spectra and elastic-modulus inversion

## Background

The supplied data contain six-layer MoS₂ centroid trajectories at twelve pressures, plus layer-order and trajectory information. Extract the shear (S) and layer-breathing (LB) branches. The bulk LB mode is the out-of-plane optical mode with adjacent layers moving in opposite phase; distinguish it from rigid translation and uniform layer-spacing change.

## Task

Analyze every pressure, convert assigned frequencies to interlayer force constants and elastic moduli, and support each assignment with quantitative evidence. Describe the signal processing and mode tracking.

## Requirements

- Environment: use the container Python on `PATH`. Preinstalled packages include NumPy, SciPy. Do not install additional packages or fetch dependencies from the network.

Use the fixed grid `[0, 0.5, 1.65, 2.4, 3.06, 4.09, 4.7, 5.48, 6.3, 7.25, 8, 9.6]` GPa, `t(P)=6.15×10⁻¹⁰(1−0.0104P)` m, and areal mass `μ=3.0738408378142946×10⁻⁶ kg m⁻²`. Report frequency in cm⁻¹, `alpha` in 10¹⁹ N m⁻³ and moduli in GPa. Preserve the ≤6% frequency–mass identity and ≤8% `C=alpha·t(P)` check, independent S/LB peak tolerances (3/8 cm⁻¹), parallel-constant agreement within 15% through 6.3 GPa, and independent high-pressure coverage. Follow `/app/verification.md` for the full contract.

## Files

Public input files:

| File path | Description |
| --- | --- |
| `/app/assets/` | Pressure-indexed trajectories, cell and layer definitions. |
| `/app/verification.md` | Methods and output specification. |

Inputs: `/app/assets/P_*.txt`, `/app/assets/trajectory_format.md`, `/app/assets/conventions.md`, `/app/assets/P_0.00.lammpstrj` (cell), and `/app/assets/6L_MoS2_origin` (layer order). Submit aligned `/app/final/results.json`, `/app/final/methods.md`, and mode evidence in `/app/final/mode_evidence.md` or `/app/final/spectra.csv`.
