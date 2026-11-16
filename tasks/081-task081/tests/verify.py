#!/usr/bin/env python3
# L1 Deliverables: Check required deliverables for completeness and parseability.
# L2 Execution: Check the use of supplied data or archived evidence where required.
# L3 Science: Analyze historical excited-state geometry results.
"""Case06 v5: candidate analysis of pinned public historical native files."""
from __future__ import annotations
import hashlib, json, os, re, shutil, sys, tempfile
from pathlib import Path
SUPPORT_DIR = Path(__file__).resolve(strict=True).parent / "_support"
if SUPPORT_DIR.is_symlink() or not SUPPORT_DIR.is_dir():
    raise RuntimeError("trusted verifier support directory is unavailable")
sys.path.insert(0, str(SUPPORT_DIR))

try:
    import verify_v2 as v2
    import verify_v3 as v3
    import verify_v5_science as science
except ImportError:
    from . import verify_v2 as v2
    from . import verify_v3 as v3
    from . import verify_v5_science as science

CONTRACT_VERSION = "case06-v5"
PUBLIC_MANIFEST_SHA256 = "7b8bcd1ca122877c07a7eed70a16e64414b5ae309f0829ab984d14fdcb08c387"
V5_SOURCE_MANIFEST = "case06-v5-public-native-source-manifest-v1.json"
ROUTE_IDS = set(v2.EXPECTED_RECORDS) | {"M14/ES/stda-pbe0-tzvp-aex0.25-remedy"}
ROLE_NAMES = ("input", "output", "trajectory")

class CandidateSubmissionFailure(ValueError):
    pass

def _safe_final_file(final: Path, rel: str) -> Path:
    if not isinstance(rel, str) or not rel or "\\" in rel or "\x00" in rel:
        raise CandidateSubmissionFailure("candidate output path is malformed")
    path = Path(rel)
    if path.is_absolute() or ".." in path.parts:
        raise CandidateSubmissionFailure("candidate output path is unsafe")
    result = final
    if final.is_symlink():
        raise CandidateSubmissionFailure("candidate final directory must not be a symlink")
    for part in path.parts:
        result = result / part
        if result.is_symlink():
            raise CandidateSubmissionFailure("candidate output contains a symlink")
    try:
        resolved = result.resolve(strict=True)
    except OSError as exc:
        raise CandidateSubmissionFailure(f"candidate output is missing: {rel}") from exc
    if not resolved.is_relative_to(final.resolve()) or not resolved.is_file():
        raise CandidateSubmissionFailure(f"candidate output is not a regular final/ file: {rel}")
    return resolved

def _load_manifest(tests: Path) -> dict:
    path = tests / "_support" / V5_SOURCE_MANIFEST
    try:
        raw = path.read_bytes()
        if hashlib.sha256(raw).hexdigest() != PUBLIC_MANIFEST_SHA256:
            raise v2.InfraError("v5 public source manifest hash mismatch")
        obj = json.loads(raw)
    except (OSError, json.JSONDecodeError) as exc:
        raise v2.InfraError(f"v5 public source manifest unavailable: {exc}") from exc
    if obj.get("schema") != "case06-v5-public-native-source-manifest/v1" or obj.get("member_count") != 122:
        raise v2.InfraError("v5 public source manifest schema or member count is invalid")
    return obj

