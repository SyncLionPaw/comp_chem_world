# Independent research: experimental SNAr activation free energies

## Background

Reliable predictions for unseen SNAr reactions require chemical evidence, computation and independent validation. No scientific data, prescribed source or model is supplied.

## Task

Investigate whether, and under what conditions, external evidence and computations you execute support reliable predictions of experimental SNAr activation free energies. Acquire evidence, define the scope, choose and justify methods, conduct research and evaluate the conclusions. Supported negative or inconclusive findings are legitimate outcomes.

## Requirements

- Environment: use the container Python on `PATH`. Preinstalled packages include NumPy, pandas, scikit-learn, SciPy. Do not install additional packages or fetch dependencies from the network.

If using HPC, follow the `hpc` workflow: probe the authorized target, submit, wait for a terminal state, collect native outputs, and validate the scientific result.

- Choose data, methods, controls and validation yourself. Public internet access is available; respect the environment’s resource limits.
- Define the physical quantity, units, conditions and population. Examine validation independence, duplicate/correlated observations and label exposure as relevant; public labels are not prospectively blind.
- Distinguish acquired results from your own calculations. Preserve inputs, code, native outputs and available receipts, including failed/stopped attempts, and record consequential decisions and limitations.
- Support quantitative claims with inspectable calculations, appropriate controls, uncertainty and applicability analysis. Separate evidence from speculation. No named dataset, engine, model, accuracy threshold or positive computational gain is required.

## Files

Public input files:

| File path | Description |
| --- | --- |
| — | No predefined research data are supplied. |

```text
/app/final/
  claim.md
  provenance.json
  results.json
  native_evidence/             acquired inputs, code, native outputs and receipts
```

```text
provenance.json:
  sources:    [{id,origin,acquisition,path}]
  decisions:  [{id,decision,reason,evidence_ids}]
  executions: [{id,stage,input_paths,output_paths,receipt_paths,status}]
  claims:     [{id,statement,result_ids,evidence_paths,source_ids,execution_ids}]
results.json:
  scope, validation
  conclusion: {status,rationale,limitations,claim_ids}
  quantities: [{id,name,value,unit,conditions,population,uncertainty,evidence_paths}]
```


`claim.md` explains the question, methods, validation, results and limitations; provide code/data sufficient to reproduce central numerical results.

In the structures above, `acquisition` is `acquired|constructed`, with a URL or construction origin. Sources reside under `native_evidence/`. IDs are unique nonempty strings within each category; references resolve to the corresponding sources, executions, claims or quantities. Path fields are arrays except source `path`; use relative POSIX paths to regular submission files, without symlinks. Receipts may be empty when unavailable; disclose this limitation. Do not treat self-reported times as independent proof.

`scope` and `validation` are nonempty text/objects; conclusion status is `supported|refuted|inconclusive`, with rationale and limitations. Quantity values are finite numbers or nonempty nested numeric arrays; state conditions, population and uncertainty, including limitations when uncertainty is unquantified. Use UTF-8 JSON with unique keys. Method-specific fields/files are welcome.

For directly recomputable scalar summaries, optional `results.json.checks` entries are `{id,quantity_id,path,operation,column}`. Cite the table in the quantity's `evidence_paths`; use UTF-8 CSV with unique headers and finite values. Operations are `sum,mean,min,max,count,mae,rmse`, with `reference_column` for MAE/RMSE; count means row count. Compatible-unit conversion may use positive `unit_factor`. Numerical agreement tolerance is absolute 1e-8 plus relative 1e-6. These optional summaries do not restrict the research methods.
