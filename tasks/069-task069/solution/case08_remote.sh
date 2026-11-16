#!/usr/bin/env bash
set -uo pipefail

ROOT="$(pwd)"
SUB="$ROOT/submission"
AS="$ROOT/inputs"
mkdir -p "$SUB/runs"
START_EPOCH="$(date -u +%s)"
START_UTC="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
JOB_ID="${SLURM_JOB_ID:-unknown}"
HOST="$(hostname -f 2>/dev/null || hostname)"

python3 - "$ROOT" "$AS" <<'PY'
import hashlib, json, sys
from pathlib import Path
root, inputs = Path(sys.argv[1]), Path(sys.argv[2])
manifest = json.loads((root / "source-manifest.json").read_text())
sha = lambda path: hashlib.sha256(path.read_bytes()).hexdigest()
if manifest.get("schema") != "case08-source-manifest/v1" or manifest.get("case_id") != "case-08-short-md-stop-go" or manifest.get("execution") != "oracle":
    raise SystemExit("source manifest identity mismatch")
if set(manifest.get("sources", {})) != {"case08_remote.sh", "case08_tools.py"}:
    raise SystemExit("source manifest does not cover the full remote source set")
for name, expected in manifest.get("sources", {}).items():
    if sha(root / name) != expected:
        raise SystemExit("remote source hash mismatch: " + name)
expected_inputs = {"NVT-50ps-dt1fs.mdp", "NVT-50ps-dt2fs.mdp", "NVT.mdp", "b.gro", "conf_template.pdb", "remote-input-provenance.json", "topol.top", "u.gro"}
if set(manifest.get("inputs", {})) != expected_inputs:
    raise SystemExit("source manifest does not cover the full input set")
for name, expected in manifest.get("inputs", {}).items():
    if sha(inputs / name) != expected:
        raise SystemExit("remote input hash mismatch: " + name)
plan = manifest.get("run_plan", {})
if plan.get("labels") != ["B-dt1fs", "B-dt2fs", "U-dt1fs", "U-dt2fs"] or plan.get("max_ps_each") != 50 or plan.get("max_total_ps") != 200:
    raise SystemExit("remote run-plan bounds mismatch")
allocation = manifest.get("allocation", {})
if (allocation.get("nodes"), allocation.get("cpus"), allocation.get("memory_gib"), allocation.get("walltime")) != (1, 8, 8, "00:30:00"):
    raise SystemExit("remote allocation bounds mismatch")
PY
if [[ $? -ne 0 ]]; then exit 70; fi
cp "$ROOT/source-manifest.json" "$SUB/source-manifest.json"

if ! type module >/dev/null 2>&1; then
  for init in /etc/profile.d/modules.sh /usr/share/Modules/init/bash /etc/profile.d/lmod.sh; do
    if [[ -r "$init" ]]; then
      # shellcheck disable=SC1090
      source "$init"
      break
    fi
  done
fi
if ! type module >/dev/null 2>&1; then
  printf '%s\n' 'INFRA_ERROR: environment-modules command is unavailable' >&2
  exit 70
fi
module load gromacs/2022.6 || exit 70
GMX="$(command -v gmx)"
"$GMX" --version > "$SUB/gromacs-version.txt" 2>&1 || exit 70
python3 "$ROOT/case08_tools.py" index --gro "$AS/b.gro" --out "$ROOT/index.ndx" || exit 70

