# Reaction-energy predictions and Hess-cycle consistency

## Background

Supplied source-derived predictions permit a finite comparison of Hess-cycle closure and reaction-energy accuracy.

The inputs include cycle definitions and signed coefficients, direct and indirect DFT- and UFF-geometry predictions, DFT references, and reaction-network records. They also document source structures, the intensive-model training FPS order, data splits, model provenance and build protocol.

## Task

Compare direct and indirect predictions for both DFT and UFF geometries over 12 correlated four-reaction cycles of rank 11, and distinguish closure from absolute prediction accuracy.

## Requirements

- Compare direct/indirect predictions for DFT/UFF geometries over all 12 four-reaction cycles (rank 11). Preserve exact cycle row identities and signed coefficients; correlated cycles are not independent replicates.
- Use only supplied predictions and source DFT references. Keep matched identities and disclose that all 19 indirect evaluation nodes are training members; direct training/validation have 500/100 reaction groups isolated from 27 evaluation groups, with shared species allowed. This is a finite source-derived evaluation, not a full paper reproduction.
- Compute per-model accuracy, closures, stoichiometric rank/nullity, cycle span and geometry ratios. Report geometry sufficiency as null/status `not_identifiable`; no application threshold is supplied.
- Choose a complete finite source-node potential and independently reconstruct S^T h, shifted predictions, closures and MAE. Require maximum closure difference ≤2e-7 while base/shifted MAE differ under 1e-10 absolute/relative comparison. The required boolean is true; ineffective perturbations, omitted species, duplicate keys or self-reported unsupported values fail.
- `potential_species_id` is an integer cohort ID and `potential_eV` matches its `species_potential_eV` entry within 2e-7. Follow the listed output convention for complete fields and numerical definitions; extra source cycle metadata is allowed.
- Explain closure versus accuracy and geometry-causality limits. Use supplied data locally without network.

- Submit the required results and evidence under `/app/` according to the listed output convention.

The public OUTPUT-CONTRACT.yaml explicitly lists the numeric fields inside each models.{dft,uff}.{direct,indirect} record and both geometry-comparison ratios. Cycle records may retain the original metadata in addition to the mandatory row and coefficient identities; extra source metadata is not a mismatch.

## Files

| Path | Description |
| --- | --- |
| `/app/environment/assets/` | Model predictions, reaction cycles and reference data. |
| `/app/` | Submitted results and required execution evidence. |
| `/app/environment/assets/OUTPUT-CONTRACT.yaml` | Required outputs and submission format. |
