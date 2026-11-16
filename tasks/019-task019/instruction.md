# Validate chemical requests and charge-model choices within the workflow's supported scope

## Background
The 2025 AutoSolvate Web workflow has a limited chemical domain.

## Task
Screen every request and implement reusable routing: report the first failed condition or the charge model.

## Requirements
Use element counts, formal charge, spin multiplicity, component count and iodine bond degree, not names/IDs. Electron count is Σ(atomic number×count)−charge. Valid multiplicity is a positive integer ≤electron count+1 and electron_count−(multiplicity−1) even. Check order: electronic state; elements H,C,N,O,P,S,F,Cl,Br,I; exactly one component; iodine degree null or ≤1. Report only the first failure and never launch rejected requests. Route admitted singlets to AM1-BCC, open-shell to RESP. One decision per request; preserve charge/spin and finite integer-valued counts. Read requests.json; write decisions.json, runnable route.py, analysis.md in /app/final/. Public output contract defines fields/reasons. No quantum calculation is needed.

## Files

Public input files:

| File path | Description |
| --- | --- |
| `/app/inputs/` | Requests to audit. |
| `/app/output-contract.yaml` | Output format and evidence requirements. |

/app/inputs/: requests; /app/output-contract.yaml: schema; /app/final/: decisions/code/analysis.
