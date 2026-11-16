#!/usr/bin/env python3
# L1 Deliverables: Check required deliverables for completeness and parseability (including native-labels.json).
# L2 Execution: Check native records, run evidence and their linkage where required by this task.
# L3 Science: Run three fresh periodic-water CP2K labels.
"""Check fresh Case02 CP2K artifacts; any score covers artifact consistency, not authenticated science."""
import argparse
import hashlib
import json
import math
import re
from pathlib import Path

HA_EV = 27.211386245988
HA_BOHR_EV_A = 51.422067476325886
ORDINALS = (0, 10, 19)
FLOAT = r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[Ee][-+]?\d+)?"
class CandidateError(ValueError):
    pass


class TrustedError(RuntimeError):
    pass


_ADMISSION_SOURCE = '"""Consumer for the runner-owned Bench28 grader-admission context."""\nfrom __future__ import annotations\nimport hashlib\nimport json\nimport os\nimport re\nfrom pathlib import Path\n\nclass HostAdmissionError(RuntimeError):\n    pass\n\n_SCHEMA = "bench28.runner-admission/v1"\n_PATH = "/trusted/bench28-context.json"\n_HEX = re.compile(r"[0-9a-f]{64}\\Z")\n_CASES = {\n    "case-02-water-periodic-seed-labels": "water-periodic-seed-labels",\n    "case-03-water-committee-training": "water-committee-training",\n    "case-07-water-holygrail-tesla": "water-holygrail-tesla",\n}\n_ENV = ("CCB_BENCH28_ADMISSION_ENABLED", "CCB_BENCH28_CONTEXT_PATH",\n        "CCB_BENCH28_CONTEXT_SHA256", "CCB_BENCH28_CASE_KEY",\n        "CCB_BENCH28_CASE_ID", "CCB_BENCH28_RUN_ID", "CCB_BENCH28_IMAGE_ID")\n\ndef read_host_admission(expected_case_key: str, expected_case_id: str):\n    """Return an admission diagnostic, None for legacy/manual grading.\n\n    A context never attests remote work and cannot change the task reward.\n    """\n    present = [name in os.environ for name in _ENV]\n    if not any(present):\n        return None\n    if not all(present) or os.environ.get("CCB_BENCH28_ADMISSION_ENABLED") != "1":\n        raise HostAdmissionError("Bench28 runner admission environment is incomplete")\n    env = os.environ\n    if (expected_case_key not in _CASES or _CASES[expected_case_key] != expected_case_id\n            or env["CCB_BENCH28_CASE_KEY"] != expected_case_key\n            or env["CCB_BENCH28_CASE_ID"] != expected_case_id\n            or env["CCB_BENCH28_CONTEXT_PATH"] != _PATH\n            or not re.fullmatch(r"[A-Za-z0-9_.-]{1,128}", env["CCB_BENCH28_RUN_ID"])\n            or not re.fullmatch(r"sha256:[0-9a-f]{64}", env["CCB_BENCH28_IMAGE_ID"])\n            or not _HEX.fullmatch(env["CCB_BENCH28_CONTEXT_SHA256"])):\n        raise HostAdmissionError("Bench28 runner admission environment does not match the case")\n    path = Path(_PATH)\n    if path.is_symlink() or not path.is_file():\n        raise HostAdmissionError("Bench28 trusted runner context is missing or unsafe")\n    raw = path.read_bytes()\n    if hashlib.sha256(raw).hexdigest() != env["CCB_BENCH28_CONTEXT_SHA256"]:\n        raise HostAdmissionError("Bench28 trusted runner context digest mismatch")\n    try:\n        doc = json.loads(raw)\n    except (UnicodeDecodeError, json.JSONDecodeError) as exc:\n        raise HostAdmissionError("Bench28 trusted runner context is malformed") from exc\n    if (not isinstance(doc, dict) or doc.get("schema") != _SCHEMA\n            or doc.get("scope") != "RUNNER_GRADER_ADMISSION_ONLY"\n            or doc.get("case_key") != expected_case_key\n            or doc.get("case_id") != expected_case_id\n            or doc.get("run_id") != env["CCB_BENCH28_RUN_ID"]\n            or doc.get("image_id") != env["CCB_BENCH28_IMAGE_ID"]\n            or not isinstance(doc.get("attempt_nonce"), str)\n            or not re.fullmatch(r"[0-9a-f]{32}", doc["attempt_nonce"])\n            or not isinstance(doc.get("task_sha256"), str) or not _HEX.fullmatch(doc["task_sha256"])\n            or not isinstance(doc.get("instruction_sha256"), str) or not _HEX.fullmatch(doc["instruction_sha256"])\n            or type(doc.get("execution_completed")) is not bool or doc["execution_completed"] is not False\n            or type(doc.get("formal_reward_available")) is not bool or doc["formal_reward_available"] is not False\n            or doc.get("remote_execution_status") != "NOT_CAPTURED"\n            or not isinstance(doc.get("public_input_pins"), list)):\n        raise HostAdmissionError("Bench28 trusted runner context identity/status is invalid")\n    seen = set()\n    for row in doc["public_input_pins"]:\n        rel = row.get("path") if isinstance(row, dict) else None\n        from pathlib import PurePosixPath\n        if (not isinstance(rel, str) or "\\\\" in rel or "\\x00" in rel\n                or PurePosixPath(rel).is_absolute() or PurePosixPath(rel).as_posix() != rel\n                or not rel.startswith("environment/assets/")\n                or any(part in {"", ".", ".."} for part in rel.split("/"))\n                or rel in seen or not isinstance(row.get("sha256"), str)\n                or not _HEX.fullmatch(row["sha256"]) or type(row.get("bytes")) is not int\n                or row["bytes"] < 0):\n            raise HostAdmissionError("Bench28 trusted public-input pins are malformed")\n        seen.add(row["path"])\n    return {"schema": _SCHEMA, "status": "ADMISSION_ONLY",\n            "remote_execution_status": "NOT_CAPTURED",\n            "execution_completed": False, "formal_reward_available": False,\n            "attempt_nonce": doc["attempt_nonce"], "image_id": doc["image_id"],\n            "public_input_count": len(doc["public_input_pins"])}\n'

