# Task: Conditional fate of bicyclic peroxy radicals

## Background

SI reports O2-addition and RO2+NO constants and loss estimates; MESMER XML gives two BPR ring-opening channels. Missing thermochemistry and return kinetics prevent validation of K_eq and pre-equilibrium.

Follow the descriptions below for inputs and available resources; independently acquire materials where required.

## Task

Use SI DOCX, Source Data workbook, and MESMER XML in /app/assets/ to quantify rearrangement-versus-NO competition for a bicyclic alkyl radical. Sum native channels at selected temperatures; compute densities, effective rates, competition, and pool rate. Compare species bases; state assumptions and limits.

## Requirements

- Environment: use the container Python on `PATH`; required scientific packages are preinstalled. Do not install additional packages or fetch dependencies from the network.

Cite SI Eq. (2) and its parameter statement for supplied K_eq and k_RO2+NO; state K_eq is unverified. Give temperature, pressure, O2 mole fraction, NO ppbv, number densities, and dimensionally consistent conversions. Report MR and NO rates per B-alkyl, their ratio and branching fractions, NO crossover, and the total-pool comparison. Compare the 300 K 0.03 s^-1 ceiling with native k_mer on the BPR basis; compare effective rates and k_oxy on the B-alkyl basis, preserving SI estimates and their bases.

Sensitivity spans at least two native temperatures, O2 levels, and NO levels. Use native k_mer at each temperature, label fixed-SI parameters, include an equal-temperature/pressure/NO O2 pair (main condition may be one member), and do not extrapolate SI temperature dependence. Derive finite-return MR QSSA with both sinks and the pre-equilibrium MR coefficient per total [B-alkyl]+[BPR] concentration. Declare QSSA basis as B-alkyl or total_pool via approximation.QSSA_MR_basis or expression_targets.QSSA_MR_expression; unclear targets require the former, and BPR basis is unsupported. Legacy formulas without a basis declaration default to B-alkyl. pool_MR_expression always uses total pool and must be the pre-equilibrium coefficient, not the finite-return total-pool expression. Use only + - * /, parentheses, and k_add,k_return,k_mer,k_NO,NO,O2,K_eq; formulas must be general and define K_eq=k_add/k_return. State k_return >> k_mer+k_NO*NO, disclose unknown k_return, and distinguish the per-B-alkyl SI coefficient from total-pool inverse lifetime.

### Input and deliverable details

Write final/fate_analysis.json, final/fate_sensitivity.csv, final/unit_conventions.json, and final/conclusion.md. JSON sections are conditions,parameters,SI_provenance,native_rate_records,quantities,comparisons,competition,temperature_model,approximation. All are nonempty objects except native_rate_records (array). conditions contains numeric temperature_K,pressure_Pa,x_O2,NO_ppbv. SI parameters K_eq,k_RO2_NO contain value,unit,basis=supplied_SI; K_eq.independently_verified=false. SI_provenance gives the SI path in source_file or source_asset; if both appear they must agree. Native records contain temperature_K,source_file,source_pressure_Torr,bath_gas,k_mer_per_s,channels; channels contain fromRef,toRef,rate_per_s. Source paths use assets/.

Required quantities: air_molecules_cm3,O2_molecules_cm3,NO_molecules_cm3,k_mer_per_s,K_eq_cm3_per_molecule,k_NO_cm3_per_molecule_s,q_BPR_over_Balkyl,k_NO_pseudo_per_s,k_eff_MR_per_Balkyl_s,k_eff_NO_per_Balkyl_s,MR_fraction_two_sinks,k_MR_per_equilibrated_pool_s. Required comparisons: prior_ceiling_per_BPR_s,prior_reference_species,prior_comparison_temperature_K,MR_over_prior_BPR_ceiling,k_oxy_per_Balkyl_s,MR_effective_over_oxy_Balkyl,SI_effective_MR_per_s,SI_effective_NO_per_s. competition includes MR_over_NO,MR_fraction_two_sinks,NO_crossover_ppbv, exactly two MR/NO sinks, and other_sinks_excluded; sinks may be strings or objects with a sink identifier. If supplied, number_of_sinks or sink_count must be 2; included/is_included flags must be true. Conflicting sink or exclusion declarations are invalid. Use JSON null for zero-NO ratio.

temperature_model includes K_eq,k_RO2_NO,thermodynamic_prediction=false,bath_gas_composition_recomputed=false,source_pressure_Torr. Parameters may be the string `fixed_SI` or typed records matching SI value/unit with label or basis `fixed_SI` and temperature_dependence_applied="none". approximation requires QSSA_MR_expression,pool_MR_expression,return_must_dominate_sink_sum,k_return_known,K_eq_independently_verified,explanation. QSSA_MR_basis and expression_targets may declare the QSSA basis. 

CSV contains conditions, all required quantities, source_pressure_Torr, and scenario_kind=fixed_K_eq_and_k_NO. Unit JSON contains k_B_J_per_K,N_A_per_mol,Pa_per_atm,cm3_per_m3,cm3_per_L,mole_fraction_per_ppbv,K_eq_L_per_mol,k_NO_L_per_mol_s,molar_to_molecular_factor and a verifiable molar conversion identity in `concentration_relation`, `concentration_expression`, `concentration_identity_molar`, or `molar_concentration_identity`. `concentration_expression` may instead state the ideal-gas number density; every supplied molar-conversion identity must agree, and relations may be written in either direction. Molecular units may use cm3/molecule (/s) or equivalent cm³ molecule⁻¹ and cm^3 molecule^-1 s^-1; molar units may use L/mol (/s) or L mol⁻¹ (/s). Concentration expressions may use N_A or N_A_per_mol with mol_per_L and cm3_per_L. Check any existing expression against its stated units. If molar_to_molecular_factor denotes parameter conversion, also provide molar_to_molecular_factor_for_concentrations. The conclusion states competition, species bases, conditions, fixed-SI temperature assumptions, and limitations.

## Files

Public input files:

| File path | Description |
| --- | --- |
| `/app/assets/` | Source records and reaction data for the analysis. |

| Path | Contents |
| --- | --- |
| `/app/final` | Required result; use the contents and format specified above. |
