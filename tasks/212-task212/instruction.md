# Charge-model sensitivity of dilute CO₂ adsorption

## Background

Framework charges affect CO₂–host electrostatics and hence the heat of adsorption and Henry coefficient at infinite dilution.

The inputs define the sampling arms, structures, method order and proposals per stage; periodic cells, fractional coordinates and site IDs; site-aligned framework charges and DDEC3 references with source row IDs; and CO₂ geometry, interaction parameters, temperature, unit conversions, cutoffs, Ewald settings and resolution targets.

## Task

At 298 K, how much do PQeq and zero framework charge change CO₂ adsorption relative to DDEC3 in DOTSOV02 and ICOYIK? Estimate the change in isosteric heat and the natural log of the Henry-coefficient ratio for each framework. Distinguish the direction of each effect from how precisely its magnitude is known.

## Requirements

- Perform paired Widom insertions on the supplied rigid cells. For each pose use the same geometry and orientation for DDEC3, PQeq_GMP and NO_Q. Report method minus DDEC3. Apply the two Ewald settings and the hard-core, UFF and TraPPE conventions in the public protocol. Keep isolated pockets and retain the complete proposal denominator.
- Use eight independent replicas per sampling arm and two fresh stages per replica. Use uniform sampling for DOTSOV02 and both uniform and volume-weighted stratified sampling for ICOYIK. Compare the initial and cumulative estimates, the pooled and replica-wise estimates, and the results of the two ICOYIK samplers. Report pointwise uncertainty for each observable separately.
- Use only the public inputs for this task and submit the two outputs at the specified paths.

- Submit the required artifacts according to the listed output contract.

## Files

| Path | Description |
| --- | --- |
| `/opt/qeq-public/` | Public data, models and calculation parameters. |
| `/opt/qeq-public/output-contract.yaml` | Required outputs and submission format. |
| `/app/outputs/` | Submitted results and required execution evidence. |
