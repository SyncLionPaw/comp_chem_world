# Fair Method Ranking Under Coverage Confounding

## Background

Different valid structure sets can confound charge-method adsorption rankings.

Public inputs provide archived observations, the archive structure and family-proxy method conventions.

## Task

Compare own-set and common-domain method rankings, coverage costs and family sensitivity from archived observations.

## Requirements

- Keep Only Def2 atoms=1 and PO Vol.>0. Valid-table ok defines validity; preserve ko/nan denominators and unknown failure causes. Compare four methods for CO2 heat and at least one uptake observable. Report structure weighting and the exact six-uppercase-letter CCDC refcode-root family proxy, leaving unmatched IDs unresolved. Select primary cohort, observable, metric and weighting with computed rank-change facts. Supply rerunnable analysis.py and retain exact fields and undefined-correlation empty cells. Do not rerun adsorption simulations.
- Use only this case’s public inputs; retain required statuses, failures, units and reproducible evidence.
- The replay runs `outputs/code/analysis.py` unprivileged with `--inputs /inputs --output /out`. Only the submitted code directory and public inputs are available as read-only data.

- Submit the required artifacts according to the listed output contract.

## Files

| Path | Description |
| --- | --- |
| `/opt/qeq-public/` | Public data, models and calculation parameters. |
| `/opt/qeq-public/output-contract.yaml` | Required outputs and submission format. |
| `/app/outputs/` | Submitted results and required execution evidence. |
