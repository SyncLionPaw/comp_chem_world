# AGENTS.md

Guidance for coding agents working in this repo.

## Newcomer path (clone → run all)

End users should be able to evaluate **without** rebuilding the offline archive:

1. Confirm the **Linux host kernel is ≥ 6.8** (`uname -r`; Ubuntu 24.04 LTS default). Base images are `ubuntu:24.04` and Harbor/Docker expect **cgroup v2**. Kernels older than 6.8 are unsupported. On macOS/Windows only the Docker Desktop (or equivalent) **Linux VM kernel** counts.
2. Install [uv](https://docs.astral.sh/uv/): `curl -LsSf https://astral.sh/uv/install.sh | sh`
3. Clone this repo; `cd` into it.
4. Obtain the offline archive from **AI4EC** (not in git) and place it at **`shared/inputs.tar.zst`** (only path that matters; do not unpack by hand).
5. Ensure Docker works (`docker info`; Cgroup Version 2), then: **`uv run init`** (full restore). To restore only tasks listed in a job config: **`uv run init -s configs/local-a-selected-20.yaml`**.
6. Put `ANTHROPIC_API_KEY` and `ANTHROPIC_BASE_URL` in `.env` (created from `.env.example` by `init` if missing). Any Anthropic-compatible endpoint works. Change the default model in `configs/agent.yaml`, or override per run with `-m` / `--base-url` / `--api-key-name` (see README).
7. Run all local tasks: **`uv run harbor run -c configs/local.yaml -c configs/agent.yaml --env-file .env -y`**; run HPC tasks with **`configs/hpc.yaml -c configs/agent.yaml`**.

That is the supported onboarding loop. Human-oriented copy lives in `README.md`; keep both in sync when the path changes.

## Project

- **Name**: `comp-chem-world` — computational chemistry agent environments / evals
- **Host**: Linux kernel **≥ 6.8** (cgroup v2); validated on Ubuntu 24.04 (`6.8.x`)
- **Python**: 3.13 (see `.python-version`)
- **Package manager / build**: `uv` + `uv_build`, src layout under `src/comp_chem_world/`
- **Entry**: `uv run init` / `reset` / `pack` → `comp_chem_world.cli:command_main`; `uv run harbor` → Harbor CLI, pinned as a dev dependency (`harbor==0.26.0` in `[dependency-groups]`)

## Commands

```bash
# verify resources and build base images (requires Docker and uv)
uv run init

# only verify/restore shared wheels + assets (no Docker / image build)
uv run init --inputs-only

# restore only tasks listed in a Harbor job config (same inputs.tar.zst; narrower prepare)
uv run init -s configs/local-a-selected-20.yaml

# pack offline inputs (requires a complete, non-restored store: uv run reset first if needed)
uv run pack
uv run pack -s configs/local-a-selected-20.yaml
# -> shared/inputs-local-a-selected-20.tar.zst (recipients rename to shared/inputs.tar.zst)

# clean restored task inputs while keeping images, results, and the project environment
uv run reset

# run all local tasks (after init + .env)
uv run harbor run -c configs/local.yaml -c configs/agent.yaml --env-file .env -y

# run Harbor with other args
uv run harbor run ...

# sync / install for package development (creates .venv as needed)
uv sync

# add a runtime dependency
uv add <package>

# add a dev dependency
uv add --dev <package>
```

Prefer `uv run …` over activating `.venv` manually. Do not commit `.venv`. After changing dependencies, keep `pyproject.toml` (and lockfile if present) consistent via `uv add` / `uv remove` / `uv sync` — do not hand-edit dependency pins unless necessary.

## Layout

```
src/comp_chem_world/   # installable package only
tasks/                 # Harbor tasks (one subdirectory per task)
docs/benchmarks/       # paper-to-task catalog and preserved bench READMEs
shared/inputs.tar.zst  # single offline inputs archive (wheels + assets); gitignored
shared/wheelhouse/     # content-addressed, deduplicated offline Python wheels
shared/asset-store/    # deduplicated large task assets, test inputs, and solution payloads
scripts/               # repository maintenance helpers
images/                # shared Docker base images
  base/                #   → comp-chem-world-base (Python, uv, pytest, Claude Code)
  chem/                #   → comp-chem-world-base-chem (ase, rdkit)
  build.sh
configs/               # Harbor job configs (task sets in local/hpc/local-a/local-b; agent/model in agent.yaml; compose task set + agent.yaml)
jobs/                  # Harbor run outputs (gitignored)
.env.example           # API key template (copy to .env; never commit .env)
pyproject.toml         # project metadata + deps
AGENTS.md              # this file
```

- Put library code in `src/comp_chem_world/`.
- Keep the package importable; avoid scripts that only work from a specific cwd.
- Harbor tasks live under `tasks/NNN-<name>/` (e.g. `tasks/000-hello/`). Imported benchmark tasks are flattened into this same directory so Harbor's `datasets.path: tasks` discovers them directly. Each task has `instruction.md`, `task.toml`, `environment/`, `tests/`, optional `solution/`; not mixed into library modules.
- Imported task assets can be very large. Keep task input data with its task when needed for reproducibility; do not copy Harbor `jobs/`, runner metadata, or source-repository author archives into a task.
- **Agent visibility of `environment/assets/`**: Harbor builds with `environment/` as the Docker context and does **not** bind-mount `assets/` into the agent container. The agent only sees paths that the task `Dockerfile` `COPY`s into the final image (typically `/app/inputs` or `/app/assets`). Prefer narrow `COPY` of required inputs; put offline build caches under paths copied only to `/tmp` in a multi-stage build. Never add a read/write bind of `environment/assets` in `docker-compose.yaml` (if a bind is unavoidable, `read_only: true`). `uv run init` restores asset files as read-only on the host to reduce accidental write-back; `scripts/audit_task_assets.py` reports visibility and mount issues. Do not leave `__pycache__`, `reward.*`, or other run outputs under `assets/`.
- **Verifier `refs.json` modes**: Harbor `prepare.py` rejects group/world-writable `tests/refs.json`. Prefer host `umask 022`. `uv run init` clears those write bits on all `tasks/*/tests/refs.json` after restore. Separate-verifier Dockerfiles that run `harbor_runtime/prepare.py` must `chmod go-w` on `refs.json` after `COPY tests/` (tasks 042–047).
- **Offline inputs archive (required for newcomers)**: put the file at **`shared/inputs.tar.zst`** only. It is gitignored and is the single distribution bundle for all offline wheels + scientific assets (tasks 001–185 and 186–245). `uv run init` unpacks it into `shared/wheelhouse/` + `shared/asset-store/` and restores task paths; then Harbor can run the full dataset. Maintainers rebuild with `uv run pack` (full) or `uv run pack -s <job-config.yaml>` (subset → `shared/inputs-<stem>.tar.zst`; recipients still rename to `shared/inputs.tar.zst` and may use `uv run init -s` with the same config). `uv run reset` removes restored copies under `tasks/` (required before packing if restore-state is present). Manifests (`shared/wheelhouse/manifest.json`, `shared/asset-store/manifest.json`) stay in git as the path→SHA-256 source of truth.
- Offline wheels live in `shared/wheelhouse/`; task assets live in `shared/asset-store/` (all of `tasks/*/environment/assets/`, plus `tasks/*/tests/` and `tasks/*/solution/` files ≥ 1 MiB). Both have SHA-256 manifests. Maintainers: `python3 -I scripts/task_wheels.py compact` / `task_assets.py compact`, then `python3 -I scripts/task_inputs.py pack` to refresh `shared/inputs.tar.zst`. Do not commit restored paths, `*.whl` / `*.blob` under `shared/`, or `inputs.tar.zst`—commit manifests only; do not modify shared blobs in place.
- Preserve both ARM64 and x86_64 dependency variants when migrating tasks. Store both wheels in the shared store, include both hashes in pip locks, and select Conda manifests and local binaries by host architecture; do not replace one architecture with the other.
- Do not use Git LFS by default. Only use it when you understand which files are covered by `.gitattributes`, where the LFS objects are stored, how collaborators and CI will retrieve them, and how migration or removal affects existing pointers. If any of that is unclear, do not enable Git LFS, run `git lfs install`, or add LFS-tracked files; use the repository's shared asset-store workflow instead.
- Maintain the paper/task index in `docs/benchmarks/README.md` and the 28 preserved bench Markdown files in `docs/benchmarks/` when imported bench tasks change. Bench 17 has no paper common to every task: its MACE-OFF23 citation applies only to Task 110.
- Build base images from `images/`: `bash images/build.sh` or `bash images/build.sh -f` (pass host `http_proxy`/`https_proxy` so downloads work). `images/base/uv` is downloaded by `build.sh` (host-arch-matched, recorded in `images/base/uv.arch`) when missing and is gitignored.
- Image chain: `ubuntu:24.04` → `comp-chem-world-base` (Python, uv, pytest, Claude Code) → `comp-chem-world-base-chem` (+ ase, rdkit in `/app/.venv`). Task Dockerfiles `FROM` one of these; there is no separate Claude image.
- Local tasks use `comp-chem-world-base`; HPC/cluster tasks may retain `compchembench-connectivity:hpc` because they require a separately built connectivity image with SSH/Slurm tooling. Do not replace that image with a credential-free base without checking the task's execution model.
- Claude Code version is pinned in two places that must stay equal: `CLAUDE_CODE_VERSION` in `images/build.sh` and `kwargs.version` in both full-run configs. When they match, Harbor reuses the preinstalled binary.


## Python style

- Clear and minimal: no unnecessary wrappers, facades, or entities.
- No try/except solely to soft-fail imports; missing deps should fail loudly.
- No `_`-prefixed pseudo-private helpers unless there is a real encapsulation need.
- Type-annotate public functions; prefer stdlib and explicit dependencies over ad-hoc utilities.
- Match existing naming: `snake_case` modules/functions, `PascalCase` classes.

## Harbor (when touching evals)

This repo is expected to integrate with [Harbor](https://harborframework.com/) for sandboxed agent evaluation.

- Harbor is pinned in `[dependency-groups] dev` in `pyproject.toml` and runs via `uv run harbor …` (the project venv provides the CLI). Do not add it to the library's runtime deps; the package does not import it. Bump the pin with `uv add --dev harbor==<version>`.
- Task verifiers must write a numeric reward to `/logs/verifier/reward.txt` or `/logs/verifier/reward.json`.
- Prefer absolute paths inside `tests/test.sh`.
- Local task run shape: `harbor run -p "<path/to/task-or-dataset>" -a "<agent>" -m "<model>"`.
- Full local job: `harbor run -c configs/local.yaml -c configs/agent.yaml --env-file .env -y`.
- Full HPC job: `harbor run -c configs/hpc.yaml -c configs/agent.yaml --env-file .env -y`.
- Default agent/model: `configs/agent.yaml` (override model with clear + `-m`, or edit that file).
- Check a task's reference solution with the `oracle` agent before running a model against it.

## Commits

Use [Conventional Commits](https://www.conventionalcommits.org/):

```
<type>(<scope>): <summary>

<optional body: what changed and why>
```

- **type**: `feat`, `fix`, `refactor`, `docs`, `test`, `build`, `chore`.
- **scope** (optional): `images`, `tasks/<task-name>`, `configs`, `pkg` (for `src/comp_chem_world/`), `docs`.
- **summary**: imperative mood, lowercase, no trailing period, ≤ 72 chars. Write in English.
- One logical change per commit. Don't mix image changes, task additions and refactors in one commit.
- Use a body when the reason isn't obvious from the diff (e.g. a version bump or a verifier change).
- Never commit `.env`, `jobs/`, `.venv`, `images/base/uv`, `images/base/uv.arch`, or any API key. Check `git status` before committing.
- Bumping the Claude Code version updates `images/build.sh` and both full-run configs in the same commit.

Examples:

```
feat(tasks/001-geometry-opt): add ASE geometry optimization task
build(images): merge Claude Code into base image
fix(configs): align claude-code version with build.sh
```

## Do / Don’t

- **Do** use `uv` for all Python env and dependency changes.
- **Do** keep changes scoped; update this file when workflow or layout conventions change.
- **Don’t** invent parallel packaging (poetry/pipenv/conda) or commit secrets / API keys.
- **Don’t** expand scope into unrelated docs or refactors.
