# Local Chemical-Environment Attribution of Halogen Charge Anomalies

## Background

Halogen partition-charge anomalies depend on local periodic chemical environments and uncertain archive mappings.

Public inputs provide the charge data, geometry index, mapping bounds and method conventions.

## Task

Attribute Cl/F deviations using actual geometry, compare environment statistics and construct chemical counterevidence.

## Requirements

- Cover all 2438 Cl/F sites in 186 structures and 707 matching components. Preserve ok/ko/nan/missing and whole-row methods. Use complete one-to-one allowed-edge matchings at publication precision 5.1e-6. Choose an inclusive 1.8–2.2 Å neighbor cutoff and retain both endpoint descriptors, periodic images, class strata and sensitivity. Provide Cl:O4/Cl:C1 populations, complete matching extrema, contrasts and two distinct conditional perchlorate oxygen partitions (-3<q<0), differing by at least 1e-3 e. Motif serialization tolerance is 1e-8 e; interval arithmetic 1e-12 e.
- Make `environment_class` a deterministic function of the computed geometry descriptor: repeated descriptors must have the same class, and `Cl:O4` and `Cl:C1` must remain distinct classes. Do not use charges or status values to define geometry classes.
- Source claims remain conditional on the frozen archive-block assumptions in the public ambiguity card; do not claim native site identity recovery.
- Use only this case’s public inputs; retain required statuses, failures, units and reproducible evidence.
- Supply `outputs/code/analysis.py` accepting `--inputs` and `--output`. It must regenerate all scientific results from public inputs in a fresh unprivileged workspace. Both copies receive independent scientific checks; `environments.csv` and `errors.csv` must reproduce the same field values (row and column order may vary).

- Submit analysis.py and its dependencies in outputs/code/; it must regenerate the scientific results in an empty directory.

- Submit the required artifacts according to the listed output contract.

## Files

| Path | Description |
| --- | --- |
| `/opt/qeq-public/` | Public data, models and calculation parameters. |
| `/opt/qeq-public/output-contract.yaml` | Required outputs and submission format. |
| `/app/outputs/` | Submitted results and required execution evidence. |
