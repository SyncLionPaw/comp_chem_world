# Task: reconcile published TNEP values and conventions

## Background

Reconcile the published TNEP numerical values and conventions, including the physical definitions and limits of the reported evidence.

## Task

Record the source version and exact source locations. Extract the requested cells from the primary sources, then assess the scientific conventions and limits of the aggregate evidence.

The `(table, cell)` identifiers below list the required values. Determine their values, units, conventions and evidence limits from the source documents.

### Required value cells

| Source | Cell identifier |
|---|---|
| Table 1 | H2O rmse; H2O rrmse; (H2O)2 rmse; (H2O)2 rrmse; H5O2+ rmse; H5O2+ rrmse; liquid water rmse; liquid water rrmse |
| Table 2 | H2O diag rmse; H2O offdiag rmse; (H2O)2 diag rmse; (H2O)2 offdiag rmse; H5O2+ diag rmse; H5O2+ offdiag rmse; liquid water diag rmse; liquid water offdiag rmse |
| QM7B | dipole rmse per atom; alpha diag rmse per atom; alpha offdiag rmse per atom; dipole r2 |
| Table S1 | H2O Nneu; QM7B Nneu; rRc; rAc |
| Table S2 | BaZrO3 Nneu; BaZrO3 Ngen; BaZrO3 Npop; BaZrO3 nmax |
| Table S3 | liquid water Nneu; liquid water Ngen |
| Text | BaZrO3 structures; BaZrO3 R2 diagonal; BaZrO3 R2 off-diagonal; OH stretch FWHM cm-1; experimental FWHM cm-1 |

### Conventions and evidence limits

For each fixed topic, provide a sourced prose statement and a structured field recording the conclusion. Keep the two consistent. For related unit conventions, use one consistent system reported or defined by the cited material and explain its basis. Use these field shapes without filling them from this instruction:

In the examples, `<boolean>` is a placeholder: replace it with a JSON `true` or `false` value without quotation marks.

In the `liquid water dipole normalization` object, `count` is an optional source note; if supplied, it must be a finite non-negative integer.

Write the equation as a plain arithmetic equality: use explicit multiplication and division, and write integer powers with `^` or `**`.

```json
"normalized": {
  "liquid water dipole normalization": {"entity": "<entity>"},
  "qm7b normalization": {"denominator_entity": "<entity>"},
  "unit conventions": {"mu": "<unit>", "alpha": "<unit>", "chi": "<unit>"},
  "clausius-mossotti": {"equation": "<equation>", "applicability": ["<condition>"]},
  "chi/rho reconstructability": {"unique": "<boolean>", "reason": "<reason>"}
}
```

Provide one sourced statement for each fixed topic:

- `liquid water dipole normalization`
- `qm7b normalization`
- `unit conventions`
- `clausius-mossotti`
- `chi/rho reconstructability`

For `chi/rho reconstructability`, assess whether the molecular polarizability `alpha` can be uniquely reconstructed when only the reported `chi/rho` ratio is given, with no independent `chi` or `rho` value supplied. For `clausius-mossotti`, explain the physical preconditions relevant to the relation and assess whether the stated applicability conditions are complete; you may report multiple conditions.

For at least one of these fixed categories, assess whether the published evidence is sufficient for the inference it represents. `hardware_performance_extrapolation` asks whether the reported measurements justify performance claims on untested hardware or beyond the studied system-size range; `per_configuration_error_distribution` asks whether the reported aggregate metrics determine the distribution of individual-configuration errors. The `claim` and `why` must address the chosen fixed inference. Record your independently derived Boolean assessment and source-based reasoning. Use the named evidence-boundary categories and the `unsupported` key to report conclusions supported by the sources.

## Requirements

- Environment: use the container Python on `PATH`; required scientific packages are preinstalled. Do not install additional packages or fetch dependencies from the network.

For every cell, report its value, the unit as printed or implied by the source, and a precise provenance (page/table/row or section). Do not combine cells that have different definitions. Use relative transcription tolerances of 2% for error metrics, 1% for R² and OH-stretch FWHM, and 3% for the experimental-width comparison. Discrete counts and hyperparameter settings must match the source exactly. Unit strings may use source notation or an unambiguous ASCII equivalent, including an explicit base-10 scale when the reported number uses that scale; percentage notation is accepted for dimensionless RRMSE and R² values. This instruction does not map individual cells to units.

Automatic checks verify structured numerical and convention fields. The source-based prose and its consistency with the structured conclusions require scientific review.

## Files

Public input files:

| File path | Description |
| --- | --- |
| `/app/environment/inputs/` | Source material and scientific inputs for this task. |

Write `/app/final/reconciliation.json`:

```json
{
  "values": [{"table": "Table 1", "cell": "<identifier>", "value": 0,
              "units": "<unit found in source>", "provenance": "<page/table/row>"}],
  "normalized": {},
  "conventions": [{"topic": "<fixed topic>", "statement": "<your conclusion>",
                    "basis": "<source location>"}],
  "unsupported": [{"category": "<evidence-boundary class>", "supported": "<boolean>",
                   "claim": "<claim>", "why": "<evidence-based reason for your assessment>"}]
}
```

Include each required cell exactly once and use finite values. Ensure structured convention fields agree with the sourced prose. Use only official articles and their supplementary information as scientific sources.
