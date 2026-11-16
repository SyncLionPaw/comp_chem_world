# Phosphocysteine Intermediate System Preparation

## Background

Prepare the PTP1B phosphocysteine hydrolysis intermediate.

The inputs include crystal structures, CSP force-field parameters and starting heavy-atom coordinates.

## Task

Prepare the PTP1B phosphocysteine hydrolysis intermediate, and calculate and interpret the quantities specified below and in the public contract.

## Requirements

- Use the supplied CSP template and frcmod with an Amber protein force field.
- Resolve all titratable states, including explicit HID/HIE/HIP; the phosphate-nearest catalytic Asp must be ASP.
- Retain crystallographic waters unless they clash.
- Use periodic octahedral TIP3P with clearance ≥10 Å and Na+/Cl− neutralisation: charge 0.000 ±0.001 e.
- Require exactly one covalent S–P CSP, no heavy-atom separation <0.8 Å, matching topology/coordinate atom counts and LEaP/CPPTRAJ readability.
- Audit every titratable residue by one-based topology index; deposited numbering is one below canonical numbering.
- Do not fetch external scientific data.

- JSON submissions must use unique object member names and finite numbers. Artifact paths may resolve to files inside `/app`.
- Submit the required artifacts according to the listed output contract.

## Files

| Path | Description |
| --- | --- |
| `/app/inputs/` | Structures, calculation records and reference data. |
| `/app/inputs/output-contract.json` | Required outputs and submission format. |
| `/app/` | Submitted results and required execution evidence. |
