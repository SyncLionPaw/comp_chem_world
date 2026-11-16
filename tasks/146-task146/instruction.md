# Rate identifiability from photoluminescence

## Background

Three sets of noiseless fluorescence and phosphorescence traces describe singlet–triplet kinetics. Each contains 100 logarithmically spaced times from 10⁻⁹ to 10⁻² s. Within each condition, fluorescence is normalized by its zero-time value and phosphorescence by its window maximum; absolute intensities and cross-channel calibration are unavailable.

## Task

Determine which rate constants the traces constrain, demonstrate any ambiguity quantitatively, and propose a measurement that distinguishes the unresolved alternatives.

Use \(\dot p=Ap\), \(p(0)=(1,0)\), with positive rates in s⁻¹:

\[
A=\begin{pmatrix}-(f+nrS+isc)&risc\\isc&-(risc+ph1+nr1)\end{pmatrix}.
\]

Relative to `baseline`, `intervention_A` multiplies only `ph1` by 3 and `intervention_B` multiplies only `nr1` by 3.

## Requirements

- Environment: use the container Python on `PATH`. Preinstalled packages include h5py, NumPy, PySCF, SciPy. Do not install additional packages or fetch dependencies from the network.

- Fit all conditions consistently, recording coordinates, positive bounds, fitting window, weights and at least two starting points with their fitted RMS residuals. Select the lowest-RMS fit; its RMS over all observations must not exceed 10⁻⁸.
- Provide another positive parameter set with RMS and maximum curve difference ≤ 10⁻⁸. It must differ by more than rounding: at least one rate difference must exceed 10⁻⁸ times the larger of the selected maximum rate and 1 s⁻¹. If the pair preserves the observed curves but not the generator, also demonstrate a relative change > 10⁻⁶ in at least one rate.
- Distinguish structural ambiguity from practical uncertainty. Quantify uncertainty only with an explicit noise model and supporting parameter profile.
- Predict an absolute fluorescence yield, directly measured rate, or calibrated fluorescence flux for both alternatives, and explain why the measurement separates them. Yield separation must exceed 10⁻⁵; rate/flux separation must exceed 10⁻⁶ of the larger absolute prediction.
- Provide a program that reproduces the analysis from the supplied inputs. It must run as `python final/experiment.py` from a directory containing only `inputs/` and `final/`.

## Files

Public input files:

| File path | Description |
| --- | --- |
| `/app/inputs/observations.csv` | Observed data. |
| `/app/inputs/benchmark.json` | Benchmark parameters and conditions. |

Read `/app/inputs/observations.csv` and `/app/inputs/benchmark.json`. Write `/app/final/experiment.py`, a short scientific discussion in `/app/final/diagnosis.md`, and `/app/final/result.json` with:

- `rates`: selected and alternative parameter dictionaries, each containing `f`, `nrS`, `isc`, `risc`, `ph1`, `nr1` in s⁻¹.
- `fit`: `coordinates`, `bounds` (coordinate → `[lower, upper]`), `starts` (vectors in coordinate order), corresponding fitted `rms`, `window_s` and `weights`. Starts and selected parameters must respect the bounds; the window must span at least two observed times.
- `measurement`: `type` (`yield`, `rate` or `flux`) and two `predictions` for the first two rate sets. For `rate`, name the `parameter`; for `flux`, give `scenario` and `time_s` (nonnegative, with flux per initially excited molecule).
- `uncertainty`: `noise_model: null` if not quantified; otherwise the explicit model and `profile_indices` referencing supporting alternatives in `rates` (zero-based).

Use finite values and full numerical precision.
