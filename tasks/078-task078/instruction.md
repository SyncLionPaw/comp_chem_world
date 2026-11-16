# Task: Recompute ADMM Errors in Adiabatic Excitation and Fluorescence Energies

## Background

Auxiliary-basis approximations can affect adiabatic excitation and fluorescence energies through changes in both electronic energies and relaxed geometries. Their errors must be assessed separately and with consistent reference definitions.

## Task

Recompute ADMM error statistics for molecule-level adiabatic excitation and fluorescence energies, independently locating the raw data and matching published error summaries. Separately transcribe the published kernel-level statistics, keeping their reference methods distinct. Use the recomputed results to assess the source’s published energy-MAE claim about triple-zeta auxiliary bases. Molecule-level vertical excitation energies are unpublished and outside this task.

## Requirements

- Environment: use the container Python on `PATH`. Preinstalled packages include NumPy, pandas, pillow. Do not install additional packages or fetch dependencies from the network.

- Derive molecule-level Ead/Efl errors as ADMM minus conventional PBE0 with the same primary basis. Recompute ME, MAE, signed MAX, and population STD (`ddof=0`) in eV from all 35 molecules for each basis pair; account for rounding in the printed molecule energies.
- The kernel-level Ead rows use EOM-CCSD references; kernel-level Efl rows use PBE0/def2-QZVPP/Turbomole references. These rows are transcriptions because the corresponding molecule-level reference energies are not published. Do not mix references or claim these rows were recomputed.
- Independently locate and quote both bounds of that published energy-MAE interval and evaluate them using the recomputed triple-zeta MAEs. State that molecule-level vertical excitation energies are unpublished and out of scope.

### Input and deliverable details

Use the provided PDF documentation and supporting data supplied in `/app/inputs/`; identify the relevant data independently. Put outputs under `/app/final/`:

- `statistics.csv`: columns `row_type,quantity,pbs,abs,method,me,mae,max,std,source_table,reference`. Include 18 `recomputed-from-raw` rows: EAD and EFL for the nine pairs `(dzp,DZVP)`, `(dzp,TZVP)`, `(dzp,TZV2P)`, `(dzp,cc-GRB-D)`, `(tzp,TZVP)`, `(tzp,TZV2P)`, `(tzp,cc-GRB-T)`, `(tz2p,TZV2P)`, `(tz2p,cc-GRB-Q)`. In `source_table`, identify the corresponding published aggregate comparator you discover, using its printed table identifier; `reference` is “ADMM − conventional PBE0 (same primary basis).” Also include seven `verified-against-SI` EAD rows and eleven EFL rows from the published SI kernel summaries, transcribing ME, MAE, MAX, and STD. EAD covers PBE0/DZVP, TZVP, TZV2P; ADMM-PBE0/TZVP+tzp and TZV2P+tzp; sTDA@PBE0/TZVP; and sTDA@ADMM-PBE0/TZVP+tzp (`reference`: EOM-CCSD). EFL has three PBE0, six ADMM-PBE0, and two sTDA entries (`reference`: Turbomole). Identify a verify-only row by `method` and its complete basis string in `abs` (for example, method `ADMM-PBE0` with basis `TZVP+tzp`); `pbs` may be blank.
- `provenance.json`: `samples` keyed `EAD|<abs>|<pbs>` or `EFL|<abs>|<pbs>`; identify the raw-data source for each group and include all 35 `{ "mol": number, "err": signed_ADMM_minus_PBE0_error }` entries. Do not include molecule-level samples for verify-only rows.
- `report.md`: summarize the triple-zeta MAE comparison and vertical-energy scope.

Per-molecule error comparisons use ±0.006 eV and aggregate comparisons ±0.02 eV. For verify-only transcription, use ±0.001 eV for non-sTDA and ±0.005 eV for sTDA values. Record independently located source identifiers; report file references must resolve within `final/`.

## Files

Public input files:

| File path | Description |
| --- | --- |
| `/app/inputs/` | Directory of supplied inputs and resources. |

| Path | Contents |
| --- | --- |
| `/app/final/statistics.csv` | columns `row_type,quantity,pbs,abs,method,me,mae,max,std,source_table,reference` |
| `/app/final/provenance.json` | `samples` keyed `EAD\|<abs>\|<pbs>` or `EFL\|<abs>\|<pbs>` |
| `/app/final/report.md` | summarize the triple-zeta MAE comparison and vertical-energy scope. |
