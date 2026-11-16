#!/usr/bin/env python3
# L1 Deliverables: Check required deliverables for completeness and parseability.
# L2 Execution: Check native records, run evidence and their linkage where required by this task.
# L3 Science: Run the existing water committee on fresh MLMD trajectories.
"""Check fresh Case03 LAMMPS artifacts; score covers consistency, not authenticated science."""
import argparse
import hashlib
import json
import math
import re
from pathlib import Path

EXPECTED_REFS_SHA256 = "91aef9b9a96a7f5000f38718d93d71c095b0ed84a565cadd7041ef34b70db7ba"


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
    if not isinstance(refs, dict) or refs.get("schema") != "bench28-task181-grading/v1":
        raise TrustedError("grading references have an unexpected schema")
    return refs

def expected_steps(refs):
    cadence = refs["trajectory"]
    return list(range(cadence["start_step"], cadence["stop_step"] + 1, cadence["step_interval"]))


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


def _validate_runtime_path(value, label):
    if (not isinstance(value, str) or not value.startswith("/")
            or re.fullmatch(r"/[A-Za-z0-9._+:/-]+", value) is None
            or "//" in value or any(part in {".", ".."} for part in value.split("/")[1:])):
        raise CandidateError(f"{label} must be a safe absolute runtime path")
    return value


def check_input(path, template, seed):
    # Resolve only the candidate APP files and pinned evaluator assets. Runtime paths
    # inside lammps.in may belong to another mount and are compared as strings.
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise CandidateError(f"cannot read candidate LAMMPS input: {exc}") from exc
    data_rows = re.findall(r"^variable DATA_FILE string ([^\r\n]+)$", text, re.M)
    plugin_rows = re.findall(r"^plugin load ([^\r\n]+)$", text, re.M)
    model_rows = re.findall(
        r"^pair_style deepmd ([^\s]+) ([^\s]+) ([^\s]+) ([^\s]+) out_freq \$\{SAMPLE_FREQ\} out_file model_devi\.out$",
        text, re.M,
    )
    if len(data_rows) != 1 or len(plugin_rows) != 1 or len(model_rows) != 1:
        raise CandidateError("LAMMPS input must contain one data path, plugin load, and four-member pair_style")
    data_runtime = _validate_runtime_path(data_rows[0], "start.data path")
    plugin_runtime = _validate_runtime_path(plugin_rows[0], "DeepMD plugin path")
    model_runtime = [_validate_runtime_path(x, f"model member {i} path") for i, x in enumerate(model_rows[0])]
    if len(set(model_runtime)) != 4:
        raise CandidateError("each committee member must have a distinct runtime path")
    rendered = template.read_text(encoding="utf-8")
    mapping = {
        "@START_DATA@": data_runtime,
        "@MODEL0@": model_runtime[0],
        "@MODEL1@": model_runtime[1],
        "@MODEL2@": model_runtime[2],
        "@MODEL3@": model_runtime[3],
        "@DEEPMD_PLUGIN@": plugin_runtime,
        "variable SEED equal 101": f"variable SEED equal {seed}",
    }
    for token, value in mapping.items():
        rendered = rendered.replace(token, value)
    if text != rendered:
        raise CandidateError("LAMMPS input differs from the pinned execution template")
    return {"start_data": data_runtime, "models": model_runtime, "plugin": plugin_runtime}


def check_start_data(path, include, refs=None):
    refs = refs or load_refs(Path(__file__).resolve().parent)
    text = path.read_text(encoding="utf-8")
    if f"{refs['trajectory']['atom_count']} atoms" not in text or "2 atom types" not in text or any(f"0.0 {refs['trajectory']['box_length_angstrom']} {axis}lo {axis}hi" not in text for axis in "xyz"):
        raise CandidateError("LAMMPS data file has incorrect atom count or box")
    match = re.search(r"Atoms\s+#\s*atomic\s*\n(.*)", text, re.S)
    if not match:
        raise CandidateError("LAMMPS atomic coordinate section missing")
    rows=[]
    for line in match.group(1).splitlines():
        f=line.split()
        if len(f)==5:
            try: rows.append((int(f[0]),int(f[1]),tuple(float(x) for x in f[2:])))
            except ValueError: raise CandidateError("malformed LAMMPS atom record")
    if len(rows)!=refs["trajectory"]["atom_count"] or [r[0] for r in rows]!=list(range(1,refs["trajectory"]["atom_count"]+1)):
        raise CandidateError("LAMMPS starting atom table is incomplete/reordered")
    inc_text=include.read_text(encoding="utf-8")
    cm=re.search(r"&COORD\s*(.*?)&END\s*",inc_text,re.S|re.I)
    if not cm: raise TrustedError("trusted geometry coordinate section missing")
    atoms=[]
    for line in cm.group(1).splitlines():
        f=line.split()
        if f: atoms.append((f[0],tuple(float(x) for x in f[1:])))
    if len(atoms)!=refs["trajectory"]["atom_count"]: raise TrustedError("trusted geometry atom count mismatch")
    for row,(symbol,xyz) in zip(rows,atoms):
        expected_type=1 if symbol=="O" else 2
        if row[1]!=expected_type or any(abs(x-y)>refs["tolerances"]["start_coordinate_angstrom"] for x,y in zip(row[2],xyz)):
            raise CandidateError("LAMMPS starting coordinates or atom types differ from pinned geometry")


