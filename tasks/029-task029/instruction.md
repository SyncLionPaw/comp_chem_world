# Reliable Correlation Lengths from Scattering Curves

## Background

The supplied SANS measurement was made at 150 mM NaCl. The supplied source’s 20 mM ABSINTH atomistic Monte Carlo calculation is a separate parameterization reference; no RDF curve is supplied. Scattering intensity contains background, form factor and structure factor, and the lowest-q points are especially sensitive to background and finite sampling.

## Task

Identify robust real-space correlation lengths, \(d=2\pi/q\), in the SANS curve. Decide which features are supported by the data, which are noise or low-q artifacts, and how background, peak window, and uncertainty choices affect the result.

## Requirements

Use the supplied `error_cminv` uncertainties, or justify a different noise estimate. Explain the background model, peak/fit windows, uncertainty propagation, and sensitivity to model and window choices. Do not equate the measured \(I(q)\) with the structure factor \(S(q)\), and do not claim numerical agreement with the 20 mM atomistic reference. A feature is robust only if it survives reasonable changes in background and window and is distinguishable from low-q noise.

## Files

Public input files:

| File path | Description |
| --- | --- |
| `/app/environment/assets/sans.csv` | Scattering intensities and errors. |

Inputs are in `/app/environment/assets/` (`sans.csv` with `q_Ainv`, `I_cminv`, `error_cminv`). Write these deliverables under `/app/final/`:

- `peaks.json`: a nonempty `peaks` list. Each peak gives positive finite `q_Ainv` (Å⁻¹), an ordered `q_interval_Ainv=[low,high]` (Å⁻¹) that brackets `q_Ainv`, `length_A=2*pi/q_Ainv` (Å), and a JSON boolean `reliable`. Add nonempty `noise_method` and `low_q_limitations` strings.
- `diagnostics.csv`: one row per input q bin with columns `q_Ainv,raw_I,estimated_background,processed_signal,uncertainty`. `raw_I` reproduces the input `I_cminv`; `processed_signal = raw_I - estimated_background`; uncertainty is finite and non-negative.
- `report.md`: methods, peaks and lengths, uncertainty, model/window sensitivity, low-q limitations, and the distinction between \(I(q)\), \(S(q)\), the 150 mM experiment and the 20 mM atomistic reference.
- `analysis.py`: deterministic, reproducible analysis. It must accept `--input-dir` and `--output-dir`, read `sans.csv` from the input directory, write the other three outputs, and document methods, windows and uncertainty.

Use enough numeric precision to reproduce the input grid and the `length_A` relation; avoid NaN/Infinity. Place only these four files in `/app/final/`.

`analysis.py` must run under the container's provided Python using only its preinstalled packages (NumPy, SciPy, matplotlib). The analysis must be self-contained and require no additional packages, network access, or alternative interpreter.
