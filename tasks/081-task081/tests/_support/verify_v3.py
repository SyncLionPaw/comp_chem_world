#!/usr/bin/env python3
"""Versioned Case06 v3 verifier; v2 verifier remains unchanged."""
from __future__ import annotations

import hashlib
import json
import csv
import math
import os
import re
import sys
import tempfile
from pathlib import Path

try:
    import verify_v2 as v2
    import science_core_v3
except ImportError:
    from . import verify_v2 as v2
    from . import science_core_v3

CONTRACT_VERSION = "case06-v3"
RECORD_COUNT = 26
CONTEXT_SCHEMA = "case12-case06-runner-context/v1"
CONTEXT_CONTRACT = "case06-v3"
CONTEXT_PATH = "/trusted/case12-case06-context.json"
PACKAGE_ROOT_PATH = "/trusted/case12-package"
RECEIPT_PATH = "/trusted/case12-case06-receipt.json"
AGENT_CP2K_VERSION = "2024.3"
AGENT_CP2K_BINARY_SHA256 = "c75789c5fd95107e97097f875ef3a6b1589cccf5400cdaf9b6d44ba8e1aca954"
AGENT_LAUNCHER_SHA256 = "44bfd78e4526d8ba9db281cc8ddd57947fffcdad3f3f0e413e7f960c0018a4f8"
AGENT_DATA_MANIFEST_SHA256 = "ccb775f69a93a92ca84d5b3c6cc9af07398c914c9004e6c8b7f00f5a3c858c9a"
PACKAGE_PROFILE_FILES = {
    'task.toml',
    'instruction.md',
    'instruction.zh-CN.md',
    'solution/solve.sh',
    'tests/test.sh',
    'tests/verify.py',
    'tests/refs.json',
    'tests/_support/verify_v2.py',
    'tests/_support/verify_v3.py',
    'tests/_support/verify_v5_science.py',
    'tests/_support/science_profile.py',
    'tests/_support/science_core_v3.py',
    'tests/_support/native_science.py',
    'tests/_support/scientific_summary.py',
    'tests/_support/report_claims_v51.py',
    'tests/_support/science_profile.json',
    'tests/_support/science-profile-policy.md',
    'tests/_support/historical-source-profile.json',
    'tests/_support/case06_contract_v3.json',
    'tests/_support/case06-v5-public-native-source-manifest-v1.json',
    'environment/assets/inputs/ct2c00144_si_001.pdf',
    'environment/assets/inputs/hehn2022_main.pdf',
    'environment/assets/inputs/case06-v5-agent-historical-results-contract-v1.json',
    'environment/assets/inputs/case06-v5-public-native-source-manifest-v1.json'
}


class V3ClaimFailure(ValueError):
    """A measured v3-required claim is outside its frozen scientific rule."""


class V3ClaimUnverified(ValueError):
    """Required evidence is missing or cannot resolve a frozen comparison."""


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _validate_runner_context(context: object, mode: object, tests: Path,
                             package_root: Path | None = None) -> dict:
    if not isinstance(context, dict):
        raise v2.InfraError("host runner context is not a JSON object")
    if context.get("schema") != CONTEXT_SCHEMA or context.get("context_schema") != CONTEXT_CONTRACT:
        raise v2.InfraError("host runner context schema mismatch")
    if context.get("task_id") != v2.CASE_ID:
        raise v2.InfraError("host runner context task identity mismatch")
    for key in ("run_id", "eval_nonce"):
        value = context.get(key)
        if not isinstance(value, str) or not value.strip():
            raise v2.InfraError(f"host runner context {key} is missing")
    if context.get("answer_mode") != mode or mode not in {"oracle", "agent"}:
        raise v2.InfraError("host answer mode disagrees with trusted runner context")
    package_root = (package_root or tests.parent).resolve()
    if context.get("task_sha256") != _sha256(package_root / "task.toml"):
        raise v2.InfraError("host runner context task SHA-256 mismatch")
    if context.get("instruction_sha256") != _sha256(package_root / "instruction.md"):
        raise v2.InfraError("host runner context instruction SHA-256 mismatch")
    profile = package_root / "tests/_support/package-profile-v3.json"
    if not profile.is_file() or context.get("package_profile_sha256") != _sha256(profile):
        raise v2.InfraError("host runner context package-profile SHA-256 mismatch")
    try:
        profile_data = json.loads(profile.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise v2.InfraError(f"package profile is unavailable: {exc}") from exc
    if not isinstance(profile_data, dict) or profile_data.get("schema") != "case06-v3-package-profile/v1":
        raise v2.InfraError("package-profile schema mismatch")
    files = profile_data.get("files")
    if not isinstance(files, dict) or set(files) != PACKAGE_PROFILE_FILES:
        raise v2.InfraError("package-profile source inventory mismatch")
    for relpath, expected_hash in files.items():
        source = (package_root / relpath).resolve()
        if not source.is_relative_to(package_root) or not source.is_file():
            raise v2.InfraError(f"package-profile source path is invalid: {relpath}")
        if not isinstance(expected_hash, str) or _sha256(source) != expected_hash:
            raise v2.InfraError(f"package-profile source SHA-256 mismatch: {relpath}")
        if relpath.startswith("tests/"):
            mounted_source = (tests / relpath[len("tests/"):]).resolve()
            if not mounted_source.is_file() or _sha256(mounted_source) != expected_hash:
                raise v2.InfraError(f"grader /tests mount differs from trusted package source: {relpath}")
    image_id = context.get("image_id")
    if not isinstance(image_id, str) or not image_id.startswith("sha256:"):
        raise v2.InfraError("host runner context image identity is malformed")
    expected_image_id = os.environ.get("CCB_IMAGE_ID")
    if expected_image_id and image_id != expected_image_id:
        raise v2.InfraError("host runner context image identity mismatch")
    receipt_path = context.get("receipt_path")
    if mode == "oracle" and receipt_path is not None:
        raise v2.InfraError("Oracle context must not contain an Agent receipt path")
    if mode == "agent" and receipt_path != RECEIPT_PATH:
        raise v2.InfraError("Agent context receipt path is not the fixed host mount")
    return context


def _load_runner_context(tests: Path, mode: object) -> dict:
    path = os.environ.get("CCB_CASE12_CASE06_CONTEXT_PATH", CONTEXT_PATH)
    if path != CONTEXT_PATH:
        raise v2.InfraError("host runner context path is not the fixed trusted mount")
    package_root = os.environ.get("CCB_CASE12_PACKAGE_ROOT", PACKAGE_ROOT_PATH)
    if package_root != PACKAGE_ROOT_PATH:
        raise v2.InfraError("trusted package root path is not the fixed host mount")
    try:
        context = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise v2.InfraError(f"trusted host runner context unavailable: {exc}") from exc
    return _validate_runner_context(context, mode, tests, Path(package_root))


def _expected_agent_routes() -> set[str]:
    routes = set(v2.EXPECTED_RECORDS)
    routes.add("M14/ES/stda-pbe0-tzvp-aex0.25-remedy")
    return routes


def _is_sha256(value: object) -> bool:
    return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) is not None


