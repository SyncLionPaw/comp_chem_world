#!/usr/bin/env bash
# Oracle reference solution for task 150. Real execution against the public inputs;
# no precomputed answers. The solver is embedded so the task keeps a single
# solution entrypoint.
set -euo pipefail

exec python3 - "$@" <<'PY'
#!/usr/bin/env python3
"""Build the complete heavy-atom geometry diagnosis from the public structure."""
import argparse
import json
import math
import os
import shlex
from pathlib import Path


def read_xyz(path):
    lines = Path(path).read_text(encoding="utf-8").splitlines()
    count = int(lines[0])
    if count <= 0 or len(lines) < count + 2:
        raise ValueError("truncated XYZ input")
    rows = []
    for line in lines[2:count + 2]:
        fields = line.split()
        if len(fields) != 4:
            raise ValueError("malformed XYZ coordinate row")
        xyz = tuple(float(v) for v in fields[1:])
        if not all(math.isfinite(v) for v in xyz):
            raise ValueError("non-finite XYZ coordinate")
        rows.append((fields[0], *xyz))
    if len(rows) != count:
        raise ValueError("XYZ atom count mismatch")
    return rows


def read_ccd(path):
    lines = Path(path).read_text(encoding="utf-8").splitlines()
    loops = []
    i = 0
    while i < len(lines):
        if lines[i].strip() != "loop_":
            i += 1
            continue
        i += 1
        headers = []
        while i < len(lines) and lines[i].lstrip().startswith("_"):
            headers.append(lines[i].strip())
            i += 1
        rows = []
        while i < len(lines):
            line = lines[i].strip()
            if not line or line.startswith("#"):
                i += 1
                if rows:
                    break
                continue
            if line == "loop_" or line.startswith("_") or line.startswith("data_"):
                break
            fields = shlex.split(line)
            if len(fields) != len(headers):
                raise ValueError("malformed CCD loop row")
            rows.append(dict(zip(headers, fields)))
            i += 1
        loops.append((headers, rows))
    atom_rows = next(rows for headers, rows in loops if "_chem_comp_atom.atom_id" in headers)
    bond_rows = next(rows for headers, rows in loops if "_chem_comp_bond.atom_id_1" in headers)
    atoms = {r["_chem_comp_atom.atom_id"]: {
        "element": r["_chem_comp_atom.type_symbol"],
        "aromatic": r["_chem_comp_atom.pdbx_aromatic_flag"] == "Y"} for r in atom_rows}
    bonds, adjacency = {}, {name: set() for name in atoms}
    for row in bond_rows:
        a, b = row["_chem_comp_bond.atom_id_1"], row["_chem_comp_bond.atom_id_2"]
        edge = frozenset((a, b))
        if a not in atoms or b not in atoms or edge in bonds:
            raise ValueError("invalid STI bond inventory")
        bonds[edge] = {"order": row["_chem_comp_bond.value_order"]}
        adjacency[a].add(b)
        adjacency[b].add(a)
    return atoms, bonds, adjacency


def atom_mapping(path):
    record = json.loads(Path(path).read_text(encoding="utf-8"))
    xyz_map = next(row["xyz_index_to_ccd_atom_id"] for row in record["mapped_xyz"]
                   if Path(row["xyz"]).name == "1xbb_reference.xyz")
    return {int(i): atom for i, atom in xyz_map.items()}


def edge_in_cycle(adjacency, a, b):
    todo, seen = [a], {a}
    while todo:
        here = todo.pop()
        for nxt in adjacency[here]:
            if frozenset((here, nxt)) == frozenset((a, b)):
                continue
            if nxt == b:
                return True
            if nxt not in seen:
                seen.add(nxt)
                todo.append(nxt)
    return False


def rotatable(edge, atoms, bonds, adjacency):
    a, b = tuple(edge)
    if edge_in_cycle(adjacency, a, b) or bonds[edge]["order"] != "SING":
        return False
    for n, c in ((a, b), (b, a)):
        if atoms[n]["element"] == "N" and atoms[c]["element"] == "C":
            if any(atoms[q]["element"] == "O" and bonds[frozenset((c, q))]["order"] == "DOUB"
                   for q in adjacency[c]):
                return False
    degree = [sum(atoms[n]["element"] != "H" for n in adjacency[x]) for x in (a, b)]
    if min(degree) < 2:
        return False
    if atoms[a]["aromatic"] and atoms[b]["aromatic"]:
        return True
    return True