def _validate_agent_manifest(provenance: object, final: Path, app: Path, tests: Path) -> tuple[dict, dict]:
    expected_fields = {"schema", "evidence_mode", "source_record", "archive_url", "source_manifest_sha256",
                       "execution_authenticity", "launcher_exit_code", "stderr", "scheduler_provenance_status", "records"}
    if not isinstance(provenance, dict):
        raise CandidateSubmissionFailure("historical candidate provenance must be an object")
    manifest = _load_manifest(tests)
    unknown = set(provenance) - expected_fields
    if unknown:
        raise CandidateSubmissionFailure(f"historical provenance has unknown fields: {sorted(unknown)}")
    fixed = {"schema": "case06-v5-historical-candidate-provenance/v1",
             "evidence_mode": "candidate_historical_native_results",
             "source_record": manifest["source_record"], "archive_url": manifest["archive_url"],
             "source_manifest_sha256": PUBLIC_MANIFEST_SHA256,
             "execution_authenticity": "historical_unverified", "launcher_exit_code": None, "stderr": None,
             "scheduler_provenance_status": "NOT_AVAILABLE_HISTORICAL"}
    # Normalize only absent fixed metadata in a private copy. Explicit null or
    # incorrect values remain visible and are rejected below.
    normalized = dict(provenance)
    for key, value in fixed.items():
        if key not in normalized:
            normalized[key] = value
        elif normalized[key] != value:
            raise CandidateSubmissionFailure(f"historical provenance metadata is invalid: {key}")
    rows = normalized.get("records")
    if not isinstance(rows, list) or len(rows) != 26:
        raise CandidateSubmissionFailure("historical provenance must list exactly 26 routes")
    public_records = {row["id"]: row["artifacts"] for row in manifest["route_records"]}
    if set(public_records) != ROUTE_IDS:
        raise v2.InfraError("public source route inventory is inconsistent with the frozen route set")
    input_root_raw = app / "inputs" / "public-source"
    if input_root_raw.is_symlink() or not input_root_raw.is_dir():
        raise v2.InfraError("public source input directory is unavailable or unsafe")
    input_root = input_root_raw.resolve(strict=True)
    member_by_name = {}
    for item in manifest["members"]:
        if (not isinstance(item, dict) or set(item) != {"member", "bytes", "sha256", "crc32"}
                or not isinstance(item.get("member"), str) or item["member"] in member_by_name
                or type(item.get("bytes")) is not int or item["bytes"] < 0
                or not re.fullmatch(r"[0-9a-f]{64}", str(item.get("sha256", "")))
                or not re.fullmatch(r"[0-9a-f]{8}", str(item.get("crc32", "")))):
            raise v2.InfraError("public source manifest has a malformed or duplicate member declaration")
        member_by_name[item["member"]] = item
    if len(member_by_name) != manifest["member_count"]:
        raise v2.InfraError("public source member inventory is incomplete")
    # Validate the entire mounted public source set against its source manifest.
    for member, pinned in member_by_name.items():
        rel = Path(member)
        if rel.is_absolute() or ".." in rel.parts or not member.startswith("DATA_MATERIALS_CLOUD/"):
            raise v2.InfraError("pinned public source path is unsafe")
        source = input_root / rel
        cursor = input_root
        for part in rel.parts:
            cursor = cursor / part
            if cursor.is_symlink():
                raise v2.InfraError("public source member path contains a symlink")
        try:
            raw = source.read_bytes()
        except OSError as exc:
            raise v2.InfraError(f"pinned public source member is unavailable: {member}") from exc
        if len(raw) != pinned["bytes"] or hashlib.sha256(raw).hexdigest() != pinned["sha256"]:
            raise v2.InfraError(f"mounted public source member fails its pinned integrity check: {member}")
    bound, seen = {}, set()
    normalized_rows = []
    role_fields = {"member", "path", "bytes", "sha256"}
    for row in rows:
        if not isinstance(row, dict) or set(row) != {"id", "artifacts"}:
            raise CandidateSubmissionFailure("historical route record is malformed")
        route_id = row["id"]
        if not isinstance(route_id, str) or route_id not in ROUTE_IDS or route_id in bound:
            raise CandidateSubmissionFailure("historical route ID is unknown or duplicated")
        artifacts = row["artifacts"]
        if not isinstance(artifacts, dict) or set(artifacts) != set(ROLE_NAMES):
            raise CandidateSubmissionFailure(f"{route_id}: input/output/trajectory mappings are required")
        bound[route_id] = {}
        normalized_artifacts = {}
        for role in ROLE_NAMES:
            entry = artifacts[role]
            if not isinstance(entry, dict) or "member" not in entry or not set(entry).issubset(role_fields):
                raise CandidateSubmissionFailure(f"{route_id}/{role}: a public member declaration is required")
            member = public_records[route_id].get(role)
            expected_path = f"/app/inputs/public-source/{member}"
            if entry["member"] != member:
                raise CandidateSubmissionFailure(f"{route_id}/{role}: source member differs from the public manifest")
            if member not in member_by_name:
                raise v2.InfraError(f"public route references an unpinned source member: {member}")
            if member in seen:
                raise CandidateSubmissionFailure("a public archive member is assigned more than once")
            seen.add(member)
            pinned = member_by_name[member]
            expected_artifact = {"member": member, "path": expected_path,
                                 "bytes": pinned["bytes"], "sha256": pinned["sha256"]}
            for key in ("path", "bytes", "sha256"):
                if key in entry and (type(entry[key]) is not type(expected_artifact[key])
                                     or entry[key] != expected_artifact[key]):
                    raise CandidateSubmissionFailure(f"{route_id}/{role}: explicit {key} differs from the public manifest")
            normalized_artifacts[role] = expected_artifact
            rel = Path(member)
            if rel.is_absolute() or ".." in rel.parts or not member.startswith("DATA_MATERIALS_CLOUD/"):
                raise v2.InfraError("pinned public source path is unsafe")
            source = input_root / rel
            cursor = input_root
            for part in rel.parts:
                cursor = cursor / part
                if cursor.is_symlink():
                    raise v2.InfraError("public source member path contains a symlink")
            try:
                actual = source.read_bytes()
            except OSError as exc:
                raise v2.InfraError(f"pinned public source member is unavailable: {member}") from exc
            if len(actual) != pinned["bytes"] or hashlib.sha256(actual).hexdigest() != pinned["sha256"]:
                raise v2.InfraError(f"mounted public source member fails its pinned integrity check: {member}")
            bound[route_id][role] = source
        normalized_rows.append({"id": route_id, "artifacts": normalized_artifacts})
    if set(bound) != ROUTE_IDS:
        raise CandidateSubmissionFailure("historical route inventory is incomplete")
    expected_maps = {
        "M2": [0,1,2,3], "M3": [0,1,2,3], "M14": [0,1,3,2],
        "M19": [0,3,1,2,4,5,6], "M29": [5,0,1,4,2,3,6,7,8,9]}
    if manifest.get("canonical_to_source_indices") != expected_maps:
        raise v2.InfraError("public canonical atom maps differ from the reviewed source mapping")
    if any(sorted(value) != list(range(len(v2.SPECIES[mol]))) for mol, value in expected_maps.items()):
        raise v2.InfraError("reviewed canonical atom mapping is invalid")
    normalized["records"] = normalized_rows
    return bound, manifest