def _agent_artifact_path(route_id: str, filename: str) -> str:
    return f"geometries/{route_id}/{filename}"


def _expected_resource_profile(route_id: str) -> tuple[str, int, int]:
    if "/stda-" not in route_id:
        return "case06-v3-9mpi-36000m/v1", 9, 36000
    if route_id.startswith("M3/"):
        return "case06-v3-36mpi-140000m/v1", 36, 140000
    if route_id.startswith("M14/"):
        return "case06-v3-32mpi-128000m/v1", 32, 128000
    return "case06-v3-16mpi-64000m/v1", 16, 64000


def _check_alloc_tres(text: str, route_id: str) -> None:
    profile_id, ranks, memory_mib = _expected_resource_profile(route_id)
    parts = dict(item.split("=", 1) for item in text.split(",") if "=" in item)
    if (parts.get("cpu") != str(ranks) or parts.get("mem") != f"{memory_mib}M"
            or parts.get("node") != "1"):
        raise v2.InfraError(f"{route_id}: Slurm allocation does not match {profile_id}")


def _receipt_artifact(job: dict, manifest_name: str, expected_path: str,
                      final: Path, label: str) -> Path:
    rows = job.get(manifest_name)
    if not isinstance(rows, list):
        raise v2.InfraError(f"{label}: receipt {manifest_name} is not a list")
    selected = [row for row in rows if isinstance(row, dict) and row.get("artifact_path") == expected_path]
    if len(selected) != 1:
        raise v2.InfraError(f"{label}: receipt must bind exactly one {expected_path}")
    row = selected[0]
    if row.get("path") != expected_path or row.get("artifact_path") != expected_path:
        raise v2.InfraError(f"{label}: receipt artifact path fields disagree")
    host_path = row.get("host_path")
    if (not isinstance(host_path, str) or not host_path or Path(host_path).is_absolute()
            or ".." in Path(host_path).parts or "\\" in host_path or "\x00" in host_path):
        raise v2.InfraError(f"{label}: receipt host path is malformed")
    if not _is_sha256(row.get("sha256")) or type(row.get("bytes")) is not int or row["bytes"] < 0:
        raise v2.InfraError(f"{label}: receipt artifact size/hash is malformed")
    rel = Path(expected_path)
    if rel.is_absolute() or ".." in rel.parts or "\x00" in expected_path:
        raise v2.InfraError(f"{label}: expected host artifact path is unsafe")
    final_root = final.resolve()
    if final.is_symlink():
        raise V3ClaimFailure(f"{label}: candidate final directory must not be a symlink")
    artifact = final
    for part in rel.parts:
        artifact = artifact / part
        if artifact.is_symlink():
            raise V3ClaimFailure(f"{label}: candidate artifact path contains a symlink")
    artifact = artifact.resolve()
    if not artifact.is_relative_to(final_root):
        raise v2.InfraError(f"{label}: expected host artifact resolves outside final/")
    if not artifact.is_file():
        raise V3ClaimFailure(f"{label}: candidate did not materialize a host-collected artifact")
    actual_size = artifact.stat().st_size
    if actual_size != row["bytes"] or _sha256(artifact) != row["sha256"]:
        raise V3ClaimFailure(f"{label}: submitted artifact differs from the host-collected receipt")
    return artifact


