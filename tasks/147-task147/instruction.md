## Background

Benzophenone has low-lying carbonyl n–π* states. This task tests how their energies and character depend on the exchange-correlation functional when geometry and numerical settings are controlled.

## Task

Independently optimize neutral benzophenone (C13H10O, 24 atoms; `O=C(c1ccccc1)c1ccccc1`) and establish that it is a minimum. At that geometry calculate the three lowest singlet and three lowest triplet roots using two genuinely distinct TDDFT functionals. Compare their energies and state character.

## Requirements

- Environment: use the container Python on `PATH`. Preinstalled packages include h5py, NumPy, PySCF, SciPy. Do not install additional packages or fetch dependencies from the network.

If using HPC, follow the `hpc` workflow: probe the authorized target, submit, wait for a terminal state, collect native outputs, and validate the scientific result.

Use the task’s configured remote execution profile within its run budget. Do not start from a task-answer geometry.

Hold the optimized geometry, basis, response approximation, DFT grid and density-fitting settings fixed across both functionals. The functional labels must resolve to different PySCF/libxc functionals; aliases of the same functional do not count as a pair. Report each root's excitation energy in Hartree, oscillator strength (exactly zero for triplets), leading NTO-pair weight and 24-atom AO-overlap Mulliken gross hole and particle populations. Each population vector must sum to one; these are gross populations, not probabilities. Use the population vectors and NTO overlaps to compare oxygen-hole and carbonyl-particle character. Identify corresponding states using leading hole/particle NTO overlaps, a 3×3 pair-similarity matrix and the one-to-one root assignment that maximizes the matrix total; root number alone does not identify a state. Compare functional sensitivity from the matched root energies and NTO evidence. These quantities do not establish spin-orbit coupling (SOC) or an absolute intersystem-crossing (ISC) rate. You may include a written interpretation in the optional `decision.md`.

The maximum absolute Cartesian gradient must be ≤ `1e-4 Eh/bohr` both at the accepted optimizer evaluation and at an independent final-geometry gradient recheck. Compute all 66 harmonic frequencies; all must be positive. Preserve the raw Cartesian Hessian. Its maximum-entry and Frobenius antisymmetry ratios relative to the symmetrized Hessian must each be ≤ `1e-4`; raw and symmetrized spectra must be stable and agree mode-by-mode within `0.1 cm-1`. Independent reconstruction from the submitted Hessian must reproduce every frequency within `0.01 cm-1`; the dimensionless C=O projection array must agree with `rtol=2e-7, atol=2e-9`. Use one consistent geometry for frequencies, modes and projections; optimizer coordinates and `structure.xyz` must agree within `1e-9 Å`.

## Files

Public input files:

| File path | Description |
| --- | --- |
| `/app/inputs/benchmark.json` | Benchmark parameters and calculation conditions. |

`final/result.json` is a concise report with this structure: one `response_approximation` (`full TDDFT` or `TDA`); optional `functional_pair_rationale`; optional single `engine_version` only if native logs do not identify it; `methods`, exactly two objects of the form `{functional, singlet, triplet}`, with three energy-ordered roots per spin; and `comparison`, with `singlet` and `triplet` objects, each containing `nto_similarity_3x3` and your `root_mapping` (string keys `"1"`–`"3"`, integer values `1`–`3`). Use letters, digits, underscores or hyphens in each functional identifier because it also names the native files.

Matrix element `(i,j)` is the absolute product of the leading hole- and particle-NTO overlaps in the AO overlap metric. Each root object contains `excitation_energy_hartree`, `oscillator_strength`, `leading_nto_pair_weight`, `hole_atom_mulliken` (24 values) and `particle_atom_mulliken` (24 values). The duplicate `excitation_energy_eV` in the root report is optional. Input context is in `/app/inputs/benchmark.json`.

You may add optional scientific notes in `final/decision.md`. The optional `functional_pair_rationale` field can record why you selected the pair.

Write deliverables under `/app/final/`:

| Artifact | Required evidence |
|---|---|
| `structure.xyz` | 24-atom optimized geometry, with stable atom order. |
| `native/optimization_summary.json` | `accepted_attempt`, `gtol_hartree_per_bohr`, `grid_level`, `functional`, `basis`, `scf_converged`, `max_abs_gradient_hartree_per_bohr`, `rms_gradient_hartree_per_bohr`, `final_energy_hartree`, `frequency_recheck_max_abs_gradient_hartree_per_bohr`, `frequency_recheck_rms_gradient_hartree_per_bohr`, `frequency_recheck_energy_hartree`. |
| `native/<accepted_attempt>/evaluation_*.npz` | `coordinates_angstrom` `(24,3)`, `gradient_hartree_per_bohr` `(24,3)`, scalar `energy_hartree`; retain the optimizer evaluations. |
| `native/final_gradient.npz`, `native/final_frequency_gradient.npz` | The same three keys and shapes; the second is a separate gradient at the final geometry. |
| `native/final_frequency_gradient.log`, `native/frequency.log`, `native/optimized_geometry.xyz` | Native independent-gradient log with converged SCF and gradient output, converged RKS/frequency records; optimized XYZ must match `structure.xyz` within `1e-10 Å`. |
| `native/cartesian_hessian_hartree_per_bohr2.npy` | Raw finite `(24,24,3,3)` Cartesian Hessian in `hartree/bohr^2`. |
| `native/normal_modes.npz` | `frequencies_cm1` `(66,)`, `mass_weighted_modes` `(66,24,3)`, dimensionless `co_stretch_overlap_squared` `(66,)`; reconstruction tolerances are specified above. |
| `native/<functional-lower>_tddft.log` | Keep the complete native log for each method, with the converged SCF, functional, basis, grid, input geometry and density-fitting evidence. Include exactly six `NATIVE_QC_ROOT ` records, one per spin/root, each a JSON object with `method`, `spin`, `root`, `excitation_energy_hartree`, `excitation_energy_eV`, and `oscillator_strength`. Its `[INPUT]` atom list must match `structure.xyz` in order and coordinates; show `auxbasis` when density fitting is enabled. |
| `native/<functional-lower>_<singlet|triplet>_root<1..3>_nto.npz` | Six root files per method. Required arrays: `coefficients` and AO `overlap` `(nao,nao)`, `weights` `(nocc,)`, `mo_coeff` `(nao,nmo)`, `mo_occ` `(nmo,)`, `td_x` and `td_y` `(nocc,nvir)`, scalar `excitation_energy_hartree`, scalar `oscillator_strength`. `coefficients[:,0]` is the leading hole NTO and `coefficients[:,nocc]` the leading particle NTO. |
| `decision.md` | Optional scientific notes. |

The compact report accepts only the stated keys; a legacy `schema`/metadata bundle cannot be mixed into the compact form. The native records must show actual calculations and their settings.
