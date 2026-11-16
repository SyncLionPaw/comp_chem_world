# Task: DCM inversion of intra- and interlayer force constants

## Background

The supplied pressure-dependent Raman data contain E₂g¹ and E₂g² frequencies for several layer counts. Public conventions define the masses, units and diatomic-chain model (DCM).

## Task

Invert the DCM for each available layer/pressure pair to obtain intralayer and interlayer force constants. Report their pressure slopes and `Cs_b/Cs_w`; explain selection of the physical root and pairing of the Raman branches.

## Requirements

- Environment: use the container Python on `PATH`. Preinstalled packages include NumPy, SciPy. Do not install additional packages or fetch dependencies from the network.

Use the pressure points actually present for each layer in E₂g²; there is no common grid. Pair E₂g¹ and E₂g² to the nearest source point within 0.25 GPa. Report constants in N m⁻¹, slopes in N m⁻¹ GPa⁻¹ and dimensionless ratios. Put explanations in `physical_root_rationale` and `pairing_rule`. Preserve the 0.08 slope tolerance, 6% `Cs_b` and 8% `Cs_w` evaluated-route tolerances, ≤5% ratio match with ratio ≤0.05, and ≤1 cm⁻¹ back-calculated frequency error. Exact fields and coverage are in `/app/verification.md`.

Provide nonempty scientific explanations in `physical_root_rationale` and `pairing_rule`.

## Files

Public input files:

| File path | Description |
| --- | --- |
| `/app/assets/` | Pressure-dependent Raman series and conventions. |
| `/app/verification.md` | Methods and output specification. |

Inputs: `/app/assets/public_e2g1_vs_p.csv`, `/app/assets/public_e2g2_vs_p.csv`, and `/app/assets/conventions.md`. Submit `/app/final/results.json` and `/app/final/dcm_table.csv` under the public contract.