def _write_xyz_segment(source: Path, first: int, last: int, target: Path) -> None:
    lines = source.read_text(encoding="utf-8", errors="strict").splitlines(keepends=True)
    starts, i = [], 0
    while i < len(lines):
        if not lines[i].strip():
            i += 1
            continue
        try:
            count = int(lines[i].strip())
        except ValueError as exc:
            raise CandidateSubmissionFailure("historical XYZ has a malformed frame count") from exc
        if count < 1 or i + count + 1 >= len(lines):
            raise CandidateSubmissionFailure("historical XYZ has a truncated frame")
        starts.append((i, i + count + 2))
        i += count + 2
    if last >= len(starts) or first < 0 or first > last:
        raise CandidateSubmissionFailure("historical XYZ selected frame segment is out of bounds")
    target.write_text("".join("".join(lines[a:b]) for a, b in starts[first:last + 1]), encoding="utf-8")

def _normalize_historical_sources(bound: dict, temp: Path) -> dict:
    normalized = {}
    for route_id, roles in bound.items():
        target = temp / route_id.replace("/", "__")
        target.mkdir(parents=True)
        input_path, output_path, xyz_path = roles["input"], roles["output"], roles["trajectory"]
        try:
            input_text = input_path.read_text(encoding="utf-8", errors="strict")
            output_text = output_path.read_text(encoding="utf-8", errors="replace")
            output_run, run_count = v2._select_last_output_run(output_text)
            segment = v2._select_last_run_xyz_segment(output_run, xyz_path)
        except (OSError, UnicodeError, ValueError, TypeError) as exc:
            raise CandidateSubmissionFailure(f"{route_id}: historical last-run/XYZ binding failed: {exc}") from exc
        if run_count < 1:
            raise CandidateSubmissionFailure(f"{route_id}: historical output has no complete CP2K run")
        ip, op, xp = target / "input.inp", target / "cp2k.out", target / "trajectory.xyz"
        ip.write_text(input_text, encoding="utf-8")
        op.write_text(output_run, encoding="utf-8")
        _write_xyz_segment(xyz_path, segment["start_zero_based"], segment["end_zero_based_inclusive"], xp)
        normalized[route_id] = {"input": ip, "output": op, "trajectory": xp}
    return normalized

