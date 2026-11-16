# Interaction Hierarchy and Modularity of Acidic Tracts

## Background

The supplied WT and neutralized-mutant RDFs describe A0/A1/A2 correlations in the N130 condensate. The source files label uncertainty only as `error`; their meaning (SD, SEM, or something else) is unresolved. A pair PMF derived from an RDF is an effective pair potential, not a binding free energy.

## Task

Convert the tract RDFs to PMFs, identify the first-shell peak windows, and use the WT and mutant responses to assess the interaction hierarchy and modularity of A0/A1/A2. Determine which comparisons the supplied evidence actually supports.

## Requirements

Compute \(-\!RT\ln g\) at 300 K with \(R=0.00198720425864083\) kcal mol⁻¹ K⁻¹. Report the PMF transformation, selected peak and response windows, relative effects, and uncertainty. Explain that the RDF error semantics remain unresolved; do not convert the supplied `author_error` to a standard error or infer independent replicates. Justify window choice and sensitivity, rank the tracts only as far as the supplied error supports, and assess whether the mutant responses are modular. Do not present the neutralization as an isolated charge-only causal effect, and do not call a pair PMF a binding free energy.

## Files

Public input files:

| File path | Description |
| --- | --- |
| `/app/environment/assets/` | Wild-type and mutant tract measurements. |

Inputs are in `/app/environment/assets/` (`tracts_WT.csv`, `mutants_{PD,A0,A1,A2}.csv`). Write these deliverables under `/app/final/`:

- `pmf.csv`: columns `r_A,A0_kcalmol,A1_kcalmol,A2_kcalmol`; one row per RDF bin. Compute the PMF for each tract; leave a cell blank only when that tract's \(g=0\).
- `interventions.json`: `window_A` is the PD peak window (ordered finite pair, at least three bins); `PD_peaks` has `WT`, `A0mut`, `A1mut`, `A2mut`, each giving `r_A`, `height` and `author_error` from the maximum of that column of `mutants_PD.csv` inside the window. `tract_response` has `metric: "relative_peak_change"`, its own `window_A`, and `matrix[mutant][tract]`. The outer mutant keys may be `A0`, `A1`, `A2` or `A0mut`, `A1mut`, `A2mut`; the inner tract keys must be exactly `A0`, `A1`, `A2`. The mutant peak comes from the corresponding `A0mut`, `A1mut`, or `A2mut` column in `mutants_<tract>.csv`, the WT baseline from `tracts_WT.csv` column `<tract>`, and the entry is `(mutant_peak - WT_peak)/WT_peak`. Add nonempty `supported_rank` (text, or an object with a nonempty `summary`), `uncertainty_definition`, and a list `indistinguishable_contrasts`.
- `report.md`: PMF convention, windows and sensitivity, supported hierarchy and modularity, unresolved error semantics, and the pair-PMF/charge-only caveats.
- `analysis.py`: deterministic, reproducible analysis. It must accept `--input-dir` and `--output-dir`, read the five CSVs from the input directory, write the other outputs, and document methods, windows and uncertainty.

`analysis.py` must run under the container's provided Python using only its preinstalled packages (NumPy, SciPy, matplotlib). The analysis must be self-contained and require no additional packages, network access, or alternative interpreter.

Avoid NaN/Infinity and place only these four files in `/app/final/`.
