# A2 intervention and N130-rpL5 condensate structure (reduced-sampling Oracle)

## Question
Assess whether the author-defined A2 intervention changes PD spatial structure and A2-rpL5 association in the condensed phase.

## Method
The supplied four public inputs define the model and the A2 intervention. The starting configuration is a 300 A periodic subsystem extracted from the author-provided 50,328-bead WT configuration at 300 K; it contains 34 pentamers and 495 rpL5 peptides (15,589 beads). Molecules were selected by minimum-image center of mass and placed without changing their internal geometry; the extraction introduces no new overlaps. Three independent velocity seeds per condition were integrated with LAMMPS 2Aug2023_update4 at 0.1 fs with a Nose-Hoover thermostat at 300 K. WT uses the supplied force field; A2 additionally zeroes the nine declared acidic-region atom types and replaces their self-LJ terms with epsilon 0.25 kcal/mol, sigma 3.39 A, cutoff 8.47 A. The original quadratic dihedral coefficients are in the LAMMPS 16Dec2013 convention; the built-in quadratic style was used with the equivalent degree-valued, sign-flipped phi0 (verified to reproduce the plugin energy to better than 1e-3 kcal/mol).

## Findings
PD radius of gyration: WT 28.4892 A, A2 28.1557 A; difference -0.3334 A
(95% interval -0.4971 to -0.1698).
A2-rpL5 contacts per A2 bead: WT 4.9023, A2 5.9525; difference +1.0502
(95% interval +0.7959 to +1.3044).

## Uncertainty and limitations
The intervals are seed-level 95% t intervals with three independent velocity seeds. Production windows are 8 ps WT and 7 ps A2; the subsystem is not the full 108-pentamer target, so long-time diffusion, percolation and finite-size convergence are not resolved. The starting configuration is author-provided public data, not a new equilibration; finite-size effects remain. No physical threshold or author response direction was used.
