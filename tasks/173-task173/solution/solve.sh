#!/bin/sh
set -eu
APP_DIR=${APP:-/app}
ASSETS="$APP_DIR/environment/assets"
mkdir -p "$APP_DIR/final"
PYTHON=${PYTHON:-python3}
PYTHONDONTWRITEBYTECODE=1 "$PYTHON" - "$ASSETS" "$APP_DIR/final/composition.json" <<'PY'
import json, math, re, sys
from collections import Counter
from pathlib import Path
assets, output = map(Path, sys.argv[1:])
xyz = (assets / "frame_late.xyz").read_text().splitlines()
n_atoms = int(xyz[0].strip())
comment = xyz[1]
match = re.search(r"cubic\s+box\s+([0-9]+(?:\.[0-9]*)?)", comment, re.I)
if not match:
    match = re.search(r"(?:box(?:_length)?|L)\s*[=:]\s*([0-9]+(?:\.[0-9]*)?)\s*(?:A|angstrom)?", comment, re.I)
if not match:
    match = re.search(r"([0-9]+(?:\.[0-9]*)?)\s*(?:Å|angstrom)\b", comment, re.I)
if not match:
    raise ValueError("XYZ comment has no readable box edge")
box = float(match.group(1))
elements = Counter(line.split()[0] for line in xyz[2:] if line.split())
if sum(elements.values()) != n_atoms:
    raise ValueError("XYZ atom count does not match coordinate records")
# Each TFSI anion is C2F6NO4S2; N uniquely counts intact anions.
n_tfsi = elements["N"]
n_li = elements["Li"]
n_water = elements["H"] // 2
if elements["H"] % 2 or elements["O"] != 4*n_tfsi + n_water or elements["C"] != 2*n_tfsi or elements["F"] != 6*n_tfsi or elements["S"] != 2*n_tfsi:
    raise ValueError("element counts do not match LiTFSI plus H2O stoichiometry")
if n_water == 0 or n_li == 0:
    raise ValueError("molality and water-to-lithium ratio require Li and water")
params = {}
for line in (assets / "experimental_sans.txt").read_text().splitlines():
    m = re.match(r"\s*sans_peak_(q_min|q_max)_Ainv\s+([0-9.eE+-]+)\s*$", line)
    if m:
        params[m.group(1)] = float(m.group(2))
if set(params) != {"q_min", "q_max"} or not (0 < params["q_min"] <= params["q_max"]):
    raise ValueError("invalid or missing SANS q window")
qmin, qmax = params["q_min"], params["q_max"]
repeat = [2*math.pi/qmax, 2*math.pi/qmin]
midpoint_repeat = 2*math.pi/((qmin+qmax)/2)
result = {
    "n_atoms": n_atoms, "n_Li": n_li, "n_TFSI": n_tfsi, "n_H2O": n_water,
    "charge_neutral": n_li == n_tfsi,
    "molality_mol_kg": (n_tfsi/6.02214076e23)/(n_water*18.01528e-3/6.02214076e23),
    "n_H2O_per_Li": n_water/n_li, "box_length_A": box,
    "sans_repeat_A": repeat,
    "correlation_lengths_along_edge": box/midpoint_repeat,
    "cell_spans_multiple_repeats": box > midpoint_repeat,
}
output.write_text(json.dumps(result, indent=2) + "\n")
PY