def check_render_manifest(path, geom_id, seed, include, inp, data, models, runtime_paths):
    if path.is_symlink() or not path.is_file():
        raise CandidateError("render manifest missing or unsafe")
    try:
        render = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise CandidateError(f"invalid render manifest: {exc}") from exc
    if not isinstance(render, dict):
        raise CandidateError("render manifest must be a JSON object")
    if (render.get("start_geometry_id") != geom_id or type(render.get("seed")) is not int
            or render.get("seed") != seed):
        raise CandidateError("render manifest geometry or seed differs from the frozen input")
    if (render.get("start_geometry_sha256") != sha(include)
            or render.get("lammps_input_sha256") != sha(inp)
            or render.get("data_sha256") != sha(data)):
        raise CandidateError("render manifest geometry/input/data hashes differ from submitted files")
    expected_model_hashes = [sha(model) for model in models]
    if render.get("model_sha256_by_member") != expected_model_hashes:
        raise CandidateError("render manifest model hashes differ from the pinned committee")
    expected_bindings = {
        "start_data": {"path": runtime_paths["start_data"], "sha256": sha(data)},
        "models": [
            {"member_index": i, "path": runtime_paths["models"][i], "sha256": expected_model_hashes[i]}
            for i in range(4)
        ],
    }
    bindings = render.get("runtime_bindings")
    if (not isinstance(bindings, dict) or set(bindings) != {"start_data", "models"}
            or not isinstance(bindings.get("start_data"), dict)
            or set(bindings["start_data"]) != {"path", "sha256"}
            or not isinstance(bindings["start_data"].get("path"), str)
            or not isinstance(bindings["start_data"].get("sha256"), str)
            or not isinstance(bindings.get("models"), list) or len(bindings["models"]) != len(expected_bindings["models"])):
        raise CandidateError("runtime path/member/hash bindings have invalid schema")
    for item in bindings["models"]:
        if (not isinstance(item, dict) or set(item) != {"member_index", "path", "sha256"}
                or type(item.get("member_index")) is not int
                or not isinstance(item.get("path"), str)
                or not isinstance(item.get("sha256"), str)):
            raise CandidateError("runtime path/member/hash bindings have invalid schema")
    if bindings != expected_bindings:
        raise CandidateError("runtime path/member/hash bindings differ from the rendered input or pinned assets")
    return render


