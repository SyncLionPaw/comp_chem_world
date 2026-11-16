# EVB Reaction Region Topology and Force Field Parameter Integrity Validation

## Background

Validate deposited Q6 EVB hydrolysis parameter inputs.

The deposited archive supplies coordinates, protocols and EVB inputs.

## Task

Validate deposited Q6 EVB hydrolysis parameter inputs, and calculate and interpret the quantities specified below and in the public contract.

## Requirements

- Parse four .fep files, topologies and the 51-window input set.
- Identify all 17 Q atoms: Asp 6, CSP 8, HOW 3.
- All referenced types require defined atom_types/Lennard-Jones records; zero hydrogen LJ is legitimate.
- Verify CSP.SGP–CSP.PO breaking and CSP.PO–HOW.OW formation in change_bonds.
- Compare atom types, LJ and bonded parameters across all four systems allowing PDB index differences.
- Either deposited label spelling is accepted.
- Use Python standard library; no Q6 dynamics is needed.
- Do not fetch external scientific data.

- JSON submissions must use unique object member names and finite numbers. Artifact paths may resolve to files inside `/app`.
- Submit the required artifacts according to the listed output contract.

## Files

| Path | Description |
| --- | --- |
| `/app/inputs/` | Structures, calculation records and reference data. |
| `/app/inputs/output-contract.json` | Required outputs and submission format. |
| `/app/` | Submitted results and required execution evidence. |
