#!/usr/bin/env bash
# Portable reference workflow for Case 01. Runs fresh MD when invoked; do not
# invoke for a dry-run review of the task package.
set -euo pipefail

HERE="$(cd -- "$(dirname -- "$0")" && pwd)"
IMPL="$HERE/_impl"
GMX="${GMX:-gmx}"
PYTHON="${PYTHON:-python3}"

# The evaluator selects the historical author route explicitly at the CLI.
# A stray context variable alone must never change ordinary Agent execution,
# and a missing context on the selected author command must fail closed before
# dry-run handling or any fresh-MD branch can run.
if [[ "${1:-}" == "--historical-archive" ]]; then
  if [[ "$#" -ne 2 || "${CASE01_AUTHOR_ARCHIVE_CONTEXT:-}" != "/trusted/case01-author/context.json" ]]; then
    echo "Historical archive route requires the exact evaluator context and one work directory." >&2
    exit 2
  fi
  exec "$PYTHON" "$IMPL/archive_replay.py" "$2"
fi
if [[ -n "${CASE01_AUTHOR_ARCHIVE_CONTEXT:-}" ]]; then
  echo "Historical archive context requires the explicit --historical-archive command." >&2
  exit 2
fi

WORK="${1:-$PWD/case01-reference-output}"
THREADS="${OMP_NUM_THREADS:-${SLURM_CPUS_PER_TASK:-1}}"
MPI_RANKS="${GMX_MPI_RANKS:-1}"
if [[ "${CASE01_DRY_RUN:-0}" == 1 ]]; then
  printf 'Dry run only; no files or dynamics will be produced.\n'
  printf 'work=%s\nGMX=%s\nPYTHON=%s\nthreads=%s mpi_ranks=%s\n' "$WORK" "$GMX" "$PYTHON" "$THREADS" "$MPI_RANKS"
  printf 'workflow=solvate9033,EM,NVT200ps,NPT200ps,production20ns,analysis\n'
  exit 0
fi

# Normalize lexically, then reject symlinks anywhere in the destination path
# before mkdir/cd can follow one into an unrelated tree.
WORK="$(python3 -c 'import os,sys; print(os.path.abspath(os.path.expanduser(sys.argv[1])))' "$WORK")"
cursor="/"
IFS='/' read -r -a work_parts <<< "${WORK#/}"
for part in "${work_parts[@]}"; do
  [[ -n "$part" ]] || continue
  cursor="${cursor%/}/$part"
  [[ ! -L "$cursor" ]] || { echo "Refusing symlink in work path: $cursor" >&2; exit 3; }
done
if [[ -e "$WORK" || -L "$WORK" ]]; then
  [[ -d "$WORK" && ! -L "$WORK" ]] || { echo "Refusing to use non-directory or symlink work path: $WORK" >&2; exit 3; }
  WORK="$(cd -- "$WORK" && pwd)"
else
  mkdir -p "$WORK"
  WORK="$(cd -- "$WORK" && pwd)"
fi

# GROMACS may restart from checkpoints or append to trajectory/energy files
# even when the corresponding TPR or log was removed. Refuse any prior run
# state before invoking tools or creating workflow outputs.
outputs=(
  em.tpr em.log em.gro em.edr em.xtc em.trr em.cpt
  nvt.tpr nvt.log nvt.gro nvt.edr nvt.xtc nvt.trr nvt.cpt
  npt.tpr npt.log npt.gro npt.edr npt.xtc npt.trr npt.cpt
  production.tpr production.log production.gro production.edr production.xtc production.trr production.cpt
  solvated.gro topol.template.top topol.runtime.top
  em.mdp nvt.mdp npt.mdp production.mdp run_case01.sh
  final logs science-validation analysis
  em_prev.cpt nvt_prev.cpt npt_prev.cpt production_prev.cpt
)
for name in "${outputs[@]}"; do
  if [[ -e "$WORK/$name" || -L "$WORK/$name" ]]; then
    echo "Refusing to reuse or overwrite existing workflow state: $WORK/$name" >&2
    exit 3
  fi
done

# GROMACS may leave split native outputs such as production.part0002.cpt or
# production.part0002.xtc. Any such file means this is not a fresh work tree.
if find "$WORK" \( -type f -o -type l \) -name '*part[0-9]*' -print -quit 2>/dev/null | grep -q .; then
  echo "Refusing to reuse prior split native output under: $WORK" >&2
  exit 3
fi

command -v "$GMX" >/dev/null || { echo "GROMACS executable not found: $GMX" >&2; exit 127; }
command -v "$PYTHON" >/dev/null || { echo "Python executable not found: $PYTHON" >&2; exit 127; }
"$PYTHON" -c 'import numpy, scipy, MDAnalysis' || { echo "Analysis dependencies required: NumPy, SciPy, MDAnalysis" >&2; exit 2; }

