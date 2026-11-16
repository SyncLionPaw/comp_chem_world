# Task: Implement RDKit internal-coordinate restraints

## Background

Conformer generation from mixed distance, angle and signed-torsion restraints requires constraint propagation and geometry sampling while preserving molecular graph and stereochemistry. The exact public API, numerical rules and error semantics are defined in `/app/SPEC.md`.

## Task

Complete `/app/rdkit_ic_constraints/` with `build_constraint_bounds` and `embed_with_constraints` for RDKit molecules and the specified geometric restraints.

## Requirements

- Environment: use the container Python on `PATH`. Preinstalled packages include NumPy, pillow, RDKit, SciPy. Do not install additional packages or fetch dependencies from the network.

Support distance, angle, signed-torsion and ambiguous-distance restraints, including wrapped torsion intervals and OR alternatives. Return sound triangle-consistent lower/upper distance-bound matrices; generate a complete deterministic conformer ensemble satisfying the restraints while preserving atom order, graph and stereochemistry. Preserve the input molecule unchanged. Distinguish validation errors, certified infeasibility and uncertified generation failure in the specified order. Use only dependencies already installed.

Follow the API and numerical contract in `/app/SPEC.md`. Use the public utilities and tests as permitted by that specification.

## Files

Public input files:

| File path | Description |
| --- | --- |
| `/app/SPEC.md` | Public function and geometry specification. |
| `/app/rdkit_ic_constraints/` | Public constraint types. |
| `/app/rdkit_ic_spec/` | Reference interface and examples. |
| `/app/public_tests/` | Public tests. |

**Inputs**

- `/app/SPEC.md`: normative specification.
- `/app/rdkit_ic_spec/` and `/app/public_tests/`: read-only public specification module and tests.

**Deliverables**

- Complete and submit the package in `/app/rdkit_ic_constraints/`.

Time budget: 28,800 s.
