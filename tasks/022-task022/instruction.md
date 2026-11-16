# Task: Transition-state validation and conformer selection

## Background

Use native Gaussian frequencies and conformers to audit the deposited isomer barriers.

## Task

Audit all Gaussian logs from native data; classify stationary points, group and select conformers, recompute the four site barriers, and report differences from published values.

## Requirements

- Environment: use the container Python on `PATH`; required scientific packages are preinstalled. Do not install additional packages or fetch dependencies from the network.

- Include all 196 logs. For each, report exact source path, theory level, multiplicity, atom count, formula, vibrational mode count, all imaginary frequencies, classification, and normal-termination status. Use the latest complete harmonic-frequency block; count modes and imaginary modes from it, confirm formula from final geometry and electronic state from the log. Expect 3N−6 modes for nonlinear structures and the one physical mode (3N−5) for deposited linear diatomic NO.
- Assign exactly one of `transition_state`, `minimum`, or `higher_order_saddle` from frequency evidence, not the filename. Disclose abnormal or non-normal terminations.
- Group only calculations sharing species, source directory, formula, stationary-point class, and theory level. Remove a `Conf` number suffix to identify the parent species, but keep minima and saddles separate. Include every member, including singletons and members outside the retention window; check parent/Conf naming for aliases and document any identity inconsistencies. An unnumbered record in the same directory and source batch with the same formula, method, charge/multiplicity and connectivity as a `ConfN` series is a member of that parent family, not a separate family.
- Within each family, compare Gaussian electronic-plus-zero-point energies only at the same theory level. Identify the minimum, each member's offset and whether it is within 2.0 kcal/mol, and the retained spread. Do not compare energies across levels.
- For each of four sites and both C1/C2 channels, identify minimum and saddle DFT/F12 source files. Calculate each composite barrier as `(F12 saddle − F12 minimum + DFT ZPE saddle − DFT ZPE minimum) × 627.509474063 kcal mol⁻¹ Hartree⁻¹`. Report both channels and the lower channel at each site. Compare all sites with the published profile using 0.20 kcal/mol as the agreement tolerance; report and investigate any site-specific discrepancy.

## Files

Public input files:

| File path | Description |
| --- | --- |
| `/app/assets/` | Source records and reaction data for the analysis. |

Submit under `/app/final/`:

- `saddle_audit.csv`: exactly 196 rows; columns `file,directory,level,multiplicity,n_atoms,formula,n_modes,n_imaginary,imaginary_freq_cm1,classification,normal_termination`.
- `conformer_members.csv`: all 196 members; columns `relative_path,family_id,level,zpe_au,delta_from_family_min_kcal_per_mol,within_2_kcal,selected_lowest`. Here `zpe_au` is the Gaussian sum of electronic and zero-point energies. Boolean values may use consistent true/false, yes/no, or 1/0.
- `conformer_selection.csv`: one row per family; columns `reaction_key,n_conformers_found,selected_file,energy_quantity_used,spread_within_window_kcal_per_mol`. Use the same family label for `reaction_key` and `family_id`; identify the energy quantity as the Gaussian electronic-plus-zero-point sum.
- `isomer_barriers.csv`: exactly eight site/channel rows; columns `site,channel,minimum_dft,minimum_f12,saddle_dft,saddle_f12,composite_kcal_per_mol,published_kcal_per_mol,deviation_kcal_per_mol`. Identify deposited source files; deviations may be signed or absolute. Published values may follow the SI site-lowest convention or a matching channel-resolved Source Data profile where available; compute each deviation against the reference used. The site-level comparison uses the lower computed channel.
- `validation_rules.json`: set the 2.0 kcal/mol window using `conformer_window_kcal_per_mol` or `conformer_retention.window_kcal_per_mol`. Use top-level `saddle_rule` or `saddle_point_acceptance.acceptance_rule`; saddles and minima must terminate normally, with exactly one imaginary frequency for saddles and zero for minima. Text may explain transition-state, minimum, and higher-order classifications in separate clauses; each criterion is read in its stated context, and required conditions must be stated affirmatively (negated, hedged or limiting wording does not satisfy them). Rules may be text or dicts with `acceptance_rule` and/or boolean aliases `require_normal_termination` / `normal_termination_required` and `exactly_one_imaginary_frequency` / `n_imaginary: 1`. Conflicting declarations fail.
- `audit_notes.md`: describe evidence used, name every rejected member/file and why, and document any naming aliases found.

Use the classification labels above and ensure all six outputs agree with native evidence. Asset-relative paths may optionally start with `assets/`; unique basenames may be paired with their containing directory. No quantum-chemistry calculation is required.

Inputs: the 196 Gaussian logs span `/app/assets/Figure2/`, `/app/assets/Figure4/`, `/app/assets/RONO2/`, and `/app/assets/Toluene-iBPR-rearrangment/`; the Source Data workbook and SI DOCX are under `/app/assets/`; twelve Molpro F12 outputs for the site minima and C1/C2 saddles are under `/app/assets/Figure4/Toluene/`. Use the asset tree for exact filenames.
