# Task: Temperature-dependent ring-opening rates and branching

## Background

The deposited MESMER outputs report two toluene ipso-BPR ring-opening channels over a temperature grid at 760 Torr in nitrogen. The Source Data workbook reports published rates at a subset of those temperatures.

## Task

Extract both native channel rates at every temperature, compare matched rates with the published table, fit modified Arrhenius curves for C1, C2, and their sum, and characterize the temperature-dependent branching under the available pressure conditions.

## Requirements

- Environment: use the container Python on `PATH`. Preinstalled packages include NumPy. Do not install additional packages or fetch dependencies from the network.

- Use all 23 native XML files. In the MESMER namespace, read the two `<me:firstOrderRate>` entries under `<me:analysis>/<me:rateList>`, not population/density records or input parameters. Record both entries' `fromRef`/`toRef`, source path, temperature, pressure, and bath gas.
- Report C1, C2, and total rates in s⁻¹ at all 23 temperatures. At each of the 20 temperatures shared with the workbook, each channel must match within relative deviation 1e-4. Include the three temperatures absent from the workbook.
- Fit all 23 points over 200–500 K to `k(T)=A*(T/T_ref)^n*exp[-Ea/(R*T)]`, with `R=0.00198720425864 kcal mol⁻¹ K⁻¹`. For C1, C2, and total, report A, n, Ea, fit range, point count, and directly recomputed maximum absolute ln(k) residual; do not understate the residual.
- Calculate C1's branching fraction from the two native rates at every temperature. Report its value at 300 K and its 200–500 K range with endpoint temperatures; do not imply a temperature-independent split.
- State that all files represent 760 Torr N2 and that a single-pressure grid cannot establish pressure dependence. Explain the fit-window choice relative to when the published split was examined.

## Files

Public input files:

| File path | Description |
| --- | --- |
| `/app/assets/` | Source records and reaction data for the analysis. |

Submit under `/app/final/`:

- `rates_by_temperature.csv`: 23 unique rows; columns `source_file,temperature_K,pressure_Torr,bath_gas,k_C1_per_s,k_C2_per_s,k_total_per_s,C1_fromRef,C1_toRef,C2_fromRef,C2_toRef`.
- `arrhenius_fit.json`: records for `c1`, `c2`, and `total` (or `k_c1_full_range`, `k_c2_full_range`, `k_total_full_range`) with `A_per_s,n_T_exponent,Ea_kcal_per_mol,T_ref_K,fit_min_K,fit_max_K,n_points,max_ln_k_deviation,formula`. Use all 23 points over 200–500 K. Equivalent arithmetic, reordered factors, `^` or `**`, and aliases `Ea`, `T_ref`, `n`, `A` are accepted. Another reference temperature is acceptable if A and the resulting curve agree. After `;`, comma- or semicolon-separated notes may state `R`, `T_ref`/`T_ref_K`, `Ea`, `A`, or `n` values/units; R must match the stated gas constant `0.00198720425864 kcal mol⁻¹ K⁻¹` within `max(|R|×10⁻¹⁰, 10⁻¹⁴)`, T_ref must match `T_ref_K` within `10⁻⁹ K`, and Ea, A, and n must match to displayed precision. R, T_ref, and A must be positive. Use scientific units (R and Ea in kcal mol⁻¹ K⁻¹ and kcal mol⁻¹; T_ref in K; A in s⁻¹; n dimensionless). Repeated notes are allowed if each agrees. The formula and parameters must reproduce native rates.
- `branching_curve.csv`: columns `temperature_K,branching_C1_percent`, one row per temperature.
- `derivation_notes.md`: explain native rate extraction, fitting and branching scope, fixed-pressure limitation, the endpoint branching values/range, and fit-window choice relative to examining the published split.

Paths may be asset-relative with optional `assets/` prefix or unique basenames. Write scientific scope in English or Chinese.

Inputs: the 23 XML files (200–500 K, including the 255–310 K 5 K inset) are under `/app/assets/Toluene-iBPR-rearrangement-Tdep-MESMER/`; the Source Data workbook and SI DOCX are under `/app/assets/`. No MESMER or quantum-chemistry run is needed.
