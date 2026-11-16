# Reference analysis choices

This is a reproducible reference method, with choices made where the public
protocol leaves them open. It is not a list of additional universal protocol
requirements.

- Periodic trilinear charge assignment (CIC), a 256^3 primary reciprocal mesh,
  and a paired 384^3 mesh/direct-coordinate comparison.
- Production coordinates are saved at 1 ps. The estimator samples every tenth
  frame from the full 20 ns trajectory; paired direct and mesh checks use 200
  evenly spaced configurations.
- Reciprocal modes are grouped into 0.05 A^-1 bins through 6 A^-1. The response
  applies each mode's own k^-2 factor before bin averaging; k=0 is reported
  separately from total molecular-dipole fluctuations.
- Uncertainty uses 10,000 resamples of contiguous 1 ns blocks, with 0.5 ns and
  2 ns reblocking sensitivity reported separately. The confidence level is 95%.
- The SPC/E system uses LINCS constraints, PME interpolation order 4, 0.12 nm
  Fourier spacing, and a 1 ps compressed-coordinate interval. These are
  implementation choices for this reference workflow.

The analysis records both the estimates and each scientific gate. A completed
calculation can therefore have `scientific_status: PARTIAL` when a numerical,
sampling, or stability gate is not supported by the generated trajectory.
