#!/usr/bin/env bash
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CASE="$(cd "$HERE/.." && pwd)"
APP="${APP:-$PWD}"
RUN_ROOT="$APP/runs/cp2k-label-v2"
TMP_RUNNER="$(mktemp "${TMPDIR:-/tmp}/task180-runner.XXXXXX.py")"
trap 'rm -f "$TMP_RUNNER"' EXIT
cat > "$TMP_RUNNER" <<'PY_RUNNER'
#!/usr/bin/env python3
"""Parse fresh CP2K ENERGY_FORCE outputs into a labeled-data table."""
import argparse
import hashlib
import json
import math
import os
import re
import socket
from pathlib import Path

HA_EV = 27.211386245988
HA_BOHR_EV_A = 51.422067476325886
ORDINALS = (0, 10, 19)
FLOAT = r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[Ee][-+]?\d+)?"


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def parse_include(path):
    text = path.read_text(encoding="utf-8")
    coord = re.search(r"&COORD\s*(.*?)&END\s*", text, re.S | re.I)
    cell = re.search(r"&CELL\s*(.*?)&END", text, re.S | re.I)
    if not coord or not cell:
        raise ValueError("coordinate include lacks COORD or CELL")
    atoms = []
    for line in coord.group(1).splitlines():
        fields = line.split()
        if not fields:
            continue
        if len(fields) != 4 or fields[0] not in ("O", "H"):
            raise ValueError("invalid coordinate row")
        xyz = [float(x) for x in fields[1:]]
        if not all(math.isfinite(x) for x in xyz):
            raise ValueError("nonfinite coordinate")
        atoms.append((fields[0], xyz))
    vectors = []
    for axis in "ABC":
        m = re.search(rf"^\s*{axis}\s+({FLOAT})\s+({FLOAT})\s+({FLOAT})\s*$", cell.group(1), re.M)
        if not m:
            raise ValueError("invalid cell vector")
        vectors.append([float(x) for x in m.groups()])
    if len(atoms) != 192 or sum(x[0] == "O" for x in atoms) != 64 or sum(x[0] == "H" for x in atoms) != 128:
        raise ValueError("expected 192-atom O64H128 cell")
    return atoms, vectors


def parse_output(path, atoms, source_cell):
    text = path.read_text(errors="replace")
    if not re.search(r"SCF run converged", text, re.I) or re.search(r"SCF run NOT converged|forrtl.? error", text, re.I):
        raise ValueError("CP2K output has no positive SCF convergence record")
    if text.count("PROGRAM ENDED AT") != 1:
        raise ValueError("CP2K output lacks a unique normal-end marker")
    for pattern in (r"FUNCTIONAL\|\s+BECKE88:", r"FUNCTIONAL\|\s+LYP:", r"vdW POTENTIAL\|\s+DFT-D3", r"Orbital Basis Set\s+TZV2P-GTH"):
        if not re.search(pattern, text, re.I):
            raise ValueError("CP2K output method echo differs from the requested BLYP-D3/TZV2P setup")
    coords = text.split("MODULE QUICKSTEP: ATOMIC COORDINATES IN ANGSTROM")
    if len(coords) != 2:
        raise ValueError("native coordinate echo missing or repeated")
    cr = re.findall(rf"^\s*(\d+)\s+\d+\s+([A-Za-z]+)\s+\d+\s+({FLOAT})\s+({FLOAT})\s+({FLOAT})\s+", coords[1], re.M)
    if [int(x[0]) for x in cr] != list(range(1, 193)) or [x[1] for x in cr] != [x[0] for x in atoms]:
        raise ValueError("native coordinate echo does not preserve submitted atom order")
    for got, source in zip(cr, atoms):
        if any(abs(float(got[i + 2]) - source[1][i]) > 5.1e-7 for i in range(3)):
            raise ValueError("native coordinate echo differs from submitted geometry")
    et = re.findall(rf"ENERGY\|\s+Total FORCE_EVAL \( QS \) energy \[a\.u\.\]:\s*({FLOAT})", text)
    blocks = text.split("ATOMIC FORCES in [a.u.]")
    if len(et) != 1 or len(blocks) != 2:
        raise ValueError("expected exactly one CP2K energy and force block")
    fb = blocks[1].split("SUM OF ATOMIC FORCES", 1)[0]
    fr = re.findall(rf"^\s*(\d+)\s+\d+\s+([A-Za-z]+)\s+({FLOAT})\s+({FLOAT})\s+({FLOAT})\s*$", fb, re.M)
    if [int(x[0]) for x in fr] != list(range(1, 193)) or [x[1] for x in fr] != [x[0] for x in atoms]:
        raise ValueError("native force rows do not map to submitted atom order")
    cellrows = re.findall(rf"CELL\| Vector ([abc]) \[angstrom\]:\s*({FLOAT})\s+({FLOAT})\s+({FLOAT})", text)
    if [x[0] for x in cellrows] != ["a", "b", "c"]:
        raise ValueError("native cell echo missing")
    cell = [[float(v) for v in x[1:]] for x in cellrows]
    if any(abs(cell[i][j] - source_cell[i][j]) > 5.1e-4 for i in range(3) for j in range(3)):
        raise ValueError("native cell echo differs from submitted geometry")
    e_ha = float(et[0])
    f_ha = [[float(v) for v in x[2:5]] for x in fr]
    e_ev = e_ha * HA_EV
    f_ev = [[v * HA_BOHR_EV_A for v in row] for row in f_ha]
    if not math.isfinite(e_ev) or any(not math.isfinite(x) for row in f_ev for x in row):
        raise ValueError("nonfinite energy or force")
    return e_ha, e_ev, f_ha, f_ev, cell


