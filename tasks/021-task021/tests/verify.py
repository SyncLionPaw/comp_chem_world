#!/usr/bin/env python3
# L1 Deliverables: Check required deliverables for completeness and parseability.
# L2 Execution: Check the use of supplied data or archived evidence where required.
# L3 Science: Reconstructing the bicyclic peroxy radical ring-opening profile.
"""Scientific grader for P04 cases 01/02/03/05/06.

The checks read the public output contract and compare machine-readable submitted
results to independently frozen tables. Candidate parsing faults score zero; damaged
inputs, references, or grader dependencies invalidate the run without a reward.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import re
import sys
from pathlib import Path
import xml.etree.ElementTree as ET

HARTREE_KCAL = 627.509
EXPECTED_CRITERIA = [('profile_rows_complete', 'L1'), ('native_quantities_traceable', 'L2'), ('barriers_match_published_profile', 'L3'), ('combination_rule_identified_not_assumed', 'L3'), ('saddle_and_electronic_state_consistent', 'L3')]
PINNED_REFERENCES: dict[str, str] = {'derived_ibpr_barriers.csv': 'sha256:765606501de2a2a75f11549af81a4ce5d0ab28c30c67cc445ceda949e8543883', 'native_ibpr_cluster_energies.csv': 'sha256:9ed8febf3dcdc89c9eae837b7d3d3dccf0a2bbe9c00e9b424541546e998ba070'}
PINNED_ASSET_REFS: dict[str, str] = {'assets/41467_2023_40675_MOESM1_ESM.docx': 'sha256:52c8854e125cac6ea714c61a4e711fea66565cef62d0f176511e819e59fd568a', 'assets/41467_2023_40675_MOESM3_ESM.xlsx': 'sha256:69969f05b7fb9b75335737bfc4e65cd49218d75da632197d929f6196784b67f1', 'assets/Toluene-iBPR-rearrangment/P-C1-DFT.log': 'sha256:6c129624447dbab6e34f6195cb32a2aa8c04658f08419510113c8d8f8380f2f0', 'assets/Toluene-iBPR-rearrangment/P-C1-F12.out': 'sha256:9f7e5ccff2425ed72fa730c8190fa85cd43d4d4e8aef7d230c6e50c47fef8858', 'assets/Toluene-iBPR-rearrangment/P-C2-DFT.log': 'sha256:249341d49148b71394d84ff7b8f03daf17168c7d2ad29720c6f2d8585b7930b1', 'assets/Toluene-iBPR-rearrangment/P-C2-F12.out': 'sha256:0cdbf908defe9396e15ef73dd1e597465ebde667a2583d1b4578ef5d2d69f58c', 'assets/Toluene-iBPR-rearrangment/Toluene-iBPR-DFT.log': 'sha256:d2d7720643c371c07c3e34ea673ac6e70f7e4d610577241e7a7a87e368d168f1', 'assets/Toluene-iBPR-rearrangment/Toluene-iBPR-F12.out': 'sha256:39fb1698aec8630e572a979d929e5ce11817a639930b1ff7641cfa61f064fa6e', 'assets/Toluene-iBPR-rearrangment/Toluene-iBPR-TS-C1-DFT.log': 'sha256:f02930ff0889df3b786d4313edb5a2202c993737b5bd32eda272cbeb5e1381e5', 'assets/Toluene-iBPR-rearrangment/Toluene-iBPR-TS-C1-F12.out': 'sha256:9554d77f3303690a7316f588849e8bc9dcf2ab85c82d89240957cc2daac08eb1', 'assets/Toluene-iBPR-rearrangment/Toluene-iBPR-TS-C2-DFT.log': 'sha256:b598d6a3f39fc3e01b3057e1410d77fe8e0ade8032c8886b2a6480806496fc7f', 'assets/Toluene-iBPR-rearrangment/Toluene-iBPR-TS-C2-F12.out': 'sha256:4d2ff3a288cc3da670f36c6085d94875c80d64259b1e695dcbf5975ea3f99777'}
PINNED_CASE_ID = 'case-01-bpr-rearrangement-energy-profile'


class CandidateFault(Exception):
    pass


class EnvironmentFault(Exception):
    pass


def sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return "sha256:" + h.hexdigest()


def rows(path: Path) -> list[dict[str, str]]:
    try:
        with path.open(encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)
            fields = reader.fieldnames
            if not fields or len(fields) != len(set(fields)):
                raise CandidateFault(f"missing or duplicate CSV header: {path.name}")
            data = list(reader)
            if any(None in r or any(v is None for v in r.values()) for r in data):
                raise CandidateFault(f"inconsistent CSV field count: {path.name}")
            return [{k: v.strip() for k, v in r.items()} for r in data]
    except (OSError, UnicodeError, csv.Error) as e:
        raise CandidateFault(f"cannot read {path.name}: {e}") from e


def json_obj(path: Path) -> object:
    def unique(pairs):
        result = {}
        for k, v in pairs:
            if k in result: raise CandidateFault(f"duplicate JSON field: {k}")
            result[k] = v
        return result
    def finite_tree(value):
        if isinstance(value, float) and not math.isfinite(value):
            raise CandidateFault("non-finite JSON number")
        if isinstance(value, dict):
            for x in value.values(): finite_tree(x)
        if isinstance(value, list):
            for x in value: finite_tree(x)
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"), object_pairs_hook=unique)
        finite_tree(value)
        return value
    except (OSError, UnicodeError, ValueError) as e:
        raise CandidateFault(f"cannot read {path.name}: {e}") from e


def text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8").lower()
    except (OSError, UnicodeError) as e:
        raise CandidateFault(f"cannot read {path.name}: {e}") from e


def num(row: dict, key: str) -> float:
    try:
        if isinstance(row[key], bool): raise ValueError("boolean is not a number")
        x = float(row[key])
        if not math.isfinite(x): raise ValueError("not finite")
        return x
    except (KeyError, TypeError, ValueError, OverflowError) as e:
        raise CandidateFault(f"invalid numeric field {key}: {e}") from e


def near(a: float, b: float, tol: float, *, rel: bool = False) -> bool:
    return (not isinstance(a, bool) and not isinstance(b, bool) and math.isfinite(a) and
            math.isfinite(b) and abs(a-b) <= (tol*max(abs(b),1e-300) if rel else tol))


def regular_file(path: Path, root: Path) -> bool:
    try:
        parts = path.relative_to(root).parts
        current = root
        if root.is_symlink(): return False
        for part in parts:
            current = current / part
            if current.is_symlink(): return False
        return path.is_file() and root.resolve() in path.resolve().parents
    except (OSError, ValueError): return False

def public_asset(app: Path, value: str) -> Path:
    root = app / "assets"
    rel = Path(normalized_path(value))
    if len(rel.parts) == 1:
        matches = list(root.rglob(rel.name))
        if len(matches) != 1: raise CandidateFault("ambiguous/missing asset basename: "+rel.name)
        path = matches[0]
    else: path = root / rel
    if not regular_file(path, root): raise CandidateFault("asset is not a regular public file: "+str(value))
    return path

def submitted_path_matches(app: Path, value: str, expected: Path) -> bool:
    try:
        rel=Path(normalized_path(value))
        # In a field with a separately established species/site/channel source,
        # that scientific context disambiguates an exact expected basename.
        if len(rel.parts)==1:
            return rel.name==expected.name and regular_file(expected,app/"assets")
        return public_asset(app, value).resolve() == expected.resolve()
    except CandidateFault: return False

def level_name(value: str) -> str:
    return value.lower().replace(" ", "").replace("6-31+g*", "6-31+g(d)")

def disposition(value) -> bool:
    v = str(value).strip().lower()
    if v in {"true", "yes", "1", "reconciled"}: return True
    if v in {"false", "no", "0", "unreconciled"}: return False
    raise CandidateFault("unknown Boolean disposition: "+str(value))

def number_in_prose(value: str, target: float, tol: float) -> bool:
    return any(near(float(x),target,tol) for x in re.findall(r"(?<![\w.])[-+]?\d+(?:\.\d*)?(?:[Ee][-+]?\d+)?", value))

def missing_native_reason(value: str) -> bool:
    value = value.lower()
    return ("native" in value or "原生" in value) and any(x in value for x in ("no ","not ","missing","absent","未存储","未提供","不存在","缺失","并非","不是"))

def identical_reason(value: str) -> bool:
    return any(x in value.lower() for x in ("identical","byte-identical","相同","一致"))

def formula_value(formula: str, names: dict[str, float]) -> float:
    """Evaluate arithmetic only: no eval, imports, attributes, or arbitrary calls."""
    import ast
    expr = formula.split("=",1)[-1].strip().lower().replace("^","**").replace("math.exp", "exp").replace("math.log", "log")
    expr = expr.replace("[", "(").replace("]", ")")
    if len(expr)>500: raise CandidateFault("formula too long")
    try: tree=ast.parse(expr,mode="eval")
    except SyntaxError as e: raise CandidateFault("invalid formula syntax") from e
    if len(list(ast.walk(tree)))>80: raise CandidateFault("formula too complex")
    def visit(node):
        if isinstance(node,ast.Expression): return visit(node.body)
        if isinstance(node,ast.Constant) and type(node.value) in (int,float): return float(node.value)
        if isinstance(node,ast.Name) and node.id in names: return names[node.id]
        if isinstance(node,ast.UnaryOp) and isinstance(node.op,(ast.USub,ast.UAdd)):
            v=visit(node.operand);return -v if isinstance(node.op,ast.USub) else v
        if isinstance(node,ast.BinOp) and isinstance(node.op,(ast.Add,ast.Sub,ast.Mult,ast.Div,ast.Pow)):
            a,b=visit(node.left),visit(node.right)
            if isinstance(node.op,ast.Add): v=a+b
            elif isinstance(node.op,ast.Sub): v=a-b
            elif isinstance(node.op,ast.Mult): v=a*b
            elif isinstance(node.op,ast.Div): v=a/b
            else:
                if abs(b)>100: raise CandidateFault("excessive formula exponent")
                v=a**b
            if not isinstance(v,(int,float)) or not math.isfinite(v): raise CandidateFault("non-finite formula value")
            return v
        if isinstance(node,ast.Call) and isinstance(node.func,ast.Name) and node.func.id in ("exp","log") and len(node.args)==1 and not node.keywords:
            v=visit(node.args[0]);return math.exp(v) if node.func.id=="exp" else math.log(v)
        raise CandidateFault("unsupported formula node")
    return visit(tree)


def need(ok: bool, msg: str) -> None:
    if not ok:
        raise CandidateFault(msg)


def read_ref(test: Path, name: str) -> list[dict[str, str]]:
    path = test / "references" / name
    if not regular_file(path, test/"references") or name not in PINNED_REFERENCES or sha(path) != PINNED_REFERENCES[name]:
        raise EnvironmentFault(f"missing frozen reference table {name}")
    try:
        with path.open(encoding="utf-8-sig", newline="") as f:
            return list(csv.DictReader(f))
    except (OSError, UnicodeError, csv.Error) as e:
        raise EnvironmentFault(f"frozen reference table {name} is unreadable: {e}") from e


def check_columns(data: list[dict], expected: set[str], label: str) -> None:
    need(bool(data), f"{label}: empty table")
    missing = expected - set(data[0])
    need(not missing, f"{label}: missing columns {sorted(missing)}")


def pick(row: dict, *names: str) -> str:
    for n in names:
        if n in row:
            return row[n]
    raise CandidateFault("missing one of required fields: " + ", ".join(names))


def normalized_path(value: str) -> str:
    if not isinstance(value, str): raise CandidateFault("asset path must be a string")
    path = Path(value.strip().replace("\\", "/"))
    if path.is_absolute() or ".." in path.parts:
        raise CandidateFault("absolute/traversal asset path is not accepted")
    parts = list(path.parts)
    if parts and parts[0] == "assets": parts = parts[1:]
    if parts and parts[0] == "raw_data": parts = parts[1:]
    # Frozen source tables retain the original deposit prefix; strip only that
    # known prefix, never an arbitrary leading directory or a traversal segment.
    if len(parts) >= 3 and parts[0] == "unpacked" and re.fullmatch(r"QC-Files3-[a-f0-9]+", parts[1]) and parts[2] == "QC-Files3": parts = parts[3:]
    elif parts and parts[0] == "QC-Files3": parts = parts[1:]
    return Path(*parts).as_posix() if parts else ""


def criterion(name: str, passed: bool, reason: str, level: str) -> dict:
    return {"name": name, "level": level, "passed": bool(passed), "reason": reason}


def case01_asset(app: Path, source: str, directory: str = "") -> Path:
    """Resolve public asset paths or unambiguous basenames without escaping assets."""
    root = app / "assets"
    rel = Path(source)
    hint = Path(directory) if directory else Path()
    for path in (rel, hint):
        if path.is_absolute() or ".." in path.parts:
            raise CandidateFault("asset path must stay inside assets")
    if rel.parts and rel.parts[0] == "assets": rel = Path(*rel.parts[1:])
    if hint.parts and hint.parts[0] == "assets": hint = Path(*hint.parts[1:])
    if len(rel.parts) == 1:
        matches = list(root.rglob(rel.name))
        # A directory hint cannot make an ambiguous basename acceptable.
        if len(matches) != 1: raise CandidateFault(f"asset basename is missing or ambiguous: {source}")
        file = matches[0]
        if directory and file != root / hint / rel:
            raise CandidateFault(f"source_directory disagrees with asset: {source}")
    else:
        file = root / rel
    if not file.is_file() or any(x.is_symlink() for x in (file, *file.parents) if x == root or root in x.parents):
        raise CandidateFault(f"asset is missing or a symlink: {source}")
    if not file.resolve().is_relative_to(root.resolve()):
        raise CandidateFault("asset path escaped assets")
    return file.resolve()


def case01_markdown_vectors(document: str, scheme: str) -> list[list[float]]:
    """Read numeric table cells without depending on heading wording."""
    vectors = []
    number = r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[Ee][-+]?\d+)?"
    section_scheme = None
    for line in document.splitlines():
        if re.match(r"^\s*#{1,6}\s", line):
            section_scheme = next((name for name in ("dft_zero_point", "dft_electronic", "dft_gibbs", "f12_only")
                                   if re.search(rf"(?<![\w]){re.escape(name)}(?![\w])", line)), None)
        if "|" not in line:
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        row_scheme = bool(re.search(rf"(?<![\w]){re.escape(scheme)}(?![\w])", cells[0]))
        scoped_row = section_scheme == scheme and cells[0].strip("`* ").lower() in {"predicted", "prediction", "predictions", "deviation", "deviations", "signed deviations", "absolute deviations"}
        if len(cells) < 2 or not (row_scheme or scoped_row):
            continue
        scalars = []
        for cell in cells[1:]:
            value = cell.strip("`* ").replace("−", "-").replace("＋", "+")
            # Four numbers may occupy four columns or one vector-valued cell.
            # Consume the whole numeric cell so prose/minimum misses cannot
            # accidentally supply the required four-point evidence.
            matches = re.findall(number, value)
            remainder = re.sub(number, "", value)
            if len(matches) == 4 and re.fullmatch(r"[\s/,;\[\]()]*", remainder):
                vectors.append([float(x) for x in matches])
            if re.fullmatch(number, value):
                scalars.append(float(value))
            else:
                if len(scalars) >= 4:
                    vectors.extend(scalars[i:i+4] for i in range(0, len(scalars)-3, 4))
                scalars = []
        if len(scalars) >= 4:
            vectors.extend(scalars[i:i+4] for i in range(0, len(scalars)-3, 4))
    return vectors


def case01(app: Path, final: Path, test: Path) -> list[dict]:
    native = read_ref(test, "native_ibpr_cluster_energies.csv")
    derived = read_ref(test, "derived_ibpr_barriers.csv")
    names = ["profile_rows_complete", "native_quantities_traceable", "barriers_match_published_profile",
             "combination_rule_identified_not_assumed", "saddle_and_electronic_state_consistent"]
    result = {n: False for n in names}
    notes = {n: "" for n in names}
    by_species: dict[str, dict] = {}
    nref = {r["species"].upper(): r for r in native}
    dref = {r["species"].upper(): r for r in derived}
    try:
        candidate = rows(final / "bpr_profile.csv")
        required = {"species", "file_dft", "file_f12", "e_electronic_au", "zpe_au", "e_zero_point_au", "e_f12_au", "derived_kcal_per_mol"}
        check_columns(candidate, required, "bpr_profile.csv")
        by_species = {r["species"].strip().upper(): r for r in candidate}
        output_files_ok = all((final / name).is_file() for name in
                              ("bpr_profile.csv", "bpr_profile.json", "energy_rule.md", "native_parse_manifest.json"))
        result[names[0]] = output_files_ok and len(candidate) == 5 and len(by_species) == 5 and set(by_species) == set(nref)
        if result[names[0]]:
            for row in by_species.values():
                for col in ("e_electronic_au", "zpe_au", "e_zero_point_au", "e_f12_au", "derived_kcal_per_mol"):
                    num(row, col)
                for col in ("file_dft", "file_f12"):
                    file = case01_asset(app, row[col])
                    expected_suffix = ".log" if col == "file_dft" else ".out"
                    result[names[0]] &= file.suffix == expected_suffix
        if result[names[0]]:
            for sp, ref in nref.items():
                result[names[0]] &= Path(by_species[sp]["file_dft"]).name == ref["file_dft"]
                result[names[0]] &= Path(by_species[sp]["file_f12"]).name == ref["file_f12"]
                if sp == "BPR": result[names[0]] &= near(num(by_species[sp], "derived_kcal_per_mol"), 0.0, 1e-8)
        notes[names[0]] = "five unique stationary point rows and all required numeric fields"
    except CandidateFault as e:
        result[names[0]] = False
        notes[names[0]] = str(e)

    manifest_records = []
    try:
        manifest = json_obj(final / "native_parse_manifest.json")
        manifest_records = manifest.get("records", []) if isinstance(manifest, dict) else manifest
        if not isinstance(manifest_records, list): raise CandidateFault("manifest records must be a list")
        expected_labels = {}
        for sp in nref:
            expected_labels[(sp, "zpe_au")] = ("dft", "Zero-point correction=")
            expected_labels[(sp, "e_zero_point_au")] = ("dft", "Sum of electronic and zero-point Energies=")
            expected_labels[(sp, "e_f12_au")] = ("f12", "RCCSD(T)-F12A/cc-pVDZ-F12 energy=")
        required_keys = set(expected_labels)
        for sp in nref:
            expected_labels[(sp, "e_electronic_au")] = ("dft", "SCF Done:")
            expected_labels[(sp, "e_dft_gibbs_au")] = ("dft", "Sum of electronic and thermal Free Energies=")
            expected_labels[(sp, "e_gibbs_au")] = ("dft", "Sum of electronic and thermal Free Energies=")
        found = {}
        gibbs_species = set()
        trace_ok = True
        for r in manifest_records:
            if not isinstance(r, dict): trace_ok = False; continue
            key = (str(r.get("species", "")).upper(), str(r.get("quantity", "")))
            if key not in expected_labels or key in found: trace_ok = False; continue
            if key[1] in {"e_dft_gibbs_au", "e_gibbs_au"}:
                if key[0] in gibbs_species: trace_ok = False; continue
                gibbs_species.add(key[0])
            kind, label = expected_labels[key]
            source = str(r.get("source_file", ""))
            try:
                p = case01_asset(app, source, str(manifest.get("source_directory", "")) if isinstance(manifest, dict) else "")
            except CandidateFault:
                trace_ok = False
                continue
            source_lines = p.read_text(errors="replace").splitlines()
            actual_label_lines = [i + 1 for i, source_line in enumerate(source_lines) if label in source_line]
            if not actual_label_lines: trace_ok = False; continue
            raw_line_no = r.get("line_number")
            if raw_line_no in (None, ""):
                line_no = actual_label_lines[-1]
            else:
                try: line_no = int(raw_line_no)
                except (TypeError, ValueError): line_no = 0
                if line_no != actual_label_lines[-1]: trace_ok = False; continue
            if not (1 <= line_no <= len(source_lines)): trace_ok = False; continue
            line = source_lines[line_no - 1]
            label_record = str(r.get("label", ""))
            if label not in line or (label_record.strip() and label_record.strip() not in line): trace_ok = False; continue
            pattern = (r"SCF Done:\s+E\([^)]*\)\s*=" if key[1] == "e_electronic_au" else re.escape(label))
            m = re.search(pattern + r"\s*([-+]?(?:\d+\.?\d*|\.\d+)(?:[EeDd][-+]?\d+)?)", line)
            if not m: trace_ok = False; continue
            actual = float(m.group(1).replace("D", "E").replace("d", "e"))
            try: asserted = float(r["value_au"])
            except (KeyError, TypeError, ValueError): trace_ok = False; continue
            if not near(actual, asserted, 5.1e-7): trace_ok = False; continue
            if Path(p).name not in {nref[key[0]]["file_dft"], nref[key[0]]["file_f12"]}: trace_ok = False; continue
            expected_candidate_file = by_species[key[0]]["file_dft" if kind == "dft" else "file_f12"]
            if p != case01_asset(app, expected_candidate_file): trace_ok = False; continue
            found[key] = asserted
        if not required_keys <= found.keys(): trace_ok = False
        # Manifest primitives must reproduce the row values, not merely cite files.
        for sp, row in by_species.items():
            for col in ("zpe_au", "e_zero_point_au", "e_f12_au"):
                if (sp, col) not in found or not near(num(row, col), found[(sp, col)], 1e-5): trace_ok = False
            if (sp, "e_electronic_au") in found and not near(num(row, "e_electronic_au"), found[(sp, "e_electronic_au")], 5.1e-7): trace_ok = False
            if not near(num(row, "e_electronic_au"), num(row, "e_zero_point_au") - num(row, "zpe_au"), 5e-6): trace_ok = False
        result[names[1]] = trace_ok and result[names[0]]
        notes[names[1]] = f"{len(found)} native records validated; required primitives, source lines, pairing and CSV values " + ("agree" if result[names[1]] else "failed validation")
    except (CandidateFault, KeyError, TypeError, ValueError) as e:
        notes[names[1]] = str(e)

    energy_ok = result[names[0]] and result[names[1]]
    if energy_ok:
        published = {"C1": 18.8, "C2": 17.9, "P-C1": -51.7, "P-C2": -49.4}
        for sp, val in published.items():
            row = by_species[sp]
            calculated = ((num(by_species[sp], "e_f12_au") - num(by_species["BPR"], "e_f12_au")) +
                          (num(by_species[sp], "zpe_au") - num(by_species["BPR"], "zpe_au"))) * HARTREE_KCAL
            energy_ok &= near(num(row, "derived_kcal_per_mol"), calculated, 0.10)
            energy_ok &= near(num(row, "derived_kcal_per_mol"), float(dref[sp]["f12_plus_dft_zpe"]), 0.10)
            energy_ok &= near(num(row, "derived_kcal_per_mol"), val, 0.10)
    result[names[2]] = energy_ok
    notes[names[2]] = "Hartree differences are independently recomputed and compared with all four published values at 0.10 kcal/mol"

    rule_ok = False
    try:
        rule = json_obj(final / "bpr_profile.json")
        rule_text = json.dumps(rule, ensure_ascii=False).lower()
        rule_fields = rule.get("rule", {}) if isinstance(rule, dict) else {}
        if isinstance(rule_fields, dict):
            electronic_source = str(rule_fields.get("electronic_source", "")).lower()
            correction_source = str(rule_fields.get("correction_source", "")).lower()
            unit = str(rule_fields.get("unit", "")).lower().replace("−", "-").replace("⁻", "-").replace("¹", "1")
            unit = re.sub(r"[\s·]", "", unit)
            negated_electronic = re.search(r"\b(?:not|non|no|without|excluding|instead[ _-]+of)[ _-]+(?:f12|molpro|coupled[ _-]*cluster|r?ccsd)", electronic_source)
            negated_correction = re.search(r"\b(?:not|non|no|without|excluding|instead[ _-]+of)[ _-]+(?:zpe|zero[ _-]*point)", correction_source)
            negated_electronic = negated_electronic or re.search(r"(?:f12|molpro|coupled[ _-]*cluster|r?ccsd)[\w ()_-]{0,30}(?:not|never)[ _-]+(?:used|included|applied|selected)|(?:f12|molpro)[ _-]+(?:omitted|unused)", electronic_source)
            negated_correction = negated_correction or re.search(r"(?:zpe|zero[ _-]*point)[\w ()_-]{0,30}(?:not|never)[ _-]+(?:used|included|applied|selected)|(?:zpe|zero[ _-]*point)[ _-]+(?:omitted|unused)", correction_source)
            rule_ok = bool(re.search(r"f12|molpro|coupled[ _-]*cluster|r?ccsd", electronic_source)) and not negated_electronic and \
                      bool(re.search(r"zpe|zero[ _-]*point|零点", correction_source)) and not negated_correction and \
                      str(rule_fields.get("reference_species", "")).upper() == "BPR" and \
                      unit in {"kcal/mol", "kcalmol-1", "kcalmol^-1", "kcalmol**-1"} and \
                      near(float(rule_fields.get("hartree_to_kcal", 0)), HARTREE_KCAL, 0.001)
        else:
            rule_ok = "f12" in rule_text and "zpe" in rule_text
        rule_md = text(final / "energy_rule.md")
        alternatives = {
            "dft_zero_point": [float(dref[x]["dft_zero_point"]) for x in ("C1", "C2", "P-C1", "P-C2")],
            "dft_electronic": [float(dref[x]["dft_electronic"]) for x in ("C1", "C2", "P-C1", "P-C2")],
            "dft_gibbs": [float(dref[x]["dft_gibbs"]) for x in ("C1", "C2", "P-C1", "P-C2")],
            "f12_only": [float(dref[x]["f12_only"]) for x in ("C1", "C2", "P-C1", "P-C2")],
        }
        rejected_schemes = set()
        alternative_issues = []
        rejected_records = rule_fields.get("rejected_alternatives", []) if isinstance(rule_fields, dict) else []
        for rec in rejected_records:
            if not isinstance(rec, dict): continue
            scheme = str(rec.get("scheme", "")).lower()
            vector = alternatives.get(scheme)
            supplied = rec.get("values_kcal_per_mol")
            if not vector or not isinstance(supplied, (dict, list)): continue
            try:
                actuals = ([float(supplied[k]) for k in ("C1", "C2", "P-C1", "P-C2")] if isinstance(supplied, dict)
                           else [float(x) for x in supplied])
            except (KeyError, TypeError, ValueError): continue
            section = re.search(rf"(?ms)^## rejected {re.escape(scheme.replace('_', ' '))}\s*\n(.*?)(?=^## |\Z)", rule_md)
            predicted_line = re.search(r"c1, c2, p-c1, p-c2:\s*([^\n]+)", section.group(1)) if section else None
            deviation_line = re.search(r"absolute deviations from the published profile in that order:\s*([^\n]+)", section.group(1)) if section else None
            try:
                text_values = [float(x) for x in re.findall(r"[-+]?\d+(?:\.\d+)?", predicted_line.group(1))] if predicted_line else []
                text_devs = [float(x) for x in re.findall(r"[-+]?\d+(?:\.\d+)?", deviation_line.group(1))] if deviation_line else []
            except ValueError: text_values, text_devs = [], []
            expected_devs = [abs(v-pub) for v, pub in zip(vector, (18.8, 17.9, -51.7, -49.4))]
            vectors = case01_markdown_vectors(rule_md, scheme)
            if text_values: vectors.append(text_values)
            if text_devs: vectors.append(text_devs)
            signed_devs = [v-pub for v, pub in zip(vector, (18.8, 17.9, -51.7, -49.4))]
            predictions_ok = any(len(v) == 4 and all(near(a, b, 0.02) for a, b in zip(v, vector)) for v in vectors)
            deviations_ok = any(len(v) == 4 and any(all(near(a, b, 0.02) for a, b in zip(v, devs))
                                  for devs in (expected_devs, signed_devs)) for v in vectors)
            if not predictions_ok: alternative_issues.append(f"{scheme}: four Markdown predictions missing or incorrect")
            if not deviations_ok: alternative_issues.append(f"{scheme}: four per-point deviations missing or incorrect (a minimum miss alone is insufficient)")
            if (len(actuals) == 4 and all(near(a, b, 0.02) for a, b in zip(actuals, vector))
                and predictions_ok and deviations_ok):
                rejected_schemes.add(scheme)
        json_values = rule.get("derived_values_kcal_per_mol", {}) if isinstance(rule, dict) else {}
        json_pub = rule.get("published_values_kcal_per_mol", {}) if isinstance(rule, dict) else {}
        json_agrees = isinstance(json_values, dict) and isinstance(json_pub, dict)
        for sp, pub in (("C1", 18.8), ("C2", 17.9), ("P-C1", -51.7), ("P-C2", -49.4)):
            try:
                json_agrees &= near(float(json_values[sp]), num(by_species[sp], "derived_kcal_per_mol"), 0.01)
                json_agrees &= near(float(json_pub[sp]), pub, 0.01)
            except (KeyError, TypeError, ValueError): json_agrees = False
        result[names[3]] = rule_ok and len(rejected_schemes) >= 2 and energy_ok and json_agrees
        notes[names[3]] = f"machine rule plus {len(rejected_schemes)} distinct measured alternative energy vectors" + ("; " + "; ".join(alternative_issues) if alternative_issues else "")
    except CandidateFault as e:
        notes[names[3]] = str(e)

    modes_ok = True
    for sp, ref in nref.items():
        path = app / "assets" / "Toluene-iBPR-rearrangment" / ref["file_dft"]
        try:
            source = path.read_text(errors="replace")
            freq_groups = re.findall(r"Frequencies --\s+([^\n]+)", source)
            frequencies = [float(x.replace("D", "E")) for group in freq_groups for x in re.findall(r"[-+]?\d+(?:\.\d+)?", group)]
            charges = re.findall(r"Charge =\s*(-?\d+)\s+Multiplicity =\s*(\d+)", source)
            expected_imag = 1 if sp in {"C1", "C2"} else 0
            modes_ok &= len(frequencies) == 57 and sum(x < 0 for x in frequencies) == expected_imag
            modes_ok &= bool(charges) and int(charges[-1][1]) == 2
            row = by_species.get(sp, {})
            modes_ok &= Path(row.get("file_dft", "")).name == ref["file_dft"]
            orientations = list(re.finditer(r"Standard orientation:", source))
            if not orientations:
                modes_ok = False
            else:
                tail = source[orientations[-1].end():].splitlines()
                atom_lines, separator_count = [], 0
                for line in tail:
                    if re.match(r"\s*-{5,}", line):
                        separator_count += 1
                        if separator_count == 3: break
                        continue
                    if separator_count == 2 and re.match(r"\s*\d+\s+\d+\s+\d+\s+[-+\d.]", line): atom_lines.append(line)
                modes_ok &= len(atom_lines) == 21
        except OSError:
            modes_ok = False
    result[names[4]] = modes_ok and result[names[0]]
    notes[names[4]] = "Gaussian source frequency list, final multiplicity, and profile file assignment independently checked"
    return [
        criterion(n, result[n], notes[n], level) for n, level in zip(names, ("L1", "L2", "L3", "L3", "L3"))
    ]


def case02(app: Path, final: Path, test: Path) -> list[dict]:
    census = read_ref(test, "native_gaussian_census.csv")
    members = read_ref(test, "derived_conformer_members.csv")
    barriers = read_ref(test, "derived_si_table7_isomer_barriers.csv")
    audit = rows(final / "saddle_audit.csv")
    check_columns(audit, {"file", "level", "multiplicity", "n_atoms", "formula", "n_modes", "n_imaginary",
                          "imaginary_freq_cm1", "classification", "normal_termination"}, "saddle_audit.csv")
    expected_by_path = {normalized_path(r["relative_path"]): r for r in census}
    audit_by_path = {normalized_path(pick(r, "file")): r for r in audit}
    census_ok = len(audit) == len(census) == 196 and len(audit_by_path) == 196 and set(audit_by_path) == set(expected_by_path)
    mode_ok = census_ok
    for path, ref in expected_by_path.items():
        row = audit_by_path.get(path)
        if not row: continue
        try:
            asset = app / "assets" / path
            if not asset.is_file() or asset.is_symlink(): mode_ok = False; continue
            source = asset.read_text(errors="replace")
            nat_match = re.findall(r"NAtoms=\s*(\d+)", source)
            charges = re.findall(r"Charge =\s*(-?\d+)\s+Multiplicity =\s*(\d+)", source)
            harm = source.rfind("Harmonic frequencies")
            zpe_at = source.find("Zero-point correction=", harm)
            freq_section = source[harm:zpe_at if zpe_at >= 0 else None]
            native_freqs = [float(x) for line in re.findall(r"Frequencies --([^\n]+)", freq_section)
                            for x in re.findall(r"[-+]?\d+(?:\.\d*)?(?:[Ee][-+]?\d+)?", line)]
            orientation = source.rfind("Standard orientation:")
            tail = source[orientation:] if orientation >= 0 else ""
            atom_nums = []
            sep_count = 0
            for line in tail.splitlines()[1:]:
                if re.match(r"\s*-{5,}", line):
                    sep_count += 1
                    if sep_count >= 3: break
                    continue
                if sep_count == 2:
                    m = re.match(r"\s*\d+\s+(\d+)\s+\d+\s+", line)
                    if m: atom_nums.append(int(m.group(1)))
            element = {1:"H",6:"C",7:"N",8:"O",9:"F",15:"P",16:"S",17:"Cl"}
            counts = {}
            for anum in atom_nums: counts[element.get(anum, f"X{anum}")] = counts.get(element.get(anum, f"X{anum}"),0)+1
            formula = "".join(e+(str(counts[e]) if counts[e] != 1 else "") for e in ("C","H") if e in counts)
            formula += "".join(e+(str(counts[e]) if counts[e] != 1 else "") for e in sorted(counts) if e not in {"C","H"})
            route = " ".join(line.strip().lower() for line in source.splitlines() if re.match(r"\s*#",line))
            expected_level = ref["level"].lower().replace(" ", "")
            if "b3lyp" in expected_level: native_level = "b3lyp" in route and ("6-31+g(d)" in route.replace(" ", "") or "6-31+g*" in route.replace(" ", ""))
            else: native_level = "wb97xd" in route and "aug-cc-pvtz" in route.replace(" ", "")
            nat = int(nat_match[-1]) if nat_match else -1
            imag_values = [x for x in native_freqs if x < 0]
            modes, imag = len(native_freqs), len(imag_values)
            mode_ok &= nat == int(float(row["n_atoms"])) == len(atom_nums)
            expected_modes = 3*nat-5 if formula == "NO" and nat == 2 else 3*nat-6
            mode_ok &= modes == int(float(row["n_modes"])) == expected_modes and imag == int(float(row["n_imaginary"])) == int(float(ref["n_imaginary"]))
            mode_ok &= formula == row["formula"] == ref["formula"] and native_level
            mode_ok &= row["classification"].lower() == ref["class"].lower()
            mode_ok &= row["level"].lower().replace(" ", "") == ref["level"].lower().replace(" ", "")
            mode_ok &= bool(charges) and near(float(row["multiplicity"]), float(charges[-1][1]), 1e-6) and near(float(charges[-1][1]), float(ref["multiplicity"]),1e-6)
            claimed_imag = [float(x) for x in re.findall(r"[-+]?\d+(?:\.\d*)?(?:[Ee][-+]?\d+)?", row["imaginary_freq_cm1"])]
            mode_ok &= len(claimed_imag) == len(imag_values) and all(any(near(x,y,0.05) for y in imag_values) for x in claimed_imag)
            mode_ok &= "normal termination of gaussian" in source.lower()
            mode_ok &= row["normal_termination"].lower() in {"true", "yes", "1"}
        except (ValueError, KeyError): mode_ok = False
    counts = {c: sum(1 for r in audit if r.get("classification", "").lower() == c)
              for c in ("transition_state", "minimum", "higher_order_saddle")}
    partition_ok = counts.get("transition_state") == 79 and counts.get("minimum") == 117 and \
                   counts.get("higher_order_saddle") == 0 and all(r.get("normal_termination", "").lower() in {"true", "yes", "1"} for r in audit)
    levels = {"wB97XD/aug-cc-pVTZ": 191, "B3LYP/6-31+G(d)": 5}
    level_counts = {k: sum(1 for r in audit if r.get("level", "").replace(" ", "").lower() == k.replace(" ", "").lower()) for k in levels}
    levels_ok = level_counts == levels
    member_file = final / "conformer_members.csv"
    member_ok = False
    if member_file.is_file():
        submitted = rows(member_file)
        check_columns(submitted, {"relative_path", "family_id", "level", "zpe_au", "delta_from_family_min_kcal_per_mol", "within_2_kcal", "selected_lowest"}, "conformer_members.csv")
        expected_members = {normalized_path(r["relative_path"]): r for r in members}
        actual_members = {normalized_path(r["relative_path"]): r for r in submitted}
        member_ok = len(actual_members) == len(expected_members) and set(actual_members) == set(expected_members)
        for path, ref in expected_members.items():
            row = actual_members.get(path, {})
            try:
                member_ok &= row["family_id"] == ref["family_id"]
                member_ok &= row["level"].replace(" ", "").lower() == ref["level"].replace(" ", "").lower()
                member_ok &= near(float(row["zpe_au"]), float(ref["zpe_au"]), 5e-7)
                member_ok &= near(float(row["delta_from_family_min_kcal_per_mol"]), float(ref["delta_from_family_min_kcal_per_mol"]), 0.05)
                member_ok &= row["within_2_kcal"].lower() == ref["within_2_kcal"] and row["selected_lowest"].lower() == ref["selected_lowest"]
            except (KeyError, ValueError): member_ok = False
    notes = text(final / "audit_notes.md")
    alias_ok = "r1" in notes and ("alias" in notes or "conf" in notes)
    selection = rows(final / "conformer_selection.csv")
    check_columns(selection, {"reaction_key", "n_conformers_found", "selected_file", "energy_quantity_used", "spread_within_window_kcal_per_mol"}, "conformer_selection.csv")
    expected_groups: dict[str, list[dict]] = {}
    for member in members: expected_groups.setdefault(member["family_id"], []).append(member)
    selected_by_key = {r["reaction_key"]: r for r in selection}
    select_ok = len(selection) == len(selected_by_key) == len(expected_groups) == 118 and set(selected_by_key) == set(expected_groups)
    for family, group in expected_groups.items():
        row = selected_by_key.get(family)
        if row is None: select_ok = False; continue
        min_member = min(group, key=lambda x: float(x["zpe_au"]))
        retained = [float(x["delta_from_family_min_kcal_per_mol"]) for x in group if x["within_2_kcal"] == "yes"]
        expected_spread = max(retained)-min(retained) if retained else float("nan")
        select_ok &= int(float(row["n_conformers_found"])) == len(group)
        select_ok &= normalized_path(row["selected_file"]) == normalized_path(min_member["relative_path"])
        select_ok &= pick(row,"energy_quantity_used").lower() in {"sum of electronic and zero-point energies (zpe)","zpe"}
        select_ok &= near(float(row["spread_within_window_kcal_per_mol"]), expected_spread, 0.05)
    # Recompute each channel from the public Gaussian ZPE and Molpro F12 energy
    # files; never accept the candidate's barrier number as its own evidence.
    barrier_ok = False
    submitted_barriers = rows(final / "isomer_barriers.csv")
    check_columns(submitted_barriers, {"site", "channel", "minimum_dft", "minimum_f12", "saddle_dft", "saddle_f12",
                                      "composite_kcal_per_mol", "published_kcal_per_mol", "deviation_kcal_per_mol"}, "isomer_barriers.csv")
    sites = {"ipso": "iBPR", "meta": "mBPR", "para": "pBPR", "ortho": "OBPR"}
    submitted_map = {(r["site"].lower(), r["channel"].upper()): r for r in submitted_barriers}
    barrier_ok = len(submitted_map) == 8 and len(submitted_barriers) == 8
    def gaussian_zpe(path: Path) -> float:
        vals = re.findall(r"Zero-point correction=\s*([-+0-9.Ee]+)", path.read_text(errors="replace"))
        if not vals: raise CandidateFault(f"no Gaussian ZPE in {path.name}")
        return float(vals[-1])
    def molpro_f12(path: Path) -> float:
        vals = re.findall(r"RCCSD\(T\)-F12A/cc-pVDZ-F12 energy=\s*([-+0-9.Ee]+)", path.read_text(errors="replace"))
        if not vals: raise CandidateFault(f"no F12A energy in {path.name}")
        return float(vals[-1])
    for site, base in sites.items():
        for channel in ("C1", "C2"):
            row = submitted_map.get((site, channel))
            if not row: barrier_ok = False; continue
            dft_min_name = f"Toluene-{base}-DFT.log" if site != "ortho" else "Toluene-oBPR-DFT.log"
            dft_ts_name = f"Toluene-{base}-TS-{channel}-DFT.log"
            f12_base = base
            f12_min_name = f"Toluene-{f12_base}-F12.out"
            f12_ts_name = f"Toluene-{f12_base}-TS-{channel}-F12.out"
            if site == "ortho": f12_min_name = "Toluene-OBPR-F12.out"
            paths = [app / "assets/Figure4/Toluene" / x for x in (dft_min_name, f12_min_name, dft_ts_name, f12_ts_name)]
            try:
                barrier_ok &= [Path(row[k]).name for k in ("minimum_dft","minimum_f12","saddle_dft","saddle_f12")] == [x.name for x in paths]
                composite = ((molpro_f12(paths[3])-molpro_f12(paths[1]))+(gaussian_zpe(paths[2])-gaussian_zpe(paths[0])))*627.509474063
                barrier_ok &= near(num(row,"composite_kcal_per_mol"),composite,0.02)
                expected_published = {"ipso":17.9,"meta":21.0,"para":22.0,"ortho":23.2}[site]
                barrier_ok &= near(num(row,"published_kcal_per_mol"),expected_published,0.02)
                barrier_ok &= near(num(row,"deviation_kcal_per_mol"),abs(composite-expected_published),0.02)
            except (OSError, CandidateFault, ValueError): barrier_ok = False
    site_min = {}
    for site in sites:
        entries = [r for (s,_),r in submitted_map.items() if s == site]
        if len(entries) == 2:
            site_min[site] = min(num(r,"composite_kcal_per_mol") for r in entries)
    barrier_ok &= all(site in site_min for site in sites)
    barrier_ok &= all(near(site_min[s],v,0.20) for s,v in {"ipso":17.9,"meta":21.0,"para":22.0}.items())
    barrier_ok &= near(site_min.get("ortho", float("nan")),24.39,0.03) and abs(site_min.get("ortho",0)-23.2)>1.0
    return [
        criterion("audit_table_covers_deposit", census_ok, "one audit row for each of 196 native logs", "L1"),
        criterion("mode_count_and_classification_consistent", mode_ok, "per-row 3N-6 modes, imaginary counts, level and termination", "L2"),
        criterion("saddle_minimum_partition_reproduced", partition_ok, "79 first-order saddles, 117 minima, no higher saddles or abnormal terminations", "L3"),
        criterion("levels_and_electronic_states_identified", levels_ok, "191 wB97XD and 5 B3LYP; all parsed rows have multiplicity", "L3"),
        criterion("conformer_window_applied_explicitly", member_ok and select_ok and alias_ok, "same-level member offsets and 2 kcal/mol retention verified; R1 alias disclosed", "L3"),
        criterion("isomer_barriers_reproduced", barrier_ok, "ipso/meta/para barriers and ortho published discrepancy disclosed", "L3"),
    ]


def case03(app: Path, final: Path, test: Path) -> list[dict]:
    names = ["rate_table_complete_per_temperature", "rates_read_from_analysis_block", "rates_match_published_table",
             "fit_within_measured_curvature", "branching_validity_range_stated", "fixed_pressure_scope_reported"]
    result = {n: False for n in names}; reason = {n: "" for n in names}
    reference = read_ref(test, "mesmer_tdep_rates.csv")
    published = read_ref(test, "SD_figure1c_arrhenius.csv")
    # Native filenames are stable identifiers; CSV source_file may be asset-relative.
    expected = {Path(r["file"]).name: r for r in reference}
    rates = rows(final / "rates_by_temperature.csv")
    required = {"source_file", "temperature_K", "pressure_Torr", "bath_gas", "k_C1_per_s", "k_C2_per_s", "k_total_per_s",
                "C1_fromRef", "C1_toRef", "C2_fromRef", "C2_toRef"}
    check_columns(rates, required, "rates_by_temperature.csv")
    actual = {Path(pick(r, "source_file")).name: r for r in rates}
    try:
        unique_t = {round(num(r, "temperature_K"), 6) for r in rates}
        all_outputs_parseable = (final / "arrhenius_fit.json").is_file() and (final / "branching_curve.csv").is_file() and (final / "derivation_notes.md").is_file()
    except CandidateFault:
        unique_t = set(); all_outputs_parseable = False
    result[names[0]] = len(rates) == len(actual) == len(expected) == len(unique_t) == 23 and set(actual) == set(expected) and all_outputs_parseable
    reason[names[0]] = "23 unique temperature/source rows and complete output files" if result[names[0]] else "expected 23 unique source files and temperatures"
    xml_ok = result[names[0]]
    for file, ref in expected.items():
        row = actual.get(file)
        if row is None: xml_ok = False; continue
        rel = Path(str(row["source_file"]))
        if rel.is_absolute() or ".." in rel.parts: xml_ok = False; continue
        if rel.parts and rel.parts[0] == "assets": rel = Path(*rel.parts[1:])
        matches = list((app / "assets").rglob(Path(file).name))
        source_path = app / "assets" / rel
        if len(matches) != 1 or source_path.resolve() != matches[0].resolve() or source_path.is_symlink(): xml_ok = False; continue
        try:
            import xml.etree.ElementTree as ET
            root = ET.parse(source_path).getroot()
            ns = {"me": "http://www.chem.leeds.ac.uk/mesmer"}
            pt = root.find(".//me:PTpair", ns)
            lists = root.findall(".//me:analysis/me:rateList", ns)
            if pt is None or len(lists) != 1: xml_ok = False; continue
            rate_list = lists[0]
            rxns = rate_list.findall("me:firstOrderRate", ns)
            by_to = {x.attrib.get("toRef"): x for x in rxns}
            c1, c2 = by_to.get("ringopen-prod1"), by_to.get("ringopen-prod2")
            if len(rxns) != 2 or c1 is None or c2 is None: xml_ok = False; continue
            t, pressure = float(pt.attrib["T"]), float(pt.attrib["P"])
            k1, k2 = float(c1.text), float(c2.text)
            xml_ok &= c1.attrib.get("fromRef") == row["C1_fromRef"] == "RO2"
            xml_ok &= c1.attrib.get("toRef") == row["C1_toRef"] == "ringopen-prod1"
            xml_ok &= c2.attrib.get("fromRef") == row["C2_fromRef"] == "RO2"
            xml_ok &= c2.attrib.get("toRef") == row["C2_toRef"] == "ringopen-prod2"
            xml_ok &= near(num(row, "temperature_K"), t, 1e-8) and near(num(row, "pressure_Torr"), pressure, 1e-8)
            xml_ok &= near(num(row, "k_C1_per_s"), k1, 1e-4, rel=True) and near(num(row, "k_C2_per_s"), k2, 1e-4, rel=True)
            xml_ok &= near(num(row, "k_total_per_s"), k1 + k2, max(1e-30, (k1+k2)*1e-6))
            xml_ok &= row["bath_gas"].upper() == pt.attrib.get("bathGas", "").upper() == "N2"
            xml_ok &= rate_list.attrib.get("units") == "s-1"
        except (OSError, ET.ParseError, KeyError, ValueError, TypeError): xml_ok = False
    result[names[1]] = xml_ok
    reason[names[1]] = "two analysis firstOrderRate elements, species refs, PTpair metadata and values checked against XML" if xml_ok else "candidate does not match both native first-order rates and species references"

    pub_map = {(round(float(r["temperature_K"]), 6), r["block"]): r for r in published}
    pub_ok = result[names[1]]
    for row in rates:
        t = round(num(row, "temperature_K"), 6)
        ref = expected.get(Path(pick(row, "source_file")).name)
        if ref is None:
            pub_ok = False
            continue
        block = ref["source_data_block"]
        if block == "absent": continue
        p = pub_map.get((t, block))
        if p is None: pub_ok = False; continue
        pub_ok &= near(num(row, "k_C1_per_s"), float(p["k_C1_per_s"]), 1e-4, rel=True)
        pub_ok &= near(num(row, "k_C2_per_s"), float(p["k_C2_per_s"]), 1e-4, rel=True)
    result[names[2]] = pub_ok
    reason[names[2]] = "all shared published temperatures match the frozen source-data table within 1e-4 relative"

    fits = json_obj(final / "arrhenius_fit.json")
    if isinstance(fits, dict):
        fit_records = {str(k).lower(): v for k, v in fits.items()}
        if isinstance(fits.get("fits"), list): fit_records = {str(v.get("quantity", "")).lower(): v for v in fits["fits"] if isinstance(v, dict)}
    elif isinstance(fits, list): fit_records = {str(v.get("quantity", "")).lower(): v for v in fits if isinstance(v, dict)}
    else: fit_records = {}
    series = {"c1": [num(r, "k_C1_per_s") for r in rates], "c2": [num(r, "k_C2_per_s") for r in rates],
              "total": [num(r, "k_total_per_s") for r in rates]}
    temps = [num(r, "temperature_K") for r in rates]
    fit_ref = {r["quantity"].lower(): r for r in read_ref(test, "derived_arrhenius_fits.csv") if r["n_points"] == "23"}
    fit_ok = len(fit_records) >= 3 and len(temps) == 23
    R = 0.00198720425864
    for q, measured in series.items():
        rec = fit_records.get(q) or fit_records.get("k_" + q + "_full_range")
        if not isinstance(rec, dict): fit_ok = False; continue
        try:
            a = float(rec["A_per_s"]); n = float(rec["n_T_exponent"]); ea = float(rec["Ea_kcal_per_mol"])
            tref = float(rec["T_ref_K"]); lo = float(rec["fit_min_K"]); hi = float(rec["fit_max_K"])
            claimed = float(rec["max_ln_k_deviation"]); points = int(rec["n_points"])
            formula = str(rec["formula"]).lower().replace(" ", "").replace("**", "^")
            fit_ok &= a > 0 and tref > 0 and lo == 200 and hi == 500 and points == 23
            fit_ok &= formula in {"k(t)=a*(t/t_ref_k)^n*exp(-ea_kcal_per_mol/(r*t))",
                                  "k=a*(t/t_ref_k)^n*exp(-ea_kcal_per_mol/(r*t))"}
            predictions = [math.log(a) + n*math.log(t/tref) - ea/(R*t) for t in temps]
            measured_logs = [math.log(x) for x in measured]
            residual = max(abs(x-y) for x,y in zip(predictions, measured_logs))
            gold_fit = fit_ref["k_"+q+"_full_range"]
            target_residual = float(gold_fit["max_ln_k_deviation"])
            fit_ok &= claimed >= residual - 0.001 and abs(claimed - residual) <= 0.01 and abs(residual-target_residual) <= 0.01
            # Compare the submitted curve to the frozen full-range modified-Arrhenius
            # fit pointwise. Gold's documented convention uses T_ref=1e6 K.
            ga, gn, gea = (float(gold_fit[k]) for k in ("A_per_s", "n_T_exponent", "Ea_kcal_per_mol"))
            gold_predictions = [math.log(ga) + gn*math.log(t/1.0e6) - gea/(R*t) for t in temps]
            fit_ok &= max(abs(x-y) for x,y in zip(predictions, gold_predictions)) <= 0.01
        except (KeyError, TypeError, ValueError, OverflowError): fit_ok = False
    result[names[3]] = fit_ok
    reason[names[3]] = "declared modified Arrhenius equation is evaluated at all 23 temperatures; residuals match measured curvature"

    branch = rows(final / "branching_curve.csv")
    check_columns(branch, {"temperature_K", "branching_C1_percent"}, "branching_curve.csv")
    bmap = {round(num(r, "temperature_K"), 6): r for r in branch}
    branch_ok = len(branch) == 23 and len(bmap) == 23 and set(bmap) == {round(t,6) for t in temps}
    for row in rates:
        t = round(num(row, "temperature_K"), 6)
        if t not in bmap: branch_ok = False; continue
        expected_pct = 100*num(row,"k_C1_per_s")/(num(row,"k_C1_per_s")+num(row,"k_C2_per_s"))
        branch_ok &= near(num(bmap[t], "branching_C1_percent"), expected_pct, 0.01)
    branch_ok &= near(num(bmap[300.0], "branching_C1_percent"), 21.907, 0.5) if 300.0 in bmap else False
    notes = text(final / "derivation_notes.md")
    notes_l = notes.lower()
    has_300 = any(s in notes_l for s in ("300 k", "300k"))
    has_range = any(s in notes_l for s in ("12.8", "12.9")) and any(s in notes_l for s in ("31.0", "31.1"))
    branch_ok &= has_300 and has_range and any(s in notes_l for s in ("temperature-dependent", "varies with temperature", "随温度"))
    result[names[4]] = branch_ok
    reason[names[4]] = "branching fractions recomputed at every row, including the bounded 300 K statement and temperature range"
    pressure_ok = len(rates) == 23 and all(near(num(r,"pressure_Torr"),760,1e-8) and r["bath_gas"].upper()=="N2" for r in rates)
    pressure_ok &= any(s in notes_l for s in ("cannot infer pressure", "cannot be inferred", "single pressure", "single-pressure", "单压不能", "不能推断压力"))
    result[names[5]] = pressure_ok
    reason[names[5]] = "all rows state 760 Torr/N2 and notes state this grid cannot establish pressure response"
    return [criterion(n, result[n], reason[n], level) for n, level in zip(names, ("L1","L2","L3","L3","L3","L3"))]


def case05(app: Path, final: Path, test: Path) -> list[dict]:
    ref = read_ref(test, "mesmer_figure4_rates.csv")
    published = read_ref(test, "SD_figure4_rates.csv")
    matrix = rows(final / "bpr_rate_matrix.csv")
    check_columns(matrix, {"molecule", "oh_addition_site", "source_file", "temperature_K", "pressure_Torr", "bath_gas", "k_channel1_per_s", "k_channel2_per_s", "k_dominant_per_s"}, "bpr_rate_matrix.csv")
    exp = {Path(r["file"]).name: r for r in ref}
    got = {Path(pick(r, "source_file")).name: r for r in matrix}
    provenance = len(got) == 15 and len(matrix) == 15 and set(got) == set(exp)
    for file, e in exp.items():
        r = got.get(file, {})
        try:
            rel=Path(str(r["source_file"]))
            if rel.is_absolute() or ".." in rel.parts: provenance=False; continue
            if rel.parts and rel.parts[0]=="assets": rel=Path(*rel.parts[1:])
            native=app/"assets"/rel
            matches=list((app/"assets").rglob(file))
            if len(matches)!=1 or native.resolve()!=matches[0].resolve() or native.is_symlink(): provenance=False;continue
            root=ET.parse(native).getroot(); ns={"me":"http://www.chem.leeds.ac.uk/mesmer"}
            pt=root.find(".//me:PTpair",ns); rate=root.find(".//me:analysis/me:rateList",ns)
            if pt is None or rate is None: provenance=False;continue
            entries={x.attrib.get("toRef"):x for x in rate.findall("me:firstOrderRate",ns)}
            k1=float(entries["ringopen-prod1"].text);k2=float(entries["ringopen-prod2"].text)
            provenance &= rate.attrib.get("units")=="s-1" and len(entries)==2
            provenance &= r["molecule"].lower() == e["molecule"].lower() and r["oh_addition_site"].lower() == e["oh_addition_site"].lower()
            provenance &= near(num(r,"temperature_K"),float(pt.attrib["T"]),1e-8) and near(float(e["temperature_K"]),float(pt.attrib["T"]),1e-8)
            provenance &= near(num(r,"pressure_Torr"),float(pt.attrib["P"]),1e-8) and near(num(r,"pressure_Torr"),760,1e-8)
            provenance &= r["bath_gas"].upper()==pt.attrib.get("bathGas","").upper()=="N2"
            provenance &= near(num(r,"k_channel1_per_s"),k1,1e-4,rel=True) and near(num(r,"k_channel2_per_s"),k2,1e-4,rel=True)
            provenance &= near(num(r,"k_dominant_per_s"),max(k1,k2),1e-4,rel=True)
        except (CandidateFault, OSError, ET.ParseError, KeyError, ValueError, TypeError): provenance = False
    reconciliation = rows(final / "cell_reconciliation.csv")
    check_columns(reconciliation, {"molecule", "oh_addition_site", "published_value_per_s", "source_file", "temperature_K", "matched_definition", "matched_value_per_s", "relative_deviation", "reconciled"}, "cell_reconciliation.csv")
    rec_map={(r["molecule"].lower(),r["oh_addition_site"].lower()):r for r in reconciliation}
    pub_map={(r["molecule"].lower(),r["oh_addition_site"].lower()):r for r in published}
    native_map={(r["molecule"].lower(),r["oh_addition_site"].lower()):r for r in matrix}
    rec_ok=len(reconciliation)==len(rec_map)==len(pub_map)==16 and set(rec_map)==set(pub_map)
    bad_expected = {("benzene", "ipso"), ("ethylbenzene", "ipso"), ("m-xylene", "meta"), ("p-xylene", "ipso"), ("toluene", "meta"), ("m-xylene","ortho")}
    for key,pub in pub_map.items():
        row=rec_map.get(key,{})
        try:
            published_rate=float(pub["k_298_per_s"])
            rec_ok &= near(num(row,"published_value_per_s"),published_rate,max(1e-14,published_rate*1e-8))
            native=native_map.get(key)
            if native is None:
                rec_ok &= key==("m-xylene","ortho") and row["matched_definition"].lower()=="missing_native" and not row["source_file"].strip() and not row["temperature_K"].strip() and not row["matched_value_per_s"].strip() and not row["relative_deviation"].strip() and row["reconciled"].lower() in {"false","no","unreconciled"}
                continue
            rec_ok &= Path(row["source_file"]).name==Path(native["source_file"]).name and near(num(row,"temperature_K"),num(native,"temperature_K"),1e-8)
            vals={"channel1":num(native,"k_channel1_per_s"),"channel2":num(native,"k_channel2_per_s"),"faster":max(num(native,"k_channel1_per_s"),num(native,"k_channel2_per_s")),"sum":num(native,"k_channel1_per_s")+num(native,"k_channel2_per_s")}
            definition=row["matched_definition"].lower().replace(" ","")
            aliases={"channel1":"channel1","channel 1":"channel1","channel_prod1":"channel1","channel2":"channel2","channel 2":"channel2","channel_prod2":"channel2","faster":"faster","max":"faster","max_channel":"faster","sum":"sum"}
            canonical=aliases.get(definition)
            rec_ok &= canonical is not None
            if canonical is None: continue
            matched=vals[canonical]; rel=abs(matched-published_rate)/published_rate
            rec_ok &= near(num(row,"matched_value_per_s"),matched,max(1e-14,matched*1e-6))
            rec_ok &= near(num(row,"relative_deviation"),rel,1e-5)
            best_rel=min(abs(v-published_rate)/published_rate for v in vals.values())
            expected_yes=best_rel<=0.05
            got_yes=row["reconciled"].lower() in {"true","yes","reconciled"}
            rec_ok &= got_yes==expected_yes
            if got_yes: rec_ok &= rel<=0.05
        except (CandidateFault,KeyError,ValueError,ZeroDivisionError): rec_ok=False
    unreconciled={(r["molecule"].lower(),r["oh_addition_site"].lower()) for r in reconciliation if r["reconciled"].lower() in {"false","no","unreconciled"}}
    unreconciled_ok=unreconciled==bad_expected and sum(1 for r in reconciliation if r["reconciled"].lower() in {"true","yes","reconciled"})==10
    anomalies = json_obj(final / "anomalies.json")
    anomaly_entries=anomalies.get("unreconciled",[]) if isinstance(anomalies,dict) else []
    anomaly_map={(str(x.get("molecule","")).lower(),str(x.get("site","")).lower()):x for x in anomaly_entries if isinstance(x,dict)}
    anomaly_ok=len(anomaly_entries)==len(anomaly_map)==6 and set(anomaly_map)==bad_expected
    for key in bad_expected:
        e=anomaly_map.get(key,{})
        row=rec_map.get(key,{})
        anomaly_ok &= bool(e.get("reason"))
        anomaly_ok &= near(float(e.get("published_value_per_s","nan")),num(row,"published_value_per_s"),max(1e-14,num(row,"published_value_per_s")*1e-8))
        native=native_map.get(key)
        if native is None:
            anomaly_ok &= not e.get("candidates") and not e.get("source_file") and e.get("temperature_K") in (None,"") and "no deposited native" in str(e.get("reason","")).lower()
            continue
        anomaly_ok &= Path(str(e.get("source_file",""))).name==Path(native["source_file"]).name and near(float(e.get("temperature_K","nan")),num(native,"temperature_K"),1e-8)
        expected_candidates={"channel1":num(native,"k_channel1_per_s"),"channel2":num(native,"k_channel2_per_s"),"faster":max(num(native,"k_channel1_per_s"),num(native,"k_channel2_per_s")),"sum":num(native,"k_channel1_per_s")+num(native,"k_channel2_per_s")}
        got={str(c.get("definition","")).lower().replace(" ",""):c for c in e.get("candidates",[]) if isinstance(c,dict)}
        anomaly_ok &= {"channel1","channel2","faster","sum"} <= set(got)
        for definition,value in expected_candidates.items():
            c=got.get(definition,{})
            anomaly_ok &= near(float(c.get("value_per_s","nan")),value,max(1e-14,value*1e-6))
            pubval=num(row,"published_value_per_s")
            anomaly_ok &= near(float(c.get("relative_deviation","nan")),abs(value-pubval)/pubval,1e-5)
    trend = text(final / "trend_analysis.md")
    trend_evidence=json_obj(final/"trend_evidence.json")
    single_claim_ok=isinstance(trend_evidence,dict) and trend_evidence.get("single_definition_claim") is False
    scope=trend_evidence.get("temperature_scope",{}) if isinstance(trend_evidence,dict) else {}
    recorded=scope.get("recorded_temperatures_K",[])
    temp_ok=len(recorded)==3 and all(any(near(float(x),t,0.005) for x in recorded) for t in (298,298.15,300))
    temp_ok &= scope.get("normalisation_status")=="indeterminate_without_molecule_specific_temperature_coefficients"
    arange=scope.get("toluene_ipso_298_to_300_activation_percent_range",[]); nrange=scope.get("with_n_percent",[])
    temp_ok &= len(arange)==2 and near(float(arange[0]),21.7,0.15) and near(float(arange[1]),22.8,0.15)
    temp_ok &= len(nrange)==2 and near(float(nrange[0]),23,0.5) and near(float(nrange[1]),24,0.5)
    temp_ok &= scope.get("close_orderings_indeterminate") is True
    temp_ok &= any(x in trend for x in ("temperature", "温度")) and any(x in trend for x in ("cannot", "indeterminate", "不确定", "无法"))
    count_reconciled = sum(1 for r in reconciliation if r["reconciled"].lower() in {"true", "yes", "reconciled"})
    count_ok = count_reconciled == 10
    return [
        criterion("matrix_and_reconciliation_present", len(matrix) == 15 and len(reconciliation) == 16, "15 native outputs and 16 published cells supplied", "L1"),
        criterion("provenance_per_cell", provenance, "source files, temperatures, and both MESMER channels match the frozen native-output register", "L2"),
        criterion("reconcilable_cells_reproduced", count_ok and rec_ok, "all 16 published values map to a native definition or the explicit missing-witness state; values and residuals recomputed", "L3"),
        criterion("irreconcilable_cells_disclosed", unreconciled_ok and anomaly_ok, "five measured conflicts are named with candidate values and residuals", "L3"),
        criterion("single_definition_claim_rejected", anomaly_ok and single_claim_ok, "structured evidence rejects a universal single-definition claim", "L3"),
        criterion("temperature_normalisation_before_trend", temp_ok, "recorded temperatures and the limited toluene sensitivity example are stated", "L3"),
    ]


def case06(app: Path, final: Path, test: Path) -> list[dict]:
    """Recompute the 30 deposited energy candidates from the public native files."""
    ref = read_ref(test, "derived_rono2_si_table9.csv")
    conflict = read_ref(test, "rono2_meta_alkoxy_identity_conflict.csv")
    si = read_ref(test, "SI_table9_organonitrate.csv")
    expected_cells = {(r["species_column"], r["quantity"]) for r in ref}
    published = {(r["species_column"], r["quantity"]): r for r in si if r.get("unit") == "kcal/mol"}
    def candidate_rows(name: str) -> list[dict[str,str]]:
        try:return rows(final / name)
        except CandidateFault:return []
    candidate = candidate_rows("rono2_energies.csv")
    cand_cols = {"species_column", "quantity", "file_stem", "species_file", "anchor_file", "source_dft_file", "source_f12_file", "anchor_dft_file", "anchor_f12_file", "includes_no2", "dft_zero_point_kcal_per_mol", "composite_kcal_per_mol", "published_kcal_per_mol", "deviation"}
    main_schema=bool(candidate) and cand_cols<=set(candidate[0])
    all_candidates = candidate_rows("rono2_candidates.csv")
    candidate_schema=bool(all_candidates) and cand_cols<=set(all_candidates[0])
    mainmap = {(r["species_column"],r["quantity"]):r for r in candidate}
    candmap = {(r["species_column"],r["quantity"],r["file_stem"]):r for r in all_candidates}
    safe = True
    native_calc: dict[tuple[str,str,str],dict] = {}
    dirs = {"benzene":"RONO2/Benzene", "toluene-ipso":"RONO2/Toluene/Ipso", "toluene-ortho":"RONO2/Toluene/Ortho", "toluene-meta":"RONO2/Toluene/Meta", "toluene-para":"RONO2/Toluene/Para"}
    def native_path(value: str) -> Path:
        rel=Path(value.replace("\\","/"))
        if rel.is_absolute() or ".." in rel.parts: raise CandidateFault("unsafe submitted asset path")
        parts=list(rel.parts)
        if parts and parts[0]=="assets":parts=parts[1:]
        path=app/"assets"/Path(*parts)
        if path.is_symlink() or not path.is_file() or (app/"assets").resolve() not in path.resolve().parents: raise CandidateFault("submitted native path is not a regular public asset")
        return path
    def last_float(pattern: str, raw: str) -> float:
        found=re.findall(pattern,raw,re.M)
        if not found: raise ValueError("native energy label missing")
        return float(found[-1])
    def gaussian_values(path: Path) -> tuple[float,float]:
        raw=path.read_text(encoding="utf-8",errors="replace")
        return last_float(r"Zero-point correction=\s*(-?\d+\.\d+)",raw),last_float(r"Sum of electronic and zero-point Energies=\s*(-?\d+\.\d+)",raw)
    def f12_value(path: Path) -> float:
        raw=path.read_text(encoding="utf-8",errors="replace")
        try:return last_float(r"RCCSD\(T\)-F12A/cc-pVDZ-F12 energy=\s*(-?\d+\.\d+)",raw)
        except ValueError:return last_float(r"!RHF-RCCSD\(T\)-F12a energy\s+(-?\d+\.\d+)",raw)
    no2_d=app/"assets/RONO2/NOx/NO2-DFT.log"; no2_f=app/"assets/RONO2/NOx/NO2-F12.out"
    no2_zpe,no2_e0=gaussian_values(no2_d); no2_e=f12_value(no2_f)
    identity_ok=False
    identity={}
    try:
        identity=conflict[0]
        d1=native_path("assets/"+normalized_path(identity["dft_path"]));d2=native_path("assets/"+normalized_path(conflict[1]["dft_path"]))
        f1=native_path("assets/"+normalized_path(identity["f12_path"]));f2=native_path("assets/"+normalized_path(conflict[1]["f12_path"]))
        identity_ok=sha(d1)==sha(d2)==identity["dft_sha256"] and sha(f1)==sha(f2)==identity["f12_sha256"]
    except (CandidateFault,KeyError,IndexError,OSError):identity_ok=False
    for e in ref:
        col,qty,stem=e["species_column"],e["quantity"],e["file_stem"]
        folder=dirs[col]
        dft_rel=f"{folder}/{stem}-DFT.log";f12_rel=f"{folder}/{stem}-F12.out"
        anchor_d_rel=f"{folder}/B-RONO2-DFT.log";anchor_f_rel=f"{folder}/B-RONO2-F12.out"
        no2="+ NO2" in qty
        try:
            dft=native_path("assets/"+dft_rel);f12=native_path("assets/"+f12_rel);ad=native_path("assets/"+anchor_d_rel);af=native_path("assets/"+anchor_f_rel)
            z,e0=gaussian_values(dft);az,ae0=gaussian_values(ad);ef=f12_value(f12);aef=f12_value(af)
            dft_rel_value=((e0+(no2_e0 if no2 else 0))-ae0)*HARTREE_KCAL
            composite=((ef+(no2_e if no2 else 0)-aef)+(z+(no2_zpe if no2 else 0)-az))*HARTREE_KCAL
            pub=float(published[(col,qty)]["value"])
            native_calc[(col,qty,stem)]={"dft":dft_rel_value,"composite":composite,"published":pub,"deviation":abs(composite-pub),"no2":no2,"dft_path":dft_rel,"f12_path":f12_rel,"anchor_d":anchor_d_rel,"anchor_f":anchor_f_rel}
        except (CandidateFault,OSError,ValueError,KeyError,TypeError):safe=False
    def numerical_table_check(rows_in: list[dict], is_main: bool) -> bool:
        ok=True
        exp_keys={(r["species_column"],r["quantity"],r["file_stem"]) for r in ref}
        got_keys={(r.get("species_column",""),r.get("quantity",""),r.get("file_stem","")) for r in rows_in}
        if is_main:
            ok &= len(rows_in)==20 and len(got_keys)==20 and got_keys<=exp_keys
        else:
            ok &= len(rows_in)==len(got_keys)==len(exp_keys) and got_keys==exp_keys
        if is_main:
            cells={(r.get("species_column",""),r.get("quantity","")) for r in rows_in}
            ok &= len(rows_in)==20 and cells==expected_cells
        for r in rows_in:
            key=(r.get("species_column",""),r.get("quantity",""),r.get("file_stem",""));calc=native_calc.get(key)
            if calc is None:ok=False;continue
            expected_paths={"species_file":"assets/"+calc["dft_path"],"anchor_file":"assets/"+calc["anchor_d"],"source_dft_file":calc["dft_path"],"source_f12_file":calc["f12_path"],"anchor_dft_file":calc["anchor_d"],"anchor_f12_file":calc["anchor_f"]}
            for field,value in expected_paths.items():
                try:ok &= normalized_path(r[field])==normalized_path(value)
                except (KeyError,TypeError):ok=False
            try:
                ok &= near(num(r,"dft_zero_point_kcal_per_mol"),calc["dft"],0.002)
                ok &= near(num(r,"composite_kcal_per_mol"),calc["composite"],0.002)
                ok &= near(num(r,"published_kcal_per_mol"),calc["published"],0.001)
                ok &= near(num(r,"deviation"),calc["deviation"],0.002)
                ok &= r.get("includes_no2","").lower() in {"true","yes","1"} if calc["no2"] else r.get("includes_no2","").lower() in {"false","no","0"}
            except (CandidateFault,KeyError,TypeError):ok=False
        return bool(ok)
    all_native_rows_ok=safe and candidate_schema and numerical_table_check(all_candidates,False)
    main_native_ok=safe and main_schema and numerical_table_check(candidate,True)
    valid_cells=[]
    for key in expected_cells:
        possible=[native_calc.get((key[0],key[1],r["file_stem"])) for r in ref if (r["species_column"],r["quantity"])==key]
        possible=[x for x in possible if x]
        if possible: valid_cells.append((key,min(x["deviation"] for x in possible)))
    comparable=[(k,d) for k,d in valid_cells if k!=("toluene-meta","x-B-RO + NO2")]
    energy_rows_ok=len(comparable)==19 and all(d<=0.10+1e-9 for _,d in comparable)
    selected_keys={(r.get("species_column",""),r.get("quantity","")):r for r in candidate}
    selected_devs=[]
    for key in expected_cells:
        r=selected_keys.get(key,{})
        try:
            actual=float(r["deviation"]); selected_devs.append((key,actual))
            if key!=("toluene-meta","x-B-RO + NO2"):energy_rows_ok &= actual<=0.10+1e-9
        except (KeyError,TypeError,ValueError):energy_rows_ok=False
    energy_rows_ok &= len(selected_devs)==20
    no2_rows=[r for r in all_candidates if "+ NO2" in r.get("quantity","")]
    no2_main=[r for r in candidate if "+ NO2" in r.get("quantity","")]
    no2_ok=len(no2_rows)==13 and len(no2_main)==10 and all(native_calc.get((r.get("species_column"),r.get("quantity"),r.get("file_stem")),{}).get("no2") and r.get("includes_no2","").lower() in {"true","yes","1"} for r in no2_rows)
    ipso=native_calc.get(("toluene-ipso","x-B-RO + NO2","B-RO"),{})
    no2_ok &= near(ipso.get("composite",float("nan")),40.484,0.01) and near(ipso.get("published",float("nan")),40.5,0.1)
    identity_meta=native_calc.get(("toluene-meta","x-B-RO + NO2","B-RO"),{})
    ident_report=any(r.get("species_column")=="toluene-meta" and r.get("quantity")=="x-B-RO + NO2" and r.get("file_stem")=="B-RO" for r in candidate)
    try:identity_sub=json_obj(final/"identity_conflict.json")
    except CandidateFault:identity_sub={}
    identity_items=identity_sub.get("advertised_species",[]) if isinstance(identity_sub,dict) else []
    identity_map={x.get("label"):x for x in identity_items if isinstance(x,dict)}
    identity_submission_ok=len(identity_items)==2 and set(identity_map)=={"B-RO","RB-C1-RO"} and identity_sub.get("includes_no2") is True and identity_sub.get("status")=="unrecoverable_input_identity_collision"
    for label,stem in (("B-RO","B-RO"),("RB-C1-RO","RB-C1-RO")):
        evidence=identity_map.get(label,{})
        for typ,suffix in (("dft","DFT.log"),("f12","F12.out")):
            rel=f"RONO2/Toluene/Meta/{stem}-{suffix}"
            try:
                native=native_path("assets/"+rel)
                identity_submission_ok &= normalized_path(evidence[f"{typ}_file"])==rel and evidence[f"{typ}_sha256"]==sha(native)
                if typ=="f12":
                    raw=native.read_text(encoding="utf-8",errors="replace")
                    matches=re.findall(r"geometry=\{\s*\n\s*\d+\s*\n\s*(\S+?\.log),Energy:",raw)
                    identity_submission_ok &= bool(matches) and evidence.get("f12_source_log_name")==matches[-1]
                    identity_submission_ok &= near(float(evidence["f12_energy_au"]),f12_value(native),1e-8)
            except (CandidateFault,KeyError,TypeError,ValueError,OSError):identity_submission_ok=False
    identity_submission_ok &= identity_map.get("B-RO",{}).get("dft_sha256")==identity_map.get("RB-C1-RO",{}).get("dft_sha256") and identity_map.get("B-RO",{}).get("f12_sha256")==identity_map.get("RB-C1-RO",{}).get("f12_sha256")
    identity_submission_ok &= near(float(identity_sub.get("computed_with_free_no2_kcal_per_mol","nan")),identity_meta.get("composite",float("nan")),0.002) and near(float(identity_sub.get("published_kcal_per_mol","nan")),38.4,0.001) and near(float(identity_sub.get("abs_deviation_kcal_per_mol","nan")),identity_meta.get("deviation",float("nan")),0.002)
    try:disc=text(final/"discrepancies.md")
    except CandidateFault:disc=""
    conflict_prose=all(x in disc.lower() for x in ("b-ro","rb-c1-ro","no2")) and any(x in disc.lower() for x in ("unrecoverable","unresolved","cannot be repaired","无法恢复","不可恢复","冲突"))
    conflict_ok=identity_ok and identity_submission_ok and ident_report and conflict_prose and near(identity_meta.get("composite",float("nan")),-6.6167,0.002) and near(identity_meta.get("published",float("nan")),38.4,0.001) and near(identity_meta.get("deviation",float("nan")),45.0167,0.002)
    try:unverified=json_obj(final/"unverified_rows.json")
    except CandidateFault:unverified={}
    unrows=unverified.get("rows",[]) if isinstance(unverified,dict) else []
    unverified_energy={(r.get("species_column"),r.get("quantity")) for r in unrows if r.get("status")=="unverified_input_identity_conflict"}
    rate_entries=[r for r in unrows if str(r.get("quantity","" )).startswith("kx-")]
    rate_keys={(r.get("species_column"),r.get("quantity")) for r in rate_entries}
    rate_ref={(r["species_column"],r["quantity"]) for r in si if str(r.get("quantity","")).startswith("kx-")}
    rate_values_ok=len(rate_entries)==10 and rate_keys==rate_ref
    rate_ref_values={(r["species_column"],r["quantity"]):float(r["value"]) for r in si if str(r.get("quantity","")).startswith("kx-")}
    for r in rate_entries:
        key=(r.get("species_column"),r.get("quantity"))
        try:rate_values_ok &= near(float(r["published_rate_per_s"]),rate_ref_values[key],max(1e-300,abs(rate_ref_values[key])*0.002))
        except (KeyError,TypeError,ValueError):rate_values_ok=False
    unsupported_ok=rate_values_ok and all(r.get("status")=="unsupported_no_native_witness" and "no corresponding native MESMER" in r.get("reason","") for r in rate_entries)
    unsupported_ok &= unverified_energy=={("toluene-meta","x-B-RO + NO2")} and any("identical" in r.get("reason","").lower() for r in unrows if r.get("status")=="unverified_input_identity_conflict")
    try:assignment=json_obj(final/"column_assignment.json")
    except CandidateFault:assignment={}
    life=assignment.get("lifetime_evidence",[]) if isinstance(assignment,dict) else []
    life_map={r.get("species_column"):r for r in life if isinstance(r,dict)}
    assignment_ok=len(assignment.get("columns",[]))==5 and {r.get("species_column"):r.get("assigned_column") for r in assignment.get("columns",[]) if isinstance(r,dict)}=={c:c for c in dirs}
    for col,rate,minutes in (("benzene",4.9e-4,34.0),("toluene-meta",6e-4,27.8),("toluene-para",1e-4,166.7)):
        r=life_map.get(col,{})
        try:
            assignment_ok &= near(float(r["published_rate_per_s"]),rate,rate*0.001) and near(float(r["lifetime_minutes"]),minutes,0.25) and near(1/(float(r["published_rate_per_s"])*60),float(r["lifetime_minutes"]),0.25) and r.get("assigned_column")==col
        except (KeyError,TypeError,ValueError,ZeroDivisionError):assignment_ok=False
    assignment_ok &= len(life)==3 and "not native MESMER witnesses" in assignment.get("rate_witness_scope","")
    rule=assignment.get("comparison_rule",{}) if isinstance(assignment,dict) else {}
    band_ok=isinstance(rule,dict) and near(float(rule.get("comparison_tolerance_kcal_per_mol","nan")),0.10,1e-9) and near(float(rule.get("context_tolerance_kcal_per_mol","nan")),0.5,1e-9) and "background" in str(rule.get("context_role","")).lower() and energy_rows_ok
    channel_records=assignment.get("channel_selection",[]) if isinstance(assignment,dict) else []
    channel_map={x.get("species_column"):x for x in channel_records if isinstance(x,dict)}
    channel_selection_ok=len(channel_records)==5 and set(channel_map)==set(dirs)
    for col in dirs:
        group=[r for r in all_candidates if r.get("species_column")==col and r.get("quantity")=="TSrearrangement"]
        record=channel_map.get(col,{})
        submitted={x.get("file_stem"):x for x in record.get("candidates",[]) if isinstance(x,dict)}
        expected_stems={r["file_stem"] for r in ref if r["species_column"]==col and r["quantity"]=="TSrearrangement"}
        channel_selection_ok &= set(submitted)==expected_stems=={r.get("file_stem") for r in group}
        mainrow=mainmap.get((col,"TSrearrangement"),{})
        channel_selection_ok &= record.get("selected_file_stem")==mainrow.get("file_stem")
        within=[]
        for row in group:
            stem=row.get("file_stem");calc=native_calc.get((col,"TSrearrangement",stem),{});cr=submitted.get(stem,{})
            try:
                channel_selection_ok &= near(float(cr["composite_kcal_per_mol"]),calc["composite"],0.002) and near(float(cr["published_kcal_per_mol"]),calc["published"],0.001) and near(float(cr["abs_deviation"]),calc["deviation"],0.002)
                if calc["deviation"]<=0.10:within.append(stem)
            except (KeyError,TypeError,ValueError):channel_selection_ok=False
        channel_selection_ok &= record.get("ambiguous") is (len(within)>1)
    ts=[native_calc.get(("toluene-ortho","TSrearrangement",stem),{}) for stem in ("TS-C1","TS-C2")]
    ambiguity_ok=len(ts)==2 and near(ts[0].get("composite",float("nan")),25.563,0.002) and near(ts[1].get("composite",float("nan")),25.408,0.002) and all(x.get("deviation",99)<=0.10 for x in ts) and near(abs(ts[0]["deviation"]-ts[1]["deviation"]),0.029,0.003) and abs(ts[0]["composite"]-ts[1]["composite"])>0.10
    ambiguity_ok &= channel_selection_ok and all(w in disc for w in ("25.563","25.408")) and ("difference between their deviations" in disc or "偏差" in disc)
    ambiguity_ok &= all(any(r.get("species_column")=="toluene-ortho" and r.get("quantity")=="TSrearrangement" and r.get("file_stem")==stem for r in all_candidates) for stem in ("TS-C1","TS-C2"))
    band_ok &= energy_rows_ok
    return [
        criterion("energy_face_complete", len(candidate)==20 and len(mainmap)==20 and len(all_candidates)==30 and len(candmap)==30 and main_native_ok and all_native_rows_ok and assignment_ok and unsupported_ok, "20 unique energy cells and all 30 native candidates are parsed; assignment and unsupported rows are structured", "L1"),
        criterion("no2_fragment_accounting_correct", no2_ok and all_native_rows_ok, "13 NO2-containing candidates across 10 cells include native free-NO2 F12 and ZPE contributions", "L2"),
        criterion("published_energy_rows_reproduced", energy_rows_ok and main_native_ok and band_ok, "19 of 20 comparable cells reproduce within 0.10 kcal/mol, using native recomputation and the SI DOCX values", "L3"),
        criterion("meta_alkoxy_source_identity_conflict_reported", conflict_ok and unsupported_ok, "paired deposited DFT/F12 inputs are byte-identical and the computed discrepancy is disclosed", "L3"),
        criterion("column_assignment_decoded", assignment_ok, "SI lifetime evidence maps benzene, meta and para columns; SI rates are not treated as native witnesses", "L3"),
        criterion("channel_selection_among_two_saddles", ambiguity_ok and channel_selection_ok, "both ortho TS candidates and their distinct energies/deviations are reported; no unique channel is asserted", "L3"),
        criterion("unsupported_rate_rows_declared", unsupported_ok, "both SI rate rows across all five species columns are explicitly unverified", "L3"),
    ]


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--app-dir", type=Path, required=True)
    p.add_argument("--tests-dir", type=Path, required=True)
    p.add_argument("--final-dir", type=Path, required=True)
    p.add_argument("--report", type=Path, required=True)
    args = p.parse_args()
    report: dict = {"status": "ENV_INVALID", "reward": None, "checks": [], "failures": []}
    try:
        refs = json.loads((args.tests_dir / "refs.json").read_text(encoding="utf-8"))
        case_id = refs["case_id"]
        if case_id != PINNED_CASE_ID or refs.get("asset_hashes") != PINNED_ASSET_REFS:
            raise EnvironmentFault("grader refs.json does not match connector-pinned source refs")
        for rel, expected in PINNED_ASSET_REFS.items():
            path = args.app_dir / rel
            if not regular_file(path, args.app_dir/"assets") or sha(path) != expected:
                raise EnvironmentFault(f"public input missing or changed: {rel}")
        for table in PINNED_REFERENCES:
            read_ref(args.tests_dir, table)
    except EnvironmentFault as e:
        report["reason"] = str(e)
        report["status"] = "ENV_INVALID"
        report["reward"] = None
    except (OSError, UnicodeError, json.JSONDecodeError, KeyError, TypeError, ValueError) as e:
        report["reason"] = f"invalid grader refs/preflight: {type(e).__name__}: {e}"
        report["status"] = "ENV_INVALID"
        report["reward"] = None
    else:
      try:
        if case_id.startswith("case-01-"): checks = case01(args.app_dir, args.final_dir, args.tests_dir)
        elif case_id.startswith("case-02-"): checks = case02(args.app_dir, args.final_dir, args.tests_dir)
        elif case_id.startswith("case-03-"): checks = case03(args.app_dir, args.final_dir, args.tests_dir)
        elif case_id.startswith("case-05-"): checks = case05(args.app_dir, args.final_dir, args.tests_dir)
        elif case_id.startswith("case-06-"): checks = case06(args.app_dir, args.final_dir, args.tests_dir)
        else: raise EnvironmentFault(f"unsupported case id {case_id}")
        report.update(case_id=case_id, checks=checks,
                      failures=[c["name"] for c in checks if not c["passed"]])
        report.update(status="PASS" if not report["failures"] else "FAIL",
                      reward=1 if not report["failures"] else 0)
      except EnvironmentFault as e:
        report["reason"] = str(e)
        report["status"] = "ENV_INVALID"
        report["reward"] = None
      except CandidateFault as e:
        report["reason"] = str(e)
        report["status"] = "FAIL"
        report["reward"] = 0
        report["failures"].append("candidate_output_invalid")
      except (KeyError, TypeError, ValueError, AttributeError, ArithmeticError, OSError, UnicodeError, csv.Error) as e:
        # Output parsing errors are candidate failures. Reference/input faults are preflighted above.
        report["reason"] = f"{type(e).__name__}: {e}"
        report["status"] = "FAIL"
        report["reward"] = 0
        report["failures"].append("candidate_output_invalid")
    if report["status"] == "FAIL" and not report["checks"]:
        report["checks"] = [criterion(name,False,"Candidate output invalid: "+report.get("reason",""),level) for name,level in EXPECTED_CRITERIA]
        report["failures"] = [name for name,_ in EXPECTED_CRITERIA] + report["failures"]
    report["verifier_sha256"] = sha(Path(__file__))
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return {"PASS": 0, "FAIL": 1}.get(report["status"], 2)


if __name__ == "__main__":
    raise SystemExit(main())
