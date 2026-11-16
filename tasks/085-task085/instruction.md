# Task: Prediction Stability Under Controlled Simulated Spectrum Perturbations

## Background

The package provides simulated infrared spectra for a large molecular library,
with the eight functional-group classes of SI §6 recorded for the public
molecules. Five perturbations of the same blind spectra are available as
conditions: two sampling-phase splits (`phase400`, `phase402`), two Gaussian
smoothings (`smooth075`, `smooth125`), and a per-spectrum frequency scramble.

These perturbations stay inside the simulated source domain. They do not model
instrument calibration, are not equivalent to rigid ±2 cm⁻¹ shifts, and say
nothing about generalization to measured NIST spectra.

## Task

Build a lightweight eight-class predictor from the public data alone and ask
whether it is stable under those perturbations. A clean ranking that survives
smoothing and re-phasing shows the model reads broad band structure rather than
one narrow feature or the arbitrary ordering of the frequency axis.

The scramble tests the role of frequency positions. Performance after shuffling does not establish use of those positions. The clean task
must first be established against the formula-only baseline and against the
scramble before any perturbation result can be read as that model's robustness.

## Requirements

- Environment: use the container Python on `PATH`. Preinstalled packages include NumPy, pandas, pillow, PyYAML, RDKit, scikit-learn, SciPy. Do not install additional packages or fetch dependencies from the network.

**Model.** A linear one-vs-rest logistic model on the 1791-point spectrum, with
the scaler fit on training data only, so that every condition's probabilities
reproduce exactly from the submitted parameters.

**Conditions.** Produce probabilities for all six spectral conditions plus the
formula-only baseline for every blind sample, on the common analysis axis. The
perturbed inputs are defined by the transformation below; the frequency scramble
is seeded per sample identifier so that identifiers, formulas and candidate order
are untouched.

**Uncertainty.** The scientific comparisons are clean vs. baseline and clean vs.
scramble average-precision gains with molecule-level bootstrap intervals, plus
probability drift and label flips under perturbation. The blind labels are not in
the public inputs: submit paired probabilities for these comparisons and do not
self-report label-based gains or intervals. These diagnostics are descriptive: the
clean condition must first beat both controls to support a robustness claim.

**Prohibited shortcuts.** Do not reuse unaudited source checkpoints and do not
use blind labels for fitting.

### Input and deliverable details

Runtime inputs are read-only under `/app/assets/`:

- `cohort-train.npz`, `cohort-validation.npz` — `sample_id`, `formula`,
  `spectra`, `smiles`, `group_labels`, `group_names`; class columns follow
  `group_names`.
- `cohort-blind-test.npz` — `sample_id`, `formula`, `spectra` only.
- `axis-cm-1.npy` — 1791 points, 400 to 3980 cm⁻¹ in 2 cm⁻¹ steps.
- `SOURCES.yaml` — provenance of the derived inputs.

Write to `/app/final/`:

- `submission.csv` — header `sample_id,condition_id,` plus the eight class names
  in `group_names` order; each blind identifier appears once under each of
  `clean`, `formula_only`, `phase400`, `phase402`, `smooth075`, `smooth125` and
  `frequency_scrambled`. Probabilities are finite values in [0, 1].
- `model.npz` — read with `allow_pickle=False`; numeric arrays only: `coef`
  (8, 1791), `intercept` (8,), `scaler_mean` (1791,), `scaler_scale` (1791,),
  all finite with a strictly positive scale. Probabilities are
  `expit(((X - scaler_mean) / scaler_scale) @ coef.T + intercept)`, using the
  same parameters for all six spectral conditions.

The `formula_only` row is not a submitted model: it is the smoothing baseline
`(positive count for that formula and class + 1) / (samples with that formula +
2)`, falling back to the whole training set for formulas unseen there.

### Transformation definition

All conditions map onto the common 2 cm⁻¹ analysis axis. The normalization
`norm` divides each row by `max(max(spectrum), 1e-12)`, multiplies by 99,
truncates to integer and clips to [0, 99], returning float32. Blind spectra are
converted to float32 first; do not promote them to float64 before transforming.

```python
import hashlib
import numpy as np
from scipy.interpolate import interp1d
from scipy.ndimage import gaussian_filter1d

blind = np.load("/app/assets/cohort-blind-test.npz")
axis = np.load("/app/assets/axis-cm-1.npy")
raw = np.asarray(blind["spectra"], dtype=np.float32)
ids = blind["sample_id"].astype(str)
orig = np.arange(400, 3982, 2)
short = np.arange(400, 3982, 4)

def norm(x):
    return np.clip((x / np.maximum(np.max(x, axis=1, keepdims=True), 1e-12) * 99).astype(np.int16), 0, 99).astype(np.float32)

def itp(a, old_axis):
    return norm(np.stack([interp1d(old_axis, row)(axis) for row in a]))

def scramble(x, sample_ids):
    out = np.empty_like(x)
    for i, sample_id in enumerate(sample_ids):
        seed = int.from_bytes(hashlib.sha256(f"ir-local-frequency-scramble-v1|20261006|{sample_id}".encode()).digest()[:8], "little")
        out[i] = x[i, np.random.default_rng(seed).permutation(x.shape[1])]
    return out

set1 = raw[:, ::2]
set2 = np.concatenate([raw[:, 1::2], raw[:, -1:]], axis=1)
inputs = {
    "clean": norm(raw),
    "phase400": itp(set1, short),
    "phase402": itp(set2, short),
    "smooth075": itp(np.stack([gaussian_filter1d(row, 0.75) for row in raw]), orig),
    "smooth125": itp(np.stack([gaussian_filter1d(row, 1.25) for row in raw]), orig),
    "frequency_scrambled": norm(scramble(raw, ids)),
}
```

`phase402` is a different sampling phase on the same short axis, not an
independent axis starting at 402 cm⁻¹. Both phases are interpolated onto the
common axis with SciPy's default linear interpolation, and the Gaussian filters
use SciPy's default `reflect` boundary.

## Files

Public input files:

| File path | Description |
| --- | --- |
| `/app/assets/` | Directory of supplied inputs and resources. |

**Inputs**

| Path | Contents |
| --- | --- |
| `/app/assets/cohort-blind-test.npz` | `sample_id`, `formula`, `spectra` only. |
| `/app/assets/axis-cm-1.npy` | 1791 points, 400 to 3980 cm⁻¹ in 2 cm⁻¹ steps. |
| `/app/assets/SOURCES.yaml` | provenance of the derived inputs. |

**Deliverables**

| Path | Contents |
| --- | --- |
| `/app/final/submission.csv` | header `sample_id,condition_id,` plus the eight class names |
| `/app/final/model.npz` | read with `allow_pickle=False` |
