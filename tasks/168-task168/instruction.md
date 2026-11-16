# Task: Eliashberg spectral numerics

## Background

The input is a synthetic reconstruction, not a raw source spectrum. The supplied source’s μ* sensitivity statement concerns isotropic Migdal–Eliashberg results; its scope differs from this dataset's Allen–Dynes surrogate.

## Task

From `assets/a2f-unstrained.csv`, compute λ, ω_log (cm⁻¹ and K), and Allen–Dynes Tc at μ*=0.16 and
0.10; report `Tc(0.10)/Tc(0.16)` and whether it is ≤1.10. Decompose λ into [0,200], (200,300],
(300,360], (360,450], and (450,∞) cm⁻¹ bands. Explain the comparison scope in a nonempty sensitivity note; do not conflate the synthetic surrogate with the supplied source’s isotropic
Migdal–Eliashberg results.

## Requirements

- Environment: use the container Python on `PATH`; required scientific packages are preinstalled. Do not install additional packages or fetch dependencies from the network.

Use λ=2∫α²F(ω)/ω dω and ω_log=exp[(2/λ)∫(α²F(ω)/ω)ln(ω)dω], with consistent units; `1 cm⁻¹ =
0.12398420 meV = 1.4387769 K`. Use Allen–Dynes modified McMillan `Tc=(ω_log,K/1.2)
exp[-1.04(1+λ)/(λ−μ*(1+0.62λ))]`. Handle the finite low-frequency limit at grid start. Trapezoidal,
Simpson, analytic, or equivalent integration is acceptable; method sensitivity must be <0.5%.
Numerical comparison tolerances: λ and ω_log ±2%, Tc ±0.6 K, bands ±8%; ratio must match Tc division ±2%, and
band sum must be within 2% of λ.

### Input and deliverable details

Write `/app/final/eliashberg-results.json`. Required keys/types: numeric `lambda`, `omega_log_cm1`,
`omega_log_K`, `tc_mu016_K`, `tc_mu01_K`; object `mu_star_sensitivity` with numeric
`ratio_tc_mu01_over_mu016`, boolean `ad_surrogate_le_10pct_supported` (true iff ratio≤1.10), and
nonempty string `sensitivity_note`; object `decomposition` with numeric `lambda_0_200_cm1`,
`lambda_200_300_cm1`, `lambda_300_360_cm1`, `lambda_360_450_cm1`, `lambda_above_450_cm1`. Band
endpoints follow the intervals above; values are dimensionless. Extra fields are allowed.

Include `integration_check` with numerical `trapezoid_lambda`, `trapezoid_omega_log_cm1`, `midpoint_lambda` and `midpoint_omega_log_cm1`. For the midpoint rule, linearly interpolate α²F to each interval midpoint before dividing by frequency. Use the same grid span for both rules. The relative difference for each integral result must be below 0.5% of the trapezoid value.

## Files

Public input files:

| File path | Description |
| --- | --- |
| `assets/a2f-unstrained.csv` | Supplied scientific input or resource; see the task requirements for format and units. |

| Path | Contents |
| --- | --- |
| `/app/final/eliashberg-results.json` | Required result; use the contents and format specified above. |