def verify(app: Path, tests: Path):
    # Validate grader-owned reference/profile inputs before inspecting candidate
    # provenance or applying any scientific classification. Corrupt or missing
    # reference material is an environment error in every evidence mode.
    try:
        science._require_trusted_science_inputs(tests)
    except v2.InfraError as exc:
        return {"case_id": v2.CASE_ID, "contract_version": CONTRACT_VERSION,
                "status": "ENV_INVALID", "scientific_result_status": "trusted_input_or_verifier_error",
                "problems": [str(exc)]}, 2
    final = app / "final"
    try:
        provenance = json.loads((final / "provenance.json").read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        return {"case_id": v2.CASE_ID, "contract_version": CONTRACT_VERSION, "status": "FAIL",
                "scientific_result_status": "candidate_provenance_missing_or_invalid", "problems": [str(exc)]}, 1
    if not isinstance(provenance, dict):
        return {"case_id": v2.CASE_ID, "contract_version": CONTRACT_VERSION, "status": "FAIL",
                "scientific_result_status": "candidate_provenance_invalid", "problems": ["provenance root must be object"]}, 1
    mode = (provenance["evidence_mode"] if "evidence_mode" in provenance
            else "candidate_historical_native_results")
    if mode == "historical_oracle_archive":
        if os.environ.get("CCB_ANSWER_MODE") != "oracle":
            return {"case_id": v2.CASE_ID, "contract_version": CONTRACT_VERSION,
                    "status": "FAIL", "scientific_result_status": "candidate_historical_analysis_invalid",
                    "problems": ["Oracle archive evidence mode is reserved for the official runner Oracle"]}, 1
        report, code = science.verify(app, tests)
        report["contract_version"] = CONTRACT_VERSION
        return report, code
    report = {"case_id": v2.CASE_ID, "contract_version": CONTRACT_VERSION, "status": "FAIL",
              "evidence_mode": "candidate_historical_native_results", "scientific_result_status": "candidate_historical_analysis_invalid",
              "checks_passed": [], "problems": [], "pending_science_reviews": [],
              "limits": ["Historical launcher and scheduler evidence are unavailable.",
                         "This result is Agent analysis of pinned historical data, not fresh execution.",
                         "Minimum and curvature are outside v5 scope."]}
    try:
        if mode == "candidate_native_results":
            # Keep the original v4 strict one-allocation scheduler-receipt branch intact.
            report, code = science.verify(app, tests)
            report["contract_version"] = CONTRACT_VERSION
            return report, code
        if mode != "candidate_historical_native_results":
            raise CandidateSubmissionFailure("unsupported v5 evidence mode")
        for name in ("comparison.csv", "scientific-summary.json", "report.md"):
            _safe_final_file(final, name)
        provenance_path = _safe_final_file(final, "provenance.json")
        provenance = json.loads(provenance_path.read_text(encoding="utf-8"))
        bound, manifest = _validate_agent_manifest(provenance, final, app, tests)
        science._require_trusted_science_inputs(tests)
        with tempfile.TemporaryDirectory(prefix="case06-v5-historical-native-") as tempdir:
            work = Path(tempdir)
            normalized = _normalize_historical_sources(bound, work / "native")
            analysis_final = work / "final"
            analysis_final.mkdir()
            for name in ("comparison.csv", "scientific-summary.json", "report.md"):
                shutil.copyfile(_safe_final_file(final, name), analysis_final / name)
            for route_id, files in normalized.items():
                route_dir = analysis_final / "geometries" / route_id
                route_dir.mkdir(parents=True)
                for role, src in files.items():
                    shutil.copyfile(src, route_dir / {"input":"input.inp","output":"cp2k.out","trajectory":"trajectory.xyz"}[role])
            maps = manifest["canonical_to_source_indices"]
            result = science._evaluate_candidate_native(provenance, analysis_final, tests,
                    prebound=normalized, source_atom_maps=maps, native_originals=bound)
        report.update(result)
        report["checks_passed"].extend([
            "26 public historical native routes matched pinned member paths, sizes, and hashes",
            "last complete CP2K invocation and unique energy-bound XYZ segment checked for all routes",
            "36 SI rows, 13 paired method deltas, and three M14 remedy bonds passed frozen science checks",
            "historical launcher and scheduler fields remain unavailable; no fresh execution claimed",
            "minimum-curvature claims excluded"])
        report["candidate_provenance_status"] = "PUBLIC_HISTORICAL_SOURCE_HASH_BOUND"
        report["scheduler_provenance_status"] = "NOT_AVAILABLE_HISTORICAL"
        report.update(status="PASS", scientific_result_status="v5_agent_historical_analysis_pass")
        return report, 0
    except CandidateSubmissionFailure as exc:
        report["problems"].append(str(exc)); return report, 1
    except v3.V3ClaimFailure as exc:
        report["scientific_result_status"] = "candidate_science_failed"
        report["problems"].append(str(exc)); return report, 1
    except v3.V3ClaimUnverified as exc:
        report["status"] = "UNVERIFIED"; report["scientific_result_status"] = "candidate_science_unverified"
        report["pending_science_reviews"].append(str(exc)); return report, 2
    except v2.InfraError as exc:
        report["status"] = "ENV_INVALID"; report["scientific_result_status"] = "trusted_input_or_verifier_error"
        report["problems"].append(str(exc)); return report, 2
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError, KeyError, TypeError) as exc:
        report["problems"].append(str(exc)); return report, 1

def main():
    app = Path(os.environ.get("APP", "/app")).resolve()
    tests = Path(os.environ.get("TESTS", Path(__file__).resolve().parent)).resolve()
    logs = Path(os.environ.get("LOGS", "/logs/verifier")).resolve()
    logs.mkdir(parents=True, exist_ok=True)
    (logs / "reward.txt").unlink(missing_ok=True)
    try:
        report, code = verify(app, tests)
    except v2.InfraError as exc:
        print(f"grader infrastructure error: {exc}", file=sys.stderr)
        return 2
    except (OSError, UnicodeError, ValueError, KeyError, TypeError) as exc:
        print(f"grader infrastructure error: {exc}", file=sys.stderr)
        return 2
    (logs / "verification.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"contract_version": CONTRACT_VERSION, "status": report["status"],
                      "scientific_result_status": report["scientific_result_status"],
                      "problems": report.get("problems", [])}, indent=2))
    if code == 0 and report["status"] == "PASS":
        (logs / "reward.txt").write_text("1\n", encoding="utf-8")
        return 0
    if code == 1 and report["status"] == "FAIL":
        (logs / "reward.txt").write_text("0\n", encoding="utf-8")
        return 1
    return 2

if __name__ == "__main__":
    raise SystemExit(main())
