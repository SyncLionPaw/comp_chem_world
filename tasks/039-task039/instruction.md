# Task: Reanalyse native outer-sphere energy-gap evidence and its statistical limitations

## Background

This task reanalyzes the completed revision 3 (R3) outer-sphere gap study. Public materials include the source’s water/K and neutral/anion trajectories, the frozen sampling design, methods and budget records, and the R3 native-computation archive. Analyze this evidence only; do not run DFT/MD or submit HPC jobs.

## Task

Reconstruct state energies, local gaps, design estimates for the finite trajectory populations, and sensitivity to computational settings. Assess which population quantities and Marcus-model quantities are identifiable. The target is the finite trajectory population; discarding the first 2,000 frames does not establish equilibration. Distinguish archived computations from this round’s analysis, and do not report historical attempts as new computations in this round.

## Requirements

- Reconstruct energy gaps using `gap_eV = E_anion_eV − E_neutral_eV`, retaining per-state DFT and TS09 components and their original provenance. Verify the shared geometry and atom mapping, and audit each state's total charge, local charge, and convergence. Recheck at least two same-geometry two-state pairs from the anion ensembles under tighter settings, separating setting sensitivity from sample differences. Distinguish the existing helper, per-state TS09, and standard free/extrapolated energy conventions; do not treat them as equivalent or as a unique physical diabatic energy. Also distinguish the state and spin protocols used in MD, the source’s vertical calculations, and R3. `M=0` alone neither disproves a state nor establishes that it is the global minimum or a radical.
- Report the stratified design’s Horvitz–Thompson (HT) point estimates, inclusion probabilities, and limitations. The joint inclusion probability for two different frames within a stratum is zero, so the design variance cannot be unbiasedly identified. Do not use a two-point IID bootstrap or a normality test to report an unconditional population interval. An HT mean does not establish representativeness. Establish, or use counterexamples to explain, the identifiability of population means, variances, and the water/K ranking. Analyze whether conclusions reverse under defensible gap bounds or distributional assumptions; if no reliable bounds are available, leave the result unknown.
- Discuss numerical-setting error, finite-population design error, MD non-ergodicity, and Marcus-model error separately. Convergence thresholds are not a bound on total error. For the population ranking, Marcus parameters/barriers, chemical-state identity, and physical energy interpretation, evaluate each separately from the evidence and explicit assumptions, selecting and justifying an appropriate status (`supported`, `conditional`, or `not_established`) without prespecifying the scientific conclusion. Use JSON `null` for parameters unsupported by the data and explain why. Propose one valuable additional calculation for any one of the six public uncertainty topics: finite-population sampling, numerical-setting error, MD time correlation, chemical-state identity, thermodynamic transfer, or the Marcus gap distribution. Provide the objective-specific `proposal_details`, at least one missing prerequisite, two distinct possible outcomes, and an honest resource estimate. A sampling proposal must link the verified information-gain design; other topics must use their own typed proposal details. For numerical-setting work, compare both neutral and anion states against the existing base setting on frozen geometries without an existing tight replay. For chemical-state identity, propose two explicit CO₂-site initial-moment SCF variants (`co2_site_initial_moment_0_mu_B` and `co2_site_initial_moment_1_mu_B`) at the same geometry, charge and Hamiltonian, and specify spin/charge diagnostics. MD time-correlation may use one extended trajectory or independent replicas, with autocorrelation and block-sensitivity diagnostics. Count static work as geometries × states × new variants; dynamic work must report replicas and steps without inventing state-attempt counts. Use `null` and `not_estimated` for unknown cost, never zero. Propose only; do not perform additional work.

### Input and deliverable details

The required delivery fields, types, units, tolerances, provenance constraints, and replay layout are defined in `/app/assets/output-contract.json`. Write the 13 specified deliverables to `/app/final/`: `sampling_plan.json`, `decision_log.json`, `energy_gaps.csv`, `marcus.json`, `native/`, `analysis.py`, `report.md`, `source-manifest.json`, `budget-interpretation.json`, `scientific-claims.json`, `standard-electronic-gap-diagnostics.json`, `standard-electronic-gap-diagnostics.csv`, and `sampling-design-audit.json`.

`scientific-claims.json` must follow `case04-scientific-claims/v2.2`: report source-backed quantities with values, units and scopes; explicit assumptions; candidate-reported proof results; and typed claims whose statuses describe the target propositions. Use only predicates with complete proof semantics in the public contract. Each claim must cite its own proof for its target and scope; an assumption or an unrelated proof cannot support it. For the follow-up proposal, use exactly one uncertainty topic and its matching observable/calculation class; the linked relevance proof must match the same objective, and the proposal must name its missing prerequisite and both possible results. Only finite-population sampling uses the sampling design proof. Set-valued scope IDs may list their unique semicolon-separated members in any order; empty, duplicate, missing, or extra members fail. For `cross_ensemble_contrast` claims, encode `scope.id` as the ordered `<left_ensemble>-minus-<right_ensemble>` pair, joining multiple pairs with semicolons, and match the linked proof pairs exactly. The proof protocol defines normalized source-field types; unknown or not-explicit values do not establish a difference. A verified proof that a quantity is not identifiable means the target remains `not_established`; it does not make the target claim `supported`. Reported proof results must be traceable to the frozen sources and native records.

In `report.md`, use only the neutral headings `Overview`, `Evidence`, `Methods`, `Inference`, `Limitations`, and `Follow-up`, plus lines of the form `{{claim:<claim_id>}}`. Every claim must be referenced. Do not add explanatory prose, tables, HTML, comments, hidden text, or extra attachments. In explanatory fields of output JSON, use only `proof:<proof_id>` references that resolve to validated proofs; fixed source labels and schema enums are not explanations.

Inputs are provided under `/app/assets/`:

- `water_CO2/`, `water_CO2anion/`, `2K_CO2/`, and `2K_CO2anion/`, each containing `10ps.traj` and `calc.py`.
- `computegaps.py`, `methods.json`, and `OS_budget.json`.
- `revision3/tasks.json`, `revision3/sampling_plan.json`, and `r3-native-raw.tar.gz`.
- `output-contract.json`, containing the delivery and proof conventions above.

`analysis.py` is a submission you must write. The replay workspace below is not preinstalled in the image: create it from the public inputs. Place your script at `analysis/revision3/analysis.py` and the restored native records at `analysis/revision3/native/`. Copy the supplied `revision3/tasks.json` and `revision3/sampling_plan.json` to `runtimes/hpc/case04/review-v3/`, and `methods.json` to `inputs/methods.json`, relative to the replay workspace root. From that root, run `python3 analysis/revision3/analysis.py` without arguments; it must recompute `energy_gaps.csv` and `marcus.json` beside the script. Deliver the script, generated outputs and native evidence under `/app/final/` as specified above. Do not misrepresent input trajectories or historical computations as evidence generated in this round.

## Files

Public input files:

| File path | Description |
| --- | --- |
| `/app/assets/output-contract.json` | Supplied data, parameters or method documentation; see the task requirements. |
| `/app/assets/` | Directory of supplied inputs and resources. |
| `inputs/methods.json` | Supplied data, parameters or method documentation; see the task requirements. |

| Path | Contents |
| --- | --- |
| `/app/final` | Required result; use the contents and format specified above. |