def dist(a, b):
    return math.sqrt(sum((a[i] - b[i]) ** 2 for i in range(1, 4)))


def angle(a, b, c):
    u = [a[i] - b[i] for i in range(1, 4)]
    v = [c[i] - b[i] for i in range(1, 4)]
    nu = math.sqrt(sum(x*x for x in u)); nv = math.sqrt(sum(x*x for x in v))
    if nu == 0 or nv == 0:
        raise ValueError("zero-length angle vector")
    cosine = max(-1.0, min(1.0, sum(x*y for x, y in zip(u, v))/(nu*nv)))
    return math.degrees(math.acos(cosine))


def torsion(a, b, c, d):
    sub = lambda x, y: [x[i] - y[i] for i in range(1, 4)]
    cross = lambda x, y: [x[1]*y[2]-x[2]*y[1], x[2]*y[0]-x[0]*y[2], x[0]*y[1]-x[1]*y[0]]
    dot = lambda x, y: sum(i*j for i, j in zip(x, y))
    norm = lambda x: math.sqrt(dot(x, x))
    b0, b1, b2 = sub(a, b), sub(c, b), sub(d, c)
    n = norm(b1)
    if not n:
        raise ValueError("duplicate central atoms")
    axis = [x/n for x in b1]
    v0, v2 = dot(b0, axis), dot(b2, axis)
    v = [b0[i]-v0*axis[i] for i in range(3)]
    w = [b2[i]-v2*axis[i] for i in range(3)]
    if norm(v) <= 1e-8 or norm(w) <= 1e-8:
        raise ValueError("collinear torsion")
    return math.degrees(math.atan2(dot(cross(axis, v), w), dot(v, w)))


def wrapped(value):
    return (value + 180.0) % 360.0 - 180.0


