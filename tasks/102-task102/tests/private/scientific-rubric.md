# Private reviewer calibration: case 07

Do not distribute this calibration file or private source registry to the agent. It defines evidence traps for review only; automated fixture labels cannot substitute for reading the source and candidate report.

Review meaningful claims against actual source bytes, units, row/window selection, measurement role, method assumptions, uncertainty, and reproducible derivations. Relevant calibrated issues for the author Gold include:

- Figure 3a experimental pressure coverage differs across series. A candidate may choose a different honest window; assess whether claims match its declared points and scope. N3 LB is not present as an experimental series; interpolation can be valid if called a model and uncertainty is propagated.
- Figure 4b lists C33/alpha_perp and C44/alpha_parallel derived with a common t(P). Their agreement is internal consistency, not two independent elastic measurements. At 0/8 GPa alpha_perp is 8.62802/31.3568 ×10^19 N m^-3, alpha_parallel is 2.82541/8.40541 ×10^19 N m^-3; shared ratios give t=6.15/5.822027 Å. A distinct independently sourced thickness or elastic measurement could add evidence.
- OUTCAR f/i flags must not be converted to positive stable frequencies. Near-zero imaginary values merit numerical-context review, not an unsupported categorical instability claim. Cross-pressure mode identity needs evidence beyond sorted ordinal. The public bulk calculations do not establish new convergence studies or few-layer DFT.
- OLS residual slope standard errors describe scatter under the selected fit only; they are not full measurement or model uncertainty. Figure 4c published slopes are claims for comparison, not input measurements for an independent re-fit.
- A candidate-computed SHA proves internal file consistency only. Verify provenance against the identified public source/version; a new legitimate source outside the private registry is `NOT_CHECKED` by automation and can still pass independent review.

For all six gates, record concrete scientific reasoning, cite the candidate report and relevant source excerpt/derived table, state applicability and limitations, and explain how the evidence affects the claim. A report that only lists caveats without a substantive answer is insufficient. A scientifically justified negative or uncertain answer is eligible for acceptance. `paper_outcome` is distinct from `submission_validity`.
