# Task: Holy Grail: investigate the role of aromatic BPR rearrangement in aerosol formation

## Background

Bicyclic peroxy radical (BPR) rearrangement has been proposed as a route that sustains autoxidation during aromatic oxidation and leads toward oxygen-rich aerosol precursors. Determine what an independent computational investigation can establish about this claim and under which conditions. This is an open research problem: no scientific inputs, calculation method, molecular scope, required route, or reference solution are supplied. You are responsible for acquiring or constructing suitable inputs and making and justifying the scientific decisions.

## Task

Design and carry out a computational study that tests the core claim with new, traceable evidence. State a clear conclusion, the systems and conditions it covers, quantitative support, uncertainty tied to the approximations actually used, limitations, and what evidence could change the conclusion. Compare rates only when their conditions and reference populations are meaningfully matched. Explain how your calculations support—or fail to support—the proposed connection from rearrangement to aerosol precursors. Do not overstate what molecular rates alone establish about aerosol formation or yield.

Distinguish results of new calculations from acquired measurements and external reference values. Report failed, partial and unsupported work honestly. Reused calculations retain their original conditions and scope; they do not count as newly executed work or establish convergence without supporting evidence.

## Requirements

- Environment: use the container Python on `PATH`; required scientific packages are preinstalled. Do not install additional packages or fetch dependencies from the network.

If using HPC, see `/app/AGENTS.md`: use SSH alias `hpc`, keep remote work under a unique `~/submit-jobs/<task>-<utc>-<rand>/` directory, and validate the scientific result.

The attempt deadline is 8 elapsed hours, including queue waits. Count failed and cancelled allocations in the attempt record. Record submitted, failed, cancelled and completed jobs and report actual resource usage. If SSH/Slurm access is unavailable or evidence is missing, say so; never invent job records. Protect SSH credentials: do not include them in outputs or logs. Scientific conclusions must be supported independently of the format and completeness of the submission.

Perform the calculations on HPC. Preserve native calculation files, job records, and actual resource usage. Follow the cluster’s current submission policy, and distinguish requested resources from measured usage.

### Input and deliverable details

Provide `final/claim.md`, `final/native_evidence/` and `final/provenance.json`. The claim should connect each quantitative conclusion to its uncertainty and evidence. Preserve native inputs and outputs, acquired sources, job records and analysis files. The provenance file must follow the complete public schema mounted in the container at `/app/output-contract.json`, including evidence paths and hashes, source attribution, execution links and conditions/populations for rate comparisons. Cluster access is described in `/app/AGENTS.md` (SSH alias `hpc`); native-record requirements are described at `/app/research-service.md`; configuration is `/app/submit-job.json`.

See `/app/AGENTS.md` and use SSH alias `hpc` for Slurm work; retain all `.submit-job/*.json` state files unchanged in `final/native_evidence/slurm/`, including failed and cancelled jobs. Preserve the original calculation files and connect scientific stages to their job IDs.

## Files

Public input files:

| File path | Description |
| --- | --- |
| `/app/output-contract.json` | Supplied data, parameters or method documentation; see the task requirements. |
| `/app/research-service.md` | Supplied data, parameters or method documentation; see the task requirements. |
| `/app/submit-job.json` | Supplied data, parameters or method documentation; see the task requirements. |

| Path | Contents |
| --- | --- |
| `/app/final/claim.md` | Required result; use the contents and format specified above. |
| `/app/final/native_evidence` | Required result; use the contents and format specified above. |
| `/app/final/provenance.json` | Required result; use the contents and format specified above. |
