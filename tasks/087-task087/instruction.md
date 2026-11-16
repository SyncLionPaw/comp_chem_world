# Molecular structure identification from infrared spectra

## Background

Infrared spectra constrain molecular structure, but ambiguity depends on the system, spectral resolution and comparison method. No scientific dataset or model is supplied; choose suitable public materials independently.

## Task

Investigate a focused question about identifying molecular structures from infrared spectra. Motivate the question, choose the system and methods, and report the strongest conclusion supported by your results.

## Requirements

- Work in the provided local environment; do not submit remote jobs. Record sources, known licenses and actual software. Use `unknown` for an unresolved license.
- Explain methods, observations, interpretation, uncertainty, limitations and conclusions. Distinguish observed results from inferences, hypotheses and unresolved questions, and connect substantive claims to retained evidence.
- Preserve the data, analysis and execution records needed to understand and reproduce the work. Distinguish completed calculations from proposed work; do not fabricate activity or treat a complete record as scientific validation.

Submission checks cover evidence completeness. Scientific conclusions require independent review.

## Files

Public input files:

| File path | Description |
| --- | --- |
| — | No predefined research data are supplied. |

Submit `/app/final/research-report.md` and `/app/final/research-manifest.json`, together with supporting evidence.

The JSON manifest contains three entries:

| Entry | Contents |
| --- | --- |
| `claims` | Records with `claim_id`, `claim_text`, `status` (`observed`, `inferred`, `unresolved`) and `evidence_paths`. Use unique identifiers beginning with a letter or digit and containing letters, digits, `.`, `_` or `-` (up to 128 characters). Observed and inferred claims cite evidence; unresolved claims may cite none. |
| `artifacts` | One `{ "path": "final/..." }` entry for the report and each evidence file, excluding the manifest itself. All cited paths are relative to `/app` and resolve to listed regular files inside `final/`; do not use links. |
| `reproducibility` | `execution_status` (`not_run` or `executed`), `execution_evidence_paths`, `commands`, `software`, and `data_sources` (records with `description`, `license`). Executed work cites a retained log/output, actual command and software. For unexecuted work, evidence paths are empty; other lists may also be empty. |
