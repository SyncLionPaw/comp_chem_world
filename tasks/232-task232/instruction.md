# Finite-Source Paired-Energy Free-Energy Perturbation

## Background

An approximate potential and the first-principles energies it was trained on can disagree systematically across a finite set of paired configurations, and that disagreement propagates into any free-energy estimate built from them. The supplied records give four groups of 50 paired 320-atom frames for the cubic and tetragonal phases at 170 K and 194 K, with the original first-principles stdout for every frame and the corresponding archived model energies.

The original stdout contains the converged energy, cell and positions for each frame; the archived model energies are supplied as given outputs.

## Task

Parse each complete matched original stdout and preserve the frame, geometry and source identity within the 1e-4 Angstrom printed-rounding limitation. Compute delta = E_DFT - E_GAP in whole-cell eV.

Evaluate the standard model-sampled correction, -kBT * log(mean(exp(-delta/kBT))), computed stably with kB = 8.617333262145e-5 eV/K, and separately the opposite-sign printed-expression diagnostic. Normalize per atom only after exponential averaging (multiply 1000/320 for meV/atom). Report the cubic-minus-tetragonal correction at both temperatures.

Choose `block_frames` from 2, 5, 10, 25 and `stride` in 2..5.

## Requirements

- Retain the standard and opposite-sign results, all 50 ordered prefixes, all 50 reverse prefixes, the normalized importance weights, ESS and maximum weight.
- Evaluate the fixed block deletions 5 and 10 plus your selected block length, and the fixed strides 1, 2 and 5 plus your selected stride. None of these removes the full 50-frame baseline.
- Report the cubic-minus-tetragonal correction at both temperatures, in meV/atom.
- The archived model energies are given outputs, not new inference and not author-original predictions. Importance ESS is not an independent-trajectory sample size; block-deletion ranges are descriptive and not calibrated confidence intervals. These records do not establish unconditional free-energy convergence, do not reconstruct PCA/PAMM/ITRE/TI, and do not determine a physical Curie temperature or a unique explanation of the DFT/volume bias. A negative overlap or sensitivity result still completes the task when accurately computed.
- Use atol 1e-10 eV for whole-cell free-energy arithmetic, 1e-8 for meV/atom and importance weights/ESS, and 1e-9 eV/Ry for supplied and raw energies. Integers and full denominators must be exact.

Submit the results according to the listed output convention.

The specified results can be reproduced with:

```
python3 /app/public/replay.py --inputs /app/inputs --spec /app/public/example-spec.json --out /app/final
```

## Files

| Path | Description |
| --- | --- |
| `/app/inputs/` | Paired structures and energy records. |
| `/app/final/` | Submitted results and required execution evidence. |
| `/app/public/README.md` | Calculation methods and result-submission requirements. |
