# Task: ADMM Auxiliary-Basis Convergence for Excited-State Geometries

## Background

The accuracy of excited-state geometries can depend on the auxiliary basis used in ADMM. Assessing this dependence requires consistent comparisons of bond lengths, bond angles, and dihedral angles across basis combinations.

## Task

Locate the molecule-level geometry data in the supplied sources and independently derive ADMM-minus-conventional-PBE0 geometry errors using the same primary basis. Compare ground- and excited-state bond lengths and angles, and excited-state dihedrals, with the corresponding published summaries. Independently locate and establish the dihedral definitions.

## Requirements

- Environment: use the container Python on `PATH`. Preinstalled packages include NumPy, pandas, pillow. Do not install additional packages or fetch dependencies from the network.

- For every molecule-level set, recompute ME, MAE, signed MAX (the error with greatest absolute magnitude), and population STD (`ddof=0`). Bond-length errors are in pm; angle and dihedral errors are in degrees. A positive bond-length ME means longer ADMM bonds; a negative angle ME means narrower angles.
- Exclude eclipsed excited-state geometries for M8 and M35. Use C2v-constrained references for M10 and M30, with the B1 state for M30.
- Compare ES bond-length MAE across dzp, tzp, and tz2p using the same primary basis, and use the submitted data to support a quantitative convergence discussion.
- Preserve each published molecule/label/error. If printed rounding leaves a sign ambiguous for tied extrema, describe the ambiguity rather than changing the error definition. Report any discrepancy between aggregate SI values and their per-molecule rows.

### Input and deliverable details

Use the provided PDF documentation and supporting data supplied in `/app/inputs/`; identify the relevant data independently. Put outputs under `/app/final/`:

- `statistics.csv`: columns `quantity,variant,pbs,abs,me,mae,max,std`; 45 combinations. `quantity` is `bond_length`, `angle`, or `dihedral`; bond length/angle variants are GS and ES, dihedral is ES. Basis pairs: `(dzp,DZVP)`, `(dzp,TZVP)`, `(dzp,TZV2P)`, `(dzp,cc-GRB-D)`, `(tzp,TZVP)`, `(tzp,TZV2P)`, `(tzp,cc-GRB-T)`, `(tz2p,TZV2P)`, `(tz2p,cc-GRB-Q)`.
- `report.md`: convergence comparison, including ES bond MAEs for dzp/tzp/tz2p at common primary basis TZV2P, and explanation of aggregate/source-row differences.
- `provenance.json`: `samples` keyed `<quantity>|<abs>|<pbs>|<variant>`, each with `{ "mol": number, "label": lowercase SI atom label, "err": signed_error }`; labels omit ∠/η prefixes (for example `c br`, `br c br`, `s c s c br`). Identify the source of the raw data for each sample group. For unlabelled dihedral rows, use an empty label; retain repeated labels as separate samples. Preserve the full molecule-level sets; per-item errors are compared at ±0.006 in the stated unit and aggregates at ±0.03.

Record source identifiers you discover; no particular page format is required. File references in the report must resolve within `final/`.

## Files

Public input files:

| File path | Description |
| --- | --- |
| `/app/inputs/` | Directory of supplied inputs and resources. |

| Path | Contents |
| --- | --- |
| `/app/final/statistics.csv` | columns `quantity,variant,pbs,abs,me,mae,max,std` |
| `/app/final/report.md` | Use the fields, units and contents specified above. |
| `/app/final/provenance.json` | `samples` keyed `<quantity>\|<abs>\|<pbs>\|<variant>`, each with `{ "mol": number, "label": lowercase SI atom label, "err": signed_error }` |
