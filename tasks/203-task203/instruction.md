# Actual Sage Torsion Refit and Protected Validation

## Background

Improving a training torsion curve does not establish transfer to unseen angles or molecules. The supplied data include molecular structures, QM training records, the fixed Sage field and validation protocol.

## Task

Select and refit a small chemically assigned set of existing Sage Proper-torsion coefficients using the three training sources. Evaluate fitting, no-ridge controls and relaxed-geometry responses, keeping protected QM data out of selection.

## Requirements

- Use the full Sage bonded/nonbonded energy with the prescribed first-conformer AM1-BCC charges; do not substitute an independent Fourier surrogate.
- Retain all twelve alternating training angles per source. Modify at most two allowed Proper IDs, at most four existing k terms per ID, each within initial +/-20 kJ/mol; preserve all other parameters.
- Choose parameters and regularization using training data only. Keep a same-selection no-ridge control and all parameter/objective histories; at most 200 full-training objective evaluations include selection and controls.
- Perform the prescribed four-angle relaxed validation per training molecule. The other twelve angles and independent molecule remain protected; preserve adverse results and make no guaranteed-improvement or generalization claim.
- Use installed local tools without networking or remote scheduling. Use at most 2000 minimizer iterations per required relaxed grid.

- Submit results, reproducible analysis and native evidence under `/app/`, using `/app/results.json` and `/app/analysis.py` as the result and analysis entry points. Submit the remaining required files, fields and native artifacts according to the listed output convention.

## Files

| Path | Description |
| --- | --- |
| `/app/environment/assets/` | Molecular systems, force fields and calculation parameters. |
| `/app/` | Submitted results and required execution evidence. |
| `/app/environment/assets/output-contract.json` | Required outputs and submission format. |
