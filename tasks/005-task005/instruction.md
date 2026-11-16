# Blinded native-evidence review

## Background

Five blinded challenges use ORCA records to examine a two-pathway comparison and four questions of evidence quality.

## Task

Trace each challenge's `source_evidence_ids` through its `evidence-index.csv`. Evaluate the primary and listed claims, report the requested observations and supported issues, and compare barriers only when justified. Distinguish numerical electronic-energy ordering from confidence in experimental product preference.

## Requirements

- Base conclusions on the supplied native evidence. Cite archive-relative paths with their indexed content identifiers; `metadata-index` denotes the task index identified in `bundle-manifest.json`.
- Use the stated operational criteria: a substantial TS imaginary mode is below −100 cm⁻¹ along the mapped reactive coordinate. Assess minima using negative-frequency counts; |ν| < 10 cm⁻¹ is equivocal and a mode below −20 cm⁻¹ fails the minimum criterion. IRC-dependent claims require convergence in both directions. Compare barriers only across matching single-point protocols.
- For a supported two-path comparison, report barriers in kcal/mol and their numerical order. Reporting tolerances are 0.02 kcal/mol, 1e-6 Eh and 0.1 cm⁻¹; they do not establish scientific certainty. Counts and observation types must follow the records.
- `near_degenerate` means an absolute barrier gap <1.0 kcal/mol; `confidence` concerns experimental product preference. Assess claims as `supported`, `contradicted` or `underdetermined`; use `insufficient_evidence` when the requested decision is unresolved. Justify confidence from the evidence.

## Files

Public input files:

| File path | Description |
| --- | --- |
| `/app/assets/participant-audit-v2.zip` | Challenge descriptions, evidence and submission format. |

```text
/app/assets/participant-audit-v2.zip   challenge descriptions, evidence and submission schema
/app/input/                          extracted archive
/app/final/submissions/
  <case_id>.json                     one assessment per challenge
```


Extract the archive and follow each challenge's `submission_schema`, referring to the supplied root `submission.schema.json`. Each result contains the decision, supported issues, claim assessments and typed observations with `{path,sha256}` citations copied from the evidence index. Barrier values, ranking, near-degeneracy and confidence are included only when applicable. The schema specifies the output format, not the scientific answers.
