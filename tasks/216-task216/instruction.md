# Reaction-Coordinate Geometry of EVB Stationary Points for Phosphocysteine Hydrolysis

## Background

Analyse deposited EVB hydrolysis stationary-point geometries.

The deposited archive supplies coordinates, protocols and EVB inputs.

## Task

Analyse deposited EVB hydrolysis stationary-point geometries, and calculate and interpret the quantities specified below and in the public contract.

## Requirements

- Cover exactly all 12 single-frame snapshots, one per structure, and four chimeras.
- Assign RS/TS/PS to intermediate/transition_state/product with evidence.
- Report S_P, P_O_water, O_water_H and H_O_aspartate to 0.01 Å with the same geometrically assigned transferring H and nearest catalytic Asp carboxylate oxygen.
- Locate the reactive centre structurally, respecting the numbering offset and nonstandard residue names.
- Report coherent per-chimera monotonicity: S–P lengthens, P–O shortens and the proton moves from water to Asp.
- Do not fetch external scientific data.

- JSON submissions must use unique object member names and finite numbers. Artifact paths may resolve to files inside `/app`.
- Select the product-state transferring water hydrogen as specified in the output contract and track its atom serial across all three snapshots.
- Submit the required artifacts according to the listed output contract.

## Files

| Path | Description |
| --- | --- |
| `/app/inputs/` | Structures, calculation records and reference data. |
| `/app/inputs/output-contract.json` | Required outputs and submission format. |
| `/app/` | Submitted results and required execution evidence. |