def _admission_helper():
    import types
    module=types.ModuleType("_trusted_bench28_admission")
    module.__file__="<embedded:bench28_admission>"
    exec(compile(_ADMISSION_SOURCE,module.__file__,"exec"),module.__dict__)
    return module


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def parse_geometry(path):
    text = path.read_text(encoding="utf-8")
    cm = re.search(r"&COORD\s*(.*?)&END\s*", text, re.S | re.I)
    bm = re.search(r"&CELL\s*(.*?)&END", text, re.S | re.I)
    if not cm or not bm:
        raise TrustedError("trusted geometry lacks CP2K COORD/CELL")
    atoms = []
    for line in cm.group(1).splitlines():
        f = line.split()
        if f:
            if len(f) != 4 or f[0] not in {"O", "H"}:
                raise TrustedError("malformed trusted coordinate include")
            atoms.append((f[0], tuple(float(x) for x in f[1:])))
    cell = []
    for axis in "ABC":
        m = re.search(rf"^\s*{axis}\s+({FLOAT})\s+({FLOAT})\s+({FLOAT})\s*$", bm.group(1), re.M)
        if not m:
            raise TrustedError("malformed trusted cell include")
        cell.append(tuple(float(x) for x in m.groups()))
    if len(atoms) != 192 or sum(a[0] == "O" for a in atoms) != 64 or sum(a[0] == "H" for a in atoms) != 128:
        raise TrustedError("trusted geometry is not O64H128")
    return atoms, cell


EXPECTED_REFS_SHA256 = "f054f6485624c0c2a58fb96ba434ea3b10ff340f76f651ad62c19977183fba9d"


def load_refs(tests):
    path = tests / "refs.json"
    try:
        raw = path.read_bytes()
        if hashlib.sha256(raw).hexdigest() != EXPECTED_REFS_SHA256:
            raise TrustedError("grading reference integrity check failed")
        refs = json.loads(raw.decode("utf-8"))
    except TrustedError:
        raise
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise TrustedError(f"grading references are unavailable: {exc}") from exc
    if not isinstance(refs, dict) or refs.get("schema") != "bench28-task180-grading/v1":
        raise TrustedError("grading references have an unexpected schema")
    return refs

