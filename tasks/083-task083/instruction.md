# Task: Functional Group Signals in Simulated Infrared Spectra

## Background

The package provides simulated gas-phase infrared spectra computed for a large
molecular library, together with the functional groups each molecule carries.
Public training and validation cohorts give structure-spectrum pairs; a blind
cohort gives only an opaque identifier, the molecular formula and the spectrum.
Functional groups are the eight structurally clear classes of SI §6: alcohol,
carboxylic acid, ester, ketone, alkene, alkyne, benzene and cyano. Secondary and
tertiary amines are excluded because SMARTS calibration for them is disputed.

Because the source library is public, an exact spectrum can in principle be
matched against external reference tables. Within this package the identifiers
are opaque and the runtime exposes only the derived spectra, so any conclusion
about spectral information must be read as an internal diagnostic on this
public library rather than as an independent blind-test generalization.

## Task

Build an interpretable multi-label classifier for the eight groups, fit only on
the training cohort and checked on the validation cohort, then use it on the
blind cohort. The scientific question is not whether the classifier can predict
groups, but whether the spectra carry information beyond the molecular formula:
a formula-constrained prior already narrows the plausible groups considerably.

Answer that question by comparing the blinded ranking against two references:
the formula-only prior derived from the training labels, and a control in which
each blind spectrum is replaced by a cyclically shifted spectrum from another
member of the same formula group. Submit the predictions needed to estimate gains and uncertainty against the blind labels.

## Requirements

- Environment: use the container Python on `PATH`. Preinstalled packages include NumPy, pandas, pillow, PyYAML, RDKit, scikit-learn, SciPy. Do not install additional packages or fetch dependencies from the network.

**Classifier.** A linear one-vs-rest model on the 1791-point spectrum is
required so that the submitted probabilities can be reproduced exactly from the
submitted parameters. Per-spectrum scaling must be fit on training data only.

**Conditions.** Submit predictions for `full_spectrum` on every blind sample,
and for `within_formula_spectrum_shuffle` on the members of every blind formula
group that contains at least two spectra. The shift control is defined as
follows. Group the blind samples by formula string in ascending order; within a
group of size `n`, order members by `sample_id` ascending. For formula `f` take

```
seed   = int.from_bytes(SHA256(UTF8("ir-local-formula-row-shuffle-v1|20261005|" + f))[:8], "little")
offset = numpy.random.default_rng(seed).integers(1, n)
```

and give sorted row `j` the original spectrum of sorted row `(j + offset) mod n`.
Identifiers and formulas are unchanged, and groups of size one are excluded.
Choose the shift without reference to any model output.

**Frequency bands.** Report the bands the model relies on, selected from
training data only and confirmed independently on validation. Each band is a
narrow interval with a cm⁻¹ range, a direction, the validation effect and its
uncertainty. Bands that are not supported on validation must still be reported
as such.

The validation fields are recomputed from the public validation cohort, so they
must follow this definition exactly. Normalise each validation spectrum row by
`max(max(abs(spectrum)), 1e-12)`; the window feature is the mean of those
normalised intensities over the axis points with `lo <= axis <= hi`.
`validation_mean_difference` is the mean feature over positive tasks minus the
mean feature over negative tasks and is not flipped by `direction`.
`validation_ci95` is the 2.5% and 97.5% quantiles of 500 formula-cluster
bootstrap resamples: group validation rows into formula clusters in file order,
seed with

```
seed = int.from_bytes(SHA256(UTF8("ir-local01-band-bootstrap-v1|20261104|" + f"{group}|{lo:.1f}|{hi:.1f}"))[:8], "little")
```

and for each resample draw as many clusters with replacement as there are
clusters, take all their spectra, and record the positive-minus-negative mean
difference only when the resample contains both classes.

**Comparison.** The scientific comparisons are the blinded ranking against the
formula-only prior, and — on eligible formula groups — clean spectra against
the shifted control, using average-precision gains with formula-cluster
bootstrap intervals. The blind labels are not included in the public inputs: submit
predictions on exactly the required rows and do not self-report label-based gains
or intervals. Both gains must be supported for the evidence to count as resolved.

Do not use blind labels for fitting or band selection, and do not consult
external spectrum databases.

### Input and deliverable details

Runtime inputs are read-only under `/app/assets/`:

- `cohort-train.npz`, `cohort-validation.npz` — `sample_id`, `formula`,
  `spectra`, `smiles`, `group_labels`, `group_names`; class columns follow
  `group_names` exactly.
- `cohort-blind-test.npz` — `sample_id`, `formula`, `spectra` only.
- `axis-cm-1.npy` — 1791 points, 400 to 3980 cm⁻¹ in 2 cm⁻¹ steps.
- `SOURCES.yaml` — provenance of the derived inputs.

Write the deliverables to `/app/final/`:

- `submission.csv` — header `sample_id,condition_id,` followed by the eight
  class names in `group_names` order. `condition_id` is `full_spectrum` or
  `within_formula_spectrum_shuffle`. Probabilities are finite values in [0, 1].
- `model.npz` — read with `allow_pickle=False`; numeric arrays only: `coef`
  (8, 1791), `intercept` (8,), `scaler_mean` (1791,), `scaler_scale` (1791,),
  all finite with a strictly positive scale. Each spectrum is divided by
  `max(max(abs(spectrum)), 1e-12)`, standardised as `(x - scaler_mean) /
  scaler_scale`, and passed through a logistic sigmoid of `x @ coef.T +
  intercept`.
- `band_evidence.json` — `classes` keyed by all eight group names; each entry is
  a list of 1–5 bands with `range_cm1` `[lo, hi]`, `direction` (`higher_in_positive`
  or `lower_in_positive`), `validation_mean_difference` and `validation_ci95`.
  Intervals are finite, inside 400–3980 cm⁻¹, at most 4 cm⁻¹ wide, cover at
  least one axis point, and are distinct within a class.

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
| `/app/final/submission.csv` | Predicted scores for the eight functional groups. |
| `/app/final/model.npz` | read with `allow_pickle=False` |
| `/app/final/band_evidence.json` | `classes` keyed by all eight group names |
