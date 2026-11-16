# SNAr reaction and transition-state evidence audit

## Background

The supplied calculations describe two SNAr reaction contexts. Distinguish supported local structural and thermochemical conclusions from an established reaction pathway.

## Task

Audit all eight Gaussian logs and their eight GoodVibes reports, then diagnose the two native jobs. Interpret stationary-point and reactive-mode evidence, calculate three balanced candidate-state free-energy differences, and assess local mechanism, path connectivity, formal barriers and global versus model-conditional rate-determining steps.

Use only the supplied records. Do not run quantum-chemistry or scheduler jobs or invent missing evidence.

## Requirements

- Distinguish prior optimization from frequency-link convergence. Report failed force/displacement criteria and every negative frequency. Zero negative frequencies alone do not establish stationarity; a conservative unresolved interpretation needs incomplete source evidence.
- Identify the reactive carbon, nucleophile and leaving-group atoms in every Gaussian record, including separated species and zero-negative-mode intermediates. Report available C–Nu/C–X distances. For a complete mapped negative mode, project relative atomic displacements onto the corresponding bond unit vectors; a common reversal of both projections is equivalent. The printed normal coordinates have no stated displacement unit.
- Join Gaussian and GoodVibes records by source evidence. Preserve the reported temperature, concentration, QS method, cutoff and scale. For each complete complex with exactly one negative frequency, calculate qh-G(candidate) − qh-G(separated optimized substrate) − qh-G(separated optimized nucleophile), with coefficients +1, −1, −1 in the same context and conditions. These give three required comparisons; additional element- and charge-balanced comparisons cannot replace them.
- Separate local evidence from a validated path, formal barrier and global RDS. State any model-conditional RDS independently. Distinguish native engine outcome and failed module from scheduler state, and assess whether MPI/OpenFabrics causality is established. Native near-zero frequencies mean |ν| < 1 cm⁻¹.

## Files

Public input files:

| File path | Description |
| --- | --- |
| `/app/assets/` | Published records, benchmark data and task-specific inputs. |

```text
/app/assets/                  supplied context, calculation and native-job records
/app/final/
  artifact_audit.jsonl        eight Gaussian + two native-job assessments
  thermochemistry.csv        eight source rows + at least three differences
  mechanism.csv              one assessment per context
```

Use the following compact output structure; optional notes or analysis code need not duplicate the observations.

**`artifact_audit.jsonl`** — one JSON object per record. Gaussian objects contain:

```text
source_file
prior_geometry_optimization:
  optimization_completed, stationary_point_observed, normal_termination (booleans)
  failed_criteria (list)
frequency_link_optimization_completed, frequency_link_stationary_point_observed (booleans)
frequency_level_force_criteria: {failed_criteria: [...]}
negative_modes: [{frequency_cm-1: ...}, ...]
stationary_point_interpretation
thermochemistry_join: {final_scf_E_hartree: ..., gaussian_zpe_hartree: ...}
reactive_coordinate_projection:
  context_id
  central_carbon_atom_index_1based, nucleophile_atom_index_1based
  leaving_group_atom_index_1based
  C_Nu_distance_angstrom, C_X_distance_angstrom
  projected_C_Nu_change_raw, projected_C_X_change_raw
```

Use source criterion names `Maximum Force`, `RMS Force`, `Maximum Displacement`, `RMS Displacement`; an empty list means all pass. Stationary labels are `optimized minimum candidate`, `first order saddle candidate`, `higher order saddle candidate`, or `unresolved`. Only absent roles or unavailable distances/projections may be omitted or null. `projection` is also accepted as the projection-object name; the source-energy join makes a repeated GoodVibes identifier unnecessary.

Native objects contain `job_id`, `engine_termination` and the applicable observations:

```text
Successful job:
  frequencies_count, negative_frequency_count, frequency_zero_or_near_zero_count
  geometry_converged (boolean), thermochemistry_temperature_K
  final_gibbs_hartree, coordinate_atom_count
Failed job:
  execution_state, scheduler_state, scheduler_exit_code
  mpi_openfabrics_causality: {established: <boolean>, reason: <explanation>}
```

