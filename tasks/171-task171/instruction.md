# Task: Diagnose an electron–phonon campaign

## Background

`assets/epc-campaign.tar.gz` contains four reconstructed QE/EPW-style run chains, settings, SCF
records, spectra, summaries, phonon frequencies, and linewidths. These are synthetic training
reconstructions, not original source outputs. Its embedded pathology labels describe this asset
only; similar symptoms can have other causes in real calculations.

## Task

Extract and inspect every chain. Identify the unique trustworthy run based on outputs and settings,
list each untrustworthy chain's applicable embedded pathologies, and cite specific evidence for
every judgment. Independently integrate the selected a2F data, extract λ, ω_log, Tc at μ*=0.16, and
find the largest linewidth and its mode frequency. Address the three Γ-point acoustic frequencies
and SCF convergence records.

## Requirements

Allowed pathology labels only: `unconverged_scf`, `insufficient_vacuum`, `insufficient_k_mesh`,
`insufficient_q_mesh`, `excessive_smearing`. Report exact labels supported by this training asset;
trustworthy run has an empty list, every other run at least one. Every evidence string must cite a concrete setting/output observation. Judge against the specified comparison protocol: 80 Ry,
16×16×1 SCF, 192×192 k / 96×96 q, `sk=0.05 eV`, `sq=0.5 meV`, 40 Å vacuum, μ*=0.16. Extract values
from the selected chain; independent λ integral must agree with its summary within 5%. Linewidth
column 3 is cm⁻¹, column 4 is meV.

### Input and deliverable details

Write `/app/final/diagnosis.json`. `runs` object contains exactly `run-A`, `run-B`, `run-C`,
`run-D`, each an object with boolean `trustworthy`, array-of-string `pathologies`, and string
`evidence`. `selected_chain` is the unique trustworthy run ID string. `extracted` object has finite
numeric `lambda`, `omega_log_cm1`, `tc_mu016_K`, `lambda_from_a2f_dat`, `gamma_max_meV`,
`gamma_max_mode_omega_cm1`. Do not copy a result template or infer trust from filenames.

## Files

Public input files:

| File path | Description |
| --- | --- |
| `assets/epc-campaign.tar.gz` | Supplied scientific input or resource; see the task requirements for format and units. |

| Path | Contents |
| --- | --- |
| `/app/final/diagnosis.json` | Required result; use the contents and format specified above. |
