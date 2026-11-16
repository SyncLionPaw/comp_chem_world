# Single-vacancy thermodynamics

## Background

Vacancy formation energies depend on the bulk chemical potential, relaxation route and finite-size effects.

The inputs include the original sixteen-species UNEP-v1 model; `request.json` specifies the scientific scope, units and controls.

## Task

Calculate zero-temperature, zero-pressure single-vacancy formation energies for FCC Cu and BCC W using UNEP-v1. Choose a consistent fixed-cell or variable-cell route, at least three sizes including 4x5x6 conventional cells, and control the largest-two-size difference to at most 0.01 eV while separating numerical error from model bias.

## Requirements

- Execute the required scientific calculations locally in the task environment. Preserve the actual commands, inputs, native outputs and reproducible execution records.
- Use the complete supplied UNEP-v1 potential for zero-temperature, zero-pressure FCC Cu and BCC W. Establish the bulk reference and use one declared fixed-cell or variable-cell vacancy relaxation route consistently with the chemical potential.
- Calculate at least three sizes per material, including a 4×5×6 conventional-cell supercell. Record relaxed bulk and defect structures, volumes, energies, atom counts, maximum residual forces and force tolerances. The formation-energy change between the largest two sizes must be at most 0.01 eV; retain force-threshold and pressure-sensitivity checks.
- Choose the relaxation algorithm while retaining all scientific settings, units and comparisons in `request.json`. Separate numerical changes from potential-model bias. Preserve code, inputs, native outputs and failed or stopped attempts. No reference answer is supplied.

- Submit the required results and evidence under `/app/results/` according to the listed output convention.

## Files

| Path | Description |
| --- | --- |
| `/app/inputs/` | Potential model and calculation parameters. |
| `/app/results/` | Submitted results and required execution evidence. |
| `/app/assets/output-contract.json` | Required outputs and submission format. |
