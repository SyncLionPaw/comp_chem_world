# Task: SiO thermal crystallization kinetics and scattering response

## Background

Crystallinity time series and pre- and post-treatment structure factors are supplied for four SiO samples. Compare their kinetic responses and determine whether they agree with the structural scattering evidence.

## Task

Analyze every sample condition and both scattering states. Report crystallinity, onset behavior, peak metrics, and the relationship between kinetic and scattering evidence in `outputs/`.

## Requirements

- Environment: use the container Python on `PATH`; required scientific packages are preinstalled. Do not install additional packages or fetch dependencies from the network.

Analyze all four sample labels, every native crystallinity record, and both scattering states. Report crystallinity as a fraction of the source-filtered subset, not all atoms; convert steps using the supplied timestep and exclude startup records from onset. Distinguish sample preparation-rate labels from the 1400→1200 K treatment rate (1e10 K/s); the series ends at 20200 ps and excludes the configured final 10 ps hold. Use `before`/`after` states and the same X-ray S(q) channel (column 2), q window, and normalization. State the onset rule (threshold 0.001–0.05; persistence 1–5 observations) and report sensitivity at 0.001, 0.01, and 0.05. Use `scipy_prominence_half_height` or `window_minimum_half_prominence` for peak width in 3.00–4.20 Å⁻¹ on the 0.01 Å⁻¹ grid. Report uncertainty and limits, including q-position uncertainty ≥0.01 Å⁻¹ and observed-window/subset limitations; explain undefined values.

CSV must be UTF-8 with headers, JSON valid, and numbers finite.

In the summary, set `method.onset.threshold_fraction` to 0.001–0.05 and `method.onset.consecutive_observations` to an integer from 1 to 5. Record `method.uncertainty.q_peak_A_inv` (at least 0.01). In `scattering_consistency`, use `channel: "X-ray (second column)"`, `fixed_q_window_A_inv: [3.0, 4.2]`, `limitations`, `source_data_calibration` citing Figure 6, and `peak_width_method` set to `scipy_prominence_half_height` or `window_minimum_half_prominence`. Classify the final subset fraction as `strong` (≥0.1), `weak` (≥0.005 but <0.1), or `trace` (<0.005). Use `resolved_crystalline_doublet` or `broad_peak_only_in_fixed_window` for scattering. In each summary rate record use `kinetics_class`, `scattering_class` and `joint_evidence`; use `consistent` for agreement between the evidence streams when supported.

Each `rate_results` entry also includes `rate_label`, `final_subset_fraction` and `onset_ps_declared_rule`.

## Files

Public input files:

| File path | Description |
| --- | --- |
| `inputs/SiO/` | Directory of supplied inputs and resources. |
| `inputs/method-note.md` | Supplied data, parameters or method documentation; see the task requirements. |

| Path | Contents |
| --- | --- |
| `outputs/crystallinity_timeseries.csv` | `rate_K_per_s,step,time_ps,n_cubic,n_hex,n_other,n_filtered_subset,crystalline_fraction_subset,temperature_K,temperature_source` |
| `outputs/scattering_peak_metrics.csv` | `rate_K_per_s,state,peak_rank_q_ascending,q_peak_A_inv,peak_height,peak_width_A_inv,peak_width_method,window_A_inv,normalization` |
| `outputs/rate_comparison.csv` | `rate_K_per_s,onset_ps,onset_reason,final_subset_fraction,delta_peak_width_A_inv,kinetics_trend,scattering_trend,agreement,onset_definition` |
| `outputs/summary.json` | Include `method`, `rate_results`, `time_unit`, `denominator_definition`, `scattering_consistency`, `onset_sensitivity_ps`, `source_data_check`, and `source_scattering_check` for all four labels. State onset threshold/persistence, time conversion, filtered-subset denominator, X-ray column 2, q window, width method/uncertainty (q-position ≥0.01 Å⁻¹), observed-window/subset limits, and Source Data Figure 6 cross-check. Per-rate entries agree with `rate_comparison.csv`. |
| `outputs/figures/crystallinity_and_sq.png` | Valid, readable PNG. |
