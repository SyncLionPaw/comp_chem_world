# Task: Run the existing water committee on fresh MLMD trajectories

## Background

Two geometry-only starting configurations and four fixed baseline DeepMD checkpoints are supplied.

Follow the descriptions below for inputs and available resources; independently acquire materials where required.

## Task

Run two fresh 20,000-step NVT trajectories of periodic 192-atom water at 300 K. Model 0 supplies the MD force; models 1–3 are used only for the committee-deviation diagnostic. Initialize velocities with seeds 701 and 1701, respectively. Do not substitute other model checkpoints.

## Requirements

- Environment: use the container Python on `PATH`; required scientific packages are preinstalled. Do not install additional packages or fetch dependencies from the network.

If using HPC, follow the `ikkem-slurm` workflow: probe the authorized target, submit, wait for a terminal state, collect native outputs, and validate the scientific result.

Use the supplied LAMMPS template, with 0.5 fs steps and thermo, dump, and deviation output every 100 steps. Each run covers steps 0–20,000 and produces 201 aligned samples for 192 atoms in the 12.4 Å periodic cube. Keep atom-ID/type mapping stable and positions, forces, thermo, and deviations finite. The deviation file has a max_devi_f header and seven columns per sample: step plus six nonnegative values. Dump coordinates are wrapped and have no image flags; do not infer unwrapped transport. Preserve the native LAMMPS log.

Render the template by replacing only its data, four model, and plugin path slots and the seed. Keep all other settings unchanged. Use four distinct absolute model paths in the assigned member order and one absolute plugin path. Paths must be single-line, contain no template tokens or LAMMPS command separators, and use only A–Z, a–z, digits, period, underscore, plus, colon, slash, and hyphen; do not use whitespace, //, . or .. path components.

For each run, render-manifest.json must contain start_geometry_id (string 0000 for replica-0 and 0010 for replica-1), start_geometry_sha256, lammps_input_sha256, data_sha256, model_sha256_by_member (four lowercase checksums in member order), seed (integer 701 or 1701), and runtime_bindings. All content checksum fields are lowercase. These three hashes identify the exact geometry include, rendered input, and start.data bytes. runtime_bindings.start_data contains path and sha256; runtime_bindings.models contains four ordered objects with member_index, path, and sha256 matching the paths in lammps.in and the pinned model hashes. execution-manifest.json contains schema task181-app-execution-manifest/v1 and a replicas array with two ordered objects: {"replica":"replica-0","files":{...}} and {"replica":"replica-1","files":{...}}. Each files object maps every run file except render-manifest.json to its lowercase hexadecimal checksum. These candidate-side manifests do not authenticate execution; candidate-reported host or scheduler details are not required.

**Execution setup.** Follow the host execution profile and use its supported software environment.

### Input and deliverable details

Starting geometries, four checkpoints, and the LAMMPS template are in environment/assets/v2/fresh-run/. Convert each geometry include to LAMMPS atomic data in source row order: O/H types 1/2, masses 15.999/1.008, 192 atoms, two types, and bounds 0.0 12.4 on all axes, written as 0.0 12.4 xlo xhi, 0.0 12.4 ylo yhi, and 0.0 12.4 zlo zhi. Use the Atoms # atomic section and coordinates within 5.1e-12 Å of the source. Set DEEPMD_LAMMPS_PLUGIN to the site plugin path and run LAMMPS from each replica directory.

Submit runs/task181-mlmd-v2/replica-{0,1}/{lammps.in,start.data,render-manifest.json,log.lammps,dump.lammpstrj,model_devi.out} and runs/task181-mlmd-v2/execution-manifest.json.

## Files

Public input files:

| File path | Description |
| --- | --- |
| `/app/environment/assets/v2/` | Two starting structures, four DeepMD checkpoints and LAMMPS template. |

| Path | Contents |
| --- | --- |
| `/app/runs/task181-mlmd-v2` | Required result; use the contents and format specified above. |
