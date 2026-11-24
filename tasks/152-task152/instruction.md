# Task: Investigate the isolated NEO molecular model using ORCA and r2SCAN-3c

## Background

Study the supplied NEO molecule as an isolated gas-phase neutral singlet using ORCA 6.0.1 and r2SCAN-3c. Conclusions concern this model, not the protein-bound state or a global tautomer preference.

## Task

Assess optimization convergence and whether the evidence supports a bounded recovery. Evaluate frequency/Hessian and SCF stability at the same final geometry, and explain any unresolved or failed result.

## Requirements

If using HPC, follow the `hpc` workflow: probe the authorized target, submit, wait for a terminal state, collect native outputs, and validate the scientific result.

Allow one initial optimization and at most two recoveries. This study covers iteration-limit extension only: a recovery must continue the final geometry of a normally terminated but unconverged optimization, increase MaxIter and preserve all other scientific controls, including r2SCAN-3c Opt TightSCF, charge and spin.

A vibrational mode below −20 cm⁻¹ or a negative stability eigenvalue indicates failure. Modes in [−20, 0] cm⁻¹ or an exactly zero stability eigenvalue leave the result unresolved. Incomplete evidence or unsupported input syntax does not establish scientific failure.

This container has no ORCA. Follow the host execution profile. Preserve native outputs, job records and costs.

### Input and deliverable details

Inputs are under `/app/assets/`: `1br5_candidate.xyz`, `1br5_reference.xyz`, `NEO.cif` and `1BR5_NEO_A_500.pdb`. Submit `/app/report.md`, `/app/result.json` and supporting evidence under `/app/native/`; include `/app/geometry.xyz` and `/app/atom_mapping.json` when a final model exists. If no final model exists, document the supported stop without inventing one. Evidence, numerical and output-format conventions are defined in `/app/verification.md`.

## Files

Public input files:

| File path | Description |
| --- | --- |
| `/app/assets/` | Directory of supplied inputs and resources. |
| `/app/verification.md` | Supplied data, parameters or method documentation; see the task requirements. |

| Path | Contents |
| --- | --- |
| `/app/native` | Required result; use the contents and format specified above. |
| `/app/report.md` | Required result; use the contents and format specified above. |
| `/app/geometry.xyz` | Required result; use the contents and format specified above. |
| `/app/result.json` | Required result; use the contents and format specified above. |
| `/app/atom_mapping.json` | Required result; use the contents and format specified above. |
