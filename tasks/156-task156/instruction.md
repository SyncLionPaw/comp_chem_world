# Task: Finite-temperature SiO₂ phase stability and free-energy sensitivity

## Background

Thermodynamic fits are provided for `alpha_quartz`, `beta_quartz`, `coesite`, `cristobalite`, `melt`, `tridymite`, and `tridymite_low` over finite temperature and pressure ranges. Map the stable phases and boundaries, and assess how free-energy perturbations affect those conclusions.

## Task

Analyze the phase grid, phase boundaries, and sensitivity across the supported range. Submit the complete results, summary, and figure under `outputs/`.

## Requirements

- Environment: use the container Python on `PATH`. Preinstalled packages include matplotlib, NetworkX, NumPy, pandas, ParmEd, pillow, PROPKA, SciPy. Do not install additional packages or fetch dependencies from the network.

Map stable phases over the full grid: 601–3999 K at 1 K spacing and 0–50000 bar at 100 bar spacing. Report pressure support and stable intervals, distinguishing shared-valid crossings from support-edge transitions using `crossing`, `support_edge`, or `alpha_beta_line` as `kind`. Record one boundary row for every stable-phase change between adjacent pressure-grid points at each temperature; do not merge changes across temperatures. The summary `grid_transition_count`, if included, counts these pressure-direction changes only. For every distinct phase pair with a shared-valid grid crossing, select the upper median temperature among its row-level crossing records (sort by temperature, then pressure) and use the nearest reported crossing at that temperature for sensitivity. Evaluate both phases, both signs, and 0.1, 2, and 5 meV/atom. Mark a perturbed pair ambiguous if no root remains in common pressure support or a third valid phase is lower in energy. Fit the α–β line using all 15 rows or the plot-window subset and show it over 2759–32400 bar. Explain undefined values and keep outputs consistent.

The phase map must be a nonblank, inspectable PNG. CSV must be UTF-8 with headers, JSON valid, and numeric values finite. `phase_grid.csv` rows are ordered by increasing temperature, then increasing pressure.

## Files

Public input files:

| File path | Description |
| --- | --- |
| `inputs/phase_diagram/` | Contains the phase `fit_gibbs_energy.csv` files and `alpha_quartz_beta_quartz.txt`. |

| Path | Contents |
| --- | --- |
| `outputs/phase_grid.csv` | `T_K,P_bar,valid_phases,G_min_meV_per_atom,stable_phase,reason` |
| `outputs/boundaries.csv` | `boundary_id,phase_a,phase_b,T_K,P_bar,kind,valid_overlap,uncertainty_bar,basis,reason` |
| `outputs/sensitivity.csv` | `perturbation_meV_per_atom,perturbed_phase,sign,boundary_id,phase_a,phase_b,T_K,nominal_P_bar,perturbed_P_bar,delta_P_bar,valid_overlap,ambiguous_domain,reason` |
| `outputs/summary.json` | Include `units`, `method`, `boundaries`, `sensitivity`, `alpha_beta_treatment`, and `limitations`. Detailed stability ranges are represented by `phase_grid.csv`; do not duplicate the full grid in the summary. For α–β, report the three input columns, fit subset and row count, and `fit_slope_K_per_GPa`, `fit_intercept_K`, `mean_abs_estimate_gap_K`, and `max_abs_estimate_gap_K`. |
| `outputs/figures/phase_map.png` | Nonblank, inspectable phase map. |

The summary is a JSON object. `units` must state `pressure: bar`, `temperature: K`, and Gibbs energy in `meV/atom` (the Gibbs key may be `gibbs` or `gibbs_energy`; an annotation may follow the unit). Method, boundary, sensitivity, and limitation fields may use concise prose; the grid and CSV files are authoritative for their detailed values. Extra explanatory fields are allowed.

For each boundary, `basis` is a nonempty explanation; it need not use a prescribed phrase. `valid_overlap` describes whether both fits have pressure support at the reported temperature and pressure; it does not determine whether `kind` is `crossing` or `support_edge`. Shared-valid Gibbs crossings report pressure uncertainty as `max(50 bar, 50 bar + hypot(max(std_a,maxdev_a), max(std_b,maxdev_b)) / |d(G_a-G_b)/dP|)` at the reported pressure. Support-edge rows report at least the 50-bar half-grid resolution. Ordinary decimal rounding is allowed. α–β external-line uncertainty is a finite nonnegative estimate-gap conversion and is not subject to the grid half-step minimum. The α–β line must have at least 10 plotted samples inside 2759–32400 bar. The external fit summary reports the three input columns in source order; descriptive column labels are fine, and neither estimate is assigned an initial-phase identity. It may use `fit_rows` or `fit_row_count`, and `fit_basis` or `fit_subset` (`all_15_rows` or `plot_window_only`); slope may be in K/GPa or K/bar. The canonical summary keys are `fit_slope_K_per_GPa`, `fit_intercept_K`, `mean_abs_estimate_gap_K`, and `max_abs_estimate_gap_K`. For a perturbation with no root inside common support, set `valid_overlap=false`, `ambiguous_domain=true`, and provide a reason. `perturbed_P_bar` and `delta_P_bar` may be blank or finite placeholders; placeholders do not represent a root.
