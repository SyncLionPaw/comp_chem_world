#!/usr/bin/env python3
# L1 Deliverables: Check required deliverables for completeness and parseability (including report.md, result.json).
# L2 Execution: Check the use of supplied data or archived evidence where required.
# L3 Science: Audit mapped ligand geometries and stereochemical consistency in the 1XBB system.
"""Arithmetic checker for explicitly indexed 1XBB geometry observables.

Every submitted metric is recomputed against the two XYZ files.  The checker
does not decide whether the chosen atom sets adequately cover the chemistry;
that remains a scientific-review question.
"""
import json
import hashlib
import math
import os
import re
import shlex
import sys
from collections import Counter
from pathlib import Path

REFERENCE_PATH = Path(__file__).resolve().with_name("refs.json")


def _finite_positive(value):
    if type(value) is int:
        return value > 0
    return type(value) is float and math.isfinite(value) and value > 0


def _validate_reference_config(config):
    if not isinstance(config, dict) or config.get("schema_version") != "case01-test-references/v1":
        raise ValueError("unsupported reference schema")
    asset_hashes = config["public_asset_sha256"]
    if not isinstance(asset_hashes, dict) or set(asset_hashes) != {
            "context.txt", "1xbb_reference.xyz", "1xbb_aiqm1.xyz", "STI.cif", "STI-mapping.json"} or any(
            not isinstance(name, str) or not isinstance(digest, str) or
            len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest)
            for name, digest in asset_hashes.items()):
        raise ValueError("invalid public asset hash table")
    policy = config["policy"]
    expected = {"bond_angstrom", "angle_degree", "torsion_degree"}
    if set(policy["base_tolerances"]) != expected or any(
            not _finite_positive(v) for v in policy["base_tolerances"].values()):
        raise ValueError("invalid positive geometry tolerance")
    domain = policy["lambda_domain"]
    if not isinstance(domain, list) or len(domain) != 2 or not all(_finite_positive(v) for v in domain) or domain[0] >= domain[1]:
        raise ValueError("invalid positive lambda domain")
    if not _finite_positive(policy["near_collinear_projection_cutoff_angstrom"]):
        raise ValueError("invalid positive torsion cutoff")
    if not isinstance(policy["torsion_signed_difference_interval"], str):
        raise ValueError("invalid torsion difference interval")
    refs = config["reference_values"]
    if not isinstance(refs["full_geometry_baseline_json"], str) or not isinstance(refs["full_geometry_baseline_sha256"], str):
        raise ValueError("invalid full geometry reference")


try:
    REFERENCE_CONFIG = json.loads(REFERENCE_PATH.read_text(encoding="utf-8"))
    _validate_reference_config(REFERENCE_CONFIG)
    EXPECTED_ASSET_SHA256 = REFERENCE_CONFIG["public_asset_sha256"]
    EXPECTED_STI_SHA256 = EXPECTED_ASSET_SHA256["STI.cif"]
    EXPECTED_MAPPING_SHA256 = EXPECTED_ASSET_SHA256["STI-mapping.json"]
    POLICY = REFERENCE_CONFIG["policy"]
    SIGNED_DIFFERENCE_INTERVAL = POLICY["torsion_signed_difference_interval"]
    BASE_TOLERANCES = {"bond": POLICY["base_tolerances"]["bond_angstrom"],
                       "angle": POLICY["base_tolerances"]["angle_degree"],
                       "torsion": POLICY["base_tolerances"]["torsion_degree"]}
    LAMBDA_DOMAIN = POLICY["lambda_domain"]
    COLLINEAR_CUTOFF_ANGSTROM = POLICY["near_collinear_projection_cutoff_angstrom"]