def inventory(reference, candidate, atoms, bonds, adjacency, mapping):
    index_by_atom = {atom: index for index, atom in mapping.items()}
    heavy_names = {name for name, item in atoms.items() if item["element"] != "H"}
    if set(index_by_atom) != heavy_names or len(mapping) != len(heavy_names):
        raise ValueError("incomplete CCD heavy-atom mapping")
    bond_ids = set()
    angle_ids = set()
    for edge in bonds:
        a, b = tuple(edge)
        if a in heavy_names and b in heavy_names:
            bond_ids.add(tuple(sorted((index_by_atom[a], index_by_atom[b]))))
    for center in heavy_names:
        neighbors = sorted((n for n in adjacency[center] if n in heavy_names), key=index_by_atom.get)
        for i, left in enumerate(neighbors):
            for right in neighbors[i+1:]:
                q = (index_by_atom[left], index_by_atom[center], index_by_atom[right])
                angle_ids.add(min(q, q[::-1]))
    torsion_ids = set()
    for edge in bonds:
        a, b = tuple(edge)
        if a not in heavy_names or b not in heavy_names or not rotatable(edge, atoms, bonds, adjacency):
            continue
        left = sorted((n for n in adjacency[a] if n in heavy_names and n != b), key=index_by_atom.get)
        right = sorted((n for n in adjacency[b] if n in heavy_names and n != a), key=index_by_atom.get)
        for x in left:
            for y in right:
                q = (index_by_atom[x], index_by_atom[a], index_by_atom[b], index_by_atom[y])
                torsion_ids.add(min(q, q[::-1]))
    metrics, errors, undefined, groups = {}, {}, [], {}
    for kind, ids_set, fn, units in (
        ("bond", bond_ids, dist, "angstrom"),
        ("angle", angle_ids, angle, "degree"),
        ("torsion", torsion_ids, torsion, "degree"),
    ):
        metrics[kind], errors[kind] = [], []
        for ids in sorted(ids_set):
            try:
                av = fn(*(candidate[i-1] for i in ids))
                bv = fn(*(reference[i-1] for i in ids))
            except ValueError:
                if kind == "torsion":
                    statuses=[]
                    for xyz in (reference, candidate):
                        try: fn(*(xyz[i-1] for i in ids)); statuses.append("defined")
                        except ValueError: statuses.append("undefined_collinear_or_near_collinear")
                    undefined.append({"atoms":list(ids),"reference_status":statuses[0],"candidate_status":statuses[1]})
                    continue
                raise
            signed = wrapped(av-bv) if kind == "torsion" else av-bv
            metrics[kind].append({"atoms":list(ids),"candidate_minus_reference":signed,"units":units})
            errors[kind].append({"atoms":list(ids),"signed_error":signed,"absolute_error":abs(signed)})
            if kind == "torsion":
                groups.setdefault(tuple(sorted(ids[1:3])), []).append(abs(signed))
    distributions = {}
    for kind, records in errors.items():
        ordered = sorted(records, key=lambda x:(-x["absolute_error"],x["atoms"]))
        vals = sorted(x["absolute_error"] for x in records)
        quantile = lambda p: vals[max(0, math.ceil(p*len(vals))-1)]
        distributions[kind] = {"count":len(records),"records":ordered,"summary":{
            "min":vals[0],"median_nearest_rank":quantile(.5),"mean":sum(vals)/len(vals),
            "p90_nearest_rank":quantile(.9),"max":vals[-1]}}
    group_rows = [{"central_bond":list(center),"torsion_count":len(vals),
                   "mean_absolute":sum(vals)/len(vals),"maximum_absolute":max(vals)}
                  for center, vals in groups.items()]
    group_rows.sort(key=lambda r:(-r["maximum_absolute"],-r["mean_absolute"],r["central_bond"]))
    bases={"bond":.02,"angle":5.,"torsion":20.}; domain=[.25,4.]
    critical=max(max(x["absolute_error"] for x in errors[k])/bases[k] for k in bases)
    passes=max(domain[0],critical)<=domain[1]
    decision={"formula":"q = max_family(max_i(abs(error_i) / base_tolerance_family)); pass iff q <= lambda",
      "base_tolerances":bases,"lambda_domain":domain,"critical_lambda":critical,
      "passing_lambda_interval":[max(domain[0],critical),domain[1]] if passes else None,"pass_any_in_domain":passes}
    leave=[]
    for group in group_rows:
        removed=tuple(group["central_bond"])
        remaining=[abs(x["signed_error"]) for x in errors["torsion"] if tuple(sorted(x["atoms"][1:3]))!=removed]
        non_torsion=max(max(x["absolute_error"] for x in errors[k])/bases[k] for k in ("bond","angle"))
        leave.append({"excluded_central_bond":group["central_bond"],"remaining_torsion_count":len(remaining),
          "mean_absolute":sum(remaining)/len(remaining) if remaining else None,
          "maximum_absolute":max(remaining) if remaining else None,
          "critical_lambda":max(non_torsion,max(remaining)/bases["torsion"]) if remaining else non_torsion})
    return {"schema_version":"case01-neutral-geometry/v2","task_version":"2.0",
      "evaluation_scope":"paired_neutral_1xbb_geometry_only","atom_count":len(reference),
      "torsion_policy":{"signed_difference_interval":"[-180,180)","near_collinear_projection_cutoff_angstrom":1e-8},
      "geometry_metrics":metrics,"undefined_torsions":undefined,"error_distributions":distributions,
      "central_bond_groups":group_rows,"leave_one_center_group_out":leave,"tolerance_decision":decision}


