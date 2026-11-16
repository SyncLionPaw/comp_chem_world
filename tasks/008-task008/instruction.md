# Hydrogen coverage stability and conditional surface softening

## Background

Native slab records cover 0%, 50% and 100% H for CoCrNi, CoNiV and SS316L. Partial geometry matches do not prove a shared chemical/magnetic parent. Matched bulk/H₂/ZPE references and an actual H reservoir are unavailable.

## Task

Derive the zero-temperature lower envelope for the three coverages and conditional reservoir thresholds for stepwise and total surface-excess softening. Separate record-level comparisons from common-parent causal claims.

## Requirements

- Check record identities and areas. Use sigma-to-zero energies primarily; retain without-entropy and TOTEN sensitivities, and separate native from sourced −0.06 J/m² random-50% correction scenarios.
- Derive the analytic lower envelope over all real chemical-potential offsets, including coexistence ties and zero-curvature degeneracy. Derive conditions for each adjacent step, both steps, and total 0→100% excess to decrease; equality is a tie.
- Normalize by both slab faces. Propagate the native 2e-8 eV display-rounding bound on curvature separately from the conditional correction. Do not infer continuous-coverage equilibrium, finite-temperature entropy or a unique H–H interaction.
- Show affine-reference invariance using a 7.3 eV constant and −0.123 eV/H shifts, reporting residuals. The 401-point −0.2…0.2 eV grid is for display only; the analytic domain is unrestricted.
- Interpret stability/softening conditionally: these records do not identify absolute surface/free energies, an actual reservoir or a confirmed common magnetic parent. Execute the local analysis and preserve reproducible source/results.
- Use `/app/assets/native_slab_slice.csv`, nine native excerpts, matching geometries and existing `task08_task_spec.json` (`output_contract`). Create `/app/final/` with the specified contrast, surface-excess, analytic-hull, threshold, reference-identifiability and interpretation outputs, plus executable calculation source and run metadata. Preserve required filenames/serialization and source/output records; do not replace analysis with transcription.

## Files

Public input files:

| File path | Description |
| --- | --- |
| `/app/assets/` | Alloy data, source records and task conventions. |

Inputs and full output contract are under `/app/assets/`; required results are in `/app/final/`.
