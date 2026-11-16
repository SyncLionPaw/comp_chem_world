# Task: Audit COF Efficiency Claims and Cross-Table Consistency

## Background

Efficient excited-state calculations for covalent organic frameworks require a consistent assessment of accuracy and computational cost. Timings, optimization effort, and derived optical energies must support the same comparison.

## Task

Independently locate the source’s timing, optimization and optical-energy results and the supporting-information atom/basis counts, then audit the efficiency and COF-accuracy claims. Derive quantities from the printed rows where requested. Spectral-shape comparisons shown only in figures are qualitative and cannot be audited numerically.

## Requirements

- Environment: use the container Python on `PATH`. Preinstalled packages include NumPy, pandas, pillow. Do not install additional packages or fetch dependencies from the network.

- For component timings, derive component-time shares and timing speedups from the printed timings. For spectra and optimization timings, derive optimization cycles, compare per-step speedups, and convert the maximum sTDA spectrum time from seconds to minutes. For optical energies, calculate each Stokes shift as Evert − Efl for the same COF/kernel. Recompute the Evert, Ead, Efl, and Stokes MAEs as the mean absolute sTDA-minus-ADMM difference across the six COFs.
- Compare the source’s atom and basis-function counts with the corresponding supporting-information data. Use seconds for timings and eV for energies; preserve the units printed for counts and ratios.
- Report each inconsistency between derived and printed values without forcing a match or omitting it. Treat figure-only spectrum-shape comparisons as qualitative, not numeric evidence.

### Input and deliverable details

Use the provided PDF documentation and supporting data supplied in `/app/inputs/`; identify the relevant data independently. Put outputs under `/app/final/`:

- `audit.csv`: columns `claim_id,recomputed,printed,verdict,source`. Use verdicts `confirmed`, `rounding-consistent`, `documented-discrepancy`, and `not-derivable`. For transcription rows, `recomputed` and `printed` both contain the printed value. For derived rows, `printed` is the corresponding source discussion claim; for individual cycle estimates without a printed counterpart, put the derived rounded cycle count in both fields. Round cycle counts to the nearest integer. Use `confirmed` for agreement within the applicable tolerance, `rounding-consistent` for a Stokes mismatch attributable to printed rounding, and `documented-discrepancy` beyond that bound. Record the identifier of the source table you locate in every row.
- `claim_id` patterns: Component timing columns `GS_SCF` (ground-state SCF), `ES_energy_gradient` (excited-state energy and gradient), `ERI`, `DERI`, `Total`, each as `timing_<column>_<PBE0|ADMM-PBE0|sTDA@ADMM-PBE0>`, plus `timing_ERI_share_PBE0`, `timing_DERI_share_PBE0`, `timing_speedup_ADMM`, `timing_speedup_sTDA`, `timing_speedup_DERI`; Spectrum/optimization timing columns `workflow_<abs_admm|abs_stda|opt_admm|opt_admm_step|opt_stda|opt_stda_step>_<COF>`, cycles `workflow_cycles_<COF>_<ADMM|sTDA>`, and summaries `workflow_more_stda_cycles_count` (its `source` identifies any COF exceptions found by the rowwise cycle comparison), `workflow_perstep_speedup_min`, `workflow_perstep_speedup_max`, `workflow_abs_stda_max_min`; Optical-energy claims `energy_stokes_<COF>_<ADMM|sTDA>` and `energy_MAE_<Evert|Ead|Efl|stokes>`; Structure-count claims `structure_<atoms|basis>_<COF>`.
- Use COFs 05000N2, 05001N2, 15100N2, 15101N2, 20610N2, and 20611N2. The component-timing comparison covers COF 05000N2 at 4608 cores and all five timing columns for each method. The workflow comparison covers spectrum and optimization times for both kernels. The optical-energy comparison covers Evert/Ead/Efl and Stokes values.
- `report.md`: summarize quantitative comparisons from the audit rows, identify discrepancies, and state that spectrum-shape claims are qualitative. `provenance.json`: include the audit rules.

Derive shares as component/PBE0 total ×100; total-time speedups as PBE0 total/other total; DERI speedup as PBE0 DERI/ADMM-PBE0 DERI; cycles as optimization total/time per step; and per-step speedup as ADMM/sTDA. Keep the printed precision when transcribing and account for rounding when comparing derived values. Approximate comparison tolerances: Component timing transcription 0.5 s, share 1 percentage point, speedups 0.3 (total) and 1.5 (DERI), source-claim comparison 0.5; Workflow timing transcription 0.001 s, cycles 1.5, per-step speedups 0.05/0.1, spectrum maximum 0.5 min; Optical-energy Stokes derivation 0.005 eV, printed Stokes transcription exact, MAEs 0.02 eV and printed MAEs 0.005 eV; Structure counts 0.001. Record independently located source identifiers; report file references must resolve within `final/`.

For `workflow_more_stda_cycles_count`, enter the derived count in both `recomputed` and `printed`.

## Files

Public input files:

| File path | Description |
| --- | --- |
| `/app/inputs/` | Directory of supplied inputs and resources. |

| Path | Contents |
| --- | --- |
| `/app/final/audit.csv` | columns `claim_id,recomputed,printed,verdict,source` |
| `/app/final/report.md` | summarize quantitative comparisons from the audit rows, identify discrepancies, and state that spectrum-shape claims are qualitative |
