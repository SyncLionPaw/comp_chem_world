# Task: Strain and doping trends

## Background

`assets/a2f-tuning-series.csv` contains synthetic α²F spectra for 11 strain and doping members.
Positive-frequency α²F data have no phonon eigenvalues, dispersions, or imaginary modes. A
low-frequency screen is not a dynamical stability determination.

## Task

For every member compute λ, ω_log (cm⁻¹), Tc at μ*=0.16 and 0.10, and the share of λ from ω<12 cm⁻¹.
When that share is >0.30, mark `soft_mode_risk=true`, `proxy_safe=false`, and set both Tc values to
null; otherwise mark false/true and report the estimates. Set the hole proxy bracket to the highest
sampled proxy-safe hole concentration and lowest sampled risk concentration. Report all requested
trends and the +1% extreme-coupling comparison. Explain why synthetic scalar α²F and Allen–Dynes
cannot establish quantitative real-material Tc, why the stated interpretation treats this low-frequency regime as a
superconductivity-theory test, and why large λ alone proves neither Migdal-framework failure nor
dynamical instability. Provide a nonempty physical rationale.

## Requirements

- Environment: use the container Python on `PATH`; required scientific packages are preinstalled. Do not install additional packages or fetch dependencies from the network.

Cover these exact IDs once each: `strain_-2p0pct`, `strain_-1p0pct`, `strain_-0p5pct`,
`strain_0p0pct`, `strain_+0p5pct`, `strain_+1p0pct`, `hole_0p10h`, `hole_0p15h`, `hole_0p20h`,
`electron_0p5e`, `electron_1p0e`. Use λ=2∫α²F/ω dω, ω_log=exp[(2/λ)∫(α²F/ω)ln(ω)dω], and
`Tc=(ω_log,K/1.2)exp[-1.04(1+λ)/(λ−μ*(1+0.62λ))]`. Do not present proxy status as stability
evidence. Input units: 1 cm⁻¹=1.4387769 K. Compare `compression_reduces_lambda` and `compression_raises_omega_log` using the −2% member against 0%; compare `hole_doping_raises_lambda` using 0.10 h/u.c. against 0%. `expansion_1pct_lambda` and `extreme_coupling.lambda_value` must match the +1% member; `electron_1p0e_tc_mu016_K` must match the 1.0 e/u.c. member. Set `exceeds_known_materials` according to whether the +1% λ exceeds the stated known-material maximum ≈2.6. Set `electron_doping_tc_in_paper_range` true when the 1.0 e/u.c. μ*=0.16 result lies in 0.4–1.6 K (with endpoint tolerance ±0.1 K). Use numerical comparison tolerances of 3% for λ/ω_log, 1 K for Tc, and 0.05 for the low-frequency fraction. Determine trends and the proxy bracket from the supplied members using the comparisons above.

### Input and deliverable details

Write `/app/final/tuning-report.json`. `members` is an array of 11 objects, each with `series_id`
string, numeric `lambda`, numeric `omega_log_cm1`, boolean `soft_mode_risk`, boolean `proxy_safe`,
numeric-or-null `tc_mu016_K` and `tc_mu01_K`, numeric `soft_lambda_fraction_below_12cm1`. `trends`
object requires booleans `compression_reduces_lambda`, `compression_raises_omega_log`,
`hole_doping_raises_lambda`, `electron_doping_tc_in_paper_range`; numeric `expansion_1pct_lambda`,
`electron_1p0e_tc_mu016_K`; and two-number `hole_soft_mode_risk_bracket`. `extreme_coupling`
requires string `series_id` (`strain_+1p0pct`), numeric `lambda_value`, booleans
`exceeds_known_materials` and `quantitative_tc_reliable`, and nonempty rationale string.
Optional `notes` is text. Do not use a prefilled answer template.

## Files

Public input files:

| File path | Description |
| --- | --- |
| `assets/a2f-tuning-series.csv` | Supplied scientific input or resource; see the task requirements for format and units. |

| Path | Contents |
| --- | --- |
| `/app/final/tuning-report.json` | Required result; use the contents and format specified above. |