def parse_cp2k(path, atoms, cell, refs=None):
    refs = refs or load_refs(Path(__file__).resolve().parent)
    tolerances = refs["tolerances"]
    text = path.read_text(errors="replace")
    if not re.search(r"SCF run converged", text, re.I) or re.search(r"SCF run NOT converged|forrtl.? error", text, re.I):
        raise CandidateError("candidate output lacks positive SCF convergence")
    if text.count("PROGRAM ENDED AT") != 1:
        raise CandidateError("candidate output lacks a unique CP2K normal-end marker")
    method_echoes = (
        r"FUNCTIONAL\|\s+BECKE88:",
        r"FUNCTIONAL\|\s+LYP:",
        r"vdW POTENTIAL\|\s+DFT-D3",
        r"Orbital Basis Set\s+TZV2P-GTH",
    )
    if any(not re.search(pattern, text, re.I) for pattern in method_echoes):
        raise CandidateError("candidate output method echo differs from the requested BLYP-D3/TZV2P setup")
    energy = re.findall(rf"ENERGY\|\s+Total FORCE_EVAL \( QS \) energy \[a\.u\.\]:\s*({FLOAT})", text)
    forces_marker = text.split("ATOMIC FORCES in [a.u.]")
    if len(energy) != 1 or len(forces_marker) != 2:
        raise CandidateError("candidate output must contain one energy and one force block")
    force_block = forces_marker[1].split("SUM OF ATOMIC FORCES", 1)[0]
    fr = re.findall(rf"^\s*(\d+)\s+\d+\s+([A-Za-z]+)\s+({FLOAT})\s+({FLOAT})\s+({FLOAT})\s*$", force_block, re.M)
    if [int(x[0]) for x in fr] != list(range(1, 193)) or [x[1] for x in fr] != [x[0] for x in atoms]:
        raise CandidateError("candidate forces do not preserve the 192 submitted atom rows")
    coord_parts = text.split("MODULE QUICKSTEP: ATOMIC COORDINATES IN ANGSTROM")
    if len(coord_parts) != 2:
        raise CandidateError("candidate output lacks unique coordinate echo")
    cr = re.findall(rf"^\s*(\d+)\s+\d+\s+([A-Za-z]+)\s+\d+\s+({FLOAT})\s+({FLOAT})\s+({FLOAT})\s+", coord_parts[1], re.M)
    if [int(x[0]) for x in cr] != list(range(1, 193)) or [x[1] for x in cr] != [x[0] for x in atoms]:
        raise CandidateError("candidate coordinate echo changes atom order")
    for got, source in zip(cr, atoms):
        if any(abs(float(got[i + 2]) - source[1][i]) > tolerances["coordinate_echo_angstrom"] for i in range(3)):
            raise CandidateError("candidate CP2K run did not use the pinned geometry")
    crows = re.findall(rf"CELL\| Vector ([abc]) \[angstrom\]:\s*({FLOAT})\s+({FLOAT})\s+({FLOAT})", text)
    if [x[0] for x in crows] != ["a", "b", "c"]:
        raise CandidateError("candidate output lacks the periodic cell echo")
    out_cell = [[float(v) for v in x[1:]] for x in crows]
    if any(abs(out_cell[i][j] - cell[i][j]) > tolerances["cell_echo_angstrom"] for i in range(3) for j in range(3)):
        raise CandidateError("candidate output cell differs from the submitted geometry")
    e_ha = float(energy[0])
    f_ha = [[float(v) for v in x[2:5]] for x in fr]
    e_ev = e_ha * HA_EV
    f_ev = [[v * HA_BOHR_EV_A for v in row] for row in f_ha]
    if not math.isfinite(e_ev) or any(not math.isfinite(x) for row in f_ev for x in row):
        raise CandidateError("candidate CP2K labels contain nonfinite values")
    return e_ha, e_ev, f_ha, f_ev


def parse_native_text_profile(text):
    """Read fields the native log actually reports; this is not host attestation."""
    patterns = {
        "version": r"^\s*CP2K\| version string:\s*(.*?)\s*$",
        "source_revision": r"^\s*CP2K\| source code revision number:\s*(.*?)\s*$",
        "build_target": r"^\s*CP2K\| Program compiled for\s+(.*?)\s*$",
        "data_directory": r"^\s*CP2K\| Data directory path\s+(.*?)\s*$",
        "mpi_processes": r"^\s*GLOBAL\| Total number of message passing processes\s+(\d+)\s*$",
        "omp_threads": r"^\s*DBCSR\| OMP: Max number of threads\s+(\d+)\s*$",
        "cpu_model": r"^\s*GLOBAL\| CPU model name\s+(.*?)\s*$",
        "compiled_at": r"^\s*CP2K\| Program compiled at\s+(.*?)\s*$",
        "compiled_on": r"^\s*CP2K\| Program compiled on\s+(.*?)\s*$",
    }
    profile = {}
    for key, pattern in patterns.items():
        match = re.search(pattern, text, re.M)
        if not match:
            return None
        profile[key] = match.group(1).strip()
    return profile


