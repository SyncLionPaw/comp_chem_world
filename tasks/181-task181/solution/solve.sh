#!/usr/bin/env bash
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CASE="$(cd "$HERE/.." && pwd)"
APP="${APP:-$PWD}"
RUN_ROOT="$APP/runs/task181-mlmd-v2"
TMP_RUNNER="$(mktemp "${TMPDIR:-/tmp}/task181-runner.XXXXXX.py")"
trap 'rm -f "$TMP_RUNNER"' EXIT
cat > "$TMP_RUNNER" <<'PY_RUNNER'
#!/usr/bin/env python3
"""Render LAMMPS data/input files from the pinned geometry-only starts."""
import argparse
import hashlib
import json
import math
import re
import shutil
from pathlib import Path

TRUSTED_INPUT_MANIFEST_SHA256 = "9639b23004bd5b34d28284563ad10e074786d1560f21cdb7103390899457408d"


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def parse_include(path):
    text = path.read_text(encoding="utf-8")
    cm = re.search(r"&COORD\s*(.*?)&END\s*", text, re.S | re.I)
    bm = re.search(r"&CELL\s*(.*?)&END", text, re.S | re.I)
    if not cm or not bm:
        raise ValueError("geometry include lacks COORD/CELL")
    atoms = []
    for line in cm.group(1).splitlines():
        fields = line.split()
        if not fields:
            continue
        if len(fields) != 4 or fields[0] not in {"O", "H"}:
            raise ValueError("invalid geometry atom row")
        xyz = tuple(float(x) for x in fields[1:])
        if not all(math.isfinite(x) for x in xyz):
            raise ValueError("nonfinite coordinate")
        atoms.append((fields[0], xyz))
    vectors = []
    for axis in "ABC":
        m = re.search(rf"^\s*{axis}\s+([-+0-9.eE]+)\s+([-+0-9.eE]+)\s+([-+0-9.eE]+)\s*$", bm.group(1), re.M)
        if not m:
            raise ValueError("invalid periodic cell vector")
        vectors.append(tuple(float(x) for x in m.groups()))
    if len(atoms) != 192 or sum(x[0] == "O" for x in atoms) != 64 or sum(x[0] == "H" for x in atoms) != 128:
        raise ValueError("starting frame must be O64H128")
    if any(abs(vectors[i][j] - (12.4 if i == j else 0.0)) > 1e-9 for i in range(3) for j in range(3)):
        raise ValueError("only the pinned 12.4-A orthogonal box is supported")
    return atoms