def check_dump(path, refs=None):
    refs = refs or load_refs(Path(__file__).resolve().parent)
    lines = path.read_text(encoding="utf-8").splitlines()
    pos, steps = 0, []
    atom_types_by_id = None
    while pos < len(lines):
        if lines[pos].strip() != "ITEM: TIMESTEP" or pos + 1 >= len(lines):
            raise CandidateError("malformed LAMMPS dump frame")
        step = int(lines[pos + 1]); pos += 2
        if pos + 1 >= len(lines) or lines[pos].strip() != "ITEM: NUMBER OF ATOMS" or int(lines[pos + 1]) != refs["trajectory"]["atom_count"]:
            raise CandidateError("LAMMPS dump frame atom count differs from the pinned water cell")
        pos += 2
        if pos >= len(lines) or not lines[pos].startswith("ITEM: BOX BOUNDS"):
            raise CandidateError("dump cell header missing")
        head = lines[pos].split(); pos += 1
        bounds = []
        for _ in range(3):
            if pos >= len(lines):
                raise CandidateError("truncated dump cell bounds")
            row = [float(x) for x in lines[pos].split()]; pos += 1
            if len(row) not in (2, 3) or not all(math.isfinite(x) for x in row):
                raise CandidateError("malformed dump cell bounds")
            bounds.append(row)
        if any(abs(bounds[i][1] - bounds[i][0] - 12.4) > refs["tolerances"]["box_edge_angstrom"] for i in range(3)):
            raise CandidateError("dump cell differs from the 12.4-A cubic box")
        if any(len(r) == 3 and abs(r[2]) > refs["tolerances"]["box_tilt_angstrom"] for r in bounds):
            raise CandidateError("dump cell unexpectedly tilted")
        if pos >= len(lines) or not lines[pos].startswith("ITEM: ATOMS "):
            raise CandidateError("dump atom columns missing")
        columns = lines[pos].split()[2:]; pos += 1
        required = ("id", "type", "x", "y", "z", "fx", "fy", "fz")
        if any(x not in columns for x in required):
            raise CandidateError("dump lacks IDs, wrapped coordinates, or forces")
        ix = {x: columns.index(x) for x in required}
        ids, counts, frame_types = set(), {1: 0, 2: 0}, {}
        for _ in range(refs["trajectory"]["atom_count"]):
            if pos >= len(lines):
                raise CandidateError("truncated dump atom table")
            row = lines[pos].split(); pos += 1
            if len(row) != len(columns):
                raise CandidateError("dump atom row width mismatch")
            atom_id, typ = int(row[ix["id"]]), int(row[ix["type"]])
            if atom_id in ids or typ not in counts:
                raise CandidateError("dump atom IDs/types invalid")
            ids.add(atom_id); counts[typ] += 1
            frame_types[atom_id] = typ
            nums = [float(row[ix[k]]) for k in ("x", "y", "z", "fx", "fy", "fz")]
            if not all(math.isfinite(x) for x in nums):
                raise CandidateError("nonfinite dump coordinate/force")
        if ids != set(range(1, refs["trajectory"]["atom_count"] + 1)) or counts != {1: refs["trajectory"]["oxygen_count"], 2: refs["trajectory"]["hydrogen_count"]}:
            raise CandidateError("dump composition or atom IDs differ from refs.json")
        if atom_types_by_id is None:
            atom_types_by_id = frame_types
        elif frame_types != atom_types_by_id:
            raise CandidateError("dump atom ID-to-type mapping changes between frames")
        steps.append(step)
    if steps != expected_steps(refs):
        raise CandidateError("dump cadence differs from refs.json")
    return len(steps)


def check_deviation(path, refs=None):
    refs = refs or load_refs(Path(__file__).resolve().parent)
    lines = path.read_text().splitlines()
    if not lines or "max_devi_f" not in lines[0]:
        raise CandidateError("model_devi header missing")
    rows = []
    for line in lines[1:]:
        if not line.strip():
            continue
        fields = line.split()
        if len(fields) != 7:
            raise CandidateError("model_devi row width mismatch")
        step, values = int(fields[0]), [float(x) for x in fields[1:]]
        if not all(math.isfinite(x) and x >= 0 for x in values):
            raise CandidateError("model_devi has nonfinite or negative values")
        rows.append(step)
    if rows != expected_steps(refs):
        raise CandidateError("model_devi cadence does not match trajectory")
    return len(rows)


def check_log(path, refs=None):
    refs = refs or load_refs(Path(__file__).resolve().parent)
    text = path.read_text(errors="replace")
    completion = re.search(rf"Loop time of\s+([0-9.eE+-]+)\s+on\s+\d+\s+procs for {refs['trajectory']['stop_step']} steps with {refs['trajectory']['atom_count']} atoms", text)
    if not completion or not re.search(r"Total wall time:\s*[0-9:]+", text):
        raise CandidateError("LAMMPS log lacks normal 20,000-step completion and wall time")
    lines = text.splitlines(); thermo = []
    for i, line in enumerate(lines):
        cols = line.split()
        if cols[:2] == ["Step", "Temp"] and all(k in cols for k in ("TotEng", "Press")):
            for row in lines[i + 1:]:
                fields = row.split()
                if len(fields) != len(cols):
                    break
                try:
                    step = int(fields[0]); values = [float(x) for x in fields[1:]]
                except ValueError:
                    break
                if not all(math.isfinite(x) for x in values):
                    raise CandidateError("nonfinite thermo value")
                thermo.append(step)
            break
    if thermo != expected_steps(refs):
        raise CandidateError("thermo cadence does not match refs.json")
    return float(completion.group(1))


