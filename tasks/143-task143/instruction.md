# Task: bidirectional downhill paths and endpoint identity

## Background

A validated index-1 saddle geometry is supplied together with reference reactant
and product structures for the same reaction. Whether the saddle actually
connects those two endpoints cannot be assumed: it has to be established from
paths that leave the saddle in both directions under a frozen protocol.

## Task

Run the two new downhill paths required by the frozen path protocol, starting
from the packaged saddle geometry, and determine how each endpoint matches the
supplied reactant and product graphs. Report the paired classification that
follows from both directions, or a negative result, with the evidence that
supports it.

## Requirements

- Environment: use the container Python on `PATH`. Preinstalled packages include ASE, JAX, matplotlib, NetworkX, NumPy, pandas, pillow, PyTorch, PyYAML, scikit-learn, SciPy, sympy. Do not install additional packages or fetch dependencies from the network.

- Declare one of the permitted path algorithms before generating the paths, and
  follow the protocol's shared unweighted Cartesian metric, saddle checks, mode
  seeding, backtracking rule and stopping conditions.
- Generate only the two required new paths, including exactly one starting
  Hessian evaluation, and retain all trial coordinates, rejected trials
  included.
- Use the required bond perception and element-preserving graph isomorphism to
  classify each endpoint against the reference structures, and derive the
  endpoint labels and the paired classification from both directions.
- A step-limited endpoint is acceptable when the evidence is complete; state the
  stop status as it actually occurred.
- Report energies, call accounting, accepted steps against saved frames, the
  internal-mode eigenvalues with the rigid-body modes projected out, endpoint
  graph matches and the limits of the identity statement.
- Run both paths in the task container using the supplied model and the local execution profile; do not submit remote jobs.

### Input and deliverable details

Inputs are in `/app/assets`: the reference saddle geometry, the reactant and
product structures, checkpoint, model specification, `path_protocol.json`
and `output-contract.json`, which fixes the artifact list, event accounting,
coordinate ordering, hashes, tolerances and status values.

Write the required scientific artifacts to `/app/final`: both trajectories,
endpoint graph classification, the evaluation trace and the report. The report
must state the selected path method and repeat the endpoint classification you
derived.

## Files

Public input files:

| File path | Description |
| --- | --- |
| `/app/assets` | Supplied scientific input or resource; see the task requirements for format and units. |

| Path | Contents |
| --- | --- |
| `/app/final` | Required result; use the contents and format specified above. |
