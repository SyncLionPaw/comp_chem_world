# How reliably can a model describe structure and transport in reline?

## Background

Reline is a choline chloride–urea deep eutectic solvent. Agreement with one observable need not establish transferability to other properties.

## Task

Build and test an energy-and-force model and determine what it can support about reline structure, molecular self-diffusion and collective transport. Acquire or generate appropriate inputs and perform a reproducible fit and computational assessment.

## Requirements

- Choose the model, labels, independent validation, simulated conditions and sampling. Diagnose a concrete weakness or risk and use a justified change or control to test it. Distinguish single-molecule and collective motion, and quantify or bound sampling uncertainty.
- Acquire your own inputs and document their sources, access basis and transformations. Distinguish completed work from plans, preserve evidence supporting the results and justify the stopping point.
- If using cluster resources, use the authorized `hpc` interface and retain native job and resource records.

## Files

**Public input files**

| File path | Description |
| --- | --- |
| — | No predefined research input files. |

**Deliverables**

Submit under `/app/final/`.

| Path | Contents |
| --- | --- |
| `report.md` | Research question, methods, results, uncertainty, limitations and conclusion. |
| `provenance.json` | Nonempty `sources` and `claims` lists. Each claim has `claim` text and an `evidence` list of paths relative to the submission root. |
| `evidence/` | Acquired or generated inputs, scripts, native execution records and quantitative evidence. |

Scientific conclusions require independent human review.
