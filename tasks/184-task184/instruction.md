# Task: Diagnose displacement information in wrapped water trajectories

## Background

The inputs are two fixed historical 300 K periodic-water trajectories, each 10 ps with 201 frames at 50 fs spacing. They contain 64 O and 128 H atoms in a 12.4 Å cubic cell (type 1 is O; type 2 is H). Coordinates are wrapped x/y/z; image flags are absent.

Follow the descriptions below for inputs and available resources; independently acquire materials where required.

## Task

Calculate frame-to-frame minimum-image displacement diagnostics and assess whether the sampled coordinates identify a unique unwrapped MSD or diffusion coefficient D.

## Requirements

- Environment: use the container Python on `PATH`; required scientific packages are preinstalled. Do not install additional packages or fetch dependencies from the network.

Align O atoms by ID and apply orthorhombic MIC to every adjacent-frame displacement. Accumulate these increments from frame 0 and report the time and mean squared displacement from frame 0 over the 64 O atoms for all 201 samples. Describe this as a minimum-image path reconstruction, not as the observed unwrapped path.

For each replica, report the maximum adjacent MIC vector norm and component, the number of wrapped coordinate components reduced by MIC, and a source-derived witness for the maximum step. Also give a sampled endpoint pair with its wrapped delta, MIC displacement, and an alternative differing by a nonzero lattice vector; show that the alternatives have the same periodic endpoint but different lengths. Use this evidence to assess D. Do not fit a diffusion coefficient to the MIC reconstruction. Report a numerical D only if the sampled data support its unique identification.

### Input and deliverable details

The fixed inputs and conditions are in environment/assets/public-inputs-v2/trajectory-manifest.json. Submit final/validation/displacement-assessment.json with 201-sample MIC-path diagnostics, wrap counts, maximum-step and lattice-alias witnesses, source hashes, D assessment, and interpretation limits. Complete output fields and shapes are in the public output schema at environment/assets/public-docs-v2/output-schema-v2.md.

## Files

Public input files:

| File path | Description |
| --- | --- |
| `/app/environment/assets/public-inputs-v2/` | Two archived water trajectories and associated input data. |
| `/app/environment/assets/public-docs-v2/` | Data definitions and analysis conventions. |

| Path | Contents |
| --- | --- |
| `/app/final` | Required result; use the contents and format specified above. |
