# Case 06 reviewed empirical geometry acceptance policy

Review decision: use `empirical-3pm/v1` for the tracked same-method ES bond rows in the five-molecule case06 task. This is an empirical task acceptance rule, not a force/curvature theorem or a strict uncertainty bound.

The verifier recomputes each symmetry-averaged bond mean from the candidate's hash-checked native final XYZ, then compares that value with the corresponding non-null same-method target in the frozen SI reference. Each of the 36 available method/bond rows is an equal-weight tracked row after symmetry-equivalent bonds have been averaged. There are 13 tracked PBE0 rows, 13 ADMM rows, and 10 default sTDA rows. The null M14 default-sTDA target is excluded; the M14 aEX=0.25 remedy is reported separately and never substituted into the default-target comparison.

The absolute residual limit is fixed at 3.0 pm. Source-paper residuals, EOM-CCSD comparisons, and the derived triangle-consistency envelope are descriptive outputs and do not widen or replace this same-method limit. Candidate-provided aggregate metrics or uncertainty values are not acceptance evidence.

The profile does not certify a complete 25-route scientific reference calculation or make the M14 default/remedy decision from JSON claims. Those classifications require the independent native M14 and minimum adapters; missing or ambiguous native evidence remains unverified.

For projected internal vibrations, the grader-owned operational review band is 10.0 cm^-1: any mode with |nu| <= 10.0 cm^-1 remains unverified pending a same-method displacement-step sensitivity review or an independently reviewed equivalent; any mode below -10.0 cm^-1 is a material imaginary mode. This is a conservative review trigger for this workflow, not a paper value or numerical error bound.
