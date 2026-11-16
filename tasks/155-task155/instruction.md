# Task: High-pressure SiO₂ equation of state and phase stability

## Background

The phases are `low_quartz`, `coesite`, `stishovite`, `pbo2`, `rosiaite`, and `pyrite`, each with ACE and DFT energy–volume data. Compare their equations of state and high-pressure phase stability, including where the two models agree, differ, or have limited support.

## Task

Analyze all six phases in both models and submit the numerical results, summary, and figures under `outputs/`.

## Requirements

- Environment: use the container Python on `PATH`. Preinstalled packages include matplotlib, NumPy, pillow, SciPy. Do not install additional packages or fetch dependencies from the network.

Compare all six phases for ACE and DFT. Normalize cell data per formula unit using the supplied counts and reference energies. Each fit window must cover at least 80% of its source curve; `parameters_json` must contain paired `curve_volume_A3_per_fu` and `curve_energy_eV_per_fu` arrays with at least 20 volume-sorted samples. Report at least 20 enthalpy samples per curve from 0 GPa with gaps no greater than 0.5 GPa, and relative enthalpy against stishovite only on shared valid support. Enumerate all phase pairs for both models over common support, recording crossings or no crossing and whether conclusions are conditional or cover all six phases.

Quantify leave-one-out residuals, fit-window sensitivity, and method sensitivity. For the scans, compare full-data PCHIP with a PCHIP fit trimmed by one point at each end and with full-data CubicSpline; minimize E(V)+PV at 201 equally spaced pressures over common support and report the maximum absolute enthalpy change. Keep all outputs consistent. CSV must be UTF-8 with headers, JSON valid, and numeric values finite.

Report only valid fit windows. Curve RMSE must be at most 1.25 times the larger of the shape-preserving leave-one-out error and all-data BM3 residual, plus 0.03 meV/atom, for each phase and model.

## Files

Public input files:

| File path | Description |
| --- | --- |
| `inputs/high_pressure/energy_volume/` | Contains `README.txt` with column order, formula-unit counts, and DFT reference energies. |

| Path | Contents |
| --- | --- |
| `outputs/normalized_eos.csv` | `phase,model,n_formula_units,V_A3_per_fu,E_eV_per_fu` |
| `outputs/eos_parameters.csv` | `phase,model,eos_form,parameters_json,n_points,fit_rmse_meV_per_atom,fit_window_Vmin_A3_per_fu,fit_window_Vmax_A3_per_fu,fit_valid`; `parameters_json` also contains the paired curve arrays required above. |
| `outputs/enthalpy.csv` | `phase,model,P_GPa,V_A3_per_fu,H_eV_per_fu,relative_H_meV_per_fu,fit_valid,relative_valid,reason` |
| `outputs/crossings.csv` | `model,phase_a,phase_b,status,P_low_GPa,P_high_GPa,deltaH_uncertainty_meV_per_fu,domain_basis,reason`; `status` is `crossing` or `no_crossing_in_common_supported_domain`. |
| `outputs/summary.json` | Include `units` (volume=`A^3/FU`, energy=`eV/FU`, pressure=`GPa`), `method`, `valid_domain` (one phase/model record with `Pmin_GPa`,`Pmax_GPa`), `phase_results` (all 12 phase/model records, with conditional conclusion and `relative_H_at_0_meV_per_fu`, `relative_H_min_meV_per_fu`, `relative_H_max_meV_per_fu`), and `uncertainty`. Report `max_loo_residual_meV_per_atom`, `max_fit_window_sensitivity_meV_per_atom`, and `max_method_sensitivity_meV_per_atom`; include 12 records in `fit_window_scan` (`phase,model,trim_each_end_points,retained_fraction,Vmin_A3_per_fu,Vmax_A3_per_fu,common_pressure_max_GPa,max_abs_H_change_meV_per_atom`) and `method_scan` (`phase,model,reference_method,comparison_method,common_pressure_max_GPa,max_abs_H_change_meV_per_atom`). |
| `outputs/figures/` | The 12 `eos_<phase>_<model>.png` plots and `enthalpy_ace.png`, `enthalpy_dft.png`, `deltaH_ace.png`, `deltaH_dft.png`; all 16 must be nonblank, inspectable PNGs. |
