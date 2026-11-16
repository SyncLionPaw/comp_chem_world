# Dipole Autocorrelation Dielectric Response and Two-Oscillator Fitting

## Background

The dielectric response of a polar material can be estimated from the autocorrelation of its total dipole moment recorded along a molecular-dynamics trajectory. A single finite trajectory with correlated frequency bins, however, supports descriptive fits rather than unique mode assignment or an unconditional absolute permittivity. The supplied record is a 6x6x6 supercell dipole and cell-volume time series with units that must be handled explicitly.

The inputs provide the extensive supercell dipole and matching instantaneous volume for each frame, along with conditional static dielectric values under each unit hypothesis.

## Task

Complete every canonical static, autocorrelation/ESS, spectrum, one/two-oscillator fit and 2/4/6 ps window-sensitivity output.

Choose `split_fraction` in [0.3, 0.7] and two `lag_windows_ps` in [2, 8] separated by at least 1 ps, and record them as `spec`. Compute `results` by the public `autonomous_controls.py` rule: train on the initial contiguous fraction, predict the later contiguous block using the training oscillator parameters and the normalized held-out spectrum without refitting.

## Requirements

- The fixed evaluation set always includes 2, 4 and 6 ps plus every chosen window; all frequency bins and all fixed windows are required. No chosen successful window can hide an adverse fixed control.
- Report each training fit, the complete held-out residual vectors and RSS for one and two modes, and whether two modes improve both/all holdouts. A valid negative result is acceptable.
- Fitting the existing complete series remains mandatory; the held-out analysis adds evidence rather than replacing it.
- One finite record with correlated frequency bins cannot identify statistical mode necessity or an unconditional absolute permittivity. Keep `static_dielectric_constant=null`, the conditional eBohr/eAngstrom responses, both `single_oscillator_sufficient` and `two_oscillator_statistically_necessary` null, and the descriptive fit status required by the public contract. `scope` must accompany the full residual evidence.
- Use the analytic oscillator Jacobian with `ftol=xtol=gtol=1e-13` and `x_scale="jac"` at the published starts, bounds and evaluation cap. These are optimization stopping rules; the output comparison tolerances and the descriptive limits of the fit statistics are unchanged.
- Use the arithmetic tolerances in the listed output convention.

The specified results can be reproduced with:

```
python3 /app/public/replay.py /app/final
```

## Files

| Path | Description |
| --- | --- |
| `/app/inputs/` | Dipole and volume series and unit references. |
| `/app/final/` | Submitted results and required execution evidence. |
| `/app/public/README.md` | Calculation methods and result-submission requirements. |