mkdir -p "$WORK/logs" "$WORK/final" "$WORK/science-validation"
cp "$IMPL"/assets/{em,nvt,npt,production}.mdp "$IMPL/assets/topol.template.top" "$WORK/"
mkdir -p "$WORK/analysis"
cp "$IMPL"/analysis/*.py "$WORK/analysis/"
cp "$HERE/solve.sh" "$WORK/run_case01.sh"
cp "$IMPL/validate_npt_grompp.py" "$WORK/analysis/"
cp "$IMPL/science-plan.md" "$WORK/science-validation/science-plan.md"
cd "$WORK"
export OMP_NUM_THREADS="$THREADS" OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1 CASE01_FFT_WORKERS="${CASE01_FFT_WORKERS:-$THREADS}"

cp topol.template.top topol.runtime.top
"$PYTHON" - <<'PY'
from pathlib import Path
p = Path("topol.runtime.top")
lines = p.read_text().splitlines()
in_molecules = False
kept = []
for line in lines:
    if line.strip().lower() == "[ molecules ]":
        in_molecules = True
        kept.append(line)
        continue
    if in_molecules and line.split(";", 1)[0].strip().split()[:1] == ["SOL"]:
        continue
    kept.append(line)
p.write_text("\n".join(kept) + "\n")
PY
"$GMX" solvate -cs spc216.gro -box 6.5 6.5 6.5 -maxsol 9033 -scale 0.50 -o solvated.gro -p topol.runtime.top > logs/solvate.log 2>&1
natoms="$(sed -n '2p' solvated.gro | tr -d '[:space:]')"
[[ "$natoms" == 27099 ]] || { echo "Expected 27099 atoms (9033 waters), got $natoms" >&2; exit 4; }

"$GMX" grompp -f em.mdp -c solvated.gro -p topol.runtime.top -o em.tpr -maxwarn 0 > logs/em-grompp.log 2>&1
"$GMX" mdrun -deffnm em -ntmpi "$MPI_RANKS" -ntomp "$THREADS" -cpt 15
grep -q 'Finished mdrun' em.log

"$GMX" grompp -f nvt.mdp -c em.gro -p topol.runtime.top -o nvt.tpr -maxwarn 0 > logs/nvt-grompp.log 2>&1
"$GMX" mdrun -deffnm nvt -ntmpi "$MPI_RANKS" -ntomp "$THREADS" -cpt 15
grep -q 'Finished mdrun' nvt.log

"$GMX" grompp -f npt.mdp -c nvt.gro -t nvt.cpt -p topol.runtime.top -o npt.tpr -maxwarn 1 > logs/npt-grompp.log 2>&1
"$PYTHON" analysis/validate_npt_grompp.py logs/npt-grompp.log
"$GMX" mdrun -deffnm npt -ntmpi "$MPI_RANKS" -ntomp "$THREADS" -cpt 15
grep -q 'Finished mdrun' npt.log

"$GMX" grompp -f production.mdp -c npt.gro -t npt.cpt -p topol.runtime.top -o production.tpr -maxwarn 0 > logs/production-grompp.log 2>&1
"$PYTHON" analysis/audit_tpr_exclusions.py production.tpr --json logs/production-tpr-exclusions.json
"$PYTHON" analysis/audit_tpr_settings.py production.tpr --gmx "$GMX" --kind production --json logs/production-tpr-settings.json --dump logs/production-tpr-dump.txt
"$GMX" mdrun -deffnm production -ntmpi "$MPI_RANKS" -ntomp "$THREADS" -cpt 15
grep -q 'Finished mdrun' production.log
cp production.log final/md_production.log
cp npt.gro npt.log nvt.log final/
"$GMX" check -s1 production.tpr -f production.xtc > logs/production-trajectory-check.txt 2>&1
"$GMX" check -e production.edr > logs/production-edr-check.txt 2>&1
"$GMX" --version > logs/gromacs-version.txt 2>&1

CASE01_DIR="$WORK" OUTDIR="$WORK/science-validation" PLAN_FILE="$WORK/science-validation/science-plan.md" GMX="$GMX" "$PYTHON" analysis/analytic_sanity.py > science-validation/analytic_sanity.json
CASE01_DIR="$WORK" OUTDIR="$WORK/science-validation" PLAN_FILE="$WORK/science-validation/science-plan.md" GMX="$GMX" "$PYTHON" analysis/independent_validation.py
CASE01_DIR="$WORK" OUTDIR="$WORK/science-validation" "$PYTHON" analysis/summarize_science_audit.py
"$PYTHON" "$IMPL/write_provenance.py" --root "$WORK" --gmx "$GMX" --python "$PYTHON"
printf 'Fresh Case01 run and analysis completed. Review final/observables.json scientific_status and gates.\n'