any_failure=0
any_run=0
for state in B U; do
  for dt in 1 2; do
    LABEL="${state}-dt${dt}fs"
    RUN="$SUB/runs/$LABEL"
    mkdir -p "$RUN"
    if [[ "$state" == B ]]; then COORD="$AS/b.gro"; else COORD="$AS/u.gro"; fi
    if [[ "$dt" == 1 ]]; then MDP="$AS/NVT-50ps-dt1fs.mdp"; else MDP="$AS/NVT-50ps-dt2fs.mdp"; fi
    cp "$COORD" "$RUN/start.gro"
    cp "$MDP" "$RUN/input.mdp"
    cp "$AS/topol.top" "$RUN/topol.top"
    cp "$ROOT/index.ndx" "$RUN/index.ndx"
    cp "$AS/NVT.mdp" "$RUN/source-NVT-audit-only.mdp"
    (
      cd "$RUN"
      "$GMX" grompp -f input.mdp -c start.gro -p topol.top -n index.ndx \
        -o topol.tpr -po mdout.mdp -pp processed.top > grompp.console.log 2>&1
    )
    GROMPP_RC=$?
    if (( GROMPP_RC != 0 )); then
      printf '{"stage":"grompp","exit_code":%s}\n' "$GROMPP_RC" > "$RUN/failure.json"
      any_failure=1
      continue
    fi
    "$GMX" dump -s "$RUN/topol.tpr" > "$RUN/tpr-state-dump.txt" 2> "$RUN/tpr-dump.stderr"
    DUMP_RC=$?
    if (( DUMP_RC != 0 )); then
      printf '{"stage":"gmx-dump","exit_code":%s}\n' "$DUMP_RC" > "$RUN/failure.json"
      any_failure=1
      continue
    fi
    ELAPSED=$(( $(date -u +%s) - START_EPOCH ))
    LEFT=$((1680 - ELAPSED))
    if (( LEFT < 45 )); then
      printf '{"stage":"mdrun","status":"not_started_wall_guard","remaining_seconds":%s}\n' "$LEFT" > "$RUN/failure.json"
      any_failure=1
      continue
    fi
    MAXHOURS="$(python3 -c 'import sys; print(f"{max(1,int(sys.argv[1])-30)/3600:.6f}")' "$LEFT")"
    OMP_NUM_THREADS=8 "$GMX" mdrun -s "$RUN/topol.tpr" -deffnm "$RUN/md" \
      -ntmpi 1 -ntomp 8 -cpt 5 -maxh "$MAXHOURS" > "$RUN/mdrun.console.log" 2>&1
    MDRUN_RC=$?
    any_run=1
    if (( MDRUN_RC != 0 )); then
      printf '{"stage":"mdrun","exit_code":%s,"note":"native logs and available artifacts retained"}\n' "$MDRUN_RC" > "$RUN/failure.json"
      any_failure=1
      continue
    fi
    (
      cd "$RUN"
      printf '%s\n' 'Potential' 'Kinetic-En.' 'Total-Energy' 'Conserved-En.' \
        'Temperature' 'Constr.-rmsd' 'T-OCB' 'T-MOL' 'T-Water_and_ions' '0' | \
        "$GMX" energy -f md.edr -o energy.xvg > gmx-energy.log 2>&1
    )
    ENERGY_RC=$?
    if (( ENERGY_RC != 0 )); then
      printf '{"stage":"gmx-energy","exit_code":%s}\n' "$ENERGY_RC" > "$RUN/failure.json"
      any_failure=1
      continue
    fi
    python3 - "$RUN/energy.xvg" <<'PY'
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from case08_tools import read_xvg
labels = {"Potential", "Kinetic En.", "Total Energy", "Conserved En.", "Temperature", "Constr. rmsd", "T-OCB", "T-MOL", "T-Water_and_ions"}
observed, rows = read_xvg(Path(sys.argv[1]))
missing = labels - set(observed)
if missing or not rows:
    raise SystemExit("gmx energy output is missing required terms: " + ", ".join(sorted(missing)))
PY
    ENERGY_CHECK_RC=$?
    if (( ENERGY_CHECK_RC != 0 )); then
      printf '{"stage":"gmx-energy-validation","exit_code":%s}\n' "$ENERGY_CHECK_RC" > "$RUN/failure.json"
      any_failure=1
      continue
    fi
    (
      cd "$RUN"
      printf '%s\n' 'System' | "$GMX" trjconv -f md.xtc -s topol.tpr \
        -o sample.gro -skip 10 -sep > trjconv.log 2>&1
    )
    FRAME_RC=$?
    if (( FRAME_RC != 0 )); then
      printf '{"stage":"trjconv","exit_code":%s}\n' "$FRAME_RC" > "$RUN/failure.json"
      any_failure=1
    fi
  done
done

END_EPOCH="$(date -u +%s)"
END_UTC="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
python3 "$ROOT/case08_tools.py" analyze --submission "$SUB" --assets "$AS" \
  --job-id "$JOB_ID" --host "$HOST" --start "$START_UTC" --end "$END_UTC" \
  --elapsed "$((END_EPOCH - START_EPOCH))" --cpus "${SLURM_CPUS_PER_TASK:-8}" \
  --mem "${SLURM_MEM_PER_NODE:-unknown}" --gmx-version "$SUB/gromacs-version.txt" \
  --source-manifest "$ROOT/source-manifest.json"
ANALYZE_RC=$?
if (( ANALYZE_RC != 0 )); then exit 70; fi
if (( any_run == 0 || any_failure != 0 )); then exit 1; fi
exit 0
