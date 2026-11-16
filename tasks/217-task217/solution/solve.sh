#!/usr/bin/env bash
# =============================================================================
#  case-04-force-field-validation gold path -- REFERENCE SOLUTION.  NOT AGENT-VISIBLE.
# =============================================================================
#
#  Independently re-derives the two frozen deliverables from the deposited Q6
#  `.fep` files and writes them into the output directory:
#
#      topology_integrity_report.json
#      parameter_consistency_matrix.json
#
#  This implementation is deliberately written separately from tests/verify.py
#  so that a 1.0 calibration demonstrates the verifier accepts an independently
#  produced correct answer, not merely its own reflection.
#
#  Usage: solve.sh [outdir]      (default: current directory)
# =============================================================================
set -euo pipefail

PKG="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ARCHIVE="$PKG/inputs/zenodo/evb_q6_inputs_parameters.tar.gz"
OUT="${1:-$PWD}"
mkdir -p "$OUT"

python3 - "$ARCHIVE" "$OUT" <<'PYTHON'
import json
import re
import sys
import tarfile
from pathlib import Path

archive, out = Path(sys.argv[1]), Path(sys.argv[2])
SYSTEMS = ["chimera1", "chimera3", "chimera4", "chimera7"]
RES = {"1": "ASP", "ASP": "ASP", "2": "CSP", "CSP": "CSP", "3": "HOW", "HOW": "HOW"}


def canonical(raw):
    """'1.CB' / 'ASP.CB' -> ('ASP', 'CB')."""
    if "." not in raw:
        return None
    residue, atom = raw.rsplit(".", 1)
    residue = RES.get(residue.strip()) or RES.get(residue.strip().upper())
    return (residue, atom.strip().upper()) if residue else None


def parse(text):
    section = None
    rows = {"atoms": [], "atom_types": {}, "change_atoms": [], "change_bonds": []}
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith("[") and line.endswith("]"):
            section = line.strip("[]").strip().lower()
            continue
        if line.startswith("#") or line.startswith("!"):
            continue
        data = re.split(r"\s*#", line, maxsplit=1)[0].strip()
        if not data:
            continue
        whole, tokens = line.split(), data.split()
        if section == "atoms" and len(whole) >= 5:
            rows["atoms"].append({"q": int(whole[0]), "pdb": int(whole[1]),
                                  "pdb_id": whole[3], "label": whole[4]})
        elif section == "atom_types" and len(tokens) >= 8:
            rows["atom_types"][tokens[0]] = {
                "Ai": float(tokens[1]), "Bi": float(tokens[2]),
                "Ci": float(tokens[3]), "ai": float(tokens[4]), "mass": float(tokens[7]),
            }
        elif section == "change_atoms" and len(tokens) >= 3:
            rows["change_atoms"].append((int(tokens[0]), tokens[1], tokens[2]))
        elif section == "change_bonds" and len(tokens) >= 4:
            rows["change_bonds"].append(tuple(int(x) for x in tokens[:4]))
    return rows


integrity = {"case_id": "case-04-force-field-validation", "systems": {}}
per_system_atom_types = []

with tarfile.open(archive, "r:gz") as handle:
    names = handle.getnames()
    for system in SYSTEMS:
        member = next(n for n in names if n.endswith(f"libs/{system}.fep"))
        rows = parse(handle.extractfile(member).read().decode("utf-8", "replace"))

        labels = [a["label"] for a in rows["atoms"]]

        # Coverage: every type the reaction region references in either state
        # must be defined in [atom_types].
        referenced = set()
        for _q, t1, t2 in rows["change_atoms"]:
            referenced.update((t1, t2))
        coverage_complete = bool(referenced) and all(t in rows["atom_types"] for t in referenced)

        # Mechanism: resolve the PDB indices in [change_bonds] back to labels.
        by_pdb = {a["pdb"]: a["label"] for a in rows["atoms"]}
        s_p_break = p_o_form = False
        for a, b, t1, t2 in rows["change_bonds"]:
            pair = {canonical(by_pdb.get(a, "")), canonical(by_pdb.get(b, ""))}
            if pair == {("CSP", "SGP"), ("CSP", "PO")} and t1 != 0 and t2 == 0:
                s_p_break = True
            if pair == {("CSP", "PO"), ("HOW", "OW")} and t1 == 0 and t2 != 0:
                p_o_form = True

        issues = []
        if not coverage_complete:
            issues.append("reaction-region atom type missing from [atom_types]")
        if not (s_p_break and p_o_form):
            issues.append("bond changes do not encode S-P break plus P-O formation")

        integrity["systems"][system] = {
            "q_atom_count": len(labels),
            "q_atoms_identified": labels,
            "parameter_coverage_complete": coverage_complete,
            "mechanism_consistent": s_p_break and p_o_form,
            "issues": issues,
        }
        per_system_atom_types.append(rows["atom_types"])

ref = per_system_atom_types[0]
atom_types_identical = all(t == ref for t in per_system_atom_types[1:])

consistency = {
    "case_id": "case-04-force-field-validation",
    "comparison": " vs ".join(SYSTEMS),
    "atom_types_identical": atom_types_identical,
    "lj_parameters_identical": atom_types_identical,
    "bonded_parameters_identical": atom_types_identical,
    "differences": [] if atom_types_identical else ["atom/parameter tables differ between systems"],
}

(out / "topology_integrity_report.json").write_text(json.dumps(integrity, indent=2) + "\n", encoding="utf-8")
(out / "parameter_consistency_matrix.json").write_text(json.dumps(consistency, indent=2) + "\n", encoding="utf-8")
print(f"solve.sh: wrote deliverables to {out}")
PYTHON