def collect(run_root):
    rows = []
    for ordinal in ORDINALS:
        run = run_root / f"label-{ordinal:04d}"
        inp, include, output, status_path = run / "cp2k.inp", run / "coord_n_cell.inc", run / "output", run / "exit-status.json"
        if not all(p.is_file() and not p.is_symlink() for p in (inp, include, output, status_path)):
            raise ValueError(f"missing or unsafe native output bundle for label job {ordinal}")
        status = json.loads(status_path.read_text(encoding="utf-8"))
        if not isinstance(status, dict) or type(status.get("exit_code")) is not int or status.get("exit_code") != 0:
            raise ValueError(f"CP2K process did not report exit code zero for label job {ordinal}")
        text = inp.read_text()
        if "RUN_TYPE ENERGY_FORCE" not in text or "CUTOFF 500" not in text or "REL_CUTOFF 60" not in text or "GTH-BLYP" not in text:
            raise ValueError("submitted CP2K input differs from frozen method")
        atoms, source_cell = parse_include(include)
        e_ha, e_ev, f_ha, f_ev, cell = parse_output(output, atoms, source_cell)
        rows.append({"label_job_ordinal": ordinal, "exit_status": status, "input_sha256": sha(inp), "geometry_sha256": sha(include), "native_output_sha256": sha(output), "atom_count": len(atoms), "composition": {"O": 64, "H": 128}, "cell_angstrom": cell, "scf": "CONVERGED", "normal_end": True, "method": "BLYP-D3 / TZV2P-GTH / GTH-BLYP / 500 Ry / REL_CUTOFF 60", "energy_hartree": e_ha, "energy_eV": e_ev, "forces_hartree_per_bohr": f_ha, "forces_eV_per_angstrom": f_ev})
    return {"schema": "task180-native-labels/v2", "execution_claim": "APP-side self-report only; not a trusted host receipt", "host_reported": socket.gethostname(), "slurm_job_id_reported": os.environ.get("SLURM_JOB_ID"), "unit_conversion": {"hartree_to_ev": HA_EV, "hartree_per_bohr_to_ev_per_angstrom": HA_BOHR_EV_A}, "records": rows}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-root", type=Path, required=True)
    ap.add_argument("--output", type=Path, required=True)
    a = ap.parse_args()
    result = collect(a.run_root.resolve())
    a.output.parent.mkdir(parents=True, exist_ok=True)
    a.output.write_text(json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
PY_RUNNER
INPUT_ROOT="$CASE/environment/assets/v2/native-labels/label"
CP2K_BIN="${CP2K_BIN:-cp2k.psmp}"

if [[ ! -x "$(command -v "$CP2K_BIN" 2>/dev/null || true)" ]]; then
  echo "CP2K executable not found: $CP2K_BIN (set CP2K_BIN or load the site CP2K module)" >&2
  exit 2
fi
if [[ -n "${CP2K_DATA_DIR:-}" ]]; then
  for data_file in GTH_BASIS_SETS GTH_POTENTIALS dftd3.dat; do
    if [[ ! -r "$CP2K_DATA_DIR/$data_file" ]]; then
      echo "CP2K_DATA_DIR lacks required readable file: $CP2K_DATA_DIR/$data_file" >&2
      exit 2
    fi
  done
fi
if [[ -e "$RUN_ROOT" || -L "$RUN_ROOT" ]]; then
  echo "refusing to overwrite $RUN_ROOT" >&2
  exit 2
fi
mkdir -p "$RUN_ROOT"

for ordinal in 0000 0010 0019; do
  source="$INPUT_ROOT/cp2k-inc-$ordinal"
  run="$RUN_ROOT/label-$ordinal"
  mkdir "$run"
  cp "$source/coord_n_cell.inc" "$run/coord_n_cell.inc"
  sed "s/@PROJECT_NAME@/task180_label_$ordinal/" "$source/cp2k.inp" > "$run/cp2k.inp"
  set +e
  (
    cd "$run"
    "$CP2K_BIN" -i cp2k.inp -o output
  )
  exit_code=$?
  set -e
  printf '{"exit_code": %d, "claim": "candidate-side process status; not host attestation"}\n' "$exit_code" > "$run/exit-status.json"
  if [[ "$exit_code" -ne 0 ]]; then
    echo "CP2K failed for label $ordinal with exit code $exit_code" >&2
    exit "$exit_code"
  fi
done

python3 -I "$TMP_RUNNER" --run-root "$RUN_ROOT" --output "$APP/final/native-labels.json"
echo "Fresh CP2K outputs are in $RUN_ROOT; candidate-side provenance is not a trusted host receipt."
