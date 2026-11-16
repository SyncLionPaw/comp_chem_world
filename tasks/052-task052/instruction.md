# Task: Archived-chain expectations and Metropolis transitions

## Background

The checkpoint defines a fixed six-angle periodic model in kJ/mol. Its target and uniform flat-probe ensembles are mathematical model-space distributions. The finite archived chains do not establish equilibrium, physical Ala4 free energies, or new sampling.

## Task

Implement `/app/submission.py` to evaluate the network and its parameter gradient, apply target/flat Metropolis transitions, and estimate ensemble means, their gradient contrast, and block MCSE from the supplied chains.

## Requirements

- Environment: use the container Python on `PATH`. Preinstalled packages include NumPy. Do not install additional packages or fetch dependencies from the network.

Angles are `(phi1,psi1,phi2,psi2,phi3,psi3)` in radians, wrapped to `[-π,π)`. Encode all six sines followed by all six cosines. The network is `12→96→48→24→1`, with ReLU hidden layers, zero ReLU derivative at zero, and float64 calculations. The checkpoint is eight decoded arrays in `fc1.weight,fc1.bias,fc2.weight,fc2.bias,fc3.weight,fc3.bias,out.weight,out.bias` order, with shapes `(96,12),(96,),(48,96),(48,),(24,48),(24,),(1,24),(1,)`.

Provide these functions:

- `forward_and_grad(angles, checkpoint) -> (energy, gradient)`: differentiate in reverse mode; flatten all 7,105 parameter derivatives in the array order above and C order within each array.
- `set_checkpoint(checkpoint)`: retain the checkpoint for `transition`.
- `transition(state, proposal, u, ensemble, beta, gamma) -> (accepted, next_state)`: treat the proposal as absolute angles and wrap both states. For `target`, accept iff `log(u) < min(0, beta*(V(proposal)−V(state))/(gamma−1))`; `flat_probe` always accepts. On rejection return the wrapped original state. Use the passed beta/gamma; the archived reference uses gamma=10 and beta=1/(0.00831446261815324×300) mol/kJ.
- `analyze(chains, checkpoint, blocksize)`: each ensemble has two separate chains. Compute mean energy and parameter gradient, target-minus-flat gradient contrast, and componentwise `sqrt(var(target block means,ddof=1)/Ntarget + var(flat block means,ddof=1)/Nflat)`. Form blocks within each chain before pooling their means.

Raise `ValueError` for nonfinite or incorrectly shaped inputs, unknown ensembles, u outside `(0,1)`, nonfinite beta, gamma≤1, or a block size that is nonpositive/noninteger, does not divide every chain, or leaves fewer than two pooled blocks per ensemble. All outputs must be finite. Tolerances are atol/rtol `2e-9/2e-8` for forward/gradient, `2e-8/2e-8` for analysis, and `2e-12/0` for next-state angles; acceptance must be an actual Boolean. Do not generate new Monte Carlo or MD samples or claim convergence, confidence coverage, or physical FES.

### Input and deliverable details

Read `model_checkpoint.pt` and `retained-chains.json` under `/app/environment/assets/`. Submit only `/app/submission.py`, using the provided Python/NumPy environment.

`analyze` returns a dictionary with exactly `target_energy_mean`, `flat_energy_mean`, `target_gradient_mean`, `flat_gradient_mean`, `contrast`, `mcse`, or a six-element sequence in that order. The first two are scalar kJ/mol means; the remaining four have shape `(7105,)` in the same parameter order. Contrast is target minus flat and MCSE is nonnegative.

## Files

Public input files:

| File path | Description |
| --- | --- |
| `/app/environment/assets/` | Directory of supplied inputs and resources. |

Submit `/app/submission.py`. Use the interface and output conventions above.
