# Task: Accuracy of Four Response Kernels Relative to EOM-CCSD

## Background

Response kernels differ in the balance they offer between computational cost and geometric and energetic accuracy. Meaningful comparisons require consistent reference methods and clearly distinguished physical quantities.

## Task

Compare PBE0/TZVP, ADMM-PBE0/TZVP+tzp, sTDA@PBE0/TZVP, and sTDA@ADMM-PBE0/TZVP+tzp. Recompute bond, angle, and dihedral errors against EOM-CCSD from molecule-level SI data and compare them with the published aggregate statistics. Verify the published energy statistics from their SI sources and compare Evert with the source’s kernel-level energy summary.

## Requirements

- Environment: use the container Python on `PATH`. Preinstalled packages include NumPy, pandas, pillow. Do not install additional packages or fetch dependencies from the network.

- For geometry rows, use kernel geometry minus EOM-CCSD. Recompute ME, MAE, signed MAX (greatest absolute error), and population STD (`ddof=0`); bond-length errors are in pm and angle/dihedral errors in degrees. Preserve the molecule-level labels and explain the direction and magnitude of dihedral-error differences among all four kernels.
- Keep the references distinct: independently establish the reference method, optimized geometry, and state selection for each energy quantity. The Evert comparison concerns the first state at the corresponding optimized geometry; do not mix it with a multi-state aggregate. Energy rows are printed-value checks because molecule-level reference energies are not available; do not invent per-molecule energies.
- Independently find and interpret the M14 parameter exception, distinguishing default aEX=0.2 from the aEX=0.25 parameter exception when discussing whether a geometry is a normal minimum.

### Input and deliverable details

Use the provided PDF documentation and supporting data supplied in `/app/inputs/`; identify the relevant data independently. Put outputs under `/app/final/`:

- `statistics.csv`: columns `row_type,kernel,basis,quantity,me,mae,max,std,source_table`. Include 12 geometry rows: four kernels × `bond`, `angle`, `dihedral`, with `row_type=recomputed-from-raw`; identify the raw-data source and reference. Also include 18 energy rows with `row_type=verified-against-SI`: six combinations (PBE0/DZVP, PBE0/TZVP, PBE0/TZV2P, ADMM-PBE0/TZVP+tzp, sTDA@PBE0/TZVP, sTDA@ADMM-PBE0/TZVP+tzp) × Evert/Ead/Efl. Transcribe ME/MAE/STD; `max` may be blank.
- `provenance.json`: `samples` keyed `<kernel>|<basis>|<quantity>`; each geometry row has all `{ "mol": number, "label": atom_label, "err": signed_error }` entries. Atom-label case, whitespace and bond separators are normalized (`C-H`, `c–h` and `c h` are equivalent); preserve atom order and any atom indices. For unlabelled dihedral rows, set `label` to the empty string. Keep repeated labels as separate samples. Do not supply molecule-level samples for energy rows.
- `report.md`: compare the four kernels, report each kernel’s dihedral ME and quantify their differences using the submitted rows, and explain the M14 parameter exception.

For the four TZVP geometry comparisons, independently locate the MOLOPT/TZVP data for each method and its matching aggregate statistics. In `source_table`, identify the raw-data source for geometry rows and the published SI aggregate source for energy rows, using the table identifier you find. Use ±0.006 for molecule-level geometry entries, ±0.02 for geometry aggregates, and ±0.005 eV for energy transcriptions. Molecular identifiers are positive integers; an `M` prefix and leading zeros are formatting only, and integer-valued numeric forms are equivalent. Method/basis names ignore case and whitespace; `sTDA@ADMM` is equivalent to `sTDA@ADMM-PBE0`. Source citations may use `Table`, `T`, or `表`, with an optional `S` before the printed number, or a bare table identifier; sentence-ending punctuation is ignored. Quote each of the four dihedral means separately in the report; one numerical observation cannot stand for multiple methods. Record independently located source identifiers; report file references must resolve within `final/`.

## Files

Public input files:

| File path | Description |
| --- | --- |
| `/app/inputs/` | Directory of supplied inputs and resources. |

| Path | Contents |
| --- | --- |
| `/app/final/statistics.csv` | columns `row_type,kernel,basis,quantity,me,mae,max,std,source_table` |
| `/app/final/provenance.json` | `samples` keyed `<kernel>\|<basis>\|<quantity>` |
| `/app/final/report.md` | Use the fields, units and contents specified above. |
