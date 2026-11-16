# Task: Review of Functional Group Identification Results and Failure Explanations

## Background

The package contains the main documentation, its supplementary information, and the
supplementary workbook that publishes the functional-group identification
results of a simulated infrared study. The results are reported as aggregate
tables only: per-class support counts and Top-k percentages, per-class precision,
recall and F1, and a relative over/under-representation matrix over confusable
group pairs. Identical names recur across tables under different denominators.

Your job is to reconcile these published aggregates independently of the source
narrative: map out which sample population each table actually describes, which
functional-group claims the published numbers support, which remain mechanistic
hypotheses proposed by the source, and which causal statements exceed what
aggregate data can justify.

## Task

Read the provided sources and produce a single machine-readable reconciliation.
The questions to answer are:

- How many classes each published table covers, and what the aggregate
  performance is across them.
- How precision, recall and F1 relate to the identified support, and what
  confusion integers are *consistent with* the printed per-class metrics under
  an explicit assumption about what the displayed count means.
- Where a group name appears with different denominators in two different
  tables, and by how much the two supports differ.
- Which group pairs are relatively over- or under-represented in errors, and in
  which direction.
- Which interpretations are direct evidence associations in these aggregates,
  which are the source overlap hypotheses about band congestion, and which
  would require sample-level data to establish.

No new measurement is required: every submitted value is transcribed from the
provided sources or computed from them by the stated formulas.

## Requirements

### Submission schema

Write `submission.json` as a JSON object with exactly this structure; values and
interpretations must be derived independently from the provided sources.

```json
{
  "summary": {"figure4_class_count": 0, "figure4_macro_top1_percent": 0.0, "table6_class_count": 0, "macro_f1": 0.0, "support_weighted_f1": 0.0},
  "figure4_metrics": [{"group":"", "count":0, "top1_percent":0.0, "top5_percent":0.0, "top10_percent":0.0}],
  "class_metrics": [{"group":"", "support":0, "precision":0.0, "recall":0.0, "f1":0.0}],
  "conditional_support_assumption": "",
  "conditional_confusion": [{"group":"", "tp":0, "fp":0, "fn":0}],
  "category_counts": [{"source_id":"si_section6_smarts|si_table5|si_table6", "count":0}],
  "cross_table_comparisons": [{"group":"", "source_a":"", "count_a":0, "source_b":"", "count_b":0}],
  "error_relations": [{"source":"", "row_group":"", "column_group":"", "value":0.0, "direction":"overrepresented|underrepresented|neutral"}],
  "interpretations": [{"code":"support_association|spectral_overlap_hypothesis|error_composition", "evidence_refs":[], "causal_claim":false, "limits":[]}],
  "limitations": [],
  "follow_up": "optional exploratory proposal"
}
```

`summary`, `figure4_metrics`, `class_metrics`, `conditional_support_assumption`,
`conditional_confusion`, `category_counts`, `cross_table_comparisons`,
`error_relations`, `interpretations` and `limitations` are required; `follow_up`
is optional.

### Fixed field rules

- `summary`: `figure4_class_count` is the number of data rows of Figure 4;
  `figure4_macro_top1_percent` is the unweighted mean of that table's Top 1%
  column; `table6_class_count` is the number of data rows of Figure 5;
  `macro_f1` is the unweighted mean of the Figure 5 F1 column;
  `support_weighted_f1` is the Figure 5 F1 column weighted by that table's
  displayed `count`.
- `figure4_metrics`: one object per Figure 4 data row, preserving the source
  `count` and percentages with the source's percentage unit.
- `class_metrics`: one object per Figure 5 data row; `support` equals the
  source-displayed `count`, and precision/recall/F1 are the source decimals.
- `conditional_support_assumption` is the fixed value
  `figure5_displayed_count_assumed_positive_class_support`.
- `conditional_confusion`: one object per Figure 5 row with non-negative integer
  `tp`, `fp`, `fn`. This is a conditional integer reconstruction under the
  explicit assumption that the displayed `count` is the positive-class support,
  not a measured confusion matrix. It must satisfy `tp + fn = count`, and the
  integers must reproduce the source precision, recall and F1 within rounding
  tolerance. Do not present this reconstruction as sample-level confusion
  statistics.
