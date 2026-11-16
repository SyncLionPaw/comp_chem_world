# Task: Reconstruct migration barriers from deposited CI-NEB paths

## Background

Completed climbing-image NEB outputs are supplied for Li, Mg and Na migration in TiS2; no `neb.dat`, barrier values or rerun is needed. The experimental context contrasts Mg–Li cointercalation in O1 with limited Mg cointercalation in Mg–Na systems as the host changes stacking.

## Task

Recompute barriers for all ten paths: `O1_Li`, `O1_Mg`, `O1_Na`, `Li05_Li`, `Li05_Mg`, `O3_Na`, `O3_Mg_PATH1`, `O3_Mg_PATH2`, `P3_Na`, `P3_Mg`, and assess what comparisons support. `Li05` is Li0.5TiS2; include both O3 Mg paths.

## Requirements

For each image, use the final ionic-step `F=` free energy from `OSZICAR`; subtract image 00. Barrier is the maximum relative energy, with its integer image index; it is an interior saddle only if the maximum is strictly inside the endpoint images. Compare with 0.05 eV thresholds: O1 Mg vs O1 Li; O1 vs Li0.5 for Li and Mg separately; P3 vs O3 for Na; and P3 Mg vs each O3 Mg path. Report `delta_Mg_O1_minus_Li05_eV = barrier(O1_Mg)-barrier(Li05_Mg)`. The P3 comparison supports a poor Mg–Na storage explanation only if both P3 Na and P3 Mg barriers exceed the corresponding O3 barriers by >0.05 eV (Mg against both paths); barriers alone do not establish experimental mechanism.

Write `/app/barriers.json`, schema version 2, with all ten paths containing integer `n_images`, ordered `energies_rel_eV`, `barrier_eV`, integer `barrier_image`, `endpoint_rel_eV`, and boolean `interior_saddle`; also include the stated delta, claims `O1_Mg_slower_than_O1_Li`, `O1_Na_interior_saddle`, `Li05_lowers_Mg_barrier`, `Li05_lowers_Li_barrier`, `P3_Na_below_O3_Na`, `P3_Mg_below_both_O3_paths`, `low_P3_barrier_explains_poor_Mg_Na_storage`, and `methods.energy_source=last_ionic_F`. Generate `/app/report.md` with the supplied renderer.

Energy comparisons use an absolute tolerance of 0.002 eV. The historical key `low_P3_barrier_explains_poor_Mg_Na_storage` uses the higher-P3 comparison defined above.

## Files

Public input files:

| File path | Description |
| --- | --- |
| `/app/environment/assets/` | Native NEB images, energies and path definitions. |

Read all image `OSZICAR` and `CONTCAR` plus parent `INCAR` under `/app/environment/assets/neb/<path_id>/`, and `/app/environment/assets/PATHS.md`. Submit `/app/barriers.json` and `/app/report.md`.