def write_data(path, include):
    atoms = parse_include(include)
    lines = ["Bench28 Task181 starting configuration (derived from pinned CP2K geometry include)", "", "192 atoms", "2 atom types", "", "0.0 12.4 xlo xhi", "0.0 12.4 ylo yhi", "0.0 12.4 zlo zhi", "", "Masses", "", "1 15.999", "2 1.008", "", "Atoms # atomic", ""]
    for atom_id, (element, xyz) in enumerate(atoms, 1):
        typ = 1 if element == "O" else 2
        lines.append(f"{atom_id} {typ} {xyz[0]:.12g} {xyz[1]:.12g} {xyz[2]:.12g}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _runtime_path(path):
    value = str(path.resolve())
    if (re.fullmatch(r"/[A-Za-z0-9._+:/-]+", value) is None or "//" in value
            or any(part in {".", ".."} for part in value.split("/")[1:])):
        raise ValueError(f"runtime path is not safe for the LAMMPS template: {value!r}")
    return value


def stage_models(models, model_hashes, destination):
    destination = Path(destination)
    if destination.exists() or destination.is_symlink():
        raise SystemExit(f"refusing to overwrite staged models: {destination}")
    if len(models) != len(model_hashes):
        raise SystemExit("pinned model list and hash list differ")
    destination.mkdir(parents=True)
    staged = []
    for index, (source, expected_hash) in enumerate(zip(models, model_hashes)):
        target = destination / f"member-{index}.pb"
        shutil.copyfile(source, target)
        if target.is_symlink() or digest(target) != expected_hash:
            raise SystemExit(f"staged model hash mismatch for member {index}")
        staged.append(target)
    return staged


def render(template, output, data, models, plugin, seed):
    text = template.read_text(encoding="utf-8")
    runtime = {
        "start_data": _runtime_path(data),
        "models": [_runtime_path(model) for model in models],
        "plugin": _runtime_path(plugin),
    }
    mapping = {"@START_DATA@": runtime["start_data"], "@MODEL0@": runtime["models"][0], "@MODEL1@": runtime["models"][1], "@MODEL2@": runtime["models"][2], "@MODEL3@": runtime["models"][3], "@DEEPMD_PLUGIN@": runtime["plugin"], "variable SEED equal 101": f"variable SEED equal {seed}"}
    for key, value in mapping.items():
        text = text.replace(key, value)
    if re.search(r"@[A-Z0-9_]+@", text):
        raise ValueError("LAMMPS template has unresolved tokens")
    output.write_text(text, encoding="utf-8")
    return runtime


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--case-root", type=Path, required=True)
    p.add_argument("--run-root", type=Path, required=True)
    p.add_argument("--plugin", type=Path, required=True)
    a = p.parse_args()
    case = a.case_root.resolve(strict=True)
    run_root = a.run_root.resolve()
    if run_root.exists() or run_root.is_symlink():
        raise SystemExit(f"refusing to overwrite {run_root}")
    assets = case / "environment/assets/v2/fresh-run"
    manifest_path = assets / "provenance.json"
    if digest(manifest_path) != TRUSTED_INPUT_MANIFEST_SHA256:
        raise SystemExit("trusted visible-input manifest hash mismatch")
    manifest = json.loads(manifest_path.read_text())
    if manifest.get("schema") != "bench28-case03-v2-visible-inputs/v1":
        raise SystemExit("unexpected visible-input manifest")
    for row in manifest["visible_files"] + manifest["models"]:
        path = case / row["path"]
        if path.is_symlink() or not path.is_file() or digest(path) != row["sha256"]:
            raise SystemExit(f"input hash mismatch: {row['path']}")
    if a.plugin.is_symlink() or not a.plugin.is_file():
        raise SystemExit("DeepMD LAMMPS plugin missing or unsafe")
    run_root.mkdir(parents=True)
    model_sources = [assets / "models" / f"member-{i}.pb" for i in range(4)]
    pinned_model_hashes = {row["path"]: row["sha256"] for row in manifest["models"]}
    model_hashes = [pinned_model_hashes[model.relative_to(case).as_posix()] for model in model_sources]
    models = stage_models(model_sources, model_hashes, run_root / "models")
    for index, (geom_id, seed) in enumerate((("0000", 701), ("0010", 1701))):
        run = run_root / f"replica-{index}"
        run.mkdir()
        data = run / "start.data"
        write_data(data, assets / "geometries" / geom_id / "coord_n_cell.inc")
        runtime = render(assets / "lammps.template.in", run / "lammps.in", data, models, a.plugin, seed)
        runtime_bindings = {
            "start_data": {"path": runtime["start_data"], "sha256": digest(data)},
            "models": [
                {"member_index": i, "path": runtime["models"][i], "sha256": model_hashes[i]}
                for i in range(4)
            ],
        }
        (run / "render-manifest.json").write_text(json.dumps({"start_geometry_id": geom_id, "start_geometry_sha256": digest(assets / "geometries" / geom_id / "coord_n_cell.inc"), "lammps_input_sha256": digest(run / "lammps.in"), "data_sha256": digest(data), "model_sha256_by_member": model_hashes, "runtime_bindings": runtime_bindings, "seed": seed}, indent=2) + "\n")
    print(f"Rendered two fresh 20,000-step inputs under {run_root}; no LAMMPS process was started.")


if __name__ == "__main__":
    main()
PY_RUNNER
LAMMPS_BIN="${LAMMPS_BIN:-lmp}"
DEEPMD_LAMMPS_PLUGIN="${DEEPMD_LAMMPS_PLUGIN:-}"

if [[ -z "$DEEPMD_LAMMPS_PLUGIN" || ! -f "$DEEPMD_LAMMPS_PLUGIN" ]]; then
  echo 'Set DEEPMD_LAMMPS_PLUGIN to the site DeepMD LAMMPS plugin.' >&2
  exit 2
fi
if ! command -v "$LAMMPS_BIN" >/dev/null 2>&1; then
  echo "LAMMPS executable not found: $LAMMPS_BIN" >&2
  exit 2
fi
if [[ -e "$RUN_ROOT" || -L "$RUN_ROOT" ]]; then
  echo "refusing to overwrite $RUN_ROOT" >&2
  exit 2
fi

python3 -I "$TMP_RUNNER" --case-root "$CASE" --run-root "$RUN_ROOT" --plugin "$DEEPMD_LAMMPS_PLUGIN"
for run in "$RUN_ROOT"/replica-*; do
  (
    cd "$run"
    "$LAMMPS_BIN" -in lammps.in -log log.lammps
  )
  for output in log.lammps dump.lammpstrj model_devi.out; do
    [[ -s "$run/$output" ]] || { echo "missing LAMMPS output: $run/$output" >&2; exit 1; }
  done
done

python3 - "$RUN_ROOT" <<'PY'
import hashlib, json, os, socket, sys
from pathlib import Path
root=Path(sys.argv[1])
def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()
rows=[]
for run in sorted(root.glob('replica-*')):
    rows.append({'replica':run.name,'files':{p.name:sha(p) for p in sorted(run.iterdir()) if p.is_file() and p.name != 'render-manifest.json'}})
(root/'execution-manifest.json').write_text(json.dumps({'schema':'task181-app-execution-manifest/v1','execution_claim':'APP-side self-report only; trusted host receipt required for formal verification','host_reported':socket.gethostname(),'slurm_job_id_reported':os.environ.get('SLURM_JOB_ID'),'replicas':rows},indent=2)+'\n')
PY
echo "Fresh LAMMPS outputs are in $RUN_ROOT; APP-side provenance is not a trusted host receipt."