def numeric_band(energy_delta, force_rms, force_max, refs=None):
    refs = refs or load_refs(Path(__file__).resolve().parent)
    """Apply proposed v2 local bands to finite native-vs-reference diagnostics."""
    values = (energy_delta, force_rms, force_max)
    if not all(is_finite_number(value) for value in values):
        raise CandidateError("nonfinite same-geometry numeric comparison")
    if force_rms < 0 or force_max < 0:
        raise CandidateError("negative force-difference metric")
    metrics = {"energy_eV": abs(energy_delta),
               "force_rms_eV_per_angstrom": force_rms,
               "force_max_eV_per_angstrom": force_max}
    if all(metrics[key] <= limit for key, limit in refs["numeric_bands"]["pass"].items()):
        return "PASS"
    if all(metrics[key] <= limit for key, limit in refs["numeric_bands"]["gray"].items()):
        return "GRAY"
    return "FAIL"


def numeric_reference_diagnostic(ordinal, reference_row, energy_delta, force_rms, force_max,
                                candidate_profile, refs):
    reference_profile = reference_row["native_text_profile"]
    profile_match = candidate_profile is not None and candidate_profile == reference_profile
    return {
        "label_job_ordinal": ordinal,
        "reference_output_sha256": reference_row["output_sha256"],
        "energy_delta_eV": energy_delta,
        "force_max_abs_delta_eV_per_angstrom": force_max,
        "force_rms_delta_eV_per_angstrom": force_rms,
        "candidate_reported_native_text_profile": candidate_profile,
        "native_text_profile_match": profile_match,
        "host_profile_qualified": False,
        "profile_unverified_items": ["CP2K binary SHA", "compiler identity", "basis/potential/D3 data-file SHA", "protected process-to-output identity"],
        "interpretation": "candidate-visible runtime profile is diagnostic only; pinned same-method numeric bands apply regardless of profile match",
        "numeric_band": numeric_band(energy_delta, force_rms, force_max, refs),
    }


def artifact_score(bands):
    """Score all three native labels against the frozen numeric bands."""
    if len(bands) != 3 or any(band not in {"PASS", "GRAY"} for band in bands):
        return 0.0
    if all(band == "PASS" for band in bands):
        return 1.0
    if "GRAY" in bands:
        return 0.5
    return 0.0


def numeric_band_outcome(bands):
    score = artifact_score(bands)
    return ("PASS" if score == 1.0 else "PARTIAL"), score


def is_finite_number(value):
    if type(value) not in (int, float):
        return False
    try:
        return math.isfinite(value)
    except (OverflowError, TypeError):
        return False


def close_matrix(got, want, refs=None):
    refs = refs or load_refs(Path(__file__).resolve().parent)
    ulps = refs["tolerances"]["matrix_ulps"]
    return (isinstance(got, list) and len(got) == len(want)
            and all(isinstance(a, list) and len(a) == len(b)
                    and all(is_finite_number(x) and abs(x-y) <= ulps * math.ulp(y)
                            for x, y in zip(a, b))
                    for a, b in zip(got, want)))


