#!/usr/bin/env python3
"""Case06 v4 result-based verifier. Historical native records use the frozen v3 science checks."""
from __future__ import annotations
import csv, json, math, os, re, sys, tempfile
from datetime import datetime
from pathlib import Path
try:
    import verify_v2 as v2
    import verify_v3 as v3
    import science_core_v3
    import report_claims_v51 as report_claims
except ImportError:
    from . import verify_v2 as v2
    from . import verify_v3 as v3
    from . import science_core_v3
    from . import report_claims_v51 as report_claims

CONTRACT_VERSION = "case06-v4"
REPORT_CLAIM_GUARD_VERSION = report_claims.VERSION
RECORD_COUNT = v3.RECORD_COUNT
_sha256 = v3._sha256
_read = v3._read
_safe_final_file = v3._safe_final_file
# The frozen v3 helper owns native-record hash and science validation.
_evaluate_historical = v3._evaluate_historical
_agent_artifact_path = v3._agent_artifact_path
_select_agent_xyz_segment = v3._select_agent_xyz_segment
_xyz_frame_coordinate_half_units_pm = v3._xyz_frame_coordinate_half_units_pm
_check_report_minimum_claims = report_claims.check_report_minimum_claims

class CandidateManifestFailure(ValueError):
    """Candidate-submitted native files or provenance are invalid."""

def _candidate_file(final: Path, row: object, expected_path: str, label: str) -> Path:
    if not isinstance(row, dict) or set(row) != {"path", "sha256", "bytes"}:
        raise CandidateManifestFailure(f"{label}: artifact declaration is malformed")
    if row.get("path") != expected_path:
        raise CandidateManifestFailure(f"{label}: artifact path differs from the required route layout")
    digest = row.get("sha256")
    size = row.get("bytes")
    if (not isinstance(digest, str) or re.fullmatch(r"[0-9a-f]{64}", digest) is None
            or type(size) is not int or size < 0):
        raise CandidateManifestFailure(f"{label}: artifact size/hash is malformed")
    rel = Path(expected_path)
    if rel.is_absolute() or ".." in rel.parts or "\x00" in expected_path or "\\" in expected_path:
        raise CandidateManifestFailure(f"{label}: artifact path is unsafe")
    artifact = final
    if final.is_symlink():
        raise CandidateManifestFailure("candidate final directory must not be a symlink")
    for part in rel.parts:
        artifact = artifact / part
        if artifact.is_symlink():
            raise CandidateManifestFailure(f"{label}: candidate artifact path contains a symlink")
    try:
        artifact = artifact.resolve(strict=True)
        if not artifact.is_relative_to(final.resolve()) or not artifact.is_file():
            raise CandidateManifestFailure(f"{label}: artifact is missing or outside final/")
        actual = artifact.read_bytes()
    except (OSError, RuntimeError, ValueError) as exc:
        if isinstance(exc, CandidateManifestFailure):
            raise
        raise CandidateManifestFailure(f"{label}: artifact is unreadable: {exc}") from exc
    if len(actual) != size or _sha256(artifact) != digest:
        raise CandidateManifestFailure(f"{label}: submitted bytes do not match the manifest")
    return artifact

