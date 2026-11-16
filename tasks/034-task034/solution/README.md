# Reduced-sampling reference replay

`solve.sh` stages `reference-final/` from this solution directory and reruns its
analysis against the archived native compact trajectories. It does not regenerate
those trajectories, execute HPC jobs, or validate full-system sampling. These
files are evaluator-only and are never copied into the candidate image. Run with
Harbor Oracle to test this bounded replay and the ordinary self-scoring verifier.
The original simulation inputs, full trajectories and execution evidence remain
in the verified NAS migration archive named in the root README.
