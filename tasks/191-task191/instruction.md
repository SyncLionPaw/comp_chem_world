# Phonon diagnostics

## Background

Phonon frequencies depend on equilibrium geometry, finite-displacement force constants and numerical resolution.

The inputs include the original sixteen-species UNEP-v1 model; `request.json` specifies the scientific scope, units and controls.

## Task

Compute zero-temperature, zero-pressure FCC Ag phonons with the full UNEP-v1 potential, along a path containing Gamma, X and L. Use at least two supercells and two displacement amplitudes, test the key-mode change target of at most 0.1 THz, and report negative imaginary frequencies and Gamma modes before and after ASR, retaining the original structure, supercell, displacement, reciprocal-coordinate conventions, raw/ASR results and sensitivity controls specified by the supplied request.

## Requirements

- Execute the required scientific calculations locally in the task environment. Preserve the actual commands, inputs, native outputs and reproducible execution records.
- Use the complete supplied UNEP-v1 potential to calculate harmonic phonons for zero-temperature, zero-pressure FCC Ag. Preserve the equilibrium structure, primitive/conventional cell transforms and fractional reciprocal-coordinate conventions; the path must include Gamma, X and L.
- Cross at least two supercell sizes with two displacement amplitudes. Compute actual displaced structures and forces for every variant, retaining full atom mappings and normalized force-constant arrays. The key-mode change target is at most 0.1 THz.
- Report raw and acoustic-sum-rule-corrected Gamma modes, signed imaginary frequencies and supercell/displacement sensitivity. Do not conceal unstable or unresolved modes by discarding negatives or presenting only corrected force constants.
- Choose the compatible force engine, displacement and phonon implementation while preserving the complete conventions in `request.json`. Preserve code, native force data, logs, controls and failed or stopped attempts. No reference answer is supplied.

- Submit the required results and evidence under `/app/results/` according to the listed output convention.

## Files

| Path | Description |
| --- | --- |
| `/app/inputs/` | Potential model and phonon calculation parameters. |
| `/app/results/` | Submitted results and required execution evidence. |
| `/app/assets/output-contract.json` | Required outputs and submission format. |