A unique job-qualified source locator can replace `job_id`. Engine states may be `normal` or `failed_<module>`, or an object containing `status`, `failed_module`, `reason`; a plain `failed` status needs a module. Explicit identities and module declarations must agree.

**`thermochemistry.csv`** — `record_type` is `source` or `candidate_difference`:

```csv
record_type,source_file,source_ids,coefficients,identity_status,temperature_K,concentration_mol_L,qh_G_T_hartree,scale_factor,qs_treatment,frequency_cutoff_cm-1,candidate_delta_g_kcal_mol
```

Source rows give qh-G(T) and conditions; difference rows identify paired sources/coefficients, an evidence-bounded identity assessment and ΔG in kcal/mol. Put the QS method name in `qs_treatment`, with any commentary separated by a semicolon, colon or parentheses. A Gaussian identifier may identify its uniquely paired GoodVibes report.

**`mechanism.csv`**:

```csv
context_id,claim_scope,reactive_site,identity_status,mechanism,mechanism_evidence,rate_determining_step,model_conditional_RDS,barrier_status,path_connectivity
```

Use `claim_scope: local_context`. A supported site uses `C<i>/Nu<j>/F<k>` or `C<i>/Nu<j>/Cl<k>` and identity `supported_by_atom_inventory_and_reactive_geometry`; an ambiguous site is blank with identity `ambiguous` and mechanism `unresolved`.

Report the chemical judgments once, using these compact propositions rather than free-text substitutes:

```text
mechanism: SNAr_candidate | stepwise_SNAr_candidate | unresolved
mechanism_evidence (JSON in the CSV cell):
  {"local_steps": {"<Gaussian source>": "addition_like|elimination_like"},
   "intermediate_candidates": ["<Gaussian source>"]}
model_conditional_RDS (JSON in the CSV cell):
  {"model": "none|irreversible_equal_prefactors_unit_activity",
   "step": "unresolved|addition|elimination"}
```

`local_steps` covers every complete one-negative-mode complex in that context, citing Gaussian filenames or unambiguous stems. For the supplied opposite-sign C–Nu/C–X projections, the larger absolute component defines an addition-like (C–Nu) or elimination-like (C–X) **local candidate**, independent of the mode's global sign. List complete zero-negative-mode records as intermediate candidates; this does not certify their stability or connectivity. A stepwise candidate needs both local roles and an intermediate candidate; `SNAr_candidate` or unresolved full mechanism remains a valid conservative assessment.

With `model:none`, the conditional step is unresolved. The other model assumes hypothetical irreversible serial addition/elimination, equal kinetic prefactors and unit reactant activities; its observable is inverse mean completion time, `k_add*k_elim/(k_add+k_elim)`. Compare G(addition candidate) − G(separated reactants) with G(elimination candidate) − G(intermediate candidate); the larger local TST difference gives the conditional slow step (unresolved within 0.01 kcal/mol). This model needs both local roles and an intermediate candidate, and establishes neither the real global RDS nor a connected path. No additional energy table is needed. Keep the global RDS and unvalidated barrier/path status separate; unresolved status labels may use `unresolved`, `unknown`, `not established`, `unassigned`, or barrier/path `unvalidated`. Optional discussion belongs in `notes.md`; it is not a substitute for these chemical propositions.

Retain source-printed energy/frequency precision; give distances, projections and ΔG to at least two decimal places. Atom indices are 1-based and optional mode indices zero-based. Use finite numbers, unique JSON keys/CSV headings, and booleans for Boolean observations. Numerically equal integers are equivalent. Sources may be exact filenames, unambiguous stems or context IDs. Paired source/coefficient lists may be JSON arrays (including quoted CSV cells) or comma-/semicolon-separated strings; coefficients may be finite decimal numbers or numeric strings. Source order is immaterial when pairing is preserved; scaled comparisons are additional results. Full coordinates/vectors, line locators, repeated quantities and separate limitation inventories are unnecessary; supplied scientific observations must remain consistent.
