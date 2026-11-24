#!/usr/bin/env bash
set -euo pipefail

APP="${APP:-/app}"
SOLUTION="${SOLUTION:-/solution}"
OUT="$APP/submission"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)-$(python3 -c 'import uuid; print(uuid.uuid4().hex[:8])')"
WORK="$APP/.case08-work-$STAMP"
NAME="case08-${STAMP}"

if [[ -e "$OUT" || -e "$WORK" ]]; then
  echo "refusing to overwrite existing Case 08 artifacts" >&2
  exit 73
fi
mkdir -p "$OUT" "$WORK/inputs"
cp "$APP"/environment/assets/{b.gro,u.gro,topol.top,NVT-50ps-dt1fs.mdp,NVT-50ps-dt2fs.mdp,NVT.mdp,conf_template.pdb,remote-input-provenance.json} "$WORK/inputs/"
cp "$SOLUTION/case08_remote.sh" "$SOLUTION/case08_tools.py" "$WORK/"
chmod 700 "$WORK/case08_remote.sh"
python3 - "$WORK" <<'PY'
import hashlib, json, sys
from pathlib import Path
root = Path(sys.argv[1])
sha = lambda path: hashlib.sha256(path.read_bytes()).hexdigest()
manifest = {
    "schema": "case08-source-manifest/v1",
    "case_id": "case-08-short-md-stop-go",
    "execution": "oracle",
    "sources": {name: sha(root / name) for name in ("case08_remote.sh", "case08_tools.py")},
    "inputs": {name: sha(root / "inputs" / name) for name in sorted(p.name for p in (root / "inputs").iterdir() if p.is_file())},
    "run_plan": {"labels": ["B-dt1fs", "B-dt2fs", "U-dt1fs", "U-dt2fs"],
                 "max_ps_each": 50, "max_total_ps": 200, "dt_fs": [1, 2]},
    "allocation": {"host": "hpc", "partition": "cpu", "nodes": 1,
                   "cpus": 8, "memory_gib": 8, "walltime": "00:30:00"},
}
(root / "source-manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
PY

cd "$APP"
hpc probe --host hpc --partition cpu --json > "$WORK/probe.json"
SNAPSHOT_SHA="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["snapshot_sha256"])' "$WORK/probe.json")"
hpc submit --profile cpu --name "$NAME" --src "$WORK" \
  --cmd 'bash case08_remote.sh' --nodes 1 --ntasks 1 --cpus 8 --mem 8G \
  --time 00:30:00 --reason 'Bounded four-run NVT timestep comparison for case-08; at most 200 ps total, one CPU node, 8 CPUs, 8 GiB, 30 minutes.' \
  --probe-snapshot "$WORK/probe.json" --snapshot-sha256 "$SNAPSHOT_SHA" > "$WORK/submission.json"

JOB_ID="$(python3 -c 'import json,sys; d=json.load(open(sys.argv[1])); print(d.get("job_id", ""))' "$WORK/submission.json")"
if [[ -z "$JOB_ID" ]]; then
  echo "hpc did not return a job handle" >&2
  exit 70
fi

set +e
hpc wait --job "$NAME" --poll 10 --timeout 1860 > "$WORK/scheduler.json"
WAIT_RC=$?
set -e
if (( WAIT_RC == 0 )); then
  hpc collect --job "$NAME" --dest "$WORK/collected"
else
  hpc collect --job "$NAME" --dest "$WORK/collected" --allow-unsuccessful
fi

if [[ -d "$WORK/collected/submission" ]]; then
  cp -a "$WORK/collected/submission/." "$OUT/"
else
  cp -a "$WORK/collected/." "$OUT/"
fi
cp "$WORK/submission.json" "$OUT/cli-submission.json"
cp "$WORK/scheduler.json" "$OUT/cli-scheduler.json"
cp "$WORK/probe.json" "$OUT/cli-probe-snapshot.json"
python3 "$SOLUTION/case08_tools.py" finalize --submission "$OUT" --assets "$APP/environment/assets" \
  --name "$NAME" --job-id "$JOB_ID" --wait-exit "$WAIT_RC"

[[ "$WAIT_RC" -eq 0 ]]
