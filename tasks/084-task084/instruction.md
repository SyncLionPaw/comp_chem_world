# Task: Ranking of Constitutional Isomers with Identical Molecular Formula

## Background

The package provides simulated infrared spectra computed for a large molecular
library. A public training and validation set gives structure-spectrum pairs
from molecules outside this task; the query set gives only an opaque identifier,
a formula, a spectrum, and a small set of constitutional isomers sharing that
formula. The candidate order has been randomized.

The source simulation library is public, so an exact query spectrum could in
principle be matched against external reference tables. Anything derived here
must therefore be read as an internal closed-set reranking result on that
library, not as an independent blind-test generalization.

## Task

Rank the constitutional isomers for each query. Assess how much the spectrum adds over rankings based on candidate structures alone or on a frequency-scrambled spectrum.

## Requirements

- Environment: use the container Python on `PATH`. Preinstalled packages include NumPy, pandas, pillow, PyYAML, RDKit, scikit-learn, SciPy. Do not install additional packages or fetch dependencies from the network.

Submit all three rankings. The primary numerical test compares full-spectrum Top-1 accuracy with uniform random choice among each query’s candidates. It requires accuracy above the random expectation and a one-sided exact p-value below 0.05. Report the candidate-only and scrambled-spectrum results as diagnostic controls.

**Chemical validity.** Every candidate must be a neutral, connected, valid
structure with the query's molecular formula; verify formulas and graph
uniqueness with RDKit. Every candidate of a query must appear exactly once in
that query's ranking, ordered by a decreasing finite score.

**Reported uncertainty.** Each ranking carries an uncertainty in [0, 1]
reflecting the unresolved alternatives; these are interpretable model scores,
not calibrated probabilities.

**Prohibited shortcuts.** Do not retrieve source spectra for the candidate
structures, do not look up spectra in external databases, and do not use any
hidden ground truth.

### Input and deliverable details

Runtime inputs are read-only under `/app/assets/`:

- `cohort-train.npz`, `cohort-validation.npz` — structure-spectrum pairs with
  `sample_id`, `formula`, `spectra`, `smiles`, `group_labels`, `group_names`.
- `isomer-query-public.npz` — `sample_id`, `formula`, `spectra`; the spectrum
  matrix has shape (query count, 1791).
- `isomer-candidates-public.json` — one question per `query_id`, with `formula`,
  `candidate_count` and `candidates`; each candidate carries `candidate_id` and
  a SMILES string.
- `axis-cm-1.npy` — 1791 points, 400 to 3980 cm⁻¹ in 2 cm⁻¹ steps.
- `SOURCES.yaml` — provenance of the derived inputs.

Write one JSON object per line to `/app/final/submission.jsonl`, covering every
`query_id` under each of the three `condition_id` values `full_spectrum`,
`candidate_only` and `frequency_scrambled_query`:

```
{"query_id": ..., "condition_id": ..., "uncertainty": <0..1>,
 "ranked_candidates": [{"candidate_id": ..., "score": ...}, ...]}
```

`full_spectrum` ranks from the query spectrum, `candidate_only` from the shared
formula and structures alone, and `frequency_scrambled_query` from the same
query spectrum with its frequency order permuted per query; the permutation must
not alter any query or candidate identifier.

## Files

Public input files:

| File path | Description |
| --- | --- |
| `/app/assets/` | Directory of supplied inputs and resources. |

**Inputs**

| Path | Contents |
| --- | --- |
| `/app/assets/isomer-query-public.npz` | `sample_id`, `formula`, `spectra` |
| `/app/assets/isomer-candidates-public.json` | Candidate structures for each query. |
| `/app/assets/axis-cm-1.npy` | 1791 points, 400 to 3980 cm⁻¹ in 2 cm⁻¹ steps. |
| `/app/assets/SOURCES.yaml` | provenance of the derived inputs. |

**Deliverables**

Write the rankings to `/app/final/submission.jsonl`.
