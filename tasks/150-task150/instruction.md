# Task: Audit mapped ligand geometries and stereochemical consistency in the 1XBB system

## Background

The supplied reference and candidate structures describe neutral-singlet 1XBB. Their atom correspondence is fixed by the mapping, and the STI component topology defines the covalent graph.

## Task

Assess the heavy-atom geometry differences and their sensitivity to the stated tolerance policy. Limit conclusions to this structure pair; geometry alone does not establish energy accuracy, binding credibility or transferability.

## Requirements

Cover all graph-defined heavy-atom bonds and angles and all eligible acyclic single-bond torsions with heavy substituents at both ends, excluding amide-restricted and cyclic centers. Report signed candidate-minus-reference differences, wrapping torsion differences to [−180°, 180°), and identify undefined torsions.

Provide absolute-error distributions with minima, medians, means, 90th percentiles and maxima, central-bond group comparisons, and leave-one-group-out analyses that remove only that group's torsions while retaining all other observations. Assess the passing scale interval within λ ∈ [0.25, 4], using base tolerances of 0.02 Å for bonds, 5° for angles and 20° for torsions. These define a geometric screen, not physical error bars. Preserve the source data.

### Input and deliverable details

Inputs are under `/app/assets/`: `1xbb_reference.xyz`, `1xbb_aiqm1.xyz`, `STI.cif`, `STI-mapping.json` and `context.txt`. Submit `/app/result.json` with indexed measurements and derived analyses, and `/app/report.md` with the decision and its limits. Exact numerical conventions and output formats are defined in `/app/verification.md`.

## Files

Public input files:

| File path | Description |
| --- | --- |
| `/app/assets/` | Directory of supplied inputs and resources. |
| `/app/verification.md` | Supplied data, parameters or method documentation; see the task requirements. |

| Path | Contents |
| --- | --- |
| `/app/report.md` | Required result; use the contents and format specified above. |
| `/app/result.json` | Required result; use the contents and format specified above. |