def selection_profile(metrics, reference):
    by_index = {i+1: row for i,row in enumerate(reference)}
    profile = {}
    for kind, rows in metrics.items():
        centers=[]
        environments=set()
        indices=set()
        for row in rows:
            atom_ids=row["atoms"]
            indices.update(atom_ids)
            atoms=[by_index[i] for i in atom_ids]
            centers.append(tuple(sum(a[k] for a in atoms)/len(atoms) for k in (1,2,3)))
            if kind=="bond": environments.add(tuple(sorted((atoms[0][0],atoms[1][0]))))
            elif kind=="angle": environments.add((atoms[1][0],atoms[0][0],atoms[2][0]))
            else: environments.add((atoms[0][0],atoms[3][0]))
        spread=max((math.dist(a,b) for a in centers for b in centers),default=0.0)
        profile[kind]={"metric_count":len(rows),"unique_atom_count":len(indices),
                       "element_environment_count":len(environments),"spatial_spread_angstrom":spread}
    return profile


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--input-dir")
    parser.add_argument("--output-dir")
    args=parser.parse_args()
    default_assets=Path(os.environ.get("SOLUTION_ASSETS", "/app/assets"))
    source=Path(args.input_dir or os.environ.get("INPUT_DIR") or default_assets)
    output=Path(args.output_dir or os.environ.get("OUTPUT_DIR") or ".")
    reference=read_xyz(source/"1xbb_reference.xyz")
    candidate=read_xyz(source/"1xbb_aiqm1.xyz")
    context=dict(line.split("=",1) for line in (source/"context.txt").read_text().splitlines() if "=" in line)
    if context.get("system_id")!="1XBB" or context.get("charge")!="0" or context.get("multiplicity")!="1" or context.get("units")!="angstrom":
        raise ValueError("expected neutral 1XBB singlet inputs")
    if len(reference)!=68 or len(candidate)!=68 or [a[0] for a in reference]!=[a[0] for a in candidate]:
        raise ValueError("paired coordinate correspondence invalid")
    atoms,bonds,adjacency=read_ccd(source/"STI.cif")
    mapping=atom_mapping(source/"STI-mapping.json")
    result=inventory(reference,candidate,atoms,bonds,adjacency,mapping)
    result["scientific_interpretation"] = {
        "measured_scope": "One paired neutral 1XBB geometry.",
        "topology_basis": "Public STI component graph and indexed atom mapping.",
        "charge_transfer": "Not measured by the input geometries.",
        "adequacy": "The tolerance decision is specific to this geometry and policy.",
        "recommendation": "Use the geometry inventory to identify local discrepancies.",
        "evidence_gaps": ["No charged systems or independent structures are supplied."],
    }
    result["selection_profile"] = selection_profile(result["geometry_metrics"], reference)
    result["selection_sensitivity"] = {}
    for kind, block in result["error_distributions"].items():
        errors = sorted(row["absolute_error"] for row in block["records"])
        result["selection_sensitivity"][kind] = {
            "units": "angstrom" if kind == "bond" else "degree",
            "count": len(errors),
            "mean_absolute": sum(errors) / len(errors),
            "maximum_absolute": errors[-1],
            "mean_after_removing_largest": sum(errors[:-1]) / (len(errors) - 1) if len(errors) > 1 else None,
        }
    output.mkdir(parents=True,exist_ok=True)
    (output/"result.json").write_text(json.dumps(result,indent=2)+"\n")
    decision=result["tolerance_decision"]
    group=result["central_bond_groups"][0]
    scope={"evaluation_scope":"paired_neutral_1xbb_geometry_only","nonclaims":[
      "No conclusion about method-wide applicability or charge transfer generalization.",
      "No inference about energy, binding, or experimental accuracy.",
      "The tolerance family and scale are a declared screening policy, not a calibrated physical error bar."],
      "decision_interpretation":"This result describes one neutral paired geometry and applies only to the declared scaled tolerance policy."}
    report=("# 1XBB paired geometry diagnosis v2\n\n"
      "The indexed heavy-atom bond, angle, and eligible torsion inventories are enumerated directly from the public STI CCD graph and its XYZ mapping. Periodic torsion differences use [-180, 180); undefined or near-collinear quartets are excluded and identified in the structured inventory.\n\n"
      f"The largest torsion group by maximum absolute deviation is centered on {group['central_bond']} (n={group['torsion_count']}); all group summaries and leave-one-center-group-out results are in result.json. These are sensitivity diagnostics over this molecular instance.\n\n"
      f"For the public policy family tolerances (bond 0.02 Å, angle 5°, torsion 20°), q=max_family(max_i(|error_i|/base_tolerance_family)); a selected scale λ passes when q≤λ. The observed breakpoint is {decision['critical_lambda']:.6f}; the passing interval within λ∈[0.25,4] is {decision['passing_lambda_interval']}. This is a conditional screening decision, not an empirical calibration of surrogate adequacy.\n\n"
      "The input is one neutral singlet geometry pair. It does not test energies, binding outcomes, charge transfer, or transfer to other chemical domains. A useful decision therefore remains local to this evidence and the stated policy.\n\n"
      "```v2_scope\n"+json.dumps(scope,indent=2)+"\n```\n")
    for field in ("scientific_interpretation", "selection_profile"):
        report += "\n```" + field + "\n" + json.dumps(result[field], indent=2) + "\n```\n"
    (output/"report.md").write_text(report)


if __name__=="__main__":
    main()

PY
