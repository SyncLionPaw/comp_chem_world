# Fixed-activity microkinetics and state rate control

## Background

The inputs provide author reaction energies, fixed kinetic conditions, thermochemical and reference-state corrections, gas molecular and vibrational parameters, JANAF rows and transcribed Table 6 parameters. The paper and supplement supply the source evidence.

## Task

Solve the four-step fixed-activity CHE-Frumkin microkinetic model and calculate state DRC and kinetic slopes along the prescribed charging path.

## Requirements

- Solve all declared acidic/alkaline four-step CHE-Frumkin conditions using thermodynamically consistent rates, nonnegative coverages and site-weighted balance: CO2/COOH/TS3 use two sites, CO one. Diagnose absent/nonphysical roots and convert active-site density to CO current explicitly.
- Preserve Table 6 electronic parameters and the supplied thermochemical map, standard states and five CO modes. Apply each formation/thermal correction once, including the JANAF liquid-water term; retain the specified gas-activity conversion and zero-CO reverse factor.
- Use the second-PCET 0.6 eV, beta=0.5 convention and its state-specific perturbation rules. Step 3 releases a vacancy: r3=k3f*theta_COOH−k3r*theta_CO*theta_free. Do not add a forward vacancy factor, field-difference barrier or duplicate OH/pH contribution.
- Compute each state DRC at fixed activities and charge by two-sided perturbations with at least two decreasing steps. Along sigma(U)=20*(U−0.16) uC/cm², phi_RP=0, retain identical activities and compute every eligible centred log-current derivative at all three h, with correct ln/log10 and V/mV conversion.
- Report refinement and a finite reference-supported error assessment under the listed output convention. The contract fixes thermochemical equations, DRC perturbations, mass action and acceptable derivative-error evidence; equivalent accurate methods are allowed.
- This declared path is not coupled transport or a paper-exact reproduction. Do not infer transport DRC or H2 polarization; the paper's 42/101 mV/dec values are contextual, not acceptance targets.

## Files

| Path | Description |
| --- | --- |
| `/app/inputs/` | Reaction energies, thermochemistry and kinetic parameters. |
| `/opt/co2-public/output-contract.md` | Required outputs and submission format. |
| `/app/` | Submitted results and required execution evidence. |