def _select_agent_xyz_segment(output_text: str, trajectory: Path) -> dict:
    """Bind complete fresh-run optimizer energies and step IDs to its XYZ frames."""
    tail = science_core_v3._last_invocation(output_text)
    energies, step_ids = science_core_v3.optimizer_sequence(tail)
    lines = trajectory.read_text(encoding="utf-8", errors="strict").splitlines()
    frame_energies, frame_ids = [], []
    i = 0
    while i < len(lines):
        if not lines[i].strip():
            i += 1
            continue
        count = int(lines[i].strip())
        if count < 1 or i + count + 1 >= len(lines):
            raise ValueError("trajectory has an incomplete XYZ frame")
        comment = lines[i + 1]
        energy = re.search(r"(?:^|[,\s])E\s*=\s*([-+\d.EeDd]+)", comment)
        frame_id = re.search(r"(?:^|[,\s])i\s*=\s*(\d+)", comment, re.I)
        frame_energies.append(float(energy.group(1).replace("D", "E").replace("d", "e"))
                              if energy else None)
        frame_ids.append(int(frame_id.group(1)) if frame_id else None)
        i += count + 2
    expected_ids = list(range(1, len(step_ids) + 1))
    target = energies[1:]
    matches = []
    for offset in range(len(frame_energies) - len(step_ids) + 1):
        ids = frame_ids[offset:offset + len(step_ids)]
        values = frame_energies[offset:offset + len(step_ids)]
        errors = [abs(a - b) if b is not None else math.inf for a, b in zip(target, values)]
        if ids == expected_ids and all(math.isfinite(error) and error <= 5.1e-11 for error in errors):
            matches.append((offset, max(errors, default=0.0)))
    if len(matches) != 1:
        raise ValueError(f"complete fresh optimizer sequence does not identify one XYZ segment (matches={len(matches)})")
    first, max_error = matches[0]
    return {"start_zero_based": first, "end_zero_based_inclusive": first + len(step_ids) - 1,
            "count": len(step_ids), "last_invocation_energy_count": len(energies),
            "last_invocation_optimizer_step_ids": step_ids,
            "max_energy_rounding_delta_hartree": max_error,
            "method": "fresh-invocation-native-energies[1:]-and-step-ids-to-XYZ/v1"}


def _check_report_minimum_claims(report_text: str) -> None:
    positive = re.compile(r"\b(?:PASS(?:ED)?|positive|certified|proven|established|demonstrated)\b", re.I)
    negated = re.compile(r"\b(?:no|not|never|without|cannot|can't|isn't|aren't|doesn't|don't)\b", re.I)
    for line in report_text.splitlines():
        if not re.search(r"\b(?:minimum|curvature)\b", line, re.I):
            continue
        claim = positive.search(line)
        if claim and not negated.search(line[:claim.start()]):
            raise V3ClaimFailure("Agent report makes an unsupported minimum/curvature PASS claim")


