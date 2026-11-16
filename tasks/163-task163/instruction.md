# Task: Analyse alkene conical-intersection geometries and surface-hopping evidence

## Background

A central feature of alkene photoisomerization is the S1/S0 conical intersection (CI): after photon absorption, the molecule twists about H–C=C–H and stretches the C=C bond, with ultrafast internal conversion near the crossing region. For comparison, SHARC surface-hopping trajectories have jump geometries concentrated around a dihedral angle of 80–100° and r(C=C) of 2.5–2.8 Bohr.

## Task

Without training any model, perform a static photochemical analysis directly on the three public 2D grid databases. Reconstruct the scan coordinates, quantify excitation features, and locate the crossing region.

Decide how to define the CI using two complementary criteria: a low S1–S0 energy gap and the magnitude |C01|. Choose the thresholds and state them in the summary, including a sensitivity discussion. Compare the grid's crossing features with the supplied source’s trajectory window (80–100°, 2.5–2.8 Bohr). Give an evidence-based account of which dimensions agree or differ, including grid-boundary effects.

## Requirements

- Environment: use the container Python on `PATH`. Preinstalled packages include ASE, matplotlib, NumPy, pillow, SciPy. Do not install additional packages or fetch dependencies from the network.

The scan range and step sizes are not provided; reconstruct them from the geometries. Account for atom identification, units, and the dihedral-angle convention. The stored atom order is consistent across ethylene, propylene, and butylene; explain how the butylene dihedral is defined relative to cis/trans.

The oscillator strength is given by main-text equation (4): f = (2/3)·ΔE_ji·|μ_ji|² in atomic units, with ΔE in Hartree. The `row.data` energy, force, dipole, and NAC fields use the same format convention as in Task 162.

Use one of the two selector families and the calibrated search domain specified in `inputs/output-contract.md`; the dihedral search must remain within 70–110°. A low-gap/high-NAC window is a finite sampled static-grid proxy and cannot by itself establish an exact CI seam or dynamical visitation.

### Input and deliverable details

- `inputs/databases/04/05/06_3Sing_*_grid.db`: three molecular grids, each with 3,731 structures on a regular 2D scan (C=C bond length × H–C=C–H dihedral), calculated at SA(3)-CASSCF(2,2)/cc-pVDZ for S0/S1/S2. The `row.data` entries contain energies, forces, dipoles, and NACs.
- `inputs/output-contract.md`: required tables, JSON, and diagnostic plots under `outputs/`.

## Files

Public input files:

| File path | Description |
| --- | --- |
| `inputs/output-contract.md` | required tables, JSON, and diagnostic plots under `outputs/`. |
| `inputs/databases/04/05/06_3Sing_*_grid.db` | three molecular grids, each with 3,731 structures on a regular 2D scan (C=C bond length × H–C=C–H dihedral), calculated at SA(3)-CASSCF(2,2)/cc-pVDZ for S0/S1/S2. The `row.data` entries contain energies, forces, dipoles, and NACs. |

| Path | Contents |
| --- | --- |
| `/app/outputs` | Required result; use the contents and format specified above. |
