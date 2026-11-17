# Finite Polarization-Record Branch Reconstruction

## Background

BaTiO3 polarization from a finite first-principles training record is a branch-valued quantity: the same structure can be assigned different polarization vectors by integer lattice row shifts. The supplied data cover 840 geometries in the published phase order (210 each of C, T, O and R), with the T and R subsets given as 210-frame records at offsets 210 and 630.

The inputs include raw per-cell polarization and proxy values for the T and R segments. The T proxy is the published Born-effective-charge linear prediction; the R proxy uses empirical ionic charge scaled by 1.8, not a Born-effective-charge tensor.

## Task

Reconstruct the branch convention for every actual recorded geometry. Raw polarizations are flattened Cartesian triples in e/Bohr^2. For each recorded row-vector cell matrix H, convert Angstrom to Bohr using 0.529177210903 and form the physical quantum Q = H/abs(det(H)); shift each raw vector by integer row combinations n@Q and select the Euclidean-nearest proxy image, retaining the nearest/second-nearest margin. Certify the neighbourhood by the 1.5 * smallest-singular-value bound on the excluded candidates.

Choose a proxy scale `proxy_scale` in [0.8, 1.2]. Reconstruct the fixed proxy scales 0.9, 1.0 and 1.1 plus your selected scale, and report the finite-record means.

## Requirements

- Use all 840 geometries and the full T/R 210-frame subsets; do not drop, subsample or reorder frames.
- Keep every integer shift, reconstructed vector, proxy residual, nearest/second-nearest margin, and the finite-record mean for every scale.
- The T proxy is the supplied published Born-effective-charge linear prediction; the R proxy is an empirical ionic charge scaled by 1.8 and is not a Born-effective-charge tensor. Do not claim a new DFT or Born-effective-charge certificate, a 0 K spontaneous polarization, infinite-grid precision, or physical equivalence of arbitrary proxy scales.
- Use a numerical tolerance of atol 1e-9 + rtol 2e-7; integer labels, counts, shifts and complete key/array denominators must be exact.

Submit the results according to the listed output convention.

The specified results can be reproduced with:

```
python3 /app/public/replay.py --inputs /app/inputs --spec /app/public/example-spec.json --out /app/final
```

## Files

| Path | Description |
| --- | --- |
| `/app/inputs/` | Cell geometries, polarization records and proxy data. |
| `/app/final/` | Submitted results and required execution evidence. |
| `/app/public/README.md` | Calculation methods and result-submission requirements. |