def _validate_agent_receipt(receipt: object, context: dict, final: Path) -> dict[str, dict[str, Path]]:
    """Validate host-owned execution receipt and bind candidate copies to its artifacts."""
    if not isinstance(receipt, dict) or receipt.get("schema") != "case12-case06-hpc-receipt/v1":
        raise v2.InfraError("trusted Agent receipt schema mismatch")
    required_receipt = {"schema", "task_id", "run_id", "eval_nonce", "answer_mode", "task_sha256",
                        "instruction_sha256", "package_profile_sha256", "image_id", "fixture", "jobs"}
    if set(receipt) != required_receipt:
        raise v2.InfraError("trusted Agent receipt has unexpected or missing top-level fields")
    for key in ("task_id", "run_id", "eval_nonce", "answer_mode", "task_sha256",
                "instruction_sha256", "package_profile_sha256", "image_id"):
        if receipt.get(key) != context.get(key):
            raise v2.InfraError(f"trusted Agent receipt does not match runner context: {key}")
    if receipt.get("answer_mode") != "agent":
        raise v2.InfraError("trusted Agent receipt has a non-Agent answer mode")
    if receipt.get("fixture") is not False:
        raise v2.InfraError("engineering fixtures cannot establish a scientific Agent result")
    jobs = receipt.get("jobs")
    expected = _expected_agent_routes()
    if not isinstance(jobs, list) or len(jobs) != len(expected):
        raise v2.InfraError(f"trusted Agent receipt must contain exactly {len(expected)} route jobs")
    by_route = {}
    job_ids, request_ids = set(), set()
    for job in jobs:
        if not isinstance(job, dict):
            raise v2.InfraError("trusted Agent receipt contains a malformed job")
        required_job = {"route_id", "request_id", "job_id", "submitted_at_utc", "program",
                        "data_manifest_sha256", "source_template_sha256", "template_transform_id",
                        "resource_profile_id", "input_manifest", "output_manifest", "accounting", "terminal_at_utc",
                        "wrapper_sha256", "terminal_event_sha256"}
        if set(job) != required_job:
            raise v2.InfraError("trusted Agent route receipt has unexpected or missing fields")
        route_id = job.get("route_id")
        if not isinstance(route_id, str) or route_id not in expected or route_id in by_route:
            raise v2.InfraError("trusted Agent receipt has an unknown or duplicate route id")
        for key in ("request_id", "job_id", "submitted_at_utc", "terminal_at_utc"):
            if not isinstance(job.get(key), str) or not job[key].strip():
                raise v2.InfraError(f"{route_id}: receipt {key} is missing")
        if job["request_id"] in request_ids or job["job_id"] in job_ids:
            raise v2.InfraError("trusted Agent receipt reuses a request id or scheduler job id")
        request_ids.add(job["request_id"])
        job_ids.add(job["job_id"])
        if not re.fullmatch(r"[0-9a-f]{32}", job["request_id"]):
            raise v2.InfraError(f"{route_id}: receipt request_id is malformed")
        if not re.fullmatch(r"[0-9]{1,24}", job["job_id"]):
            raise v2.InfraError(f"{route_id}: receipt scheduler job id is malformed")
        for key in ("source_template_sha256", "data_manifest_sha256", "wrapper_sha256",
                    "terminal_event_sha256"):
            if not _is_sha256(job.get(key)):
                raise v2.InfraError(f"{route_id}: receipt {key} is malformed")
        if job["data_manifest_sha256"] != AGENT_DATA_MANIFEST_SHA256:
            raise v2.InfraError(f"{route_id}: CP2K basis/potential data differs from the reviewed pin")
        if job.get("template_transform_id") != "case12-case06-route-template-transforms/v2-uzh-explicit-q":
            raise v2.InfraError(f"{route_id}: host template transform is not the reviewed version")
        program = job.get("program")
        if (not isinstance(program, dict) or set(program) != {"name", "version", "binary_sha256", "launcher_sha256"}
                or any(not isinstance(program.get(key), str) or not program[key].strip()
                       for key in ("name", "version"))):
            raise v2.InfraError(f"{route_id}: CP2K program identity is missing")
        if (program.get("name") != "CP2K" or program.get("version") != AGENT_CP2K_VERSION
                or program.get("binary_sha256") != AGENT_CP2K_BINARY_SHA256):
            raise v2.InfraError(f"{route_id}: CP2K identity differs from the reviewed host pin")
        if not _is_sha256(program.get("binary_sha256")) or not _is_sha256(program.get("launcher_sha256")):
            raise v2.InfraError(f"{route_id}: CP2K binary/launcher identity is malformed")
        if program.get("launcher_sha256") != AGENT_LAUNCHER_SHA256:
            raise v2.InfraError(f"{route_id}: host launcher differs from the reviewed execution pin")
        accounting = job.get("accounting")
        if not isinstance(accounting, dict) or set(accounting) != {
                "state", "exit_code", "alloc_tres", "cpu_time", "elapsed", "raw_sha256"}:
            raise v2.InfraError(f"{route_id}: trusted Slurm accounting is missing")
        exit_ok = accounting.get("exit_code") == "0:0" or (
            type(accounting.get("exit_code")) is int and accounting.get("exit_code") == 0)
        if (accounting.get("state") != "COMPLETED" or not exit_ok
                or not all(isinstance(accounting.get(key), str) and accounting[key].strip()
                           for key in ("alloc_tres", "cpu_time", "elapsed"))
                or not _is_sha256(accounting.get("raw_sha256"))):
            raise v2.InfraError(f"{route_id}: host receipt does not establish a successful CP2K job")
        expected_resource, _ranks, _memory = _expected_resource_profile(route_id)
        if job.get("resource_profile_id") != expected_resource:
            raise v2.InfraError(f"{route_id}: host resource profile differs from the reviewed route allocation")
        _check_alloc_tres(accounting["alloc_tres"], route_id)
        artifacts = {
            "input": _receipt_artifact(job, "input_manifest", _agent_artifact_path(route_id, "input.inp"),
                                       final, f"{route_id} input"),
            "output": _receipt_artifact(job, "output_manifest", _agent_artifact_path(route_id, "cp2k.out"),
                                        final, f"{route_id} output"),
            "trajectory": _receipt_artifact(job, "output_manifest", _agent_artifact_path(route_id, "trajectory.xyz"),
                                             final, f"{route_id} trajectory"),
        }
        if len(job["input_manifest"]) != 1 or len(job["output_manifest"]) != 2:
            raise v2.InfraError(f"{route_id}: receipt must bind one input and two native output files")
        terminal_event = {
            "route_id": route_id, "job_id": job["job_id"], "program": program,
            "data_manifest_sha256": job["data_manifest_sha256"],
            "source_template_sha256": job["source_template_sha256"],
            "template_transform_id": job["template_transform_id"],
            "resource_profile_id": job["resource_profile_id"],
            "input_manifest": job["input_manifest"], "output_manifest": job["output_manifest"],
            "wrapper_sha256": job["wrapper_sha256"],
            "accounting": {key: accounting[key] for key in
                           ("state", "exit_code", "alloc_tres", "cpu_time", "elapsed", "raw_sha256")},
        }
        terminal_hash = hashlib.sha256(json.dumps(
            terminal_event, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
        if terminal_hash != job["terminal_event_sha256"]:
            raise v2.InfraError(f"{route_id}: terminal event digest does not bind the receipt artifacts")
        by_route[route_id] = artifacts
    if set(by_route) != expected:
        missing = sorted(expected - set(by_route))
        raise v2.InfraError(f"trusted Agent receipt route inventory is incomplete: {missing}")
    return by_route


def _read(path: Path) -> str:
    return path.read_bytes().decode("utf-8", errors="strict")


def _xyz_frame_coordinate_half_units_pm(path: Path, frame_index: int) -> list[tuple[float, float, float]]:
    """Bound XYZ decimal rounding for the selected frame, not an unrelated tail frame."""
    lines = _read(path).splitlines()
    number = re.compile(r"^[+-]?(?:(?:\d+(?:\.(\d*))?)|(?:\.(\d+)))(?:[Ee]([+-]?\d+))?$")
    frames = []
    i = 0
    while i < len(lines):
        if not lines[i].strip():
            i += 1
            continue
        try:
            count = int(lines[i].strip())
        except ValueError as exc:
            raise ValueError("invalid XYZ frame atom count while checking precision") from exc
        if count <= 0 or i + count + 2 > len(lines):
            raise ValueError("truncated XYZ while checking selected-frame precision")
        rows = []
        for row in lines[i + 2:i + 2 + count]:
            fields = row.split()
            if len(fields) < 4:
                raise ValueError("malformed XYZ coordinate while checking precision")
            axes = []
            for token in fields[1:4]:
                match = number.fullmatch(token)
                if not match:
                    raise ValueError("unsupported XYZ coordinate token while checking precision")
                decimals = len(match.group(1) if match.group(1) is not None else match.group(2) or "")
                exponent = int(match.group(3) or 0)
                bound = 0.5 * 10.0 ** (exponent - decimals) * 100.0
                if not math.isfinite(bound):
                    raise ValueError("nonfinite XYZ coordinate precision bound")
                axes.append(bound)
            rows.append(tuple(axes))
        frames.append(rows)
        i += count + 2
    if not 0 <= frame_index < len(frames):
        raise ValueError("selected XYZ precision frame index is out of range")
    return frames[frame_index]


def _safe_final_file(final: Path, relative: object, label: str) -> Path:
    if not isinstance(relative, str) or not relative or Path(relative).is_absolute():
        raise v2.InfraError(f"{label}: invalid relative artifact path")
    path = (final / relative).resolve()
    if not path.is_relative_to(final.resolve()) or not path.is_file():
        raise v2.InfraError(f"{label}: missing or out-of-final artifact")
    return path


def _historical_records(final: Path, provenance: dict) -> list[dict]:
    if provenance.get("evidence_mode") != "historical_oracle_archive":
        raise v2.InfraError("Oracle v3 requires the pinned historical archive adapter output")
    rows = provenance.get("calculations")
    remedies = provenance.get("remedy_calculations")
    if not isinstance(rows, list) or not isinstance(remedies, list):
        raise v2.InfraError("historical source provenance lacks calculation records")
    records = rows + remedies
    if len(records) != RECORD_COUNT or len({r.get("id") for r in records}) != RECORD_COUNT:
        raise v2.InfraError("historical source provenance does not contain exactly 26 unique route records")
    return records


def _evaluate_historical(final: Path, provenance: dict) -> list[dict]:
    results = []
    for rec in _historical_records(final, provenance):
        mid = rec.get("id")
        pins = rec.get("source_member_sha256")
        if not isinstance(pins, dict):
            raise v2.InfraError(f"{mid}: source-member pins are absent")
        paths = {}
        for role in ("input", "output"):
            pin = pins.get(role)
            if not isinstance(pin, dict):
                raise v2.InfraError(f"{mid}: missing pinned {role}")
            path = _safe_final_file(final, pin.get("path"), f"{mid} {role}")
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            if digest != pin.get("sha256"):
                raise v2.InfraError(f"{mid}: {role} SHA-256 mismatch")
            paths[role] = path
        result = science_core_v3.evaluate_optimizer_run(mid, _read(paths["input"]), _read(paths["output"]))
        result["input_sha256"] = hashlib.sha256(paths["input"].read_bytes()).hexdigest()
        result["output_sha256"] = hashlib.sha256(paths["output"].read_bytes()).hexdigest()
        result["source_scope"] = rec.get("source_correspondence_scope")
        results.append(result)
    return results


def _require_base_science_claims(base: dict, final: Path, tests: Path) -> dict:
    """Reject a base UNVERIFIED caused by any v3-required scientific component."""
    _check_base_science_gate(base)
    refs = v2.load_refs(tests)
    with (final / "comparison.csv").open(newline="", encoding="utf-8-sig") as stream:
        rows = list(csv.DictReader(stream))
    values = {}
    for row in rows:
        try:
            key = (row["molecule"], row["label"].lower())
            route = row["route"]
            distance = float(row["computed_mean_pm"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("comparison.csv has a malformed geometry row") from exc
        if not math.isfinite(distance) or (key, route) in values:
            raise ValueError("comparison.csv has nonfinite or duplicate geometry rows")
        values[(key, route)] = distance
    pair_differences = []
    for ref in refs["items"].values():
        if ref.get("state") != "ES" or ref.get("quantity") != "bond":
            continue
        key = (ref["molecule"], ref["label"].lower())
        pbe0 = values.get((key, "pbe0-tzvp"))
        admm = values.get((key, "admm-tzvp-tzp"))
        if pbe0 is None or admm is None:
            raise ValueError(f"missing PBE0/ADMM paired geometry for {key}")
        pair_differences.append({"molecule": key[0], "label": key[1],
                                 "admm_minus_pbe0_pm": admm - pbe0})
    if len(pair_differences) != 13:
        raise ValueError("expected 13 recomputed ADMM-PBE0 paired geometry differences")

    provenance = json.loads((final / "provenance.json").read_text(encoding="utf-8"))
    # The v2 SI gate uses the trajectory tail's printed-coordinate precision.
    # Confirm each selected baseline endpoint has the same per-coordinate
    # serialization bound before relying on those decisions in the v3 contract.
    for rec in provenance.get("calculations", []):
        geometry_rec = rec.get("geometry", {})
        trajectory = _safe_final_file(final, geometry_rec.get("path"), f"{rec.get('id')} trajectory precision")
        frames = v2._xyz_frames(trajectory)
        selected = geometry_rec.get("selected_frame_index_zero_based")
        if type(selected) is not int or selected < 0 or selected >= len(frames):
            raise ValueError(f"{rec.get('id')}: selected endpoint unavailable for precision audit")
        selected_precision = _xyz_frame_coordinate_half_units_pm(trajectory, selected)
        tail_precision = _xyz_frame_coordinate_half_units_pm(trajectory, len(frames) - 1)
        if selected_precision != tail_precision:
            raise ValueError(f"{rec.get('id')}: selected-frame precision differs from v2 SI-gate precision basis")
    remedy = provenance.get("remedy_calculations", [])
    if len(remedy) != 1 or remedy[0].get("id") != "M14/ES/stda-pbe0-tzvp-aex0.25-remedy":
        raise ValueError("M14 remedy source record is missing or ambiguous")
    geometry = remedy[0].get("geometry", {})
    xyz = _safe_final_file(final, geometry.get("path"), "M14 remedy trajectory")
    frames = v2._xyz_frames(xyz)
    index = geometry.get("selected_frame_index_zero_based")
    if type(index) is not int or index < 0 or index >= len(frames):
        raise ValueError("M14 remedy selected geometry frame is invalid")
    profile = json.loads((tests / "_support" / "historical-source-profile.json").read_text(encoding="utf-8"))
    atoms = [frames[index][i][1:] for i in profile["canonical_atom_maps"]["M14"]]
    atom_map = profile["canonical_atom_maps"]["M14"]
    precision = _xyz_frame_coordinate_half_units_pm(xyz, index)
    expected_bonds = {"c o": (0, 1), "c cl": (0, 2), "c h": (0, 3)}
    remedy_diagnostics = {}
    for label, (i, j) in expected_bonds.items():
        ref = refs["items"][f"bond|ES|M14|{label}"]["values"]["_stda_printed_parameter_exception"]
        measured = math.dist(atoms[i], atoms[j]) * 100.0
        uncertainty = v2._bond_coordinate_uncertainty_pm("M14", label, precision, atom_map)
        _within, detail = v2.science_profile.accept_empirical_residual(
            candidate_pm=measured, published_pm=ref,
            candidate_coordinate_uncertainty_pm=uncertainty)
        if detail["decision"] == "FAIL":
            raise V3ClaimFailure(f"M14 remedy {label} SI-14 geometry FAILs the frozen 3 pm interval rule")
        if detail["decision"] != "PASS":
            raise ValueError(f"M14 remedy {label} SI-14 geometry interval is UNVERIFIED")
        remedy_diagnostics[label] = {"computed_pm": measured, "published_pm": ref,
                                     **detail}
    return {"admm_minus_pbe0_pairs": pair_differences,
            "m14_remedy_geometry": remedy_diagnostics}


def _evaluate_agent(final: Path, tests: Path, context: dict, receipt: object) -> dict:
    """Recompute v3 science only from receipt-bound host-collected native files."""
    bound = _validate_agent_receipt(receipt, context, final)
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
        if not frames or any([atom[0].capitalize() for atom in frame] != expected_species for frame in frames):
            raise V3ClaimFailure(f"{route_id}: trajectory atom order differs from the host-fixed topology")
        if route_id == "M14/ES/stda-pbe0-tzvp":
            # The native classifier cross-checks output project/input names, force frames,
            # Mulliken populations and the collected trajectory. Stage under those names.
            project = re.search(r"(?im)^\s*GLOBAL\|\s*Project name\s+(\S+)", output_text)
            inp_name = re.search(r"(?im)^\s*CP2K\|\s*Input file name\s+(\S+)", output_text)
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
                staged_input.write_bytes(files["input"].read_bytes())
                staged_output.write_bytes(files["output"].read_bytes())
                staged_xyz.write_bytes(trajectory.read_bytes())
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
            endpoint_atoms[route_id] = frames[-1]
            endpoint_precision[route_id] = _xyz_frame_coordinate_half_units_pm(trajectory, len(frames) - 1)
            endpoint_indices[route_id] = len(frames) - 1
        result["input_sha256"] = _sha256(files["input"])
        result["output_sha256"] = _sha256(files["output"])
        result["trajectory_sha256"] = _sha256(files["trajectory"])
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
            "atom_map": list(range(len(v2.SPECIES[route_id.split("/")[0]]))),
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
        raise V3ClaimFailure("Agent must provide hash-linked scientific-summary.json and report.md")
    try:
        candidate_summary = json.loads(summary_path.read_text(encoding="utf-8"))
        report_text = report_path.read_text(encoding="utf-8")
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise V3ClaimFailure(f"Agent scientific analysis deliverable is malformed: {exc}") from exc
    if not v2.scientific_summary.summaries_match(expected_summary, candidate_summary):
        raise V3ClaimFailure("Agent scientific-summary.json differs from checker-recomputed v3 statistics/status")
    summary_hash = _sha256(summary_path)
    links = re.findall(r"(?m)^Summary artifact: scientific-summary\.json / SHA256: ([0-9a-f]{64})\s*$",
                       report_text)
    if links != [summary_hash]:
        raise V3ClaimFailure("Agent report.md must contain one valid SHA-256 link to scientific-summary.json")
    required_lines = {
        "Validated optimizer routes: 26",
        "SI same-method bond gates: 36 PASS",
        "M14 default: physical_dissociation",
        "M14 remedy: 3 SI-14 geometry checks PASS",
        "Minimum/curvature status: OUT_OF_SCOPE_FOR_V3",
    }
    if not required_lines.issubset(set(report_text.splitlines())):
        raise V3ClaimFailure("Agent report.md omits one or more required v3 analysis conclusions")
    _check_report_minimum_claims(report_text)
    return {"optimizer_records": [route_results[key] for key in sorted(route_results)],
            "si_bond_residuals_count": len(geometries), "si_bond_residuals": residual_results,
            "admm_minus_pbe0_pairs": pair_differences, "m14_remedy_geometry": remedy_results,
            "m14_default_classifier": m14_classifier, "scientific_summary": candidate_summary,
            "analysis_artifacts": {"comparison_rows": len(comparison_rows),
                                   "scientific_summary_sha256": summary_hash},
            "minimum_curvature": {"status": "OUT_OF_SCOPE_FOR_V3"}}


def _check_base_science_gate(base: dict) -> None:
    if base.get("comparison_row_count") != 36:
        raise ValueError("historical verifier did not recompute all 36 SI bond rows")
    residuals = base.get("same_method_residuals")
    if not isinstance(residuals, dict) or len(residuals) != 36:
        raise ValueError("historical verifier did not emit all 36 same-method residual decisions")
    if any(not isinstance(row, dict) for row in residuals.values()):
        raise ValueError("one or more SI bond residual decisions are malformed")
    if any(row.get("decision") == "FAIL" for row in residuals.values()):
        raise V3ClaimFailure("one or more of the 36 SI bond comparisons FAIL the frozen 3 pm rule")
    if any(row.get("decision") != "PASS" for row in residuals.values()):
        raise ValueError("one or more of the 36 SI bond comparisons is not PASS")
    classifier = base.get("m14_default_native_classifier")
    if isinstance(classifier, dict) and classifier.get("status") == "FAIL":
        raise V3ClaimFailure("M14 default native classifier establishes no physical dissociation")
    if not isinstance(classifier, dict) or classifier.get("status") != "PASS":
        raise ValueError("M14 default native dissociation classifier is not PASS")


def verify(app: Path, tests: Path) -> tuple[dict, int]:
    contract_path = tests / "_support" / "case06_contract_v3.json"
    try:
        contract = json.loads(contract_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise v2.InfraError(f"v3 contract unavailable: {exc}") from exc
    if contract.get("schema") != "case06-science-contract/v3" or contract.get("contract_version") != CONTRACT_VERSION:
        raise v2.InfraError("v3 contract identity mismatch")

    report = {"case_id": v2.CASE_ID, "contract_version": CONTRACT_VERSION,
              "status": "UNVERIFIED", "scientific_result_status": "host_evidence_required",
              "checks_passed": [], "problems": [], "pending_science_reviews": [],
              "limits": [
                  "v3 assesses optimizer execution and SI geometry; it does not certify minimum curvature",
                  "Oracle historical source correspondence is not fresh per-run aEX authentication",
                  "Agent execution requires a trusted host receipt and host-launched CP2K records"]}
    mode = os.environ.get("CCB_ANSWER_MODE")
    if os.environ.get("CCB_CASE_CONTRACT_VERSION") != CONTRACT_VERSION:
        report["scientific_result_status"] = "host_did_not_select_v3_contract"
        report["pending_science_reviews"].append("host-selected contract version is not case06-v3")
        return report, 2
    context = _load_runner_context(tests, mode)
    report["runner_context"] = {key: context[key] for key in
                                 ("task_id", "run_id", "eval_nonce", "answer_mode", "image_id")}
    final = app / "final"
    if mode == "agent":
        receipt_path = os.environ.get("CCB_CASE12_CASE06_RECEIPT_PATH", RECEIPT_PATH)
        if receipt_path != RECEIPT_PATH:
            raise v2.InfraError("host Agent receipt path is not the fixed trusted mount")
        try:
            receipt = json.loads(Path(receipt_path).read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise v2.InfraError(f"trusted Agent receipt unavailable: {exc}") from exc
        try:
            agent = _evaluate_agent(final, tests, context, receipt)
        except V3ClaimFailure as exc:
            report["status"] = "FAIL"
            report["scientific_result_status"] = "agent_scientific_or_artifact_claim_failed"
            report["problems"].append(str(exc))
            return report, 1
        except V3ClaimUnverified as exc:
            report["scientific_result_status"] = "agent_required_science_unverified"
            report["pending_science_reviews"].append(str(exc))
            return report, 2
        report.update(agent)
        report["checks_passed"].extend([
            "host-owned nonce-bound receipt attests 26 successful CP2K route executions",
            "all receipt-bound native inputs/outputs/trajectories match exact submitted artifact bytes",
            "shared v3 science core accepted optimizer routes; M14 default independently classified",
            "all 36 SI bond intervals, 13 paired method deltas, and three M14 remedy bonds recomputed",
            "minimum curvature is outside the v3 contract and was not claimed"])
        report["status"] = "PASS"
        report["scientific_result_status"] = "v3_agent_fresh_execution_pass"
        return report, 0

    try:
        provenance = json.loads((final / "provenance.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise v2.InfraError(f"historical provenance unavailable: {exc}") from exc
    if provenance.get("evidence_mode") != "historical_oracle_archive":
        report["status"] = "FAIL"
        report["scientific_result_status"] = "wrong_oracle_source_mode"
        report["problems"].append("Oracle mode accepts only the fixed historical source adapter output")
        return report, 1

    # Reuse v2's independent archive/summary/SI/M14-source checks. Its UNVERIFIED
    # result is expected because v2 additionally requires minimum-curvature evidence.
    base_report, base_code = v2.verify(app, tests)
    if base_code == 1 or base_report.get("problems"):
        report["status"] = "FAIL"
        report["scientific_result_status"] = "historical_source_or_geometry_invalid"
        report["problems"].extend(base_report.get("problems", []))
        return report, 1
    if base_code != 2 or base_report.get("status") != "UNVERIFIED":
        raise v2.InfraError("unexpected v2 historical validation status")
    report["checks_passed"].append("v2 pinned archive, 36 SI rows, remedy geometry, source hashes and summary integrity")

    try:
        additional = _require_base_science_claims(base_report, final, tests)
    except V3ClaimFailure as exc:
        report["status"] = "FAIL"
        report["scientific_result_status"] = "v3_required_science_claim_failed"
        report["problems"].append(str(exc))
        return report, 1
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError, KeyError, TypeError) as exc:
        report["status"] = "UNVERIFIED"
        report["scientific_result_status"] = "required_v3_science_claim_not_established"
        report["pending_science_reviews"].append(str(exc))
        return report, 2
    report.update(additional)
    report["si_bond_residuals"] = base_report["same_method_residuals"]
    report["m14_default_classifier"] = base_report["m14_default_native_classifier"]
    report["minimum_curvature"] = {"status": "OUT_OF_SCOPE_FOR_V3",
                                    "v2_status": base_report.get("minimum_status")}
    report["checks_passed"].extend(["all 36 SI residual intervals and the M14 default physical classifier explicitly PASS",
                                    "all 13 PBE0/ADMM paired differences recomputed from route geometry rows",
                                    "M14 remedy SI-14 CO/CH/CCl geometry comparisons explicitly PASS"])

    try:
        records = _evaluate_historical(final, provenance)
    except science_core_v3.ScienceInputError as exc:
        report["status"] = "FAIL"
        report["scientific_result_status"] = "shared_science_core_rejected_archive"
        report["problems"].append(str(exc))
        return report, 1
    if len(records) != RECORD_COUNT:
        raise v2.InfraError("shared science core did not evaluate exactly 26 records")
    report["optimizer_records"] = records
    report["checks_passed"].append("shared v3 native input/output science core accepted all 26 author-source optimizer records")
    report["checks_passed"].append("v3 fixed contract explicitly excludes minimum-curvature claims; v2 minimum gate remains unchanged")
    report["historical_caveats"] = [
        "M14 default source correspondence is reviewed but per-run aEX is not echoed",
        "M14 remedy legacy VIB fails stationarity at its own center and is not transferred to the optimizer endpoint",
        "author archive has no scheduler/launcher receipt; this is a host-owned Oracle reference replay, not fresh Agent execution"]
    report["status"] = "PASS"
    report["scientific_result_status"] = "v3_historical_oracle_reference_pass"
    return report, 0


def main() -> int:
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
                      "checks_passed": report["checks_passed"], "problems": report["problems"]}, indent=2))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
