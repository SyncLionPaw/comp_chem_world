# Actual Multi-Start Force-Field Conformer Minimization

## Background

Different QM starting conformers can lead to different local minima of a molecular-mechanics model. The supplied data include structures, identity mappings, the fixed Sage field and protocol.

## Task

Perform twelve actual Sage minimizations: the two prescribed QM starts for each of six molecules. Validate local stationarity and chemical identity, then compare geometry changes and within-molecule energy rankings.

## Requirements

- Preserve all twelve starts, explicit-hydrogen atom maps, topology and stereochemistry; never drop failed starts from the denominator.
- Use the fixed field and AmberTools AM1-BCC vector generated from the prescribed first supplied conformer per molecular identity; reuse it across starts.
- Each required final geometry must lower energy within replay precision and have maximum atomic force at most 1 kJ mol^-1 nm^-1. Retain optimization histories and native initial/final states.
- Use chirality-preserving proper-rotation symmetry RMSDs and separate energy zeros per molecule. Do not claim global minima or equilibrium populations.
- Use installed local tools without networking or remote scheduling. Use at most 5000 iterations per start.

- Submit results, reproducible analysis and native evidence under `/app/`, using `/app/results.json` and `/app/analysis.py` as the result and analysis entry points. Submit the remaining required files, fields and native artifacts according to the listed output convention.

## Files

| Path | Description |
| --- | --- |
| `/app/environment/assets/` | Molecular systems, force fields and calculation parameters. |
| `/app/` | Submitted results and required execution evidence. |
| `/app/environment/assets/output-contract.json` | Required outputs and submission format. |
