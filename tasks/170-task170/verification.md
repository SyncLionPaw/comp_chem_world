# Verification protocol — case-04 (grader-only)

The verifier preflights the public input/reference hashes, then treats missing or malformed agent deliverables as scientific FAIL (L1), not infrastructure errors. Corrupt/missing grader assets or missing dependencies are `ENV_INVALID` with no reward. QE itself is not installed or run.

It pins input semantics to Quantum ESPRESSO 7.2. Static checks parse standard Fortran namelist assignments including comma-separated entries and `D` exponents, cards, crystal positions, and cell units. The two SCF structures and plan/deck meshes must agree. Bohr conversion is supported; `alat` is never treated as bohr.

Both SCF decks must declare `ATOMIC_POSITIONS (crystal)`, contain W₂N₃ (two W, three N), and match the hash-checked starting POSCAR periodically: cell vectors within 1e-3 Å and same-species coordinates within 1e-3 Å after wrapping by lattice translations. Thus consistent-but-wrong units, species, coordinates, or cell fail as candidate science errors; a corrupt trusted POSCAR fails preflight as `ENV_INVALID`.

Necessary scientific checks cover the dense SCF `la2F` fit; coarse SCF structure/grid; QE `&INPUTPH electron_phonon='interpolated'` and `fildvscf`; q2r `fildyn`/`flfrc`/`la2F`; matdyn `flfrc`/`la2F`/DOS; the automatic q mesh and a fail-closed spglib helper that derives irreducible weights, matches QE Cartesian `tpiba` q headers to a unique full-grid point modulo reciprocal vectors, then uses the spglib orbit map for multiplicity weights; QE 7.2 lambda files are read from `elph_dir`; the helper emits standard-input `lambda.x` streams for μ*=0.16/0.10. `fldos` is treated only as the phonon DOS file. Input file prefixes/outdirs and `run.sh` command order must be consistent. Budget fields must be finite, positive, sum exactly to total, and satisfy the case limits; the verifier separately requires the plan to disclose that costs are unbenchmarked estimates.

Evidence for parser expectations:

- QE 7.2 official `PHonon/examples/example03/run_example` uses dense SCF with `&SYSTEM la2F=.true.`, coarse SCF, then `ph.x` with `&INPUTPH electron_phonon='interpolated'`, followed by q2r/matdyn and `lambda.x`: [official QE 7.2 example](https://raw.githubusercontent.com/QEF/q-e/qe-7.2/PHonon/examples/example03/run_example).
- QE 7.2 `phq_readin.f90` defines the `INPUTPH` namelist, defines `ldisp` and the `nq1/nq2/nq3` mesh fields: [official QE 7.2 PH reader](https://raw.githubusercontent.com/QEF/q-e/qe-7.2/PHonon/PH/phq_readin.f90#L111-L127).
- QE 7.2 `lambda.f90` documents/reads plain stdin: emax/degauss/method, q count, q vectors/weights, one PH lambda-output filename per point; final μ*; it writes `lambda.dat` and `alpha2F.dat`: [official QE 7.2 lambda source](https://raw.githubusercontent.com/QEF/q-e/qe-7.2/PHonon/PH/lambda.f90#L32-L52), [input reads](https://raw.githubusercontent.com/QEF/q-e/qe-7.2/PHonon/PH/lambda.f90#L56-L73), [μ* and outputs](https://raw.githubusercontent.com/QEF/q-e/qe-7.2/PHonon/PH/lambda.f90#L149-L165).

Limitations: a static PASS confirms only that the emitted templates satisfy these checks. It does not test pseudopotential licensing/availability, execute QE, validate machine-specific runtime, measure convergence, or prove the planned 300/40 core-hour budget is feasible.