def _validate_candidate_manifest(provenance: object, final: Path) -> dict[str, dict[str, Path]]:
    """Bind candidate native files and cross-check one self-submitted allocation."""
    required_top = {"schema", "evidence_mode", "provenance_authenticity", "execution_order", "records",
                    "execution_receipt", "scheduler_record", "execution_order_file"}
    if not isinstance(provenance, dict) or set(provenance) != required_top:
        raise CandidateManifestFailure("candidate provenance has unexpected or missing fields")
    if (provenance.get("schema") != "case06-v4-candidate-native-provenance/v1"
            or provenance.get("evidence_mode") != "candidate_native_results"
            or provenance.get("provenance_authenticity") != "candidate_supplied_unverified"):
        raise CandidateManifestFailure("candidate provenance identity or authenticity label is invalid")
    expected = set(v2.EXPECTED_RECORDS) | {"M14/ES/stda-pbe0-tzvp-aex0.25-remedy"}
    rows, order = provenance.get("records"), provenance.get("execution_order")
    if not isinstance(rows, list) or len(rows) != 26 or not isinstance(order, list) or len(order) != 26:
        raise CandidateManifestFailure("candidate manifest must map exactly 26 routes and execution-order entries")
    by_route, order_indices, bound = {}, {}, {}
    for row in rows:
        if not isinstance(row, dict) or set(row) != {"id", "execution_order_index", "artifacts"}:
            raise CandidateManifestFailure("candidate route record is malformed")
        route_id, index = row.get("id"), row.get("execution_order_index")
        if not isinstance(route_id, str) or route_id not in expected or route_id in by_route:
            raise CandidateManifestFailure("candidate manifest has an unknown or duplicate route id")
        if type(index) is not int or not 0 <= index < 26 or index in order_indices:
            raise CandidateManifestFailure(f"{route_id}: execution order index is invalid or duplicated")
        order_indices[index] = route_id
        artifacts = row.get("artifacts")
        if not isinstance(artifacts, dict) or set(artifacts) != {"input", "output", "trajectory"}:
            raise CandidateManifestFailure(f"{route_id}: native artifact map is incomplete")
        paths = {"input": _agent_artifact_path(route_id, "input.inp"),
                 "output": _agent_artifact_path(route_id, "cp2k.out"),
                 "trajectory": _agent_artifact_path(route_id, "trajectory.xyz")}
        bound[route_id] = {role: _candidate_file(final, artifacts[role], paths[role], f"{route_id} {role}")
                           for role in paths}
        by_route[route_id] = row
    if set(by_route) != expected:
        raise CandidateManifestFailure("candidate manifest route inventory is incomplete")
    expected_order = [order_indices[index] for index in range(26)]
    if order != expected_order or set(order) != expected:
        raise CandidateManifestFailure("candidate execution_order does not match the route records")

    order_file = _candidate_file(final, provenance.get("execution_order_file"), "execution-order.json",
                                 "candidate execution-order file")
    try:
        declared_order = json.loads(order_file.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise CandidateManifestFailure(f"candidate execution-order file is unreadable: {exc}") from exc
    if declared_order != order:
        raise CandidateManifestFailure("execution-order.json differs from manifest route order")
    receipt_file = _candidate_file(final, provenance.get("execution_receipt"), "execution-receipt.json",
                                   "candidate execution receipt")
    scheduler_file = _candidate_file(final, provenance.get("scheduler_record"), "scheduler_record.json",
                                     "candidate scheduler record")
    try:
        receipt = json.loads(receipt_file.read_text(encoding="utf-8"))
        scheduler_record = json.loads(scheduler_file.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise CandidateManifestFailure(f"candidate scheduler evidence is unreadable: {exc}") from exc
    receipt_fields = {"schema", "scheduler", "job_id", "allocation_id", "is_array", "allocation", "exit_code",
                      "submitted_at_utc", "started_at_utc", "completed_at_utc", "batch_sha256",
                      "wall_seconds", "execution_order_sha256", "logs"}
    scheduler_fields = {"schema", "scheduler", "job_id", "allocation_id", "allocation", "state",
                        "is_array", "exit_code", "submitted_at_utc", "started_at_utc", "completed_at_utc",
                        "wall_seconds", "batch_sha256"}
    if not isinstance(receipt, dict) or set(receipt) != receipt_fields:
        raise CandidateManifestFailure("execution-receipt.json has missing or unexpected fields")
    if not isinstance(scheduler_record, dict) or set(scheduler_record) != scheduler_fields:
        raise CandidateManifestFailure("scheduler_record.json has missing or unexpected fields")
    if (receipt.get("schema") != "case06-v4-execution-receipt/v1"
            or scheduler_record.get("schema") != "case06-v4-scheduler-record/v1"):
        raise CandidateManifestFailure("candidate scheduler evidence schema is invalid")
    allocation_fields = {"nodes", "gpus", "cpus", "memory_mib", "wall_time_seconds"}
    allocation = receipt.get("allocation")
    if (not isinstance(allocation, dict) or set(allocation) != allocation_fields
            or type(allocation.get("nodes")) is not int or allocation["nodes"] < 1
            or type(allocation.get("gpus")) is not int or allocation["gpus"] < 0
            or type(allocation.get("cpus")) is not int or allocation["cpus"] < 1
            or type(allocation.get("memory_mib")) is not int or allocation["memory_mib"] < 1
            or type(allocation.get("wall_time_seconds")) is not int or allocation["wall_time_seconds"] < 1):
        raise CandidateManifestFailure("submission must declare one non-array allocation object")
    cross_keys = ("scheduler", "job_id", "allocation_id", "is_array", "exit_code", "submitted_at_utc",
                  "started_at_utc", "completed_at_utc", "wall_seconds", "batch_sha256")
    if (scheduler_record.get("allocation") != allocation
            or any(receipt.get(key) != scheduler_record.get(key) for key in cross_keys)):
        raise CandidateManifestFailure("execution receipt and scheduler record disagree")
    if (not isinstance(receipt.get("scheduler"), str) or not receipt["scheduler"].strip()
            or not isinstance(receipt.get("job_id"), str) or not receipt["job_id"].strip()
            or not isinstance(receipt.get("allocation_id"), str) or not receipt["allocation_id"].strip()
            or type(receipt.get("is_array")) is not bool or receipt["is_array"]
            or scheduler_record.get("state") != "COMPLETED"
            or type(receipt.get("exit_code")) is not int or receipt["exit_code"] != 0):
        raise CandidateManifestFailure("candidate scheduler job identity or completion state is invalid")
    try:
        submitted = datetime.fromisoformat(receipt["submitted_at_utc"].replace("Z", "+00:00"))
        started = datetime.fromisoformat(receipt["started_at_utc"].replace("Z", "+00:00"))
        completed = datetime.fromisoformat(receipt["completed_at_utc"].replace("Z", "+00:00"))
    except (AttributeError, TypeError, ValueError) as exc:
        raise CandidateManifestFailure("candidate scheduler timestamps are malformed") from exc
    if (any(item.tzinfo is None for item in (submitted, started, completed))
            or not submitted <= started <= completed
            or type(receipt.get("wall_seconds")) not in (int, float)
            or not math.isfinite(receipt["wall_seconds"])
            or abs((completed - started).total_seconds() - receipt["wall_seconds"]) > 1e-6
            or receipt["wall_seconds"] > allocation["wall_time_seconds"]):
        raise CandidateManifestFailure("candidate scheduler timestamps exceed or contradict the allocation")
    logs = receipt.get("logs")
    if not isinstance(logs, dict) or set(logs) != {"batch_script", "stdout", "stderr"}:
        raise CandidateManifestFailure("execution receipt must bind batch script, stdout, and stderr")
    batch_declaration = logs.get("batch_script")
    if not isinstance(batch_declaration, dict):
        raise CandidateManifestFailure("execution receipt batch-script declaration is malformed")
    if (receipt.get("execution_order_sha256") != provenance["execution_order_file"].get("sha256")
            or receipt.get("batch_sha256") != batch_declaration.get("sha256")):
        raise CandidateManifestFailure("receipt does not bind execution order and submitted batch script")
    for role, filename in (("batch_script", "batch.sh"), ("stdout", "scheduler.stdout"),
                           ("stderr", "scheduler.stderr")):
        bound_log = _candidate_file(final, logs[role], f"provenance/{filename}", f"submission {role}")
        if role == "batch_script":
            try:
                script_text = bound_log.read_text(encoding="utf-8")
            except (OSError, UnicodeError) as exc:
                raise CandidateManifestFailure(f"submission batch script is unreadable: {exc}") from exc
            if re.search(r"(?im)^\s*#(?:SBATCH\s+(?:--array|-a)(?:=|\s)|PBS\s+-J\b|BSUB\s+-J\s+.*\[)",
                         script_text):
                raise CandidateManifestFailure("submission batch script declares an array job")
    return bound


V3ClaimFailure = v3.V3ClaimFailure
V3ClaimUnverified = v3.V3ClaimUnverified

def _require_historical_report_topics(report_text: str) -> None:
    """Require scientific coverage while accepting ordinary English or Chinese prose."""
    text = report_text.casefold().replace("_", " ").replace("–", "-").replace("—", "-")
    flat = re.sub(r"\s+", " ", text)
    checks = {
        "historical route analysis": (
            re.search(r"(?<!\d)26(?!\d)", flat) and
            any(word in flat for word in ("route", "record", "路线", "记录")) and
            any(word in flat for word in ("historical", "archive", "历史", "原生"))),
        "36 SI comparisons and the 3.0 pm rule": (
            re.search(r"(?<!\d)36(?!\d)", flat) and
            ("si" in flat or "补充信息" in flat) and
            re.search(r"\b3(?:\.0)?\s*pm\b|3(?:\.0)?\s*皮米", flat)),
        "paired PBE0/ADMM differences": (
            ("pair" in flat or "配对" in flat) and
            "pbe0" in flat and "admm" in flat),
        "M14 default aEX=0.2 physical-dissociation interpretation": (
            "m14" in flat and re.search(r"0\.2(?![\d.])", flat) and "aex" in flat and
            (re.search(r"physical.{0,32}dissociat|dissociat.{0,32}physical", flat)
             or "物理解离" in flat)),
        "three separate M14 aEX=0.25 remedy bond checks": (
            "m14" in flat and re.search(r"0\.25(?![\d.])", flat) and
            ("remedy" in flat or "补救" in flat) and
            (re.search(r"\b(?:three|3)\b.{0,48}\b(?:bond|check)\b|\b(?:bond|check)\b.{0,48}\b(?:three|3)\b", flat)
             or re.search(r"三.{0,24}(?:bond|check|键|条)|(?:bond|check|键|条).{0,24}三", flat))),
        "minimum and curvature scope limitation": (
            ("minimum" in flat or "最低点" in flat or "极小值" in flat) and
            ("curvature" in flat or "曲率" in flat) and
            (re.search(r"outside.{0,24}scope|not.{0,16}(?:assessed|evaluated|claimed|established)|unassessed", flat)
             or any(phrase in flat for phrase in ("范围外", "未评估", "不作", "不在本研究范围", "不涉及", "不声称")))),
    }
    missing = [name for name, present in checks.items() if not present]
    if missing:
        raise V3ClaimFailure("report must explain these scientific topics: " + "; ".join(missing))


def _evaluate_candidate_native(provenance: dict, final: Path, tests: Path, *, prebound=None,
                              source_atom_maps=None, native_originals=None) -> dict:
    """Recompute the unchanged v3 science checks on candidate-submitted native files."""
    bound = prebound if prebound is not None else _validate_candidate_manifest(provenance, final)
    refs = v2.load_refs(tests)
    active_profile, reason = v2.science_profile.load_profile(
        tests / "_support" / "science_profile.json", refs, v2.EXPECTED_REF_SHA256)
    if active_profile is None:
        raise V3ClaimUnverified(f"frozen same-method SI profile is unavailable: {reason}")

    route_results = {}
    endpoint_atoms = {}
    endpoint_precision = {}
    endpoint_indices = {}
    native_sha = {}
    m14_classifier = None
    for route_id in sorted(bound):
        files = bound[route_id]
        input_text, output_text = _read(files["input"]), _read(files["output"])
        starts = list(re.finditer(r"(?im)^.*PROGRAM STARTED AT\b", output_text))
        ends = list(re.finditer(r"(?im)^.*PROGRAM ENDED AT\b", output_text))
        if len(starts) != 1 or len(ends) != 1 or ends[0].start() < starts[0].start():
            raise V3ClaimFailure(f"{route_id}: receipt-bound output must contain one complete isolated invocation")
        try:
            result = science_core_v3.evaluate_optimizer_run(route_id, input_text, output_text)
        except science_core_v3.ScienceInputError as exc:
            raise V3ClaimFailure(f"{route_id}: shared v3 science core rejected host execution: {exc}") from exc
        trajectory = files["trajectory"]
        try:
            frames = v2._xyz_frames(trajectory)
        except (OSError, UnicodeError, ValueError) as exc:
            raise V3ClaimFailure(f"{route_id}: native trajectory is malformed: {exc}") from exc
        molecule = route_id.split("/", 1)[0]
        expected_species = v2.SPECIES[molecule]
        source_map = (source_atom_maps or {}).get(molecule, list(range(len(expected_species))))
        if len(source_map) != len(expected_species) or sorted(source_map) != list(range(len(expected_species))):
            raise v2.InfraError(f"{route_id}: source atom map is malformed")
        if not frames or any(len(frame) != len(expected_species)
                             or [frame[i][0].capitalize() for i in source_map] != expected_species
                             for frame in frames):
            raise V3ClaimFailure(f"{route_id}: source atom order does not match the pinned canonical topology map")
        original_files = (native_originals or {}).get(route_id, files)
        if route_id == "M14/ES/stda-pbe0-tzvp":
            # The native classifier cross-checks output project/input names, force frames,
            # Mulliken populations and the collected trajectory. Stage under those names.
            classifier_output = _read(original_files["output"])
            classifier_input = original_files["input"]
            classifier_trajectory = original_files["trajectory"]
            project = re.search(r"(?im)^\s*GLOBAL\|\s*Project name\s+(\S+)", classifier_output)
            inp_name = re.search(r"(?im)^\s*CP2K\|\s*Input file name\s+(\S+)", classifier_output)
            project_name = project.group(1) if project else ""
            if (not project or not inp_name or Path(inp_name.group(1)).name != inp_name.group(1)
                    or not project_name or Path(project_name).name != project_name
                    or project_name in {".", ".."} or "/" in project_name or "\\" in project_name):
                raise V3ClaimFailure("M14 default: native project/input identity is missing or unsafe")
            with tempfile.TemporaryDirectory(prefix="case06-v3-m14-") as temp_dir:
                temp = Path(temp_dir)
                staged_input = temp / inp_name.group(1)
                staged_output = temp / "cp2k.out"
                staged_xyz = temp / f"{project.group(1)}-pos-1.xyz"
                staged_input.write_bytes(classifier_input.read_bytes())
                staged_output.write_bytes(original_files["output"].read_bytes())
                staged_xyz.write_bytes(classifier_trajectory.read_bytes())
                m14_classifier = v2.native_science.classify_m14_dissociation(
                    staged_output, staged_xyz, staged_input, expected_method="PBE0", aex=0.2,
                    min_independent_frames=3,
                    expected_sha256={"input": _sha256(staged_input), "output": _sha256(staged_output),
                                     "trajectory": _sha256(staged_xyz)})
            if m14_classifier.get("status") == "FAIL":
                raise V3ClaimFailure("M14 default: native S1 evidence does not establish physical dissociation")
            if m14_classifier.get("status") != "PASS":
                raise V3ClaimUnverified("M14 default: native physical dissociation remains unverified: "
                                        + "; ".join(m14_classifier.get("issues", [])))
        else:
            try:
                segment = _select_agent_xyz_segment(output_text, trajectory)
            except (OSError, UnicodeError, ValueError, TypeError) as exc:
                raise V3ClaimFailure(f"{route_id}: native optimizer/XYZ closure failed: {exc}") from exc
            if (segment["start_zero_based"] != 0
                    or segment["end_zero_based_inclusive"] != len(frames) - 1
                    or segment["count"] != len(frames)):
                raise V3ClaimFailure(f"{route_id}: trajectory includes frames outside its receipt-bound invocation")
            endpoint_atoms[route_id] = [frames[-1][i] for i in source_map]
            raw_precision = _xyz_frame_coordinate_half_units_pm(trajectory, len(frames) - 1)
            endpoint_precision[route_id] = [raw_precision[i] for i in source_map]
            endpoint_indices[route_id] = len(frames) - 1
        hash_files = original_files
        result["input_sha256"] = _sha256(hash_files["input"])
        result["output_sha256"] = _sha256(hash_files["output"])
        result["trajectory_sha256"] = _sha256(hash_files["trajectory"])
        route_results[route_id] = result

    # The M14 default trajectory is intentionally a classifier input, not an SI target.
    geometries = {}
    residual_results = {}
    for ref_key, ref in refs["items"].items():
        if ref.get("state") != "ES" or ref.get("quantity") != "bond":
            continue
        molecule, label = ref["molecule"], ref["label"]
        for route, column in (("pbe0-tzvp", "PBE0|TZVP"),
                              ("admm-tzvp-tzp", "ADMM|TZVP+tzp"),
                              ("stda-pbe0-tzvp", "sTDA@PBE0|TZVP")):
            if ref["values"].get(column) is None:
                continue
            route_id = f"{molecule}/ES/{route}"
            atoms = endpoint_atoms.get(route_id)
            if atoms is None:
                raise V3ClaimUnverified(f"{route_id}: no geometry endpoint is eligible for SI comparison")
            values = v2._bond_values(molecule, label, atoms)
            if values is None:
                raise V3ClaimUnverified(f"{route_id}: no canonical topology mapping for {label}")
            measured = math.fsum(values) / len(values)
            uncertainty = v2._bond_coordinate_uncertainty_pm(
                molecule, label, endpoint_precision[route_id], list(range(len(atoms))))
            accepted, detail = v2.science_profile.accept_empirical_residual(
                candidate_pm=measured, published_pm=float(ref["values"][column]),
                candidate_coordinate_uncertainty_pm=uncertainty)
            geometries[(molecule, route, label)] = measured
            residual_results[f"{ref_key}|{route}"] = {
                "computed_pm": measured, "published_pm": float(ref["values"][column]),
                "coordinate_uncertainty_pm": uncertainty, **detail}
            if detail.get("decision") == "FAIL":
                raise V3ClaimFailure(f"{ref_key}/{route}: same-method SI geometry exceeds frozen 3 pm rule")
            if detail.get("decision") != "PASS" or not accepted:
                raise V3ClaimUnverified(f"{ref_key}/{route}: same-method SI interval is not PASS")
    if len(geometries) != 36:
        raise V3ClaimUnverified(f"expected 36 same-method SI geometry checks, got {len(geometries)}")

    # V3 includes the analysis deliverable, not just the host-executed calculations.
    # Reuse the v2 row checker without invoking its out-of-scope minimum gate.
    comparison_path = final / "comparison.csv"
    if not comparison_path.is_file() or comparison_path.is_symlink():
        raise V3ClaimFailure("Agent final/comparison.csv is missing or unsafe")
    try:
        with comparison_path.open(newline="", encoding="utf-8-sig") as stream:
            comparison_rows = list(csv.DictReader(stream))
    except (OSError, UnicodeError, csv.Error) as exc:
        raise V3ClaimFailure(f"Agent comparison.csv is unreadable: {exc}") from exc
    if len(comparison_rows) != 36:
        raise V3ClaimFailure(f"Agent comparison.csv must contain exactly 36 rows, got {len(comparison_rows)}")
    comparison_records = {}
    for route_id in v2.EXPECTED_RECORDS:
        comparison_records[route_id] = {
            "id": route_id, "molecule": route_id.split("/")[0], "state": route_id.split("/")[1],
            "route": route_id.split("/")[2],
            "trajectory_path": _agent_artifact_path(route_id, "trajectory.xyz"),
            "atom_map": ((source_atom_maps or {}).get(route_id.split("/")[0])
                         or list(range(len(v2.SPECIES[route_id.split("/")[0]])))),
            "selected_frame_index_zero_based": endpoint_indices.get(route_id, 0),
        }
    comparison_problems = []
    checked_bonds = v2._comparison_check(
        comparison_rows, refs, comparison_records, final, comparison_problems)
    if comparison_problems:
        raise V3ClaimFailure("Agent comparison.csv does not match receipt-bound native geometries: "
                             + "; ".join(comparison_problems[:4]))
    if len(checked_bonds) != 36:
        raise V3ClaimUnverified(f"checker recomputed {len(checked_bonds)} comparison bonds; expected 36")
    for key, value in geometries.items():
        if key not in checked_bonds or abs(checked_bonds[key] - value) > 1e-10:
            raise v2.InfraError("internal comparison evaluator disagrees with its receipt-bound endpoint calculation")

    pair_differences = []
    for ref in refs["items"].values():
        if ref.get("state") != "ES" or ref.get("quantity") != "bond":
            continue
        key = (ref["molecule"], ref["label"])
        if (key[0], "pbe0-tzvp", key[1]) in geometries and (key[0], "admm-tzvp-tzp", key[1]) in geometries:
            pair_differences.append({"molecule": key[0], "label": key[1],
                                     "admm_minus_pbe0_pm": geometries[(key[0], "admm-tzvp-tzp", key[1])]
                                     - geometries[(key[0], "pbe0-tzvp", key[1])]})
    if len(pair_differences) != 13:
        raise V3ClaimUnverified(f"expected 13 paired ADMM-PBE0 bond differences, got {len(pair_differences)}")

    remedy_id = "M14/ES/stda-pbe0-tzvp-aex0.25-remedy"
    remedy_atoms = endpoint_atoms.get(remedy_id)
    if remedy_atoms is None:
        raise V3ClaimUnverified("M14 remedy lacks a converged native geometry endpoint")
    remedy_precision = endpoint_precision[remedy_id]
    atom_map = list(range(len(remedy_atoms)))
    remedy_results = {}
    for label, pair in (("c o", (0, 1)), ("c h", (0, 3)), ("c cl", (0, 2))):
        ref = refs["items"][f"bond|ES|M14|{label}"]
        published = ref["values"].get("_stda_printed_parameter_exception")
        measured = math.dist(remedy_atoms[pair[0]][1:], remedy_atoms[pair[1]][1:]) * 100.0
        uncertainty = v2._bond_coordinate_uncertainty_pm("M14", label, remedy_precision, atom_map)
        accepted, detail = v2.science_profile.accept_empirical_residual(
            candidate_pm=measured, published_pm=published,
            candidate_coordinate_uncertainty_pm=uncertainty)
        if detail.get("decision") == "FAIL":
            raise V3ClaimFailure(f"M14 remedy {label}: SI-14 geometry exceeds frozen 3 pm rule")
        if detail.get("decision") != "PASS" or not accepted:
            raise V3ClaimUnverified(f"M14 remedy {label}: SI-14 interval is not PASS")
        remedy_results[label] = {"computed_pm": measured, "published_pm": published, **detail}

    default_summary = {"status": "physical_dissociation", "aex": 0.2,
                       "comparison_target": "null_target_excluded"}
    remedy_summary = {"status": "geometry_validated", "route": remedy_id, "aex": 0.25}
    minimum_summary = {"status": "OUT_OF_SCOPE_FOR_V3"}
    expected_summary = v2.scientific_summary.build_summary(
        refs, checked_bonds, m14_default=default_summary, m14_remedy=remedy_summary,
        minimum_status=minimum_summary)
    summary_path = final / "scientific-summary.json"
    report_path = final / "report.md"
    if (not summary_path.is_file() or summary_path.is_symlink()
            or not report_path.is_file() or report_path.is_symlink()):
        raise V3ClaimFailure("submission must provide scientific-summary.json and report.md")
    try:
        candidate_summary = json.loads(summary_path.read_text(encoding="utf-8"))
        report_text = report_path.read_text(encoding="utf-8")
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise V3ClaimFailure(f"Agent scientific analysis deliverable is malformed: {exc}") from exc
    normalized_summary = dict(candidate_summary) if isinstance(candidate_summary, dict) else candidate_summary
    if isinstance(normalized_summary, dict):
        if "minimum_status" not in normalized_summary:
            normalized_summary["minimum_status"] = {"status": "OUT_OF_SCOPE_FOR_V3"}
        elif normalized_summary["minimum_status"] in (
                {"status": "not_assessed"}, {"status": "not-assessed"}):
            normalized_summary["minimum_status"] = {"status": "OUT_OF_SCOPE_FOR_V3"}
    if not v2.scientific_summary.summaries_match(expected_summary, normalized_summary):
        raise V3ClaimFailure("Agent scientific-summary.json differs from checker-recomputed v3 statistics/status")
    _check_report_minimum_claims(report_text)
    _require_historical_report_topics(report_text)
    summary_hash = _sha256(summary_path)
    return {"optimizer_records": [route_results[key] for key in sorted(route_results)],
            "si_bond_residuals_count": len(geometries), "si_bond_residuals": residual_results,
            "admm_minus_pbe0_pairs": pair_differences, "m14_remedy_geometry": remedy_results,
            "m14_default_classifier": m14_classifier, "scientific_summary": candidate_summary,
            "analysis_artifacts": {"comparison_rows": len(comparison_rows),
                                   "scientific_summary_sha256": summary_hash},
            "minimum_curvature": {"status": "OUT_OF_SCOPE_FOR_V3"}}



def _require_trusted_science_inputs(tests: Path) -> None:
    pinned_files = {
        "refs.json": v2.EXPECTED_REF_SHA256,
        "_support/science_profile.json": "14f2d52d265708de948771ef0bf5a22a96ad307fc7524fa08f48a8ac218b81b4",
        "_support/historical-source-profile.json": v2.HISTORICAL_PROFILE_SHA256,
        "_support/science_core_v3.py": "3590b067521b03f5441175847fdd2d22586fd5f450e665ecdd9da1bee7fe63a9",
        "_support/native_science.py": "39d33c5b911e854e53c73bcc2bf62f9baeac585f4f52a7eb99d0f9b05d149944",
        "_support/scientific_summary.py": "8f5bdb4edb6036b991e48f23436a72a3eb50aec48357c6d0be406abcb0f32a32",
    }
    for name, expected in pinned_files.items():
        path = tests / name if name == "refs.json" else tests / name
        try:
            if not path.is_file() or _sha256(path) != expected:
                raise v2.InfraError(f"trusted science resource is missing or has a hash mismatch: {name}")
        except OSError as exc:
            raise v2.InfraError(f"trusted science resource is unreadable: {name}: {exc}") from exc
    refs = v2.load_refs(tests)
    profile_path = tests / "_support" / "science_profile.json"
    try:
        active, reason = v2.science_profile.load_profile(
            profile_path, refs, v2.EXPECTED_REF_SHA256)
    except v2.science_profile.ProfileError as exc:
        raise v2.InfraError(f"reviewed science profile is invalid: {exc}") from exc
    if active is None:
        raise v2.InfraError(f"reviewed science profile is unavailable: {reason}")

def verify(app: Path, tests: Path):
    report={"case_id":v2.CASE_ID,"contract_version":CONTRACT_VERSION,"status":"UNVERIFIED","scientific_result_status":"native_results_required","checks_passed":[],"problems":[],"pending_science_reviews":[],"limits":["Candidate-submitted scheduler provenance is not independently host-authenticated.","Fresh HPC execution is not required or calibrated in v4.","Minimum curvature remains excluded, as in v3."]}
    final=app/"final"
    try:
        provenance=json.loads((final/"provenance.json").read_text(encoding="utf-8"))
    except (OSError,UnicodeError,json.JSONDecodeError) as exc:
        report.update(status="FAIL",scientific_result_status="candidate_provenance_missing_or_invalid")
        report["problems"].append(str(exc)); return report,1
    if not isinstance(provenance, dict):
        report.update(status="FAIL",scientific_result_status="candidate_provenance_invalid")
        report["problems"].append("provenance.json root must be an object"); return report,1
    evidence_mode=provenance.get("evidence_mode")
    if evidence_mode == "candidate_native_results":
        try:
            _require_trusted_science_inputs(tests)
            result=_evaluate_candidate_native(provenance,final,tests)
        except CandidateManifestFailure as exc:
            report.update(status="FAIL",scientific_result_status="candidate_native_manifest_invalid")
            report["problems"].append(str(exc)); return report,1
        except v3.V3ClaimFailure as exc:
            report.update(status="FAIL",scientific_result_status="candidate_science_failed")
            report["problems"].append(str(exc)); return report,1
        except v3.V3ClaimUnverified as exc:
            report.update(status="UNVERIFIED",scientific_result_status="candidate_science_unverified")
            report["pending_science_reviews"].append(str(exc)); return report,2
        except v2.InfraError as exc:
            # Trusted inputs were verified above. Remaining InfraError paths are
            # reached through candidate-controlled native bytes and are candidate failures.
            report.update(status="FAIL",scientific_result_status="candidate_native_artifact_invalid")
            report["problems"].append(str(exc)); return report,1
        except science_core_v3.ScienceInputError as exc:
            report.update(status="FAIL",scientific_result_status="candidate_native_science_invalid")
            report["problems"].append(str(exc)); return report,1
        except (OSError,UnicodeError,json.JSONDecodeError,ValueError,KeyError,TypeError) as exc:
            report.update(status="FAIL",scientific_result_status="candidate_artifact_invalid")
            report["problems"].append(str(exc)); return report,1
        report.update(result)
        report["checks_passed"].extend(["26 candidate-submitted native route records matched the manifest paths, sizes, and hashes",
                                        "36 SI rows, 13 paired method deltas, and three M14 remedy bonds passed the frozen science checks",
                                        "minimum-curvature claims excluded"])
        report["candidate_provenance_status"]="NOT_VERIFIED_CANDIDATE_SUBMITTED"
        report["scheduler_provenance_status"]="NOT_VERIFIED"
        report["historical_caveats"]=["Scheduler identifiers, allocation, timestamps, batch script, stdout, and stderr are candidate-submitted metadata; their byte links are checked but their authorship is not authenticated."]
        report.update(status="PASS",scientific_result_status="v4_candidate_native_results_pass")
        return report,0
    if evidence_mode != "historical_oracle_archive":
        report.update(status="FAIL",scientific_result_status="unsupported_evidence_mode")
        report["problems"].append("v4 accepts historical_oracle_archive or candidate_native_results evidence"); return report,1
    try:
        _require_trusted_science_inputs(tests)
        # v2 gates historical source replay on this legacy selector. v4 applies
        # that same frozen validation to every candidate, so scope the selector
        # to this call and restore the caller's environment even on exceptions.
        had_answer_mode = "CCB_ANSWER_MODE" in os.environ
        previous_answer_mode = os.environ.get("CCB_ANSWER_MODE")
        os.environ["CCB_ANSWER_MODE"] = "oracle"
        try:
            base,code=v2.verify(app,tests)
        finally:
            if had_answer_mode:
                os.environ["CCB_ANSWER_MODE"] = previous_answer_mode
            else:
                os.environ.pop("CCB_ANSWER_MODE", None)
        if code==1 or base.get("problems"):
            report.update(status="FAIL",scientific_result_status="historical_science_failed"); report["problems"].extend(base.get("problems",[])); return report,1
        if code!=2 or base.get("status")!="UNVERIFIED": raise v2.InfraError("unexpected v2 historical validation status")
        report["checks_passed"].append("v2 archive, SI, M14, and source validation")
        additional=v3._require_base_science_claims(base,final,tests)
        report.update(additional)
        report["si_bond_residuals"]=base["same_method_residuals"]
        report["m14_default_classifier"]=base["m14_default_native_classifier"]
        report["minimum_curvature"]={"status":"OUT_OF_SCOPE_FOR_V3","v2_status":base.get("minimum_status")}
        # Candidate structure/native hash defects are scientific FAILs. Trusted grader
        # resources (refs/profile) were already loaded above and remain infrastructure errors.
        try:
            records=_evaluate_historical(final,provenance)
        except v2.InfraError as exc:
            report.update(status="FAIL",scientific_result_status="candidate_native_artifact_invalid")
            report["problems"].append(str(exc)); return report,1
        if len(records)!=RECORD_COUNT:
            report.update(status="FAIL",scientific_result_status="candidate_record_count_invalid")
            report["problems"].append("expected exactly 26 unique native result records"); return report,1
    except v3.V3ClaimFailure as exc:
        report.update(status="FAIL",scientific_result_status="required_science_claim_failed"); report["problems"].append(str(exc)); return report,1
    except science_core_v3.ScienceInputError as exc:
        report.update(status="FAIL",scientific_result_status="native_result_invalid"); report["problems"].append(str(exc)); return report,1
    except v2.InfraError: raise
    except (OSError,UnicodeError,json.JSONDecodeError,ValueError,KeyError,TypeError) as exc:
        report.update(status="FAIL",scientific_result_status="candidate_artifact_invalid"); report["problems"].append(str(exc)); return report,1
    report["optimizer_records"]=records
    report["checks_passed"].extend(["26 submitted historical native optimizer input/output records hash-verified and science-checked","36 SI rows, 13 paired method deltas, and M14 remedy checks passed","minimum-curvature claim excluded"])
    report["historical_caveats"]=["Historical archive correspondence is source-hash checked; it is not fresh per-run provenance.","Fresh compute receipts and scheduler execution are outside v4."]
    report.update(status="PASS",scientific_result_status="v4_historical_results_pass")
    return report,0

def main():
    app=Path(os.environ.get("APP","/app")).resolve(); tests=Path(os.environ.get("TESTS",Path(__file__).resolve().parent)).resolve(); logs=Path(os.environ.get("LOGS","/logs/verifier")).resolve(); logs.mkdir(parents=True,exist_ok=True); (logs/"reward.txt").unlink(missing_ok=True)
    try: report,code=verify(app,tests)
    except v2.InfraError as exc: print(f"grader infrastructure error: {exc}",file=sys.stderr); return 2
    except (OSError,UnicodeError,ValueError,KeyError,TypeError) as exc: print(f"grader infrastructure error: {exc}",file=sys.stderr); return 2
    (logs/"verification.json").write_text(json.dumps(report,indent=2)+"\n",encoding="utf-8"); print(json.dumps({"contract_version":CONTRACT_VERSION,"status":report["status"],"problems":report["problems"]},indent=2)); return code
if __name__=="__main__": raise SystemExit(main())
