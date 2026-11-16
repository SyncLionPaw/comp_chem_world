# Task: Compare quantum-region partitions for 5HLS–62G with a fixed protein environment

## Background

The supplied 5HLS–62G structures support a finite comparison of quantum-region partitions. The region contains the complete 42-atom ligand and optionally one complete source water; the protein remains in the fixed-charge environment.

## Task

Construct a source-traceable model and compare every allowed partition. Select a nondominated candidate under the specified static proxies and explain the trade-offs. This task does not require a quantum calculation or establish physical boundary sufficiency.

## Requirements

Preserve source coordinates and complete chemical units. Enumerate the ligand-only partition and each one-water addition whose minimum ligand-to-water heavy-atom distance is at most 4.0 Å; each water must contain OW/HW/HW. Apply limits of 50 quantum-region atoms and 210 electrons. Within both limits, minimize quantum atom count and maximize covered ligand–environment heavy-atom contact pairs within 4.0 Å and the nearest omitted environment-heavy-atom distance. Select any Pareto member and retain the full comparison table.

Provide atom-level source mapping, ligand/water connectivity and the complete fixed-charge embedding for unselected environment atoms. Account for integer formal charges using the declared residue and terminal-state convention, and use the ligand charge and multiplicity in the GJF. Check quantum-region electron/spin parity. Partial charges describe embedding sites, not formal charge; the classical environment's multiplicity field makes no total-system spin claim.

### Input and deliverable details

Inputs are under `/app/assets/`: `5hls_a_flip_H.pqr`, `model_template.gjf`, `5hls_a_flip_ligH.pdb` and `62G_optRESP.mol2`. Submit `/app/model.pdb`, `/app/design.json`, `/app/partition.json`, `/app/input.inp` and `/app/report.md`, documenting the model, source mapping, charge/spin accounting, embedding, partition comparison and decision. Source-state, numerical and output-format conventions are defined in `/app/verification.md`.

## Files

Public input files:

| File path | Description |
| --- | --- |
| `/app/assets/` | Directory of supplied inputs and resources. |
| `/app/verification.md` | Supplied data, parameters or method documentation; see the task requirements. |

| Path | Contents |
| --- | --- |
| `/app/model.pdb` | Required result; use the contents and format specified above. |
| `/app/input.inp` | Required result; use the contents and format specified above. |
| `/app/design.json` | Required result; use the contents and format specified above. |
| `/app/partition.json` | Required result; use the contents and format specified above. |
| `/app/report.md` | Required result; use the contents and format specified above. |
