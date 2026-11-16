# Sage Parameterization, Molecular Energies, and Forces

## Background

Molecular energies and forces depend on consistent parameter assignment, charges and units. The supplied data include explicit-hydrogen structures, probe geometries, the fixed Sage force field and protocol.

## Task

Build the complete Sage models for neutral methanol, ethanol and acetamide. Compute energies and Cartesian forces for all twelve supplied configurations and assess energy-gradient consistency.

## Requirements

- Preserve molecular identity, explicit hydrogens, atom order, SMIRKS assignments and the fixed unconstrained Hamiltonian.
- Generate AmberTools AM1-BCC charges from each supplied first conformer and reuse the same mapped vector across its four configurations.
- Recompute all configurations and both prescribed finite-difference steps; maximum component error must be at most 0.01 kJ mol^-1 nm^-1. Retain native models, states and numerical evidence.
- Use installed local tools without network access or remote scheduling. Keep partial results on budget exhaustion; do not replace the force field or charge model.
- Conclusions apply only to the supplied small-molecule panel.

- Submit results, reproducible analysis and native evidence under `/app/`, using `/app/results.json` and `/app/analysis.py` as the result and analysis entry points. Submit the remaining required files, fields and native artifacts according to the listed output convention.

## Files

| Path | Description |
| --- | --- |
| `/app/environment/assets/` | Molecular systems, force fields and calculation parameters. |
| `/app/` | Submitted results and required execution evidence. |
| `/app/environment/assets/output-contract.json` | Required outputs and submission format. |
