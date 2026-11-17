# Spin States and Energy Differences for Copper Ion Parameters

## Background

Isolated copper spin states determine ionization energies and QEq parameters.

The public inputs specify the atomic calculation and native control protocol.

## Task

Compare Cu(0), Cu(+1), Cu(+2) energies, select minimum-energy states and diagnose triplet substitution and downstream stability.

## Requirements

- Use CCSD(T)/def2-QZVPP with all electrons correlated. The primary nonrelativistic RHF/UHF control has no ECP or frozen core: Cu0 doublet, Cu1 singlet/triplet, Cu2 doublet; quartets are optional. Keep all attempts. Require SCF 1e-12 Eh, CC energy 1e-10 Eh and amplitude-step 1e-8; energy comparison 1e-6 Eh and S² 1e-4. Compute IP0, IP1, chi=(IP0+IP1)/2 and J=IP1-IP0. Provide two neutral pair countermodels with opposite J-K signs.
- Use only this case’s public inputs; retain required statuses, failures, units and reproducible evidence.

- Submit the required artifacts according to the listed output contract.

## Files

| Path | Description |
| --- | --- |
| `/opt/qeq-public/` | Public data, models and calculation parameters. |
| `/opt/qeq-public/output-contract.yaml` | Required outputs and submission format. |
| `/app/outputs/` | Submitted results and required execution evidence. |
