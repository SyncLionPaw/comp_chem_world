# Active-Site Coordination Geometry, Asp181 Rotamer and WPD-Loop State

## Background

Analyse deposited PTP1B and WPD-loop chimera crystal geometry.

The inputs include crystal structures.

## Task

Analyse deposited PTP1B and WPD-loop chimera crystal geometry, and calculate and interpret the quantities specified below and in the public contract.

## Requirements

- Cover exactly the ten deposited structures.
- Identify VO4, WO4 or none from coordinates; for ligand-free structures use null ligand fields.
- Locate Cys215 by the catalytic motif and Asp181 by WPD.
- Report central-atom–SG and all four ligand oxygen distances to at least two decimals in Å.
- Compute Asp181 N–CA–CB–CG χ1 in (−180°,180°]; productive means |χ1|≥120°.
- WPD closed means Asp181 CA–Cys215 CA ≤10.0 Å.
- Choose highest-occupancy alternate conformers, breaking ties by label (blank/A before B).
- Do not fetch external scientific data.

- JSON submissions must use unique object member names and finite numbers. Artifact paths may resolve to files inside `/app`.
- For each ligand oxygen, report the distance from the central V/W atom; ligand_sg_distance is central V/W to Cys SG.
- Submit the required artifacts according to the listed output contract.

## Files

| Path | Description |
| --- | --- |
| `/app/inputs/` | Structures, calculation records and reference data. |
| `/app/inputs/output-contract.json` | Required outputs and submission format. |
| `/app/` | Submitted results and required execution evidence. |
