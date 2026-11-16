# Small-System Liquid NPT Sampling and Density Prediction

## Background

Liquid-density estimates must separate sampling uncertainty, replica dependence and finite-size effects. Ethanol structures, the fixed Sage field and the NPT/native-execution protocol are supplied; periodic boxes remain to be constructed.

## Task

Construct and actually simulate liquid ethanol at 298.15 K and 1 bar for 128- and 256-molecule boxes, with three independent replicas each. Assess density support using equilibration, correlation, replica and size comparisons.

## Requirements

- Preserve the fixed Sage/AM1-BCC model, source atom identities and the prescribed PME, constraints, integration and pressure-control settings. Reuse one supplied-first-conformer molecular charge vector throughout.
- Keep all six independent replicas. Each needs at least 0.1 ns equilibration-candidate and 0.2 ns production-candidate sampling, with adaptive extension up to 1 ns per replica.
- Retain native plans, settings, trajectories and restart evidence; temperature, volume and density must be mutually consistent. Follow the supplied native-execution interface.
- Required targets are Neff>=20 per replica, total Neff>=100 per size, and 95% interval halfwidth<=0.01 g cm^-3, with replica/half consistency and a quantified size difference. An insufficient result is not converted to success by lowering targets.
- Use installed local tools without networking or remote scheduling. Make no bulk-limit or general chemical-space claim.

- Submit results, reproducible analysis and native evidence under `/app/`, using `/app/results.json` and `/app/analysis.py` as the result and analysis entry points. Submit the remaining required files, fields and native artifacts according to the listed output convention.
- Submit `/app/native-plan.json`; place supporting analysis modules and data under `/app/code/` and resolve them relative to the analysis script. During native replay `/submission`, `/inputs` and `/native` are read-only; `/out`, `/tmp` and a private `/dev/shm` are writable. Use the paths supplied on the command line.

## Files

| Path | Description |
| --- | --- |
| `/app/environment/assets/` | Molecular systems, force fields and calculation parameters. |
| `/app/` | Submitted results and required execution evidence. |
| `/app/environment/assets/output-contract.json` | Required outputs and submission format. |
| `/app/environment/assets/native-execution-contract.json` | Native execution-plan and evidence requirements. |
