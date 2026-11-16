# Task: α-quartz surface energy and thickness effects

## Background

DFT-relaxed α-quartz slabs are supplied for five surface orientations (`001`, `011`, `100_alpha`, `100_beta`, `101`), along with published cleaved-surface energies. Evaluate relaxed surface energies, their orientation ordering, thickness convergence, and comparison with the cleaved values.

## Task

Audit every slab, fit the thickness dependence, estimate surface energies, and report the orientation and relaxation comparisons in `outputs/`.

## Requirements

- Environment: use the container Python on `PATH`; required scientific packages are preinstalled. Do not install additional packages or fetch dependencies from the network.

Audit all 35 slabs across five orientations. Check composition and geometry. For each orientation, fit the contiguous last-three-slab and last-four-slab windows (at least three slabs per fit), calculate `A=|a×b|` from the first two cell vectors, and use `γ=(E_slab−Nμ)/(2A)` with `μ` from the same E(N) fit used for the relaxed surface energy. Convert using `1 eV/Å² = 16.02176634 J/m²` and compare with the supplied cleaved energies. Use `cleaved_published_input` and `relaxed_from_slab`; set cleaved `converged=not_applicable` and relaxed `converged` to a Boolean. Derive `near_degenerate` or `rank_N` from the results and uncertainty, without assuming the ranking. Cleaved geometries are not supplied, so energy comparisons do not establish an atom-by-atom reconstruction pathway.

CSV must be UTF-8 with headers, JSON valid, and numbers finite.

A valid fit window has RMSE ≤0.004 eV. For each relaxed result, report `converged=true` only with a valid fit and a spread across valid thick windows of at most 0.002 eV/Å². Report a relaxed uncertainty at least as large as that spread and at most 0.002 eV/Å², and a cleaved rounding uncertainty in [0.0005, 0.001] eV/Å². Under `surface_energy.<orientation>`, include `gamma_relaxed_eV_per_A2`, `gamma_cleaved_eV_per_A2` and `relaxation_energy_drop_eV_per_A2`. Under `ranking`, include `cleaved_low_to_high`, `relaxed_low_to_high`, `cleaved_near_degenerate`, `relaxed_near_degenerate`, `rank_change_near_degenerate` and `rank_change_robust`. Use `near_degenerate` for tied orientations and `rank_<position>` otherwise.

Record `method.conversion_eV_per_A2_to_J_per_m2`. For each orientation, `orientation_audit` includes `n_slabs`, `N_atoms`, `stoichiometry` and `area_A2`. In `reconstruction_effect` record `drop_eV_per_A2`, `drop_J_per_m2` and the Boolean `significant`. Also record `uncertainty.relaxed_surface_energy_eV_per_A2.<orientation>`.

## Files

Public input files:

| File path | Description |
| --- | --- |
| `inputs/` | Contains the slab files, published cleaved energies, and method note. |

| Path | Contents |
| --- | --- |
| `outputs/orientation_audit.csv` | `orientation,slab_file,N_atoms,N_Si,N_O,area_A2,atomic_span_A,cell_vectors_A,stoichiometry,geometry_note` |
| `outputs/slab_fit.csv` | `orientation,reconstruction,window_files,window_N_min,window_N_max,slope_eV_per_atom,intercept_eV,residual_RMSE_eV,n_points,fit_assumptions` |
| `outputs/surface_energy.csv` | `orientation,reconstruction,area_A2,gamma_eV_per_A2,gamma_J_per_m2,uncertainty_eV_per_A2,uncertainty_J_per_m2,bulk_reference,converged,decision,reason` |
| `outputs/summary.json` | Include `method`, `orientation_audit`, `bulk_reference`, `surface_energy`, `reconstruction_effect`, `ranking`, `uncertainty`, `limitations`, `figure_panels`. Record the conversion factor, per-orientation audit and `mu_eV_per_atom`, relaxed/cleaved energies and differences, energy drops and significance, uncertainties, both rankings, near-degenerate sets and ranking robustness. `figure_panels` contains `orientation_specific_E_N_fits` and `cleaved_vs_relaxed_surface_energy`. |
| `outputs/figures/thickness_fit.png` | Show both scientific comparisons in a readable PNG; layout is unrestricted. |
