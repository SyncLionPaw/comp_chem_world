#!/usr/bin/env bash
# Reference solution for case-02-coordination-geometry (not Agent-visible).
#
# Produces the expected output contract (coordination_report.json) by actually
# deriving every graded quantity from the deposited coordinates -- there is no
# tabulated gold table for this case, so the reference submission must recompute
# the ligand-SG / ligand-O first-shell distances, the Asp181 chi1 rotamer and the
# WPD-loop state from the same PDB files the agent is given.
#
#   Usage: solve.sh <workdir>            # writes <workdir>/coordination_report.json
#   Env:   CASE02_INPUT=<tarball or dir of *.pdb>   (optional override)
set -euo pipefail

WORK="${1:-$(pwd)}"
PKG="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
mkdir -p "$WORK"

: "${CASE02_INPUT:=$PKG/inputs/pdb/ptp1b_chimera_crystal_structures.tar.gz}"

python3 - "$CASE02_INPUT" "$WORK/coordination_report.json" <<'PY'
"""Derive the case-02-coordination-geometry report from the deposited coordinates.

Stdlib only.  Identical derivation to tests/verify.py, so the gold submission is
correct up to rounding by construction.
"""
import json, math, os, sys, tarfile, tempfile

STRUCTURE_IDS = ("2CM2", "3I80", "6B90", "6XE8", "6XEA", "6XED", "6XEE", "6XEF", "6XEG", "7S4F")
CATALYTIC_CYS = 215
WPD_ASP = 181
ROTAMER_TRANS_MIN = 120.0
WPD_CLOSED_MAX_A = 10.0

src, dest = sys.argv[1], sys.argv[2]
if src.endswith(".tar.gz") or src.endswith(".tgz"):
    tmp = tempfile.mkdtemp(prefix="case02_solve_")
    with tarfile.open(src) as tf:
        try:
            tf.extractall(tmp, filter="data")
        except TypeError:
            tf.extractall(tmp)
    pdb_dir = tmp
else:
    pdb_dir = src


def parse_pdb(path):
    atoms = []
    with open(path) as fh:
        for line in fh:
            if not (line.startswith("ATOM") or line.startswith("HETATM")):
                continue
            try:
                atoms.append({
                    "rec": line[:6].strip(),
                    "name": line[12:16].strip(),
                    "altloc": line[16].strip(),
                    "resname": line[17:20].strip(),
                    "resseq": int(line[22:26]),
                    "xyz": (float(line[30:38]), float(line[38:46]), float(line[46:54])),
                    "occ": float(line[54:60] or 0.0),
                })
            except (ValueError, IndexError):
                continue
    return atoms


def pick(atoms, resname, resseq, name):
    cands = [a for a in atoms if a["resname"] == resname and a["resseq"] == resseq
             and a["name"] == name]
    if not cands:
        return None
    cands.sort(key=lambda a: (-a["occ"], a["altloc"]))
    return cands[0]


def dihedral(p0, p1, p2, p3):
    """Signed torsion p0-p1-p2-p3, IUPAC handedness (validated on the right-handed
    alpha-helix residues 17-25 of 6XEA, which return phi ~ -60 deg)."""
    b1 = [p2[i] - p1[i] for i in range(3)]

    def cross(a, b):
        return [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]]

    def dot(a, b):
        return sum(x * y for x, y in zip(a, b))

    nb1 = math.sqrt(dot(b1, b1))
    bh = [x / nb1 for x in b1]
    u = [p0[i] - p1[i] for i in range(3)]
    v = [p3[i] - p2[i] for i in range(3)]
    up = [u[i] - dot(u, bh) * bh[i] for i in range(3)]
    vp = [v[i] - dot(v, bh) * bh[i] for i in range(3)]
    return math.degrees(math.atan2(dot(cross(up, vp), bh), dot(up, vp)))


def analyse(atoms):
    rec = {}
    central = [a for a in atoms if a["rec"] == "HETATM" and a["name"] in ("V", "W")]
    sg = pick(atoms, "CYS", CATALYTIC_CYS, "SG")
    if central:
        c = central[0]
        rec["ligand"] = c["resname"]
        rec["central_atom"] = c["name"]
        rec["ligand_sg_distance"] = round(math.dist(c["xyz"], sg["xyz"]), 3)
        oxy = [a for a in atoms if a["resname"] == c["resname"] and a["name"].startswith("O")]
        rec["ligand_o_distances"] = {a["name"]: round(math.dist(c["xyz"], a["xyz"]), 3)
                                     for a in oxy}
    else:
        rec["ligand"] = "none"
        rec["central_atom"] = None
        rec["ligand_sg_distance"] = None
        rec["ligand_o_distances"] = None

    n = pick(atoms, "ASP", WPD_ASP, "N"); ca = pick(atoms, "ASP", WPD_ASP, "CA")
    cb = pick(atoms, "ASP", WPD_ASP, "CB"); cg = pick(atoms, "ASP", WPD_ASP, "CG")
    chi1 = dihedral(n["xyz"], ca["xyz"], cb["xyz"], cg["xyz"])
    rec["asp181_chi1"] = round(chi1, 1)
    rec["asp181_rotamer"] = "productive" if abs(chi1) >= ROTAMER_TRANS_MIN else "unproductive"

    ca215 = pick(atoms, "CYS", CATALYTIC_CYS, "CA")
    d = math.dist(ca["xyz"], ca215["xyz"])
    rec["wpd_loop_state"] = "closed" if d <= WPD_CLOSED_MAX_A else "open"
    return rec


structures = {}
for pid in STRUCTURE_IDS:
    structures[pid] = analyse(parse_pdb(os.path.join(pdb_dir, pid + ".pdb")))

report = {
    "case_id": "case-02-coordination-geometry",
    "analysis": ("Per-structure active-site coordination geometry, catalytic aspartate "
                 "rotamer and WPD-loop state, derived from the deposited coordinates "
                 "in inputs/pdb/ptp1b_chimera_crystal_structures.tar.gz."),
    "structures": structures,
}
with open(dest, "w") as fh:
    json.dump(report, fh, indent=2)
    fh.write("\n")
print(f"solve.sh: wrote {dest}")
PY
