# Task: Hsp60 V72I Monomer Dynamics: Flexibility and Allosteric Communication

## Background

`environment/assets/` provides solvated Amber topologies and coordinates for wild type M_WT and mutant M_V72I; the force field and solvent are ff14SB/TIP3P. The topology includes Ala0, so mature-protein numbering is one less than system-residue numbering; system Val73/Ile73 is mature V72. The pre-production and production inputs in `md_inputs/` are provided for reference only; the example production duration is not mandatory. The total runtime budget for the submitted work is at most 12 hours (43,200 seconds).

## Task

Using both monomer systems, investigate the relationship of V72I to flexibility, dominant motions, catalytic-dyad preorganization, and communication between structural regions. Rigidification, preorganization, and allosteric rewiring are hypotheses to test; do not assume a direction or outcome. Limit conclusions according to sampling and convergence evidence; if evidence is insufficient, report `INSUFFICIENT_SAMPLING`.

## Requirements

- Environment: use the container Python on `PATH`. Preinstalled packages include NumPy. Do not install additional packages or fetch dependencies from the network.

If using HPC computing resources, consult `hpc`.

Choose the number of replicas, production length, equilibration criteria, and analysis segments, and explain the choices and limitations. Use at least two independent replicas with different velocity random seeds per variant; each replica must have at least 2 frames, and each variant must have at least 21 frames in total. This minimum data volume only ensures that the stated analyses are computable; it does not imply adequate sampling or reliable biological conclusions.

Map feature atoms using mature-protein numbering and verify against the supplied topology: γ is Cα(Val232)–Cα(Ala404)–Cα(Leu513), and δ is Asp50:Cγ–Asp397:Cγ. Report δ distance (Å) and γ angle (degrees), with per-frame values corresponding to native trajectory frames. Compute RMSF separately for each replica: first least-squares fit every frame to that replica's first frame, then calculate the overall mean-square fluctuation (`ddof=0`).

For each variant, compute DF by pooling all production frames and calculating the population variance (`ddof=0`) of all pairwise CA distances; set elements with `|i-j|<2` to 0. Calculate percent change as `100*(M_V72I-M_WT)/M_WT`; write NaN when `|M_WT|<=1e-15`. For PCA, fit all CA coordinates to the first production frame of WT replica 1, analyze only mature residues 2–522 (inclusive), center each coordinate, and use SVD to calculate the first 20 variance fractions for each variant and the top-20 RMSIP between them. The coordinate array's frame 0 must be the first production frame.

Follow the host execution profile and task run budget. Preserve native outputs, execution records and actual resource-use evidence. The total wall-clock budget is 12 hours.

### Input and deliverable details

Submit `run_manifest.json`, `native-artifacts.json`, `convergence.json`, `descriptors.csv`, `pca.json`, `df_delta.npy`, `rmsf.csv`, `conclusions.json`, and `report.md` under `final/`. `run_manifest.json` uses `hsp60-case01-run-manifest/v1` and records input `input_sha256`, the run list `runs`, and `runtime`; each run contains `variant`, positive-integer `replica`, `seed`, `production_frames`, `production_steps`, topology/restart hashes, the native CA atom-selection hash, and `artifacts`. Input hashes cover each variant's `.top`, `.rst`, and `md_inputs/minimisation_stage1.in`. Each run's artifacts must include files ending in `-analysis-coordinates.npz`, `.dcd`, `-state.csv`, and `-engine.log`, plus a restart ending in one of `-final-state.xml`, `.rst7`, or `.nc`. Fields that require integers must be JSON integers; booleans, strings, and decimals are not accepted. `runtime.elapsed_seconds_total` is a finite, nonnegative JSON number no greater than 43,200; `within_deadline` is a boolean reflecting that limit. State columns are `step,time_ps,temperature_K,density_g_ml,volume_nm3`; NPZ keys are `ca_angstrom`, `gamma_delta_angstrom`, `ca_mature_indices`, and `feature_atom_indices`. Coordinate arrays have shapes `(frame_count,526,3)` and `(frame_count,5,3)`, respectively; feature order is CA for Val232, Ala404, Leu513, then CG for Asp50 and Asp397; mature CA indices are exactly 0–525. `native-artifacts.json` uses `hsp60-case01-native-artifacts/v1`; its `files` lists the relative paths, byte counts, and checksums of all native artifacts and derived results, excluding the manifest itself.

`descriptors.csv` contains `variant,replica,seed,frame,time_ps,delta_angstrom,gamma_degrees`; `rmsf.csv` contains `variant,replica,mature_residue_index,rmsf_angstrom`. `pca.json` contains 20 `top20_variance_fraction` values per variant, a non-empty `fit_reference`, and numeric `cross_variant.top20_rmsip`. `convergence.json` has `overall` set to `INSUFFICIENT` or `DEMONSTRATED`; if claiming demonstrated convergence, list the criteria.

`conclusions.json` uses `hsp60-case01-conclusions/v1`; it contains `overall`, `claims.<name>.{status,effect,replicate_effects,ci95}`, and `evidence.{convergence_demonstrated,independent_replicas_per_variant}`. The status for the overall conclusion and each of `rigidification`, `dyad_preorganisation`, `pca_similarity`, and `allosteric_rewiring` must be one of `INSUFFICIENT_SAMPLING`, `NO_SIGNIFICANT_DIFFERENCE`, or `SUPPORTED_MUTATION_EFFECT`. Any component judgment other than insufficient sampling must provide demonstrated convergence, at least two independent replicas per variant, a finite effect, at least two finite replica effects, and an ordered finite 95% interval containing that effect; the effect must agree with the mean of the replica effects. The interval for no significant difference must include zero; the interval supporting a mutation effect must exclude zero and all replica effects must have a consistent direction. An overall conclusion other than insufficient sampling must also meet the convergence and replica requirements; an overall supported effect requires at least one supported component, and an overall no-significant-difference conclusion must not conflict with a supported component. Do not treat the minimum frame count as evidence of convergence. `report.md` must be a readable, non-empty scientific report describing methods, sampling, uncertainty, and limits of interpretation, including the limitation that the 2 μs trajectory described in the source study is not provided in this package; do not substitute that trajectory for your own evidence.

Input topologies, restart files, and example `md_inputs/` are in `environment/assets/`. Place all submitted results in `final/` and preserve the filenames, field units, mature-residue numbering, and correspondence to native evidence specified above. Base conclusions on your own auditable data; no particular direction is required.

If you use environment-provided helper scripts, follow their public interfaces and determine the settings your chosen workflow requires; do not assume a particular cluster, target, path, or private configuration. Put only successfully collected `final/` contents in a new empty output directory. Retain enough submission state to trace or inspect timed-out jobs, and do not resubmit jobs of unknown status.

For each trajectory, include `engine=openmm`, `engine=pmemd`, or `engine=pmemd.cuda` in its engine log, along with `seed=<integer>` using the actual replica seed.

## Files

Public input files:

| File path | Description |
| --- | --- |
| `environment/assets/` | Directory of supplied inputs and resources. |

| Path | Contents |
| --- | --- |
| `/app/final` | Required result; use the contents and format specified above. |
