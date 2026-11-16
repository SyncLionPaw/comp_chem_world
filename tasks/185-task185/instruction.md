# Build and evaluate a water potential with Ai2-Kit

## Background

No water structures, labels, trained model or reference results are supplied. You choose suitable data and evaluation sources; historical benchmark material is not a task input.

## Task

Use Ai2-Kit to coordinate a reproducible workflow that builds and evaluates a water potential. Choose water configurations and labels, fit a model, and assess it quantitatively on held-out samples. Report data provenance, methods, measured results, compute used, uncertainty and limitations. Training loss alone does not establish predictive accuracy. Distinguish evidence that the workflow ran from evidence that the model is accurate for the stated physical domain.

## Requirements

If using HPC, follow the `ikkem-slurm` workflow: probe the authorized target, submit, wait for a terminal state, collect native outputs, and validate the scientific result. Manage and close out your own jobs and temporary files.

Use a scientifically appropriate independent evaluation set and report the tested phases, temperatures, configurations and observables. Use metrics and units suited to the data; explain the split and any sampling or convergence limitations. Preserve enough configuration and execution records to reproduce how Ai2-Kit coordinated the fit. Existing traceable labels may be used; new first-principles labels are not required.

## Files

Public input files:

| File path | Description |
| --- | --- |
| — | No predefined research data are supplied. |

Store all research evidence under `/app/submission/` and submit:

| Path | Contents |
| --- | --- |
| `/app/submission/claim.md` | research report discussing methods, results and limitations, linking claim IDs; headings and layout are unrestricted. |
| `/app/submission/provenance.json` | nonempty `sources`, `decisions`, `executions`, and `claims` arrays with globally unique IDs. Each source records relative `path` and matching `sha256`; decisions contain `evidence_ids`; each claim contains `source_ids`, `execution_ids`, and relative `evidence_paths`. |
| `/app/submission/results.json` | `workflow` contains `data_paths`, `model_path`, declared `model_sha256`, and `training_record_paths`; `trajectory_paths` and `label_paths` are optional. A training record identifies a method or configuration and at least one finite fit/objective statistic. The model is an inspectable artifact; report its format and how it was used. |

- Water structures are extxyz frames with a species/position Properties declaration (for example `Properties=species:S:1:pos:R:3`), finite coordinates and O:H = 1:2. Periodic frames include a finite positive-volume cell; nonperiodic water clusters are also acceptable. If labels are submitted, map them to frames by `sample_id`, `source_path`, and `frame_index`; use `energy`/`energy_unit`, `forces`/`force_unit`, or `observables` entries `{name, unit, value}`.
- For quantitative validation, `results.json.validation` contains non-overlapping `train_sample_ids`, `test_sample_ids`, and `table_path`. The per-sample table has `sample_id`, `quantity`, `unit`, `predicted`, and `reference`, and maps to the submitted labels. New reference calculations are not required when suitable traceable labels already exist.
- For each reported reproducible metric, `results.json` contains `quantities` entries `{id, name, unit, value}` and corresponding `checks` entries `{quantity_id, path, operation, value}` pointing to the validation table. Use `mae` or `rmse`; values must be reproducible from predictions and references.

Discuss source quality, the independence and scope of the test data, model applicability and remaining uncertainty. The task is open research: no accuracy threshold or single required scientific route is specified.