def verify(app, tests):
    refs = load_refs(tests)
    case = tests.parent
    assets = case / "environment/assets/v2/fresh-run"
    manifest_path = assets / "provenance.json"
    if not manifest_path.is_file() or manifest_path.is_symlink():
        raise TrustedError("trusted fresh-run asset manifest missing")
    if sha(manifest_path) != refs["input_manifest_sha256"]:
        raise TrustedError("trusted fresh-run asset manifest hash mismatch")
    manifest = json.loads(manifest_path.read_text())
    if manifest.get("schema") != "bench28-case03-v2-visible-inputs/v1":
        raise TrustedError("unexpected fresh-run manifest schema")
    for row in manifest.get("visible_files", []) + manifest.get("models", []):
        p = case / row["path"]
        if p.is_symlink() or not p.is_file() or sha(p) != row["sha256"]:
            raise TrustedError(f"pinned baseline model or Task181 input hash mismatch: {row['path']}")
    run_root = app / "runs/task181-mlmd-v2"
    if run_root.is_symlink() or not run_root.is_dir():
        raise CandidateError("fresh MLMD run directory missing or unsafe")
    execution = run_root / "execution-manifest.json"
    if execution.is_symlink() or not execution.is_file():
        raise CandidateError("execution manifest missing")
    try:
        data = json.loads(execution.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise CandidateError(f"invalid execution manifest: {exc}") from exc
    if not isinstance(data, dict):
        raise CandidateError("execution manifest must be a JSON object")
    if data.get("schema") != "task181-app-execution-manifest/v1":
        raise CandidateError("wrong execution-manifest schema")
    replicas = data.get("replicas")
    if (not isinstance(replicas, list) or len(replicas) != 2
            or any(not isinstance(x, dict) for x in replicas)
            or [x.get("replica") for x in replicas] != ["replica-0", "replica-1"]):
        raise CandidateError("exactly two fresh replica records are required")
    for index, geom_id in enumerate(("0000", "0010")):
        run = run_root / f"replica-{index}"
        if run.is_symlink() or not run.is_dir():
            raise CandidateError("replica output path missing or unsafe")
        inp, dat, log, dump, dev = [run / n for n in ("lammps.in", "start.data", "log.lammps", "dump.lammpstrj", "model_devi.out")]
        if any(p.is_symlink() or not p.is_file() for p in (inp, dat, log, dump, dev)):
            raise CandidateError("replica is missing a required native output")
        template = assets / "lammps.template.in"
        model_paths = [assets / "models" / f"member-{i}.pb" for i in range(4)]
        expected_seed = (701, 1701)[index]
        include=assets / "geometries" / geom_id / "coord_n_cell.inc"
        runtime_paths = check_input(inp, template, expected_seed)
        render = check_render_manifest(run / "render-manifest.json", geom_id, expected_seed,
                                       include, inp, dat, model_paths, runtime_paths)
        historical = refs["historical_replay_sha256"][str(index)]
        if sha(dump) == historical["dump.lammpstrj"]:
            raise CandidateError("candidate dump is byte-identical to a historical trajectory")
        frames = check_dump(dump, refs); deviation_rows = check_deviation(dev, refs); elapsed = check_log(log, refs)
        expected_files = replicas[index].get("files")
        actual_files = {p.name: sha(p) for p in sorted(run.iterdir()) if p.is_file() and p.name != "render-manifest.json"}
        if expected_files != actual_files:
            raise CandidateError("execution manifest file hashes do not match submitted outputs")
        check_start_data(dat, include, refs)
        if frames != refs["trajectory"]["expected_frames"] or deviation_rows != frames:
            raise CandidateError("trajectory and model-deviation row counts differ")
        # Ensure this run is not an exact replay of the archived logs as well as trajectory.
        if sha(log) == historical["log.lammps"]:
            raise CandidateError("candidate log is byte-identical to historical output")
        if elapsed <= 0:
            raise CandidateError("LAMMPS reported nonpositive loop time")
    return {"status":"PASS","local_check":"PASS","artifact_consistency_status":"PASS",
            "score_kind":"native_artifact_consistency","overall_science_status":"PASS",
            "scientific_success":True,"execution_attested":False,"source_truth_verified":False,
            "human_review_required":False,"reward":1.0,
            "checked_claims":["two fresh-path LAMMPS bundles", f"{refs['trajectory']['stop_step']} steps and {refs['trajectory']['expected_frames']} aligned samples", f"{refs['trajectory']['atom_count']}-atom periodic water cell and finite data", "300 K NVT/0.5 fs settings", "four pinned baseline model paths"],
            "unverified_claims":["protected host/Runner execution receipt", "actual loaded model bytes at runtime", "long-time convergence or independent DFT accuracy"],
            "reason":"Automated scoring covers the verified trajectory, native outputs, and workflow records. Host execution provenance and actual loaded model bytes remain unauthenticated."}


def main():
    p=argparse.ArgumentParser();p.add_argument("--app-dir",type=Path,required=True);p.add_argument("--tests-dir",type=Path,required=True);a=p.parse_args()
    try:
        helper=_admission_helper()
        admission=helper.read_host_admission("case-03-water-committee-training", "water-committee-training")
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
