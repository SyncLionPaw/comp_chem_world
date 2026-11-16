# Task: Structural Protonation Assessment of the Hsp60 Catalytic Dyad

## Background

`/app/assets/` provides Amber topologies and coordinates for apo single-ring S_V72I, ATP-bound double-ring D_V72I, and football F_V72I. Asp50 and Asp397 are both deprotonated in the inputs. The topologies have no chain identifiers; identify the first complete Hsp60 monomer chain by its repeated sequence. The mature-to-system numbering map varies by system: mature Asp50/Asp397 correspond to system residues 51/398 in S and 50/397 in D and F. The physiological pH range of interest is 7.0–7.4.

## Task

Estimate pKa values for the structural environments of Asp50 and Asp397 in S_V72I, D_V72I, and F_V72I; analyze possible differences due to ATP, Mg²⁺, K⁺, and the pocket environment; and recommend which dyad protonation states should receive priority in follow-up simulations. Choose and explain ligand/metal handling and the site-selection strategy. A single-site pKa is not a dyad microscopic-state probability; do not combine the two independent estimates into joint populations. Conclusions must reflect the limitations of the prediction method and structural models; do not assume numerical or biological outcomes.

## Requirements

- Environment: use the container Python on `PATH`. Preinstalled packages include NumPy, ParmEd, PROPKA, SciPy. Do not install additional packages or fetch dependencies from the network.

Use the first complete Hsp60 protein chain derived from the supplied topology and coordinates as chain A. Locate target residues using each system's numbering map. For D and F, also document the retention or exclusion strategy and chemical rationale for active-site ATP, Mg, and K, and map listed cofactors back to the input topology and coordinates. For a consistent structural site selection, use a 12.0 Å selection radius from the CG, OD1, and OD2 atoms of Asp50/Asp397 and retain native ATP/Mg/K within that range. Other justified selections may be submitted with complete evidence but will undergo expert review.

The benchmark method is PROPKA 3.5.1. Run predictions on the chain A structures actually submitted, retaining each system's raw `.pka` file, complete tool version, actual command, and exit code; external reference values or example results are not substitutes. Other PROPKA 3.x versions or predictors must include corresponding raw outputs and complete provenance evidence, and may require expert review. State that PROPKA does not provide calibrated confidence intervals and that point estimates must not be interpreted as such intervals.

### Input and deliverable details

Submit `pka.json`, `protonation_plan.json`, `report.md`, and the following evidence under `final/`: under `evidence/structures/`, the files `S_V72I_chainA_site.pdb`, `D_V72I_chainA_site.pdb`, `F_V72I_chainA_site.pdb`, and `selection_manifest.json`; `evidence/provenance.json`; and the raw `.pka` files for all three systems under `evidence/propka/`. PDB files must retain the complete first protein chain and every included complete cofactor residue, and use chain A and native system residue numbering, keeping the native residue and atom names (including the Amber histidine names `HID`/`HIE`/`HIP` and the ion names), because PROPKA's protonation model depends on them.

`pka.json` has `schema_version` `case02-pka/v1` and `physiological_ph_range` `[7.0,7.4]`; `method` records `name`, `version`, and non-empty `uncertainty`. `systems` contains exactly `S_V72I`, `D_V72I`, and `F_V72I`. Each system has keys `Asp50` and `Asp397`, each recording numeric `pka`, integer `mature_residue`, and `system_residue`; at the same level include `input_structure_sha256`, `source_topology_sha256`, `source_coordinates_sha256`, and `evidence` paths relative to `final/`. System residue numbers are 51/398 for S and 50/397 for D and F. Use a full PROPKA version string, such as `propka3 3.5.1`; JSON numeric values must be numbers, not strings.

`protonation_plan.json` has `schema_version` `case02-protonation-plan/v1`; `physiological_pH` contains `minimum: 7.0`, `maximum: 7.4`, and `reference: 7.2`. `state_names` defines: `AspAsp` = `Asp50− / Asp397−`, `AshAsp` = `Asp50H / Asp397−`, `AspAsh` = `Asp50− / Asp397H`, and `AshAsh` = `Asp50H / Asp397H`. `systems` contains exactly the three systems; each includes `predicted_pka` consistent with the pKa results and `assessed_states` keyed by the four state names. Each state object has `decision` (`recommended`, `sensitivity`, or `low_priority`) and a non-empty `rationale`. `recommended_states` is a non-empty array of state names and must exactly match the states marked `recommended`. `coupling_caveat` is non-empty and explains that independent site estimates do not represent microscopic-state probabilities for a coupled dyad.

`selection_manifest.json` uses `schema: case02-propka-inputs/v1`; its top-level `systems` has exactly the three system names as keys. Each system's `input_topology` and `input_coordinates` include the actual input content checksum in `sha256`. `selection` contains integer `protein_residue_count` (526), `pdb_chain` (`A`), integer `protein_atom_count`, `retained_atom_count`, non-empty `ligand_policy`, numeric `cofactor_radius_angstrom`, and a `cofactor_residues` array. Each cofactor object has `name`, integer `topology_residue_number`, `nearest_dyad_distance_angstrom`, and boolean `included`; the distance is the minimum between any cofactor atom and any CG/OD1/OD2 atom of either target Asp, recorded to 4 decimal places. `target_residues` is indexed by string keys `"50"` and `"397"`; each entry has `system_residue_number`, `topology_residue_index_1based`, `residue_name` (`ASP`), `cg_coordinate_angstrom`, and an `atoms` object containing exactly `CG`, `OD1`, and `OD2`. Each atom object has `topology_atom_index_1based`, `coordinate_angstrom` (a three-number array at original precision), and `bonds` (sorted by name). `structure` contains the PDB basename `path` and its actual `sha256`. Coordinates in the complete protein and included complete cofactors in PDB must correspond to the inputs; do not submit only a pocket fragment. PDB coordinate precision is 0.001 Å.

`provenance.json` records `case_id: case-02-dyad-protonation`, `propka_version` consistent with `pka.json`, the actual `selection_manifest_sha256`, and a `systems` object keyed by system name. Each system contains `command` (the actual argument array), integer `returncode` (0 on success), `pdb: {path, sha256}`, `source_topology_sha256`, `source_coordinates_sha256`, `parsed_pka: {Asp50, Asp397}`, and `pka_output: {path, sha256}`. The PROPKA calculation command uses `propka3 --log-level INFO`, with the PDB as the final argument. `report.md` should explain in readable prose the pH range, estimate uncertainty, ATP/Mg/K handling, four states, all six pKa values, structural selection, numbering, and interpretive limitations, consistent with the structured data and actual evidence.

Write only results and evidence to the specified `final/` paths. Use the submitted native topologies, coordinates, PDB files, selection manifest, and PROPKA output to make chain selection, cofactor handling, atom mapping, and pKa parsing reproducible to other researchers; do not claim to have run commands or used methods that were not actually run or used.

## Files

Public input files:

| File path | Description |
| --- | --- |
| `/app/assets/` | Directory of supplied inputs and resources. |

| Path | Contents |
| --- | --- |
| `/app/final` | Required result; use the contents and format specified above. |