- `category_counts`: one object per official source, for the fixed `source_id`
  values `si_section6_smarts`, `si_table5` and `si_table6`. `count` is the
  number of distinct categories defined or listed in that source — not the row
  count of an input file and not a sample-support count.
- `cross_table_comparisons`: objects `{group, source_a, count_a, source_b,
  count_b}`. At minimum compare the same-named groups with different
  denominators, `Tertiary Amine` and `Benzene`: Figure 4 corresponds to
  `si_table5`, Figure 5 to `si_table6`, and each count is transcribed from its
  own table. Do not treat the two supports as one sample denominator.
- `error_relations`: objects `{source, row_group, column_group, value,
  direction}`. `source` is the fixed value `workbook:Figure6`. Report the Figure
  6 cells at row `Secondary Amine` and columns `Amide`, `Primary Amine`,
  `Tertiary Amine`, transcribing the reported value; `direction` is
  `overrepresented` for positive, `underrepresented` for negative and `neutral`
  for zero. Figure 6 reports relative over/under-representation in errors, not
  correlation or causation.
- `interpretations`: exactly three objects, one per `code` value
  `support_association`, `spectral_overlap_hypothesis` and `error_composition`.
  Every object carries `evidence_refs`, `causal_claim: false` and `limits`, and
  `limits` must include at least `aggregate_only` and `association_not_cause`.
  References may only use `main_p7`, `si_table6`, `si_table5`, `si_section6`,
  `workbook_figure4`, `workbook_figure5` and `workbook_figure6`, and each code
  must cite its direct sources: `support_association` requires `main_p7`,
  `si_table6` and `workbook_figure5`; `spectral_overlap_hypothesis` requires
  `main_p7` and `si_table6`; `error_composition` requires `main_p7` and
  `workbook_figure6`.
  - `support_association` also carries `low_support_classes` and
    `counterexample`. `low_support_classes` lists every Figure 5 row with
    `count < 100` as `{group, support, f1}` transcribed from Figure 5.
    `counterexample` is the high-support, lower-F1 counterexample from the main
    text's discussion of support quantity versus identification performance, and
    is the `Secondary Amine` Figure 5 row as `{group, support, f1}`. Both show an
    association and a counterexample; neither supports an inference that
    changing support drives performance.
  - `spectral_overlap_hypothesis` also carries `groups` and `band_cm1`. `groups`
    is exactly `Secondary Amine`, `Amide`, `Primary Amine` and `Tertiary Amine`;
    `band_cm1` is the main text's reported congestion interval as a `[lower,
    upper]` cm⁻¹ pair. This is the source overlap hypothesis and is not proven
    by these aggregate tables.
  - `error_composition` also carries `figure6_semantics`, the fixed value
    `relative_over_underrepresentation_in_errors_not_correlation`.
- `limitations` must include at least `aggregate_not_sample_level`,
  `no_causal_identification`, `table5_table6_denominators_differ` and
  `conditional_confusion_only`, and these limits must be reflected in the text
  conclusions. `follow_up` is the optional place to propose how sample-level
  evidence could be obtained.

Aggregate confusion data cannot establish per-sample causality, and support
quantity cannot be separated from spectral band congestion within these tables;
the written interpretation must stay inside those limits.

### Input and deliverable details

Runtime inputs are read-only under `/app/assets/`:

- `official_main_article.pdf`, `official_supplementary_information.pdf` — the
  source documentation and its supporting data, including the Table 5 and Table 6 semantics and the band
  congestion discussion cited above.
- `official_supplementary_data.xlsx` — the supplementary workbook holding the
  Figure 4, Figure 5 and Figure 6 sheets.
- `figure4_structure_topk.csv`, `figure5_group_metrics.csv`,
  `figure6_error_over_under.csv` — the three result tables extracted from the
  workbook.
- `SOURCES.yaml` — provenance of the extracted inputs.

Write the deliverable to `/app/final/submission.json`.

## Files

Public input files:

| File path | Description |
| --- | --- |
| `/app/assets/` | Directory of supplied inputs and resources. |

Write the analysis to `/app/final/submission.json`. The source tables and `SOURCES.yaml` are inputs under `/app/assets/`.
