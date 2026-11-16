# Can the 5HLS–62G protein–ligand structure be defensibly refined?

## Background

Structural refinement must balance chemical plausibility with agreement to independent observations and avoid overfitting.

## Task

Investigate whether a defensible refinement of the 5HLS–62G system can be obtained. Retrieve your own source material, choose a refinement and validation strategy and execute the relevant tests. If evidence or resources justify stopping, explain the attempted work and what would resolve the decision.

## Requirements

- Choose how to check identity, chemical plausibility, numerical convergence and independent agreement. Preserve the connection between native outputs and any model you claim to have refined. Distinguish missing validation from demonstrated deterioration.
- Acquire your own inputs and document their sources, access basis and transformations. Distinguish completed work from plans, preserve evidence supporting the results and justify the stopping point.
- If using cluster resources, use the authorized `ikkem-slurm` interface and retain native job and resource records.

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