except (OSError, UnicodeError, json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
    print(f"ENV_INVALID: task reference configuration unavailable: {exc}")
    raise SystemExit(2)
FULL_GEOMETRY_PATH = REFERENCE_PATH


def cif_loops(path):
    """Read the simple one-row-per-line CCD loops used by STI.cif."""
    lines = Path(path).read_text(encoding="utf-8").splitlines()
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
                raise ValueError(f"malformed CCD loop row: {line}")
            rows.append(dict(zip(headers, fields)))
            i += 1
        if headers:
            yield headers, rows


def topology_assets(root):
    """Load evaluator-side copies of the public CCD and derived index map."""
    ccd = Path(root) / "assets/STI.cif"
    mapping_path = Path(root) / "assets/STI-mapping.json"
    if hashlib.sha256(ccd.read_bytes()).hexdigest() != EXPECTED_STI_SHA256:
        raise ValueError("evaluator STI CCD reference hash mismatch")
    if hashlib.sha256(mapping_path.read_bytes()).hexdigest() != EXPECTED_MAPPING_SHA256:
        raise ValueError("evaluator STI mapping reference hash mismatch")
    atom_rows = bond_rows = None
    for headers, rows in cif_loops(ccd):
        if "_chem_comp_atom.atom_id" in headers:
            atom_rows = rows
        if "_chem_comp_bond.atom_id_1" in headers:
            bond_rows = rows
    if atom_rows is None or bond_rows is None:
        raise ValueError("STI CCD atom/bond tables are missing")
    atoms = {r["_chem_comp_atom.atom_id"]: {
        "element": r["_chem_comp_atom.type_symbol"],
        "charge": int(r["_chem_comp_atom.charge"]),
        "aromatic": r["_chem_comp_atom.pdbx_aromatic_flag"] == "Y"}
        for r in atom_rows}
    bonds = {}
    adjacency = {name: set() for name in atoms}
    for row in bond_rows:
        a, b = row["_chem_comp_bond.atom_id_1"], row["_chem_comp_bond.atom_id_2"]
        edge = frozenset((a, b))
        if a not in atoms or b not in atoms or edge in bonds:
            raise ValueError("invalid or duplicate STI bond")
        bonds[edge] = {"order": row["_chem_comp_bond.value_order"],
                       "aromatic": row["_chem_comp_bond.pdbx_aromatic_flag"] == "Y"}
        adjacency[a].add(b); adjacency[b].add(a)
    metadata = {"atom_count": len(atoms), "bond_count": len(bonds),
                "formal_charge": sum(a["charge"] for a in atoms.values())}
    mapping = json.loads(mapping_path.read_text(encoding="utf-8"))
    if metadata != {"atom_count": 68, "bond_count": 72, "formal_charge": 0}:
        raise ValueError("STI CCD identity or topology inventory mismatch")
    if mapping.get("source", {}).get("sha256") != EXPECTED_STI_SHA256:
        raise ValueError("STI mapping does not identify the authoritative CCD bytes")
    return atoms, bonds, adjacency, mapping


def index_atom_map(mapping_record):
    """Map heavy rows to CCD names and each XYZ H row to its explicit parent.

    CCD H labels are not assigned as unique atom identities because equivalent
    hydrogens (for example on methyl groups) can exchange under geometry fits.
    """
    result = {int(i): {"atom": name, "element": None, "parent": None}
              for i, name in mapping_record["xyz_index_to_ccd_atom_id"].items()}
    result.update({int(i): {"atom": None, "element": "H", "parent": row["parent"]}
                   for i, row in mapping_record["hydrogens"].items()})
    return result


def edge_is_in_cycle(adjacency, atom_a, atom_b):
    """A covalent edge is cyclic if another path connects its endpoints."""
    todo = [atom_a]; seen = {atom_a}
    while todo:
        node = todo.pop()
        for nxt in adjacency[node]:
            if frozenset((node, nxt)) == frozenset((atom_a, atom_b)):
                continue
            if nxt == atom_b:
                return True
            if nxt not in seen:
                seen.add(nxt); todo.append(nxt)
    return False


def torsion_class(atom_ids, atoms, bonds, adjacency):
    a, b = atom_ids
    edge = bonds[frozenset((a, b))]
    if edge_is_in_cycle(adjacency, a, b):
        return "ring_restricted"
    if edge["order"] != "SING" or atoms[a]["element"] == "H" or atoms[b]["element"] == "H":
        return "restricted_other"
    # Amide C-N rotation is resonance restricted; identify carbonyl C from
    # its explicit double bond to oxygen in the CCD.
    for n, c in ((a, b), (b, a)):
        if atoms[n]["element"] == "N" and atoms[c]["element"] == "C":
            if any(atoms[q]["element"] == "O" and bonds[frozenset((c, q))]["order"] == "DOUB"
                   for q in adjacency[c]):
                return "amide_restricted"
    heavy_degree_a = sum(atoms[n]["element"] != "H" for n in adjacency[a])
    heavy_degree_b = sum(atoms[n]["element"] != "H" for n in adjacency[b])
    if heavy_degree_a >= 2 and heavy_degree_b >= 2:
        # A single non-cyclic bridge between aromatic atoms (e.g. the STI
        # pyridyl-pyrimidine C5-C7 bond) is a conjugated biaryl rotor. CCD's
        # aromatic flag is preserved as source metadata, but does not make a
        # bridge cyclic or change its explicit SING bond order.
        if atoms[a]["aromatic"] and atoms[b]["aromatic"]:
            return "conjugated_rotatable"
        conjugated = any(atoms[n]["element"] == "N" and any(
            atoms[q]["element"] == "C" and atoms[q]["aromatic"]
            for q in adjacency[n] if q != partner)
            for n, partner in ((a, b), (b, a)))
        return "conjugated_rotatable" if conjugated else "rotatable"
    return "terminal_restricted"


def check_topology(metrics, reference, atoms, bonds, adjacency, mapping_record):
    """Validate indexed coordinates against CCD connectivity; return audit ledger."""
    index_map = index_atom_map(mapping_record)
    if len(index_map) != 68 or set(index_map) != set(range(1, 69)):
        return False, "CCD atom mapping does not cover all 68 XYZ rows", {}
    for i, (element, *_xyz) in enumerate(reference, 1):
        mapped = index_map[i]
        if element == "H":
            if mapped["parent"] not in atoms or atoms[mapped["parent"]]["element"] == "H":
                return False, f"CCD hydrogen-parent mapping invalid at XYZ atom {i}", {}
        elif mapped["atom"] not in atoms or atoms[mapped["atom"]]["element"] != element:
            return False, f"CCD mapping element mismatch at XYZ atom {i}", {}
    heavy_names = [index_map[i]["atom"] for i, (element, *_xyz) in enumerate(reference, 1) if element != "H"]
    if len(set(heavy_names)) != 37 or set(heavy_names) != {n for n, a in atoms.items() if a["element"] != "H"}:
        return False, "CCD mapping is not a one-to-one map of the 37 heavy atoms", {}
    h_parent_counts = Counter()
    for hname, hatom in atoms.items():
        if hatom["element"] == "H":
            parents = [n for n in adjacency[hname] if atoms[n]["element"] != "H"]
            if len(parents) != 1:
                return False, f"CCD hydrogen {hname} does not have exactly one heavy parent", {}
            h_parent_counts[parents[0]] += 1
    xyz_parent_counts = Counter()
    for i, (element, *_xyz) in enumerate(reference, 1):
        if element == "H":
            xyz_parent_counts[index_map[i]["parent"]] += 1
    if xyz_parent_counts != h_parent_counts:
        return False, "mapped XYZ hydrogen counts do not match CCD parent counts", {}
    ledger = {"bond": [], "angle": [], "torsion": []}
    for kind in ("bond", "angle", "torsion"):
        records = metrics[kind]
        for row in records:
            ids = row["atoms"]
            mapped = [index_map[i] for i in ids]
            names = [item["atom"] if item["element"] != "H" else f"H@{i}({item['parent']})"
                     for i, item in zip(ids, mapped)]
            edge_records = []
            for left, right in zip(mapped, mapped[1:]):
                if left["element"] == "H" and right["element"] == "H":
                    edge_records.append(None)
                elif left["element"] == "H":
                    edge_records.append({"order": "SING", "aromatic": False}
                                        if left["parent"] == right["atom"] else None)
                elif right["element"] == "H":
                    edge_records.append({"order": "SING", "aromatic": False}
                                        if right["parent"] == left["atom"] else None)
                else:
                    edge_records.append(bonds.get(frozenset((left["atom"], right["atom"]))))
            if any(edge is None for edge in edge_records):
                return False, f"{kind} {ids} contains a nonbonded or discontinuous CCD path", {}
            detail = {"xyz_indices": ids, "ccd_atoms": names,
                      "bond_orders": [edge["order"] for edge in edge_records]}
            if kind == "torsion":
                central = [mapped[1]["atom"], mapped[2]["atom"]]
                if central[0] is None or central[1] is None:
                    return False, f"torsion {ids} must have heavy atoms on its central bond", {}
                role = torsion_class(central, atoms, bonds, adjacency)
                detail["topology_class"] = role
            ledger[kind].append(detail)
    if not any(item["topology_class"] in {"rotatable", "conjugated_rotatable"} for item in ledger["torsion"]):
        return False, "torsion family must include at least one CCD-supported rotatable bond", {}
    return True, "submitted coordinates follow authoritative CCD STI paths", ledger


def xyz(path):
    try:
        lines = Path(path).read_text(encoding="utf-8").splitlines()
        n = int(lines[0].strip())
        if n <= 0 or len(lines) < n + 2:
            raise ValueError("truncated XYZ")
        rows = []
        for line in lines[2 : 2 + n]:
            fields = line.split()
            if len(fields) != 4 or not fields[0]:
                raise ValueError("malformed XYZ coordinate row")
            point = tuple(float(value) for value in fields[1:4])
            if not all(math.isfinite(value) for value in point):
                raise ValueError("non-finite XYZ coordinate")
            rows.append((fields[0], *point))
        if len(rows) != n:
            raise ValueError("atom count mismatch")
        return rows
    except (OSError, UnicodeError, ValueError, IndexError) as exc:
        raise ValueError(f"{path}: {exc}") from exc


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
    def sub(x, y): return [x[i] - y[i] for i in range(1, 4)]
    def cross(x, y): return [x[1]*y[2]-x[2]*y[1], x[2]*y[0]-x[0]*y[2], x[0]*y[1]-x[1]*y[0]]
    def dot(x, y): return sum(i*j for i, j in zip(x, y))
    def norm(x): return math.sqrt(dot(x, x))
    b0 = sub(a, b); b1 = sub(c, b); b2 = sub(d, c)
    b1n = norm(b1)
    if b1n == 0:
        raise ValueError("undefined torsion from duplicate central atoms")
    axis = [v / b1n for v in b1]
    projection0 = dot(b0, axis); projection2 = dot(b2, axis)
    v = [b0[i] - projection0 * axis[i] for i in range(3)]
    w = [b2[i] - projection2 * axis[i] for i in range(3)]
    if norm(v) <= COLLINEAR_CUTOFF_ANGSTROM or norm(w) <= COLLINEAR_CUTOFF_ANGSTROM:
        raise ValueError("undefined torsion from collinear or near-collinear atoms")
    return math.degrees(math.atan2(dot(cross(axis, v), w), dot(v, w)))


def wrap_degrees(value):
    """Shortest signed angular difference in [-180, 180)."""
    return (value + 180.0) % 360.0 - 180.0


def finite_number(value):
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return False
    try:
        return math.isfinite(value)
    except (OverflowError, TypeError):
        return False


def sensitivity_summary(metrics, reference, candidate):
    """Recompute absolute-error summaries and leave-one-largest-out perturbations."""
    funcs = {"bond": (dist, "angstrom"), "angle": (angle, "degree"), "torsion": (torsion, "degree")}
    summary = {}
    for kind, (fn, units) in funcs.items():
        values = []
        for row in metrics[kind]:
            indices = row["atoms"]
            a = fn(*(candidate[i-1] for i in indices))
            b = fn(*(reference[i-1] for i in indices))
            delta = wrap_degrees(a-b) if kind == "torsion" else a-b
            values.append(abs(delta))
        ordered = sorted(values)
        summary[kind] = {"units": units, "count": len(values), "mean_absolute": sum(values)/len(values),
                         "maximum_absolute": max(values),
                         "mean_after_removing_largest": sum(ordered[:-1])/(len(ordered)-1) if len(ordered) > 1 else None}
    return summary


def full_geometry_coverage(metrics, baseline):
    """Descriptive exact-index coverage against a separately calculated graph inventory."""
    def key(kind, ids):
        ids = tuple(ids)
        if kind == "bond": return min(ids, ids[::-1])
        if kind == "angle": return min(ids, ids[::-1])
        return min(ids, ids[::-1])
    selected = {kind: {key(kind, row["atoms"]) for row in rows} for kind, rows in metrics.items()}
    families = baseline["families"]
    mapping = {
        "bond": [("heavy_atom_bonds", "heavy_only"), ("all_atom_bonds", "all_atoms")],
        "angle": [("heavy_atom_angles", "heavy_only"), ("all_connected_angles", "all_atoms")],
        "torsion": [("heavy_rotatable_torsions", "heavy_outer_atoms"),
                    ("hydrogen_inclusive_rotatable_torsions", "hydrogen_inclusive")],
    }
    result = {}
    for kind, scopes in mapping.items():
        result[kind] = {}
        for family, scope in scopes:
            rows = families[family]
            keys = {key(kind, row["xyz_indices"]) for row in rows}
            chosen = keys & selected[kind]
            omitted = [abs(row["candidate_minus_reference"]) for row in rows
                       if key(kind, row["xyz_indices"]) not in chosen]
            chosen_values = [abs(row["candidate_minus_reference"]) for row in rows
                             if key(kind, row["xyz_indices"]) in chosen]
            result[kind][scope] = {
                "baseline_count": len(keys), "selected_count": len(chosen),
                "omitted_count": len(keys - chosen),
                "max_selected_abs_difference": max(chosen_values) if chosen_values else None,
                "max_omitted_abs_difference": max(omitted) if omitted else None,
                "limitation": "descriptive only; omission and maximum difference do not independently establish adequacy, error, or an incorrect recommendation"
            }
    # Literature centers show which source-supported roles are represented, without
    # turning the literature's Q labels into a mandatory checklist.
    role_report = []
    selected_torsions = selected["torsion"]
    for center in baseline["literature_role_centers"]:
        quartets = center["quartets"]
        matching = [q for q in quartets if key("torsion", q["xyz_indices"]) in selected_torsions]
        omitted = [q for q in quartets if key("torsion", q["xyz_indices"]) not in selected_torsions]
        role_report.append({"role": center["role"], "central_ccd_bond": center["central_ccd_bond"],
                            "selected_quartets": len(matching), "available_quartets": len(quartets),
                            "max_selected_abs_difference": max((abs(q["candidate_minus_reference"]) for q in matching), default=None),
                            "max_omitted_abs_difference": max((abs(q["candidate_minus_reference"]) for q in omitted), default=None),
                            "interpretation": "role-linked omission diagnostic only; materiality depends on the submitted claim and intended use"})
    return {"basis": "independent complete-graph coordinate inventory; exact mapped atom tuples",
            "families": result, "literature_roles": role_report,
            "hydrogen_parent_scope": "Heavy-only families do not cover H-parent bonds/angles. Separate all-atom family counts and hydrogen-inclusive rotor quartets are reported; hydrogen labels are equivalent by parent.",
            "decision_status": "DESCRIPTIVE_NOT_GRADED"}


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


def scientific_contract(result, report_text, reference, candidate):
    contract = result.get("scientific_interpretation")
    required = {"measured_scope", "topology_basis", "charge_transfer", "adequacy", "recommendation", "evidence_gaps"}
    if not isinstance(contract, dict) or set(contract) != required:
        return False, "scientific_interpretation must match the structured contract"
    for field in required - {"evidence_gaps"}:
        if not isinstance(contract[field], str) or not contract[field].strip():
            return False, f"scientific_interpretation.{field} must be non-empty text"
    gaps = contract["evidence_gaps"]
    if (not isinstance(gaps, list) or any(not isinstance(x, str) or not x.strip() for x in gaps)
            or len(set(gaps)) != len(gaps)):
        return False, "evidence_gaps must be a list of unique non-empty strings"
    # Only reject a narrow, explicit structured assertion contradicted by the
    # supplied assets. Unknown wording stays reviewable instead of being forced
    # into a single recommended answer or a fixed gap checklist.
    if contract["charge_transfer"].strip().lower() in {"measured", "empirically_measured", "observed_in_supplied_pair"}:
        return False, "the supplied neutral geometry pair does not measure charge transfer"
    if contract["measured_scope"].strip().lower() in {"all_charge_states", "charged_and_neutral_cases", "all_elements_and_charges"}:
        return False, "the supplied assets contain only the neutral 1XBB geometry pair"
    blocks = re.findall(r"```scientific_interpretation\s*\n(.*?)\n```", report_text, re.S)
    if len(blocks) != 1:
        return False, "report.md must contain exactly one scientific_interpretation JSON block"
    try:
        if json.loads(blocks[0]) != contract:
            return False, "report and result.json scientific interpretations disagree"
    except json.JSONDecodeError:
        return False, "report scientific_interpretation block is invalid JSON"
    metrics = result["geometry_metrics"]
    # Require a reproducible spread of atom identities and element environments,
    # while avoiding a fixed canonical atom tuple.
    reference_by_index = {i+1: row for i, row in enumerate(reference)}
    for kind in ("bond", "angle", "torsion"):
        rows = metrics[kind]
        if len({tuple(row["atoms"]) for row in rows}) != len(rows):
            return False, f"{kind} selection contains duplicate atom tuples"
    actual_profile=selection_profile(metrics, reference)
    submitted_profile=result.get("selection_profile")
    if not equivalent_numbers(submitted_profile,actual_profile):
        return False,"selection_profile must reproduce the element/spatial sampling statistics"
    profile_blocks=re.findall(r"```selection_profile\s*\n(.*?)\n```",report_text,re.S)
    if len(profile_blocks)!=1:
        return False,"report.md must contain exactly one selection_profile JSON block"
    try:
        if not equivalent_numbers(json.loads(profile_blocks[0]),actual_profile):
            return False,"report and result.json selection profiles disagree"
    except json.JSONDecodeError:
        return False,"report selection_profile block is invalid JSON"
    summary = sensitivity_summary(metrics, reference, candidate)
    submitted_summary = result.get("selection_sensitivity")
    if not isinstance(submitted_summary, dict) or submitted_summary.keys() != summary.keys():
        return False, "selection_sensitivity must report grader-recomputed summaries for all metric families"
    for kind in summary:
        if not equivalent_numbers(submitted_summary[kind], summary[kind]):
            return False, f"selection_sensitivity {kind} summary does not match coordinate-derived values"
    return True, "indexed geometry, descriptive selection inventory, structured scope and perturbation summary passed; recommendation sufficiency remains unresolved"


def equivalent_numbers(got, expected):
    if isinstance(expected, dict):
        return isinstance(got, dict) and expected.keys() <= got.keys() and all(equivalent_numbers(got[k],v) for k,v in expected.items())
    if isinstance(expected, list):
        return isinstance(got,list) and len(got)==len(expected) and all(equivalent_numbers(a,b) for a,b in zip(got,expected))
    if expected is None:
        return got is None
    if type(expected) is int:
        return type(got) is int and got == expected
    if isinstance(expected, (int,float)) and not isinstance(expected,bool):
        return finite_number(got) and abs(float(got)-float(expected)) <= 1e-6
    return type(got) is type(expected) and got == expected


def candidate_shape_error(value):
    """Reject malformed candidate containers before scientific routines inspect them."""
    if not isinstance(value, dict): return "result.json must be an object"
    gm=value.get('geometry_metrics')
    if not isinstance(gm,dict): return "geometry_metrics must be an object"
    for kind,n in (('bond',2),('angle',3),('torsion',4)):
        rows=gm.get(kind)
        if not isinstance(rows,list): return f"geometry_metrics.{kind} must be an array"
        for index,row in enumerate(rows):
            if not isinstance(row,dict): return f"geometry_metrics.{kind}[{index}] must be an object"
            ids=row.get('atoms')
            if not isinstance(ids,list) or len(ids)!=n or any(type(i) is not int for i in ids):
                return f"geometry_metrics.{kind}[{index}].atoms must contain {n} JSON integers"
            if any(i<1 or i>68 for i in ids): return f"geometry_metrics.{kind}[{index}].atoms is outside 1..68"
            value=row.get('candidate_minus_reference')
            if not finite_number(value): return f"geometry_metrics.{kind}[{index}].candidate_minus_reference must be finite"
            if not isinstance(row.get('units'),str): return f"geometry_metrics.{kind}[{index}].units must be text"
    return None


def candidate_policy_error(value):
    """Policy literals are exact constants; measurement tolerance applies only to derived values."""
    def exact_number(x, target):
        return finite_number(x) and float(x)==target
    policy=value.get('torsion_policy')
    if not isinstance(policy,dict): return 'torsion_policy must be an object'
    if policy.get('signed_difference_interval')!=SIGNED_DIFFERENCE_INTERVAL: return 'signed torsion interval differs from the public policy'
    if not exact_number(policy.get('near_collinear_projection_cutoff_angstrom'),COLLINEAR_CUTOFF_ANGSTROM):
        return 'near-collinear projection cutoff must equal the public 1e-8 Angstrom constant'
    decision=value.get('tolerance_decision')
    if not isinstance(decision,dict): return 'tolerance_decision must be an object'
    bases=decision.get('base_tolerances'); domain=decision.get('lambda_domain')
    if not isinstance(bases,dict) or any(not exact_number(bases.get(k),v) for k,v in BASE_TOLERANCES.items()):
        return 'base tolerances must equal the public policy constants'
    if not isinstance(domain,list) or len(domain)!=2 or not all(exact_number(x,t) for x,t in zip(domain,LAMBDA_DOMAIN)):
        return 'lambda domain must equal the public [0.25,4] policy interval'
    return None


def expected_v2(root, reference, candidate, baseline):
    """Recompute the complete heavy-atom inventory and tolerance decision."""
    families=baseline['families']
    specs={"bond":("heavy_atom_bonds",dist,"angstrom"),"angle":("heavy_atom_angles",angle,"degree"),"torsion":("heavy_rotatable_torsions",torsion,"degree")}
    metrics={}; errors={}; groups={}
    for kind,(base_key,fn,units) in specs.items():
        metrics[kind]=[]; errors[kind]=[]
        for item in families[base_key]:
            ids=item['xyz_indices']
            try:
                a=fn(*(candidate[i-1] for i in ids)); b=fn(*(reference[i-1] for i in ids))
            except ValueError:
                continue
            signed=wrap_degrees(a-b) if kind=='torsion' else a-b
            metrics[kind].append({'atoms':ids,'candidate_minus_reference':signed,'units':units})
            errors[kind].append({'atoms':ids,'signed_error':signed,'absolute_error':abs(signed)})
            if kind=='torsion':
                center=tuple(sorted(ids[1:3])); groups.setdefault(center,[]).append(abs(signed))
    # Deterministic distribution rows, worst first, retaining full provenance.
    distributions={}
    for kind,rows in errors.items():
        ordered=sorted(rows,key=lambda x:(-x['absolute_error'],x['atoms']))
        vals=sorted(x['absolute_error'] for x in rows)
        def quantile(p): return vals[max(0,math.ceil(p*len(vals))-1)]
        distributions[kind]={'count':len(rows),'records':ordered,'summary':{'min':vals[0],'median_nearest_rank':quantile(.5),'mean':sum(vals)/len(vals),'p90_nearest_rank':quantile(.9),'max':vals[-1]}}
    group_rows=[]
    for center,vals in groups.items():
        group_rows.append({'central_bond':list(center),'torsion_count':len(vals),'mean_absolute':sum(vals)/len(vals),'maximum_absolute':max(vals)})
    group_rows.sort(key=lambda x:(-x['maximum_absolute'],-x['mean_absolute'],x['central_bond']))
    bases=BASE_TOLERANCES; domain=LAMBDA_DOMAIN
    critical=max(max(x['absolute_error'] for x in errors[k])/bases[k] for k in bases)
    passes=max(domain[0],critical)<=domain[1]
    decisions={'formula':'q = max_family(max_i(abs(error_i) / base_tolerance_family)); pass iff q <= lambda','base_tolerances':bases,'lambda_domain':domain,'critical_lambda':critical,'passing_lambda_interval':[max(domain[0],critical),domain[1]] if passes else None,'pass_any_in_domain':passes}
    leave=[]
    for g in group_rows:
        rem=[abs(x['signed_error']) for x in errors['torsion'] if tuple(sorted(x['atoms'][1:3]))!=tuple(g['central_bond'])]
        leave.append({'excluded_central_bond':g['central_bond'],'remaining_torsion_count':len(rem),'mean_absolute':sum(rem)/len(rem) if rem else None,'maximum_absolute':max(rem) if rem else None,'critical_lambda':max(max(x['absolute_error'] for x in errors[k])/bases[k] for k in ('bond','angle')) if not rem else max(max(x['absolute_error'] for x in errors['bond'])/bases['bond'],max(x['absolute_error'] for x in errors['angle'])/bases['angle'],max(rem)/bases['torsion'])})
    return {'schema_version':'case01-neutral-geometry/v2','task_version':'2.0','evaluation_scope':'paired_neutral_1xbb_geometry_only','atom_count':len(reference),'torsion_policy':{'signed_difference_interval':SIGNED_DIFFERENCE_INTERVAL,'near_collinear_projection_cutoff_angstrom':COLLINEAR_CUTOFF_ANGSTROM},'geometry_metrics':metrics,'undefined_torsions':[],'error_distributions':distributions,'central_bond_groups':group_rows,'leave_one_center_group_out':leave,'tolerance_decision':decisions}

def topology_inventory(root,reference,candidate,atoms,bonds,adjacency,mapping_record,baseline):
    """Enumerate public-graph heavy observations and verify the frozen inventory."""
    ids={int(i):name for i,name in mapping_record['xyz_index_to_ccd_atom_id'].items()}
    inv={name:i for i,name in ids.items()}
    heavy={name for name,row in atoms.items() if row['element']!='H'}
    if set(inv)!=heavy or len(ids)!=len(heavy): raise ValueError('public heavy-atom mapping is incomplete')
    bondset={tuple(sorted((inv[a],inv[b]))) for edge in bonds for a,b in [tuple(edge)] if a in heavy and b in heavy}
    angle_set=set()
    for center in heavy:
        ns=sorted((x for x in adjacency[center] if x in heavy),key=lambda x:inv[x])
        for i in range(len(ns)):
            for j in range(i+1,len(ns)):
                a,c=inv[ns[i]],inv[ns[j]]; b=inv[center]
                angle_set.add(min((a,b,c),(c,b,a)))
    torsions=set()
    for edge in bonds:
        a,b=tuple(edge)
        if a not in heavy or b not in heavy: continue
        role=torsion_class([a,b],atoms,bonds,adjacency)
        if role not in {'rotatable','conjugated_rotatable'}: continue
        left=sorted((n for n in adjacency[a] if n in heavy and n!=b),key=lambda x:inv[x])
        right=sorted((n for n in adjacency[b] if n in heavy and n!=a),key=lambda x:inv[x])
        for x in left:
            for y in right:
                q=(inv[x],inv[a],inv[b],inv[y]); torsions.add(min(q,tuple(reversed(q))))
    expected_keys={'bond':bondset,'angle':angle_set,'torsion':torsions}
    b_families=baseline['families']; names={'bond':'heavy_atom_bonds','angle':'heavy_atom_angles','torsion':'heavy_rotatable_torsions'}
    for kind,key in names.items():
        source={min(tuple(row['xyz_indices']),tuple(reversed(row['xyz_indices']))) for row in b_families[key]}
        if source!=expected_keys[kind]: raise ValueError(f'public topology inventory and frozen independent {kind} reference disagree')
    undefined=[]; defined=[]
    for q in sorted(torsions):
        states=[]
        for xyz in (reference,candidate):
            try: torsion(*(xyz[i-1] for i in q)); states.append('defined')
            except ValueError: states.append('undefined_collinear_or_near_collinear')
        if states==['defined','defined']: defined.append(q)
        else: undefined.append({'atoms':list(q),'reference_status':states[0],'candidate_status':states[1]})
    if set(defined)!={min(tuple(row['xyz_indices']),tuple(reversed(row['xyz_indices']))) for row in b_families['heavy_rotatable_torsions']}:
        raise ValueError('frozen torsion inventory does not match geometrically defined public-graph torsions')
    return undefined

def _main(root):
    root=Path(root); result_path=root/'result.json'; report_path=root/'report.md'
    try:
        for name,digest in EXPECTED_ASSET_SHA256.items():
            if hashlib.sha256((root/'assets'/name).read_bytes()).hexdigest()!=digest: raise ValueError(f'{name} hash mismatch')
        atoms,bonds,adjacency,mapping=topology_assets(root)
        reference_config=json.loads(FULL_GEOMETRY_PATH.read_text(encoding='utf-8'))
        reference_values=reference_config['reference_values']
        baseline_text=reference_values['full_geometry_baseline_json']
        if hashlib.sha256(baseline_text.encode()).hexdigest()!=reference_values['full_geometry_baseline_sha256']:
            raise ValueError('topology inventory reference damaged')
        baseline=json.loads(baseline_text)
        reference=xyz(root/'assets/1xbb_reference.xyz'); candidate=xyz(root/'assets/1xbb_aiqm1.xyz')
        context=(root/'assets/context.txt').read_text(); fields=dict(line.split('=',1) for line in context.splitlines() if '=' in line)
        if fields.get('system_id')!='1XBB' or fields.get('charge')!='0' or fields.get('multiplicity')!='1' or fields.get('units')!='angstrom': raise ValueError('expected neutral 1XBB singlet identity')
        if len(reference)!=68 or len(candidate)!=68 or [r[0] for r in reference]!=[r[0] for r in candidate]: raise ValueError('paired coordinate correspondence invalid')
        ref_map=next((row for row in mapping['mapped_xyz'] if Path(row['xyz']).name=='1xbb_reference.xyz'),None)
        if ref_map is None: raise ValueError('public 1-based reference mapping missing')
        undefined=topology_inventory(root,reference,candidate,atoms,bonds,adjacency,ref_map,baseline)
    except (OSError,UnicodeError,ValueError,json.JSONDecodeError) as exc:
        print(f'ENV_INVALID: {exc}'); return 2
    try:
        result=json.loads(result_path.read_text()); report=report_path.read_text()
        if isinstance(result, dict):
            result.setdefault('schema_version', 'case01-neutral-geometry/v2')
            result.setdefault('task_version', '2.0')
            result.setdefault('evaluation_scope', 'paired_neutral_1xbb_geometry_only')
        if not report.strip(): raise ValueError('empty report')
    except (OSError,UnicodeError,json.JSONDecodeError,ValueError) as exc:
        print(f'FAIL: {exc}'); return 1
    shape_error=candidate_shape_error(result)
    if shape_error:
        print(f'FAIL: {shape_error}'); return 1
    policy_error=candidate_policy_error(result)
    if policy_error:
        print(f'FAIL: {policy_error}'); return 1
    expected=expected_v2(root,reference,candidate,baseline)
    expected['undefined_torsions']=undefined
    # Validate every selected path against the now-public topology and mapping.
    records={Path(row['xyz']).name:row for row in mapping['mapped_xyz']}
    ref_map=records.get('1xbb_reference.xyz')
    if ref_map is None: print('ENV_INVALID: reference mapping missing'); return 2
    valid,topology_reason,_ledger=check_topology(result.get('geometry_metrics',{}),reference,atoms,bonds,adjacency,ref_map) if isinstance(result,dict) and isinstance(result.get('geometry_metrics'),dict) else (False,'missing metric inventory',{})
    if not valid: print(f'FAIL: {topology_reason}'); return 1
    # Metric arrays are set-valued; order and reversal-equivalent atom encodings are accepted.
    normalized_result=dict(result); normalized_expected=dict(expected)
    for kind in ('bond','angle','torsion'):
        try:
            normalized_result['geometry_metrics'][kind]=sorted([{**row,'atoms':min(tuple(row['atoms']),tuple(reversed(row['atoms'])))} for row in result['geometry_metrics'][kind]],key=lambda row:row['atoms'])
            normalized_expected['geometry_metrics'][kind]=sorted([{**row,'atoms':min(tuple(row['atoms']),tuple(reversed(row['atoms'])))} for row in expected['geometry_metrics'][kind]],key=lambda row:row['atoms'])
        except (KeyError,TypeError): pass
        # Distribution records retain their required order. Only their full-path
        # reversal is canonicalized; submitted order is never repaired or sorted.
        for normalized,original in ((normalized_result,result),(normalized_expected,expected)):
            try:
                rows=original['error_distributions'][kind]['records']
                canonical=[{**row,'atoms':min(tuple(row['atoms']),tuple(reversed(row['atoms'])))} for row in rows]
                if normalized is normalized_expected:
                    canonical.sort(key=lambda row:(-row['absolute_error'],row['atoms']))
                normalized['error_distributions'][kind]['records']=canonical
            except (KeyError,TypeError): pass
    comparable_expected=dict(normalized_expected)
    comparable_expected['tolerance_decision']=dict(normalized_expected['tolerance_decision'])
    comparable_expected['tolerance_decision'].pop('formula',None)
    if not equivalent_numbers(normalized_result,comparable_expected):
        print('FAIL: full geometry inventory, distributions, group sensitivity, or tolerance decision differs from independently recomputed v2 evidence'); return 1
    decision=result.get('tolerance_decision')
    if isinstance(decision,dict) and 'formula' in decision and not isinstance(decision['formula'],str):
        print('FAIL: tolerance_decision.formula must be text when provided'); return 1
    science_ok, science_reason = scientific_contract(result, report, reference, candidate)
    if not science_ok:
        print(f'FAIL: {science_reason}')
        return 1
    # An optional scope note may clarify interpretation, but is not a scored answer field.
    blocks=re.findall(r'```v2_scope\s*\n(.*?)\n```',report,re.S)
    if len(blocks)>1: print('FAIL: at most one optional v2_scope block is allowed'); return 1
    if blocks:
        try: scope=json.loads(blocks[0])
        except json.JSONDecodeError: print('FAIL: malformed v2_scope block'); return 1
        if not isinstance(scope,dict) or ('evaluation_scope' in scope and scope['evaluation_scope']!='paired_neutral_1xbb_geometry_only'):
            print('FAIL: optional v2 scope conflicts with the evaluated scope'); return 1
    logs=Path(os.environ.get('LOGS',root)); logs.mkdir(parents=True,exist_ok=True)
    receipt={'status':'PASS','earned':1,'maximum':1,'reward':1,'task_version':'2.0','evaluation_scope':'paired_neutral_1xbb_geometry_only'}
    (logs/'verification.json').write_text(json.dumps(receipt,indent=2)+'\n'); (logs/'reward.txt').write_text('1\n'); print('PASS: complete v2 geometry decision verified'); return 0


def main(root):
    """Convert only normal verifier outcomes into score evidence; exceptions are environment failures."""
    root=Path(root); logs=Path(os.environ.get('LOGS',root)); logs.mkdir(parents=True,exist_ok=True)
    try:
        code=_main(root)
    except Exception as exc:
        print(f'ENV_INVALID: verifier exception: {type(exc).__name__}: {exc}')
        code=2
    if code==0:
        try:
            receipt=json.loads((logs/'verification.json').read_text(encoding='utf-8'))
            if not isinstance(receipt,dict) or receipt.get('status')!='PASS': raise ValueError('missing PASS receipt')
        except Exception as exc:
            print(f'ENV_INVALID: invalid PASS receipt: {exc}'); code=2
    if code==1:
        (logs/'verification.json').write_text(json.dumps({'status':'FAIL','earned':0,'maximum':1,'reward':0,'reason':'candidate submission did not satisfy the public structured contract'},indent=2)+'\n')
        (logs/'reward.txt').write_text('0\n')
    elif code==2:
        (logs/'verification.json').write_text(json.dumps({'status':'ENV_INVALID','reason':'pinned evidence or verifier execution is unavailable'},indent=2)+'\n')
        (logs/'reward.txt').unlink(missing_ok=True)
    return code

if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1] if len(sys.argv)>1 else "."))
