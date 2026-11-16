# Constrained Relaxed MM Torsion Scans Against QM

## Background

A relaxed torsion profile depends on both the angular constraint and stationarity in the remaining degrees of freedom. The supplied data include QM scans, mapped structures, the fixed Sage field and protocol.

## Task

Run forward and reverse constrained Sage scans for both supplied molecules, retaining all twenty-four 15-degree grid points per direction. Compare the physical MM and QM curves and quantify branch dependence.

## Requirements

- Preserve source identities, atom ordering and stereochemistry. Use the fixed field and one first-supplied-conformer AmberTools AM1-BCC vector per molecule across all angles and directions.
- Complete all 96 constrained optimizations. Periodic angle error must be at most 1 degree and the maximum tangent-space projected force at most 5 kJ mol^-1 nm^-1.
- Retain physical forces, torsion Jacobians and optimization histories. Exclude artificial constraint energy from the physical MM curves.
- Zero each observed direction curve separately; preserve both branches. Do not infer an unconstrained reaction barrier or general force-field superiority.
- Use installed local tools without networking or remote scheduling. Use at most 5000 iterations per grid point.

- Submit results, reproducible analysis and native evidence under `/app/`, using `/app/results.json` and `/app/analysis.py` as the result and analysis entry points. Submit the remaining required files, fields and native artifacts according to the listed output convention.

## Files

| Path | Description |
| --- | --- |
| `/app/environment/assets/` | Molecular systems, force fields and calculation parameters. |
| `/app/` | Submitted results and required execution evidence. |
| `/app/environment/assets/output-contract.json` | Required outputs and submission format. |
