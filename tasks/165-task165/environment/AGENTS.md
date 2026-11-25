# HPC cluster access

SSH alias `hpc` is preconfigured (key under `/root/.ssh/`). Use it to reach the login node.

## What you may do on the login node

- Probe and submit only: `sinfo`, `squeue`, `sacct`, `sbatch`, `scancel`, and file transfer to/from your job dir.
- Run compute inside Slurm allocations, not on the login node.
- Write local task outputs under the paths required by `instruction.md` (usually `/app/final`).

## Remote job directory

All remote work lives under `~/submit-jobs/` (unless the task says otherwise).

Create **one unique leaf** per attempt. Do not use short names like `run1`, `test`, or the task id alone.

Pattern: `~/submit-jobs/<task>-<utc>-<rand>/`

- `<task>`: Harbor task folder stem (e.g. `069-task069`)
- `<utc>`: UTC time `YYYYMMDDTHHMMSSZ`
- `<rand>`: at least 6 lowercase hex chars (`openssl rand -hex 3`)

Example: `~/submit-jobs/069-task069-20261125T043812Z-a1b2c3/`

Create `~/submit-jobs` with `mkdir -p` if needed, then create the leaf with `mkdir` **without** `-p` so an existing path fails. On collision, new `<rand>` and retry. Never reuse or overwrite a sibling directory. Do not `ls`/`find` other siblings; only use the leaf you just created.

## Stay in lane

- Do not read, list, or search other users' homes, shared trees outside your job dir, `/etc` secrets, scheduler spool internals, or unrelated files under `$HOME`.
- Do not pull back cluster data unrelated to this task; collect only from your job workdir.
- Do not install packages, edit shell rc files, or change SSH/`authorized_keys` on the login node.
- If a path is not needed to submit, monitor, or collect this job, do not open it.
