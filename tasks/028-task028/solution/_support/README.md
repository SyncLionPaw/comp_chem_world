# Case08 reference solution

Run `./solve.sh OUTPUT_DIR` from any directory. The script creates
`OUTPUT_DIR/final/claim.md`, `provenance.json`, and `native_evidence/`; it
refuses to replace a nonempty `final/` directory. Python 3.9+ standard library
is sufficient. `reference-manifest.json` freezes every solver, source, data,
and historical-run file used by this entry point.

Run `python3 test_reference.py` for the positive, incorrect-branch, incorrect-
unit and missing-output reference-validation cases. The environment/signature
negative cases run separately through the existing offline grader protocol
suite; they test protocol handling, not scientific correctness.

The script rechecks the acquired article, SI, correction, source manifest and
archived MESMER output hashes, then runs the analytic/RK4 preformed-iBPR versus
lumped-NO screen. It includes existing g50/g200 MESMER input/output/receipts as
historical local ARM64 controls. Those old runs are not rerun and do not count
as HPC evidence. The new local computation also has no scheduler receipt or
independent execution authentication.

Everything under this `solution/` directory is evaluator-side reference
material. It must not be mounted into an agent task or copied into the shared
execution image; the generated candidate receives only its own `final/` output.

The package supports a bounded early-kinetics reference, including mass
closure, nonnegativity, a step-size check and explicitly labeled stress
scenarios. Its source-backed R1+O2/RO2/O9 route map is qualitative. It does not
quantify post-open O2/HO2 flux, aerosol yield, or i-BPR formation. A valid run
through `tests/test.sh` therefore remains `REVIEW_REQUIRED` until the protected
same-attempt context and independent human review are supplied.
