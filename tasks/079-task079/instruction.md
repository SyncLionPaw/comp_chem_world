# Task: Reconcile Vertical-Excitation Statistics and Assess Basis Limits

## Background

Vertical-excitation statistics depend on the reference method, molecular geometry, state selection, and basis set. These conditions must be distinguished before differences can be attributed to a response kernel.

## Task

For the source’s auxiliary-basis and kernel-level Evert summaries, identify its SI source table and the method, reference, state count, and geometry variant represented there. Reconcile the printed ME/MAE values and use the sources to assess double-zeta basis limitations, ADMM differences, and reference-conditioned sTDA results. Keep CP2K and Turbomole reference layers distinct; molecule-level vertical excitation energies are not published.

## Requirements

- Environment: use the container Python on `PATH`. Preinstalled packages include NumPy, pandas, pillow. Do not install additional packages or fetch dependencies from the network.

- Establish each source-to-SI mapping from the tabulated methods, reference, state count, and geometry variant; do not infer one reference layer from another.
- Quantify the double-zeta limitation and the reference-conditioned sTDA@ADMM differences, identifying the methods and geometry/state variants being compared.
- Explain what the published values support about basis size and the reference dependence of sTDA, without inventing molecule-level excitation energies.

### Input and deliverable details

Use the provided PDF documentation and supporting data supplied in `/app/inputs/`; identify the relevant data independently. Put outputs under `/app/final/`:

- `reconciliation.csv`: columns `entry,printed_me,printed_mae,si_table,si_me,si_mae,match`; 12 entries. Six IDs are `admm|<abs>/<pbs>` for dzp/DZVP, dzp/TZVP, dzp/TZV2P, tzp/TZVP, tzp/TZV2P, tz2p/TZV2P. Six IDs are `kernel|<method>/<basis>` for PBE0/DZVP, PBE0/TZVP, PBE0/TZV2P, ADMM-PBE0/TZVP+tzp, sTDA@PBE0/TZVP, and sTDA@ADMM-PBE0/TZVP+tzp. Record main and supplementary documentation printed ME/MAE, the source table’s printed identifier in `si_table` (found independently), and whether their rounding is consistent.
- `provenance.json`: include the mapping rules. In `report.md`, give the independently identified SI table, method, reference, state count, and geometry variant for each source row.
- `report.md`: quantitative discussion of the submitted reconciliation and double-zeta/sTDA reference comparisons. Quote the PBE0/DZVP and sTDA@ADMM-PBE0/TZVP+tzp MEs for the first ten singlet states under each combination of reference (PBE0/TZV2P/CP2K or PBE0/def2-QZVPP/Turbomole) and geometry (EOM-CCSD optimized or optimized with the method being assessed). Independently locate all four groups; do not substitute first-state-only statistics.

Transcribe SI values within ±0.005 eV and assess source/SI agreement within ±0.011 eV for printed rounding. Use `consistent` or `rounding-consistent` for `match`. Record independently located source identifiers; report file references must resolve within `final/`.

## Files

Public input files:

| File path | Description |
| --- | --- |
| `/app/inputs/` | Directory of supplied inputs and resources. |

| Path | Contents |
| --- | --- |
| `/app/final/reconciliation.csv` | columns `entry,printed_me,printed_mae,si_table,si_me,si_mae,match` |
| `/app/final/provenance.json` | include the mapping rules |
| `/app/final/report.md` | quantitative discussion of the submitted reconciliation and double-zeta/sTDA reference comparisons |