def verify(app, tests):
    refs = load_refs(tests)
    case = tests.parent
    asset_root = case / "environment/assets/v2/native-labels/label"
    manifest = json.loads((case / "environment/assets/v2/native-labels/provenance.json").read_text())
    if manifest.get("schema") != "bench28-case02-v2-visible-inputs/v1":
        raise TrustedError("visible geometry/method manifest has an unexpected schema")
    entries = {row["path"]: row for row in manifest.get("items", [])}
    final = app / "final/native-labels.json"
    if final.is_symlink() or not final.is_file():
        raise CandidateError("final/native-labels.json missing or unsafe")
    try:
        candidate = json.loads(final.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise CandidateError(f"invalid candidate JSON: {exc}") from exc
    if not isinstance(candidate, dict) or candidate.get("schema") != "task180-native-labels/v2":
        raise CandidateError("wrong native-label result schema")
    rows = candidate.get("records")
    if not isinstance(rows, list) or len(rows) != 3:
        raise CandidateError("exactly three freshly labeled configurations are required")
    reference_diagnostics = []
    for ordinal, row in zip(ORDINALS, rows):
        if (not isinstance(row, dict) or type(row.get("label_job_ordinal")) is not int
                or row.get("label_job_ordinal") != ordinal):
            raise CandidateError("label-job ordinal mismatch")
        run = app / "runs/cp2k-label-v2" / f"label-{ordinal:04d}"
        if run.is_symlink() or not run.is_dir():
            raise CandidateError(f"missing fresh run directory for job {ordinal}")
        inp, inc, out, status_path = run / "cp2k.inp", run / "coord_n_cell.inc", run / "output", run / "exit-status.json"
        if any(p.is_symlink() or not p.is_file() for p in (inp, inc, out, status_path)):
            raise CandidateError(f"incomplete CP2K output bundle for job {ordinal}")
        try:
            exit_status = json.loads(status_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise CandidateError(f"invalid candidate process exit record for job {ordinal}: {exc}") from exc
        if (not isinstance(exit_status, dict) or type(exit_status.get("exit_code")) is not int
                or exit_status.get("exit_code") != 0):
            raise CandidateError(f"candidate process exit code is not zero for job {ordinal}")
        geometry = asset_root / f"cp2k-inc-{ordinal:04d}/coord_n_cell.inc"
        pin = entries.get(str(geometry.relative_to(case)))
        if not pin or not geometry.is_file() or sha(geometry) != pin["sha256"]:
            raise TrustedError(f"trusted starting geometry pin mismatch for {ordinal}")
        if sha(inc) != sha(geometry):
            raise CandidateError("candidate changed the pinned input geometry")
        inp_text = inp.read_text(encoding="utf-8")
        pinned_template = asset_root / f"cp2k-inc-{ordinal:04d}/cp2k.inp"
        pin = entries.get(str(pinned_template.relative_to(case)))
        if not pin or not pinned_template.is_file() or sha(pinned_template) != pin["sha256"]:
            raise TrustedError(f"trusted CP2K method-template pin mismatch for {ordinal}")
        expected_input = pinned_template.read_text(encoding="utf-8").replace(
            "@PROJECT_NAME@", f"task180_label_{ordinal:04d}")
        if inp_text != expected_input:
            raise CandidateError("rendered CP2K input differs from the pinned method template")
        atoms, cell = parse_geometry(inc)
        e_ha, e_ev, f_ha, f_ev = parse_cp2k(out, atoms, cell, refs)
        # Exact trusted values and the replay digest were extracted with the
        # original parser; raw native references remain outside the task tree.
        reference_row = refs["native_references"][f"{ordinal:04d}"]
        if sha(out) == reference_row["output_sha256"]:
            raise CandidateError("candidate output is byte-identical to the archived reference output")
        candidate_profile = parse_native_text_profile(out.read_text(errors="replace"))
        reference_profile = reference_row["native_text_profile"]
        ref_forces_ev = reference_row["forces_eV_per_A"]
        force_deltas = [abs(got-ref) for actual, expected in zip(f_ev, ref_forces_ev)
                        for got, ref in zip(actual, expected)]
        energy_delta = e_ev - reference_row["energy_eV"]
        force_max = max(force_deltas)
        force_rms = math.sqrt(sum(x*x for x in force_deltas)/len(force_deltas))
        diagnostic = numeric_reference_diagnostic(
            ordinal, reference_row, energy_delta, force_rms, force_max, candidate_profile, refs
        )
        reference_diagnostics.append(diagnostic)
        if diagnostic["numeric_band"] == "FAIL":
            raise CandidateError(
                f"same-geometry numeric band FAIL for label {ordinal}: "
                f"|delta E|={abs(energy_delta):.8g} eV, force RMS={force_rms:.8g} eV/angstrom, "
                f"force max={force_max:.8g} eV/angstrom"
            )
        if row.get("native_output_sha256") != sha(out):
            raise CandidateError("result output hash does not match the submitted native output")
        if row.get("input_sha256") != sha(inp) or row.get("geometry_sha256") != sha(inc):
            raise CandidateError("reported input or geometry hash differs from submitted files")
        row_exit = row.get("exit_status")
        if (not isinstance(row_exit, dict) or type(row_exit.get("exit_code")) is not int
                or row_exit != exit_status or type(row.get("atom_count")) is not int
                or row.get("atom_count") != 192 or not isinstance(row.get("composition"), dict)
                or set(row["composition"]) != {"O", "H"}
                or any(type(row["composition"].get(element)) is not int for element in ("O", "H"))
                or row["composition"] != {"O": 64, "H": 128}):
            raise CandidateError("reported exit status, atom count, or composition differs from submitted files")
        if row.get("scf") != "CONVERGED" or row.get("normal_end") is not True:
            raise CandidateError("result does not declare converged SCF and normal termination")
        if row.get("method") != "BLYP-D3 / TZV2P-GTH / GTH-BLYP / 500 Ry / REL_CUTOFF 60":
            raise CandidateError("reported method differs from the pinned CP2K profile")
        if not close_matrix(row.get("cell_angstrom"), cell, refs):
            raise CandidateError("reported cell differs from submitted geometry")
        unit_conversion = candidate.get("unit_conversion")
        if (not isinstance(unit_conversion, dict)
                or not is_finite_number(unit_conversion.get("hartree_to_ev"))
                or not is_finite_number(unit_conversion.get("hartree_per_bohr_to_ev_per_angstrom"))
                or unit_conversion.get("hartree_to_ev") != HA_EV
                or unit_conversion.get("hartree_per_bohr_to_ev_per_angstrom") != HA_BOHR_EV_A):
            raise CandidateError("reported unit-conversion constants differ from the frozen values")
        if not is_finite_number(row.get("energy_hartree")) or abs(row["energy_hartree"] - e_ha) > refs["tolerances"]["matrix_ulps"]*math.ulp(e_ha):
            raise CandidateError("reported Hartree energy differs from native output")
        if not is_finite_number(row.get("energy_eV")) or abs(row["energy_eV"] - e_ev) > refs["tolerances"]["matrix_ulps"]*math.ulp(e_ev):
            raise CandidateError("reported eV energy conversion differs from native output")
        if not close_matrix(row.get("forces_hartree_per_bohr"), f_ha, refs):
            raise CandidateError("reported native forces differ from the CP2K force block")
        if not close_matrix(row.get("forces_eV_per_angstrom"), f_ev, refs):
            raise CandidateError("reported eV/Angstrom forces differ from native conversion")
    bands = [d["numeric_band"] for d in reference_diagnostics]
    status, score = numeric_band_outcome(bands)
    return {"status":status,"local_check":status,
            "artifact_consistency_status":"PASS","local_numeric_status":status,
            "score_kind":"native_artifact_consistency",
            "overall_science_status":status,"scientific_success":status == "PASS",
            "execution_attested":False,"source_truth_verified":False,"human_review_required":False,
            "reward":score,
            "checked_claims":["fresh candidate paths exist", "three native CP2K outputs positively converge and end normally", "192-atom geometry/cell/atom order", "BLYP-D3/TZV2P method echo and declared Ha/eV conversions"],
            "same_geometry_numeric_bands":{"pass":refs["numeric_bands"]["pass"],"gray":refs["numeric_bands"]["gray"],"meaning":refs["numeric_band_qualification"]},
            "same_geometry_reference_diagnostics": reference_diagnostics,
            "unverified_claims":["protected host/Runner execution provenance", "causal association between reported process and native files", "results beyond these three short single points"],
            "reason":"Automated scoring covers the three native artifacts against frozen same-geometry numeric bands. It does not authenticate host execution provenance."}


def main():
    p=argparse.ArgumentParser();p.add_argument("--app-dir",type=Path,required=True);p.add_argument("--tests-dir",type=Path,required=True);a=p.parse_args()
    try:
        helper=_admission_helper()
        admission=helper.read_host_admission("case-02-water-periodic-seed-labels", "water-periodic-seed-labels")
    except (ImportError, OSError, RuntimeError) as exc:
        result={"status":"ERROR","local_check":"ERROR","overall_science_status":"INCONCLUSIVE","human_review_required":False,"reward":None,"reason":f"trusted Bench28 admission error: {exc}"};code=2
        admission=None
    else:
        try:
            result=verify(a.app_dir.resolve(),a.tests_dir.resolve()); code=0
        except CandidateError as exc:
            result={"status":"REJECTED","local_check":"FAIL","artifact_consistency_status":"FAIL",
                    "score_kind":"native_artifact_consistency","overall_science_status":"INCONCLUSIVE",
                    "scientific_success":False,"execution_attested":False,"source_truth_verified":False,
                    "human_review_required":False,"reward":0.0,"reason":str(exc)};code=1
        except (OSError,TrustedError,RuntimeError) as exc:
            result={"status":"ERROR","local_check":"ERROR","overall_science_status":"INCONCLUSIVE","human_review_required":False,"reward":None,"reason":str(exc)};code=2
        if admission is not None: result["runner_admission"]=admission
    print(json.dumps(result,indent=2,allow_nan=False));return code


if __name__ == "__main__":
    raise SystemExit(main())
