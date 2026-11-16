# Paired QE/GAP Energy Profiles and Blocked Correction

## Background

A short-range machine-learned potential (GAP) and the first-principles method it was trained on (QE) can disagree along a paired reaction path. Two complete 31-frame QE paths are supplied together with the corresponding GAP curves for the same printed geometries, so the disagreement can be quantified per frame on the exact same structures.

The inputs include printed 40-atom geometries, original QE stdout with converged energies, cells, positions and complete force blocks, and author-original GAP energy curves. Archived native model predictions for the same geometries are supplied as given outputs.

## Task

Parse every frame's final converged SCF energy, printed cell/positions and complete 40-atom force block from the original QE stdout. Use both complete 31-frame paths and all 62 paired geometries, converting 1 Ry = 13.605693122994 eV and subtracting each path's frame 0 to obtain meV per 40-atom cell.

Train a shared residual correction y = QErelative - GAPrelative on both paths using polynomial terms lambda^1..lambda^degree with no intercept, holding out frame indices 10..15 of both paths simultaneously (12 held out, 50 training frames). Use SVD factors s/(s^2 + relative_ridge * smax^2). Choose `degree` in 1..4 and `relative_ridge` in [0, 1].

## Requirements

- Evaluate all degrees 1..4 and ridge values 0, 1e-6 and 0.01, plus your selected pair. A poor held-out prediction is a valid measured result and must be reported as measured.
- Keep both supplied curves and all disagreements; report all 62 predictions and residuals, coefficients, and training and fixed held-out RMS values. A sampled path maximum is not a transition state.
- The printed-coordinate comparison carries a <= 1e-4 Angstrom matching limitation, which must be retained.
- The named curves are given outputs, not new inference, and are not interchangeable. This is algebraic calibration of observed curves, not SOP training, new DFT at refined points, a full saddle search, or a unique electrostatic attribution.
- Use a numerical tolerance of atol 2e-7 + rtol 2e-8; use atol 1e-9 eV/Ry for raw source energies; integers and complete denominators must be exact.

Submit the results according to the listed output convention.

The specified results can be reproduced with:

```
python3 /app/public/replay.py --inputs /app/inputs --spec /app/public/example-spec.json --out /app/final
```

## Files

| Path | Description |
| --- | --- |
| `/app/inputs/` | Paired path structures, energies and original calculation records. |
| `/app/final/` | Submitted results and required execution evidence. |
| `/app/public/README.md` | Calculation methods and result-submission requirements. |
