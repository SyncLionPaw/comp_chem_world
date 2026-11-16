# Vibrational spectra and isotope identifiability

## Background

The inputs define the harmonic matrix family and isotope parameters and include source material on energies, generalized eigenproblems and hydrogen isotopes.

## Task

Construct numerical harmonic counterexamples testing whether the H spectrum uniquely determines the H→D zero-point-energy shift.

## Requirements

See the listed output convention for output fields, numerical rules and scientific criteria.

- Use the supplied harmonic family, 12 positive H frequencies, C/O1/O2/H coordinate labels, isotope masses and fixed numerical rules. Keep the environment frozen; do not project translations/rotations or assign inferred observational error bars to source literals.
- Choose two distinct real symmetric positive-definite force blocks in the prescribed orthogonal family, both reproducing the H spectrum. Change only the last three masses to D and compute all H/D modes and ZPE shifts. At least one block must have genuine H–heavy-atom coupling; two permutations alone are insufficient.
- Resolve the two isotope shifts under the fixed error budget. Validate with independent formulations, such as mass whitening and a generalized symmetric eigenproblem, including eigenpair/orthogonality diagnostics.
- Explain identifiability within the declared family, additional information needed, the all-modes /sqrt(2) shortcut and the limits of a single-adsorbate ZPE shift. Distinguish numerical error from electronic-structure uncertainty; do not infer actual Au force constants, PCET activation shifts or reaction KIE.

## Files

| Path | Description |
| --- | --- |
| `/app/inputs/` | Harmonic-model parameters and source material. |
| `/opt/co2-public/output-contract.md` | Required outputs and submission format. |
| `/app/` | Submitted results and required execution evidence. |
