# Task: Reconstruct Li migration energy profiles from VASP outputs

## Background

Deposited VASP NEB outputs sample Li migration in Li33Ti40O96, Li41Ti40O96 and Li55Ti40O96. Only compressed OUTCAR energy records and hop-level INCAR/KPOINTS are supplied; structures and path-analysis files are absent.

## Task

Join the supplied hops into one sampled energy profile per composition. Select a consistent final-energy convention from each composition’s OUTCAR records and determine the highest sampled energy relative to its first image.

## Requirements

Use every image with an OUTCAR and preserve the supplied hop/image order. Align consecutive hops at their shared endpoint, set the first image to zero, convert relative energies to meV, and report the sampled maximum as the barrier. State the chosen energy quantity, alignment and conversion in `methods.md`. Do not infer missing structures or unsupplied path data.

Write `/app/final/results.json` with `path_profile` entries for `Li4_plus_delta`, `Li5_plus_delta` and `Li7_minus_delta`; each row has `hop`, `image` and finite numeric `energy_meV`. Include each profile maximum in `barriers_meV`. For Li7−x, use `NEB_Li7-x` as `hop`; otherwise use the image’s parent directory. Also write `/app/final/methods.md`.

For each composition, use one OUTCAR energy tag throughout: `energy(sigma→0)` or `energy without entropy`. The comparison tolerance is 8 meV per image.

## Files

Public input files:

| File path | Description |
| --- | --- |
| `/app/assets/` | Native VASP energy records and NEB settings. |

Read inputs from `/app/assets/`. Submit `/app/final/results.json` and `/app/final/methods.md`.
