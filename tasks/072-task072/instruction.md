# Task: Analyse residue-correlation and distance matrices with consistent residue numbering

## Background

Inputs are the WT and V72I correlation matrices and mean-distance matrices in `/app/assets/`, together with `README_residue_numbering`. Each matrix is a headerless, whitespace-delimited 526×526 array; matrix indices start at 0 and equal mature Hsp60 residue numbers, while PDB/source-file numbering is 1 greater than mature numbering. Row 0 corresponds to mature Ala0 (PDB Ala1). The correlation matrices come from the most highly populated cluster in each respective metatrajectory. Domain ranges are: equatorial, 0–133 and 410–525; intermediate, 134–188 and 374–409; apical, 189–373.

## Task

Build residue networks from the WT and V72I monomer correlation and mean-distance data, compare shortest-path edge usage, and interpret candidate allosteric routes and changes in β13 (mature residues 375–380). Use the data to assess the meaning of the paths; disconnection in a threshold display graph does not mean that no route exists in the full contact graph, and changes in path usage do not imply that structural contacts appeared or disappeared.

## Requirements

- Environment: use the container Python on `PATH`. Preinstalled packages include matplotlib, NetworkX, NumPy, pandas, ParmEd, pillow, PROPKA, SciPy. Do not install additional packages or fetch dependencies from the network.

Use the following fixed definitions so that results for the two variants can be compared directly: undirected contact edges at distances ≤ 6.0 Å, with edge length `-log(max(abs(correlation), 1e-12))`; calculate weighted all-source shortest-path edge usage on the full graph, divide usage equally among tied shortest paths, then normalize by the maximum edge usage in the full graph. Use a display threshold of 0.30 or 0.35 and output the corresponding complete threshold edge set. Do not use the display subgraph in place of full-graph path evidence.

### Input and deliverable details

`findings.json` must strictly use `spm-allostery/v1`, with top-level keys only `schema_version,method,beta13,regional_coverage,full_graph_path`. The `method` object must contain only `contact_cutoff_angstrom,correlation_to_length,correlation_floor,graph,shortest_path_policy,usage_normalization,display_threshold`, with `contact_cutoff_angstrom` = 6.0, `correlation_to_length` = `negative_log_abs_floor`, `correlation_floor` = 1e-12, `graph` = `undirected`, `shortest_path_policy` = `equal_split_all_pairs`, `usage_normalization` = `maximum_edge_usage`, and `display_threshold` = 0.30 or 0.35 (these exact tokens record the fixed method above). The `beta13` object must contain only integer `wt_internal_display_edges,v72i_internal_display_edges` and string `interpretation`; the interpretation category must agree with the edge-count comparison (`display_usage_decreased`, `display_usage_increased`, or `display_usage_unchanged`). `regional_coverage` must contain exactly `c_terminal_equatorial_to_intermediate,intermediate_to_apical,beta13_to_apical,atp_lid_region_390_409`, and the WT display graph must provide corresponding evidence. `full_graph_path` must contain only `WT,V72I`; each entry must contain only integer `source_mature,target_mature`, an integer array `path_mature`, and numeric `shortest_distance`, providing a shortest path in the full contact graph from mature residue 517 to the apical domain.

`analysis.py` must read the four matrices and reconstruct both CSVs with `python analysis.py --assets <directory> --output <directory> --threshold <value>`, and also support the optional argument `--input-manifest <file>`. The manifest is a JSON object containing only `schema_version,base_input_sha256,challenge_input_sha256,mutation`; the version is `spm-input-challenge/v1`. `base_input_sha256` and `challenge_input_sha256` are mappings from file name to hex content checksum, for example `{"corrmat_c0_WT.dat":"…","distmat_c0_WT.dat":"…","corrmat_c0_V72I.dat":"…","distmat_c0_V72I.dat":"…"}`. `mutation` contains only `matrix,removed_contact_edge,old_distance_angstrom,new_distance_angstrom` and records the removed contact edge and its distance change. The script must recompute from the inputs specified in the manifest; it must not ignore the manifest or depend on auxiliary files in the same directory.

The report must describe network construction and path comparison, explain the contact cutoff and edge-length definition consistently with `findings.json`, and distinguish full-contact-graph evidence from the threshold display graph. CSVs must list `source,target,normalized_weight`, use mature residue numbering, include each undirected edge once with `source < target`, and retain sufficient weight precision to satisfy the numerical consistency checks.

Submit `spm_WT.csv`, `spm_V72I.csv`, `analysis.py`, `findings.json`, and `report.md` in `final/`. CSV weights must correspond to the complete threshold edge set under the specified method; replaying the script must reproduce the CSVs. The report must explain changes in β13 edge usage and their biological meaning, carefully distinguishing path usage from structural contacts.

## Files

Public input files:

| File path | Description |
| --- | --- |
| `/app/assets/` | Directory of supplied inputs and resources. |

| Path | Contents |
| --- | --- |
| `/app/final/spm_WT.csv` | WT pathway network |
| `/app/final/spm_V72I.csv` | V72I pathway network |
| `/app/final/analysis.py` | Network reconstruction code |
| `/app/final/findings.json` | Structured network findings |
| `/app/final/report.md` | Scientific interpretation |
