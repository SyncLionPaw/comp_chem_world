# Finite-Summation Convergence and Representation Invariance of Periodic Charges

## Background

Periodic charge sums can depend on truncation and cell representation.

Public inputs provide the source observations, geometry, parameters and method conventions.

## Task

Establish DOTSOV02 EQeq summation convergence and invariance under equivalent cells and origin shifts.

## Requirements

- Use a finite numeric scan key for `summation_setting` (for example 1, 2, 3). In the same representation, `compared_to_setting` is empty on the first row and is the preceding numeric key thereafter. Use `run_id` for descriptive labels such as `R03-M03`.
- Retain the analytical EQeq kernel, geometric hardness mixing, K=14.4/1.67 eV Angstrom/e², neutral G=0/tinfoil convention, nonzero self-images and actual-charge Taylor coefficients. H uses -2.0 and 13.598 eV. Scan at least three increasing extents with a declared stopping rule. Final numerical charge target is 1e-6 e; at most 12 runs, range 20 per direction and twofold replication. Preserve atom mappings and runnable analysis.py.
- Use only this case’s public inputs; retain required statuses, failures, units and reproducible evidence.
- Demonstrate the stopping rule in the submitted primary scan: increase at least one cutoff on each step, never decrease either, and attain maximum adjacent charge change ≤1e-6 e at the final step. Independent reference agreement is also required. One genuinely equivalent representation suffices: a non-integral origin shift or a nonidentity cell transformation.

- Submit analysis.py and its dependencies in outputs/code/; it must regenerate the scientific results in an empty directory.

- For the frozen DOTSOV02 CIF, assign the 156 base atom IDs in the original atom-site loop row order, one-based, as `site000001` through `site000156`. CIF labels may repeat and are not stable IDs. The primary representation uses these exact IDs with zero image; equivalent representations map each atom to its base ID and integer lattice image.
- During controlled replay, `/submission` and `/inputs` are read-only; `/out`, `/tmp` and a private `/dev/shm` are writable. The public runtime and `/dev/null` and `/dev/urandom` are available; `/proc`, grading data, and host-specific paths are not. Use the provided command-line paths rather than assuming the host filesystem layout.
- In each representation, the first convergence row leaves both `compared_to_setting` and `max_delta_q_e` empty; subsequent rows compare the immediately preceding setting.
- Submit the required artifacts according to the listed output contract.

## Files

| Path | Description |
| --- | --- |
| `/opt/qeq-public/` | Public data, models and calculation parameters. |
| `/opt/qeq-public/output-contract.yaml` | Required outputs and submission format. |
| `/app/outputs/` | Submitted results and required execution evidence. |
