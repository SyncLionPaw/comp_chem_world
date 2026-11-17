# Source evidence and mechanistic limits

## Background

The source article, supplement and text layer provide the experimental evidence and its locations.

## Task

Recover source-linked experimental constraints and assess adsorption control, rate-limiting-step and proton-order identifiability using explicit numerical countermodels.

## Requirements

Preserve SHE, Current Efficiency (%), all 29 literal rows and uncertainties. Compute both Decimal sums to 5 decimals without clipping, rescaling or invented covariance. Cover pH1, pH3/6.8, buffer and Cs+/K+ controls. Supply explicitly hypothetical zero-order/positive-order PCET countermodels and zero versus positive-below-hypothetical-limit controls. No new fitting, experiments, GC reconstruction or DFT.

Follow the listed output convention for the required fields and scientific criteria.

The output contract defines source-linked claim indices and allows the source-printed efficiency heading or a contiguous complete table-header transcription.

For the hypothetical PCET controls only, `normalized_rates` may contain either raw rates r_i=k*a_i^proton_order or rates relative to the first condition, r_i/r_0; every entry must consistently follow one representation. This equivalence does not permit changing or renormalizing the 29 experimental efficiency rows. Source-role indices and source quotations must support the corresponding claims as specified in the output contract.

## Files

| Path | Description |
| --- | --- |
| `/app/inputs/` | Article material and experimental data. |
| `/opt/co2-public/output-contract.md` | Required outputs and submission format. |
| `/app/` | Submitted results and required execution evidence. |
