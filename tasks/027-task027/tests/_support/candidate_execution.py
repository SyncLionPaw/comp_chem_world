"""Candidate-submitted, cross-checked execution provenance for Case 07 v2.

This records evidence supplied with an attempt. It is deliberately not described
as evaluator-authenticated scheduler truth; native science is scored separately.
"""
from __future__ import annotations

import csv
import hashlib
import json
import math
from pathlib import Path, PurePosixPath
from datetime import datetime, timezone, timedelta
import re


class CandidateEvidenceError(ValueError):
    pass


def _sha(path: Path) -> str:
    if path.is_symlink() or not path.is_file():
        raise CandidateEvidenceError(f"missing or unsafe execution artifact: {path}")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _json(path: Path) -> dict:
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise CandidateEvidenceError(f"duplicate JSON key in {path.name}")
            result[key] = value
        return result
    value = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=pairs)
    if not isinstance(value, dict):
        raise CandidateEvidenceError(f"JSON artifact is not an object: {path.name}")
    return value


def _safe(root: Path, value: object) -> Path:
    if not isinstance(value, str) or not value or "\\" in value:
        raise CandidateEvidenceError("execution evidence path is missing or unsafe")
    rel = PurePosixPath(value)
    if rel.is_absolute() or rel.as_posix() != value or any(p in ("", ".", "..") for p in rel.parts):
        raise CandidateEvidenceError("execution evidence path escapes final/")
    path = root.joinpath(*rel.parts)
    cursor = root
    for part in rel.parts:
        cursor = cursor / part
        if cursor.is_symlink():
            raise CandidateEvidenceError("execution evidence path contains a symlink")
    if not path.resolve().is_relative_to(root.resolve()):
        raise CandidateEvidenceError("execution evidence path escapes final/")
    return path


def _utc(value: object) -> datetime:
    if not isinstance(value, str):
        raise CandidateEvidenceError("scheduler timestamp must be ISO-8601 UTC")
    raw = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        dt = datetime.fromisoformat(raw)
    except ValueError as exc:
        raise CandidateEvidenceError("scheduler timestamp is invalid") from exc
    if dt.tzinfo is None or dt.utcoffset() != timezone.utc.utcoffset(dt):
        raise CandidateEvidenceError("scheduler timestamp must carry UTC offset")
    return dt.astimezone(timezone.utc)


def _number(value: object, label: str, *, positive: bool = False) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise CandidateEvidenceError(f"{label} must be a number")
    result = float(value)
    if not math.isfinite(result) or result < 0 or (positive and result <= 0):
        raise CandidateEvidenceError(f"{label} must be finite and nonnegative")
    return result


def _exit_code(value: object) -> int:
    if isinstance(value, bool):
        raise CandidateEvidenceError("scheduler exit code must be an integer or Slurm code")
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        parts = value.split(":")
        if len(parts) in (1, 2) and all(part.isdigit() for part in parts):
            return int(parts[0]) or (int(parts[1]) if len(parts) == 2 else 0)
    raise CandidateEvidenceError("scheduler exit code is malformed")


def _raw_scheduler_time(value: object, offset_minutes: object) -> str | None:
    if value in (None, "", "Unknown"):
        return None
    if not isinstance(value, str):
        raise CandidateEvidenceError("raw P04 scheduler time is malformed")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise CandidateEvidenceError("raw P04 scheduler time is not ISO-8601") from exc
    if parsed.tzinfo is None:
        if type(offset_minutes) is not int:
            raise CandidateEvidenceError("naive P04 scheduler time has no pinned timezone offset")
        parsed = parsed.replace(tzinfo=timezone(timedelta(minutes=offset_minutes)))
    return parsed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _sacct_memory_mib(value: object, *, requested: bool = False, requested_cpus: int = 1) -> int | None:
    if not isinstance(value, str):
        return None
    pattern = r"(\d+(?:\.\d+)?)([KMGT])([cn]?)" if requested else r"(?:^|,)mem=(\d+(?:\.\d+)?)([KMGT])"
    match = re.search(pattern, value)
    if match is None:
        return None
    amount = float(match[1])
    result = int(amount * {"K": 1/1024, "M": 1, "G": 1024, "T": 1024**2}[match[2]])
    if requested and len(match.groups()) > 2 and match[3] == "c":
        result *= requested_cpus
    return result


def _sacct_maxrss_mib(value: object) -> int | None:
    if not isinstance(value, str):
        return None
    match = re.fullmatch(r"(\d+(?:\.\d+)?)([KMGT])", value)
    if match is None:
        return None
    return int(float(match[1]) * {"K": 1/1024, "M": 1, "G": 1024, "T": 1024**2}[match[2]])


def _crosscheck_p04_source(final: Path, job: dict, projection: dict, script: Path) -> tuple[bool, bool, dict | None, bool, bool]:
    """Cross-check a candidate v2 projection against collected P04 raw v1 bytes."""
    if projection.get("p04_source_schema") is None:
        if any(key in job for key in ("p04_scheduler_record", "p04_scheduler_record_sha256", "p04_source_schema")):
            raise CandidateEvidenceError("candidate receipt declares P04 source fields but projection omits its schema")
        return False, False, None, False, False
    if projection.get("p04_source_schema") != "compchemworld.p04-scheduler-record/v1":
        raise CandidateEvidenceError("unsupported P04 raw scheduler source schema")
    raw_path = _safe(final, job.get("p04_scheduler_record"))
    projected_source = (PurePosixPath(job.get("scheduler_record")).parent /
                        projection.get("p04_scheduler_record_path", "")).as_posix()
    if projected_source != job.get("p04_scheduler_record"):
        raise CandidateEvidenceError("candidate raw scheduler path differs from the projection's sibling binding")
    raw_hash = _sha(raw_path)
    if (raw_hash != job.get("p04_scheduler_record_sha256")
            or raw_hash != projection.get("p04_scheduler_record_sha256")):
        raise CandidateEvidenceError("raw P04 scheduler record hash mismatch")
    record = _json(raw_path)
    if (record.get("schema") != projection["p04_source_schema"]
            or record.get("case_id") != "case-07-independent-saddle-point-recomputation"
            or str(record.get("job_id")) != str(job.get("job_id"))):
        raise CandidateEvidenceError("raw P04 scheduler record has the wrong case or job binding")
    stage_dir = raw_path.parent
    allocated, measured, scheduler = record.get("allocated"), record.get("measured"), record.get("scheduler")
    if not isinstance(allocated, dict) or not isinstance(measured, dict) or not isinstance(scheduler, dict):
        raise CandidateEvidenceError("raw P04 scheduler/resource sections are malformed")
    raw = record.get("raw_sacct")
    if not isinstance(raw, dict):
        raise CandidateEvidenceError("raw P04 sacct fields are missing")
    try:
        alloc_cpus = int(raw["AllocCPUS"])
        elapsed_seconds = int(raw["ElapsedRaw"])
        exit_code, signal = (int(part) for part in str(raw["ExitCode"]).split(":", 1))
    except (KeyError, TypeError, ValueError, IndexError) as exc:
        raise CandidateEvidenceError("raw scheduler CPU/elapsed/exit fields are malformed") from exc
    alloc_mem = _sacct_memory_mib(raw.get("AllocTRES"))
    requested_mem = _sacct_memory_mib(raw.get("ReqMem"), requested=True,
                                      requested_cpus=record.get("requested", {}).get("cpus", 1))
    peak_mem = _sacct_maxrss_mib(raw.get("MaxRSS"))
    state_norm = re.split(r"[+\s]", str(raw.get("State", "")), maxsplit=1)[0].upper()
    if (record.get("state") != state_norm or record.get("exit_code") != exit_code
            or record.get("signal") != signal or allocated.get("cpus") != alloc_cpus
            or allocated.get("elapsed_seconds") != elapsed_seconds
            or allocated.get("allocated_cpu_seconds") != alloc_cpus * elapsed_seconds
            or allocated.get("memory_mib") != alloc_mem
            or record.get("requested", {}).get("memory_mib") != requested_mem
            or measured.get("peak_memory_mib") != peak_mem):
        raise CandidateEvidenceError("normalized scheduler resources/state disagree with raw sacct fields")
    no_start = (record.get("state") in {"FAILED", "CANCELLED"} and record.get("started_at_utc") is None
                and allocated.get("elapsed_seconds") == 0 and allocated.get("cpus") == 0
                and allocated.get("memory_mib") == 0 and raw.get("Start") in (None, "", "Unknown"))
    if (record.get("submitted_at_utc") != _raw_scheduler_time(raw.get("Submit"), record.get("scheduler_timezone_offset_minutes"))
            or record.get("started_at_utc") != _raw_scheduler_time(raw.get("Start"), record.get("scheduler_timezone_offset_minutes"))
            or record.get("ended_at_utc") != _raw_scheduler_time(raw.get("End"), record.get("scheduler_timezone_offset_minutes"))
            or record.get("state_raw") != raw.get("State")
            or record.get("exit_code_raw") != raw.get("ExitCode")):
        raise CandidateEvidenceError("normalized P04 scheduler facts disagree with raw sacct fields")
    try:
        expected = {
            "job_id": str(record["job_id"]), "scheduler": scheduler["name"],
            "stage_id": record["stage_id"], "candidate_stage_declaration": record["candidate_stage_declaration"],
            "allocation_id": scheduler["allocation_id"], "cpus": allocated["cpus"],
            "memory_gib": None if allocated["memory_mib"] is None else float(allocated["memory_mib"]) / 1024,
            "scratch_gib": None if measured.get("scratch_observed_bytes_peak") is None else
                float(measured["scratch_observed_bytes_peak"]) / 1024**3,
            "peak_memory_gib": None if measured.get("peak_memory_mib") is None else
                float(measured["peak_memory_mib"]) / 1024,
            "wall_seconds": allocated["elapsed_seconds"], "state": record["state"],
            "exit_code": record["exit_code_raw"], "submitted_at_utc": record["submitted_at_utc"],
            "started_at_utc": record["started_at_utc"], "ended_at_utc": record["ended_at_utc"],
            "batch_script_sha256": _sha(script), "array_job": scheduler["array_job"],
        }
    except (KeyError, TypeError, ValueError, OverflowError) as exc:
        raise CandidateEvidenceError("raw P04 fields cannot be projected into the v2 scheduler view") from exc
    for key, value in expected.items():
        if projection.get(key) != value or job.get(key) != value:
            raise CandidateEvidenceError(f"candidate receipt/projection differs from raw P04 field {key}")
    expected_outputs = record.get("expected_outputs")
    if not isinstance(expected_outputs, list):
        raise CandidateEvidenceError("raw P04 output identities are missing")
    output_by_path = {item.get("path"): item for item in expected_outputs
                      if isinstance(item, dict) and isinstance(item.get("path"), str)}
    job_id = str(record.get("job_id", ""))
    missing_native = {"orca.stdout", "orca.stderr", "native.exitcode", "native-stage-receipt.json"}
    required_logs = {"job.sbatch", f"slurm-{job_id}.out", f"slurm-{job_id}.err"}
    allocation_only_failure = (
        record.get("state") in {"FAILED", "CANCELLED"}
        and type(record.get("exit_code")) is int and record["exit_code"] != 0
        and record.get("started_at_utc") is not None
        and record.get("ended_at_utc") == record.get("started_at_utc")
        and allocated.get("elapsed_seconds") == 0
        and len(output_by_path) == len(expected_outputs)
        and required_logs <= output_by_path.keys()
        and all(output_by_path[name].get("present") is True for name in required_logs)
        and missing_native <= output_by_path.keys()
        and all(output_by_path[name].get("present") is False
                and output_by_path[name].get("bytes") is None
                and output_by_path[name].get("sha256") is None
                and output_by_path[name].get("absence_reason") == "not_observed_in_terminal_job_directory"
                for name in missing_native)
    )
    partial_cancelled_allocation = (
        record.get("state") in {"CANCELLED", "TIMEOUT"}
        and type(allocated.get("elapsed_seconds")) is int and allocated["elapsed_seconds"] > 0
        and type(allocated.get("cpus")) is int and allocated["cpus"] > 0
        and (allocated.get("memory_mib") is None
             or (type(allocated.get("memory_mib")) is int and allocated["memory_mib"] > 0))
        and record.get("started_at_utc") is not None
        and record.get("ended_at_utc") is not None
        and raw.get("Start") not in (None, "", "Unknown")
        and raw.get("End") not in (None, "", "Unknown")
        and record.get("ended_at_utc") != record.get("started_at_utc")
        and len(output_by_path) == len(expected_outputs)
        and {"job.sbatch", f"slurm-{job_id}.out", f"slurm-{job_id}.err", "orca.stdout", "orca.stderr"}
            <= output_by_path.keys()
        and all(output_by_path[name].get("present") is True for name in
            {"job.sbatch", f"slurm-{job_id}.out", f"slurm-{job_id}.err", "orca.stdout", "orca.stderr"})
        and {"native.exitcode", "native-stage-receipt.json"} <= output_by_path.keys()
        and all(output_by_path[name].get("present") is False
                and output_by_path[name].get("bytes") is None
                and output_by_path[name].get("sha256") is None
                and output_by_path[name].get("absence_reason") == "not_observed_in_terminal_job_directory"
                for name in {"native.exitcode", "native-stage-receipt.json"})
    )
    for item in expected_outputs:
        if not isinstance(item, dict) or set(item) != {"path", "present", "bytes", "sha256", "absence_reason"}:
            raise CandidateEvidenceError("raw P04 expected-output row is malformed")
        path = _safe(stage_dir, item["path"])
        if item["present"] is True:
            if (not path.is_file() or path.stat().st_size != item["bytes"] or _sha(path) != item["sha256"]):
                raise CandidateEvidenceError("collected file differs from raw P04 expected-output hash")
        elif item["present"] is False:
            never_started = (no_start and (item["path"] in missing_native
                              or re.fullmatch(r"slurm-\d+\.(?:out|err)", item["path"]))
                             and item.get("absence_reason") == "not_created_before_start")
            failed_bootstrap = (allocation_only_failure and item["path"] in missing_native
                                and item.get("absence_reason") == "not_observed_in_terminal_job_directory")
            partial_cancelled = (partial_cancelled_allocation
                and item["path"] in {"native.exitcode", "native-stage-receipt.json"}
                and item.get("absence_reason") == "not_observed_in_terminal_job_directory")
            if (not (never_started or failed_bootstrap or partial_cancelled) or item.get("bytes") is not None
                    or item.get("sha256") is not None or path.exists()):
                raise CandidateEvidenceError("raw P04 output absence is not valid for a never-started cancellation")
        else:
            raise CandidateEvidenceError("raw P04 expected-output presence flag is invalid")
    stage_receipt = None
    if not no_start and not allocation_only_failure and not partial_cancelled_allocation:
        stage_path = _safe(stage_dir, "native-stage-receipt.json")
        stage_receipt = _json(stage_path)
        if (stage_receipt.get("schema") != "compchemworld.p04-native-stage-receipt/v1"
                or str(stage_receipt.get("job_id")) != str(record.get("job_id"))
                or stage_receipt.get("stage_id") != record.get("stage_id")
                or stage_receipt.get("entry") is None):
            raise CandidateEvidenceError("raw P04 native-stage receipt has an invalid job/stage binding")
        stage_start, stage_end = _utc(stage_receipt.get("started_at_utc")), _utc(stage_receipt.get("ended_at_utc"))
        allocation_start = _utc(record.get("started_at_utc"))
        allocation_end = _utc(record.get("ended_at_utc"))
        if (stage_end <= stage_start or stage_start < allocation_start or stage_end > allocation_end):
            raise CandidateEvidenceError("raw P04 native-stage interval lies outside its scheduler allocation")
    return no_start, ((not no_start and measured.get("peak_memory_mib") is None)
                      or measured.get("scratch_observed_bytes_peak") is None
                      or allocated.get("memory_mib") is None), stage_receipt, allocation_only_failure, partial_cancelled_allocation


def _p04_provider_stage_matches(binding: dict, receipt: dict) -> bool:
    """Match a logical report role to its exact P04 provider receipt identifier."""
    logical = binding.get("stage_id")
    provider = binding.get("provider_stage_id", logical)
    return (isinstance(logical, str) and bool(logical) and isinstance(provider, str) and bool(provider)
            and provider == receipt.get("stage_id"))


def _report_stages(report: dict) -> dict[str, dict]:
    """Build the required provenance stages directly from the submitted science report."""
    expected = {}
    pilots = report.get("short_pilots")
    if not isinstance(pilots, list) or not pilots:
        raise CandidateEvidenceError("report does not declare executed short pilots")
    for index, item in enumerate(pilots, 1):
        expected[f"pilot:{index}"] = {"kind": "pilot", "files": {
            key: item.get(key) for key in ("native_input", "native_output", "geometry_path", "receipt_path")}}
    channels = report.get("channels")
    if not isinstance(channels, dict) or set(channels) != {"C1", "C2"}:
        raise CandidateEvidenceError("report must declare both scientific channels")
    for channel in ("C1", "C2"):
        screens = channels[channel].get("screening")
        if not isinstance(screens, list) or len(screens) < 3:
            raise CandidateEvidenceError(f"report must declare at least three {channel} screening stages")
        for index, item in enumerate(screens, 1):
            files = {key: item.get(key) for key in ("native_input", "native_output", "geometry_path", "receipt_path")}
            if item.get("native_engrad") is not None:
                files["native_engrad"] = item["native_engrad"]
            expected[f"screen:{channel}:{index}"] = {"kind": "screen", "channel": channel,
                "geometry_sha256": item.get("geometry_sha256"), "files": files}
    selected = report.get("selected_channel")
    if selected not in {"C1", "C2"}:
        raise CandidateEvidenceError("report has no selected channel for production provenance")
    validation = channels[selected].get("validation")
    if not isinstance(validation, dict):
        raise CandidateEvidenceError("selected channel has no validation stages")
    production = {"ts_opt": validation.get("ts_opt"), "ts_freq": validation.get("ts_freq")}
    for side in ("minus", "plus"):
        pair = validation.get(f"endpoint_{side}")
        if not isinstance(pair, dict):
            raise CandidateEvidenceError(f"selected channel lacks {side} endpoint validation")
        production[f"endpoint_{side}_opt"] = pair.get("opt")
        production[f"endpoint_{side}_freq"] = pair.get("freq")
    for role, path in production.items():
        expected[f"production:{role}"] = {"kind": "production", "channel": selected,
                                            "validation_stage": role,
                                            "stage_path": path, "files": {}}
    refinement = channels[selected].get("refinement")
    if isinstance(refinement, dict) and isinstance(refinement.get("stage_path"), str):
        expected["production:screen_refinement"] = {"kind": "production", "channel": selected,
            "validation_stage": "screen_refinement", "stage_path": refinement["stage_path"], "files": {}}
    extras = report.get("native_extra_stages", [])
    if not isinstance(extras, list):
        raise CandidateEvidenceError("native_extra_stages must be a list")
    for item in extras:
        if (not isinstance(item, dict) or set(item) != {"stage_id", "stage_path", "route", "reason", "outcome"}
                or not isinstance(item["stage_id"], str) or not item["stage_id"].strip()
                or item["stage_id"] in expected or not isinstance(item["stage_path"], str)
                or not isinstance(item["route"], str) or not item["route"].strip()
                or not isinstance(item["reason"], str) or not item["reason"].strip()
                or item["outcome"] not in {"COMPLETED", "FAILED", "CANCELLED", "RESTARTED"}):
            raise CandidateEvidenceError("native extra stage declaration is malformed or duplicated")
        expected[item["stage_id"]] = {"kind": "extension", "channel": selected,
            "route": item["route"], "reason": item["reason"], "stage_path": item["stage_path"],
            "outcome": item["outcome"], "files": {}}
    return expected


def _queue_credit(final: Path, receipt: dict, rows: dict) -> float:
    """Credit documented scheduler pending intervals after removing all running time."""
    certificates = receipt.get("queue_certificates", [])
    if not isinstance(certificates, list):
        raise CandidateEvidenceError("queue_certificates must be an array")
    covered = set()
    pending = []
    for jid, row in rows.items():
        lower = row["submitted_at"]
        upper = row["started_at"] if row["started_at"] is not None else row["ended_at"]
        if upper > lower:
            pending.append((lower, upper))
    for cert in certificates:
        if not isinstance(cert, dict) or cert.get("schema") != "case07-candidate-queue-certificate/v1":
            raise CandidateEvidenceError("queue certificate schema is malformed")
        jid = cert.get("job_id")
        if jid not in rows or jid in covered:
            raise CandidateEvidenceError("queue certificate job ID is missing or duplicated")
        row = rows[jid]
        observations = cert.get("observations")
        if not isinstance(observations, list) or len(observations) < 2:
            raise CandidateEvidenceError(f"queue certificate has fewer than two pending observations for {jid}")
        times = []
        for obs in observations:
            if not isinstance(obs, dict) or obs.get("state") != "PENDING":
                raise CandidateEvidenceError(f"queue observation is not PENDING for {jid}")
            at = _utc(obs.get("observed_at_utc"))
            raw = _safe(final, obs.get("record_path"))
            content = raw.read_text(encoding="utf-8", errors="strict")
            if _sha(raw) != obs.get("record_sha256") or f"JobId={jid}" not in content or "JobState=PENDING" not in content:
                raise CandidateEvidenceError(f"queue observation bytes/hash/state disagree for {jid}")
            times.append(at)
        if times != sorted(times) or any((b-a).total_seconds() <= 0 or (b-a).total_seconds() > 20
                                        for a, b in zip(times, times[1:])):
            raise CandidateEvidenceError(f"queue observation coverage has a gap or time reversal for {jid}")
        lower, upper = times[0], times[-1]
        submitted, started = row["submitted_at"], row["started_at"] or row["ended_at"]
        if lower < submitted or upper > started:
            raise CandidateEvidenceError(f"queue observation lies outside the scheduler pending interval for {jid}")
        covered.add(jid)
        # V1 certificates are an optional sampled corroboration format. Its
        # 20-second observation cadence applies only to that format.
    running = [(row["started_at"], row["ended_at"]) for row in rows.values()
               if row["started_at"] is not None and row["ended_at"] > row["started_at"]]
    # Remove intervals in which any other allocation was running.
    queue_only = []
    for lower, upper in pending:
        pieces = [(lower, upper)]
        for run_start, run_end in running:
            next_pieces = []
            for left, right in pieces:
                if run_end <= left or run_start >= right:
                    next_pieces.append((left, right))
                else:
                    if left < run_start:
                        next_pieces.append((left, run_start))
                    if run_end < right:
                        next_pieces.append((run_end, right))
            pieces = next_pieces
        queue_only.extend(pieces)
    # Concurrent pending intervals are a union: never double-credit a wait.
    merged = []
    for lower, upper in sorted(queue_only):
        if merged and lower <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], upper))
        else:
            merged.append((lower, upper))
    return sum((upper-lower).total_seconds() for lower, upper in merged)


def audit(final: Path, report: dict) -> dict:
    """Validate required files, linkage, and aggregate task limits; return FAIL/PASS."""
    receipt_path = final / "execution-receipt.json"
    try:
        receipt = _json(receipt_path)
        if receipt.get("schema") == "case07-ikkem-slurm-execution/v1":
            import slurm_records
            return slurm_records.audit_execution(final, report, receipt)
        if receipt.get("schema") != "case07-candidate-execution/v2":
            raise CandidateEvidenceError("execution-receipt.json must use case07-candidate-execution/v2")
        attempt_id = receipt.get("attempt_id")
        if not isinstance(attempt_id, str) or len(attempt_id) != 32 or any(c not in "0123456789abcdef" for c in attempt_id):
            raise CandidateEvidenceError("attempt_id must be a lowercase 32-character hex identifier")
        jobs = receipt.get("jobs")
        if not isinstance(jobs, list) or not jobs:
            raise CandidateEvidenceError("execution receipt must list every submitted allocation")
        ids = [str(job.get("job_id", "")) for job in jobs if isinstance(job, dict)]
        if len(ids) != len(jobs) or not all(ids) or len(ids) != len(set(ids)):
            raise CandidateEvidenceError("allocation job IDs are missing or duplicated")
        rows = {}
        resource_measurement_missing = False
        for job in jobs:
            jid = str(job["job_id"])
            scheduler = _safe(final, job.get("scheduler_record"))
            data = _json(scheduler)
            if data.get("schema") != "case07-scheduler-record/v2":
                raise CandidateEvidenceError(f"scheduler record schema invalid for {jid}")
            fields = ("job_id", "scheduler", "allocation_id", "cpus", "memory_gib", "scratch_gib", "wall_seconds",
                      "state", "exit_code", "submitted_at_utc", "started_at_utc", "ended_at_utc",
                      "batch_script_sha256", "array_job")
            if any(job.get(k) != data.get(k) for k in fields):
                raise CandidateEvidenceError(f"receipt and scheduler record disagree for {jid}")
            if type(data.get("cpus")) is not int:
                raise CandidateEvidenceError(f"CPU count must be an integer for {jid}")
            cpus = data["cpus"]
            script = _safe(final, job.get("batch_script"))
            no_start, missing_measurement, native_stage_receipt, allocation_only_failure, partial_cancelled_allocation = _crosscheck_p04_source(
                final, job, data, script)
            resource_measurement_missing = resource_measurement_missing or missing_measurement
            memory = (None if data["memory_gib"] is None and missing_measurement else
                      _number(data["memory_gib"], f"memory_gib for {jid}", positive=not no_start))
            scratch = (None if data["scratch_gib"] is None else
                       _number(data["scratch_gib"], f"scratch_gib for {jid}"))
            wall = _number(data["wall_seconds"], f"wall_seconds for {jid}")
            if ((no_start and (data.get("state") not in {"FAILED", "CANCELLED"} or cpus != 0 or memory != 0 or wall != 0))
                    or (not no_start and cpus < 1)
                    or (memory is not None and (not math.isfinite(memory)
                    or (not no_start and memory <= 0)))):
                raise CandidateEvidenceError(f"per-job CPU or memory accounting is invalid for {jid}")
            if wall > 8 * 3600:
                raise CandidateEvidenceError(f"per-job wall-time budget exceeded for {jid}")
            if scratch is None:
                resource_measurement_missing = True
            elif not math.isfinite(scratch) or scratch < 0:
                raise CandidateEvidenceError(f"per-job scratch measurement is invalid for {jid}")
            if data.get("array_job") is not False or not jid.isdigit():
                raise CandidateEvidenceError(f"allocation {jid} is an array/task/step, not a root job")
            state = str(data.get("state", "")).split()[0].upper().rstrip("+")
            exit_code = _exit_code(data.get("exit_code"))
            if state not in {"COMPLETED", "FAILED", "CANCELLED", "TIMEOUT", "OUT_OF_MEMORY", "PREEMPTED"}:
                raise CandidateEvidenceError(f"scheduler final state is unsupported for {jid}")
            if (str(job.get("state", "")).split()[0].upper().rstrip("+") != state
                    or job.get("exit_code") != data.get("exit_code")):
                raise CandidateEvidenceError(f"receipt state/exit code disagrees for {jid}")
            if state == "COMPLETED" and exit_code != 0:
                raise CandidateEvidenceError(f"scheduler final state and exit code disagree for {jid}")
            submitted_at = _utc(data["submitted_at_utc"])
            ended_at = _utc(data["ended_at_utc"])
            start_value = data.get("started_at_utc")
            if start_value is None:
                if state == "COMPLETED" or wall != 0 or ended_at < submitted_at:
                    raise CandidateEvidenceError(f"allocated execution timing missing for {jid}")
                started_at = None
            else:
                started_at = _utc(start_value)
                measured = (ended_at-started_at).total_seconds()
                if ended_at < started_at or abs(measured-wall) > max(60, 0.02*max(measured, wall)):
                    raise CandidateEvidenceError(f"scheduler duration and timestamp span disagree for {jid}")
                if started_at < submitted_at:
                    raise CandidateEvidenceError(f"scheduler start predates submission for {jid}")
            digest = _sha(script)
            if digest != data.get("batch_script_sha256") or digest != job.get("batch_script_sha256"):
                raise CandidateEvidenceError(f"submitted batch script hash mismatch for {jid}")
            scheduler_digest = _sha(scheduler)
            if scheduler_digest != job.get("scheduler_record_sha256"):
                raise CandidateEvidenceError(f"scheduler record hash mismatch for {jid}")
            for key in ("stdout", "stderr"):
                if job.get(key) is None:
                    if (not no_start or job.get(f"{key}_absence_reason") != "not_created_before_start"
                            or job.get(f"{key}_sha256") is not None):
                        raise CandidateEvidenceError(f"{key} absence is not valid for {jid}")
                else:
                    output = _safe(final, job.get(key))
                    if _sha(output) != job.get(f"{key}_sha256"):
                        raise CandidateEvidenceError(f"{key} hash mismatch for {jid}")
            bindings = job.get("native_artifacts", [])
            if not isinstance(bindings, list):
                raise CandidateEvidenceError(f"native artifact bindings are malformed for {jid}")
            if native_stage_receipt is not None:
                if len(bindings) != 1 or not isinstance(bindings[0], dict):
                    raise CandidateEvidenceError(f"candidate stage identity/times disagree with raw P04 stage receipt for {jid}")
                binding = bindings[0]
                if (not _p04_provider_stage_matches(binding, native_stage_receipt)
                        or bindings[0].get("started_at_utc") != native_stage_receipt.get("started_at_utc")
                        or bindings[0].get("ended_at_utc") != native_stage_receipt.get("ended_at_utc")):
                    raise CandidateEvidenceError(f"candidate stage identity/times disagree with raw P04 stage receipt for {jid}")
            elif (no_start or allocation_only_failure or partial_cancelled_allocation) and bindings:
                raise CandidateEvidenceError(f"allocation without a native stage cannot bind native artifacts for {jid}")
            elif any(isinstance(binding, dict) and "provider_stage_id" in binding for binding in bindings):
                raise CandidateEvidenceError(f"provider_stage_id requires a hash-bound raw P04 stage receipt for {jid}")
            for binding in bindings:
                if not isinstance(binding, dict) or not isinstance(binding.get("stage_id"), str):
                    raise CandidateEvidenceError(f"native stage binding is malformed for {jid}")
                listed = binding.get("native_files")
                if not isinstance(listed, list) or not listed:
                    raise CandidateEvidenceError(f"native file manifest is absent for {jid}/{binding['stage_id']}")
                filemap = {}
                for item in listed:
                    if not isinstance(item, dict) or not isinstance(item.get("path"), str):
                        raise CandidateEvidenceError(f"native file row is malformed for {jid}/{binding['stage_id']}")
                    path = _safe(final, item["path"])
                    if item["path"] in filemap or _sha(path) != item.get("sha256"):
                        raise CandidateEvidenceError(f"native file hash mismatch for {jid}/{binding['stage_id']}")
                    filemap[item["path"]] = item["sha256"]
                binding["_verified_files"] = filemap
                if started_at is None:
                    raise CandidateEvidenceError(f"native stage {binding['stage_id']} has no allocated execution interval")
                stage_start, stage_end = _utc(binding.get("started_at_utc")), _utc(binding.get("ended_at_utc"))
                if stage_end <= stage_start or stage_start < started_at or stage_end > ended_at:
                    raise CandidateEvidenceError(f"native stage {binding['stage_id']} lies outside its scheduler allocation")
            if data.get("job_id") != jid or not data.get("scheduler") or not data.get("allocation_id"):
                raise CandidateEvidenceError(f"scheduler identity incomplete for {jid}")
            rows[jid] = {"cpus": cpus, "memory_gib": 0.0 if memory is None else memory, "scratch_gib": scratch,
                         "no_start": no_start,
                         "wall_seconds": wall, "exit_code": exit_code, "state": state,
                         "submitted_at": submitted_at, "started_at": started_at,
                         "ended_at": ended_at, "allocation_id": data["allocation_id"]}
        order = receipt.get("execution_order")
        if not isinstance(order, list) or not order or any(not isinstance(x, str) or not x for x in order):
            raise CandidateEvidenceError("execution_order must enumerate required arms/stages")
        if len(order) != len(set(order)):
            raise CandidateEvidenceError("execution_order contains duplicate stages")
        binding_map = {}
        for job in jobs:
            for binding in job.get("native_artifacts", []):
                if binding["stage_id"] in binding_map:
                    raise CandidateEvidenceError("native stage IDs are duplicated across allocations")
                binding_map[binding["stage_id"]] = (job, binding)
        if len(order) != len(set(order)) or set(order) != set(binding_map):
            raise CandidateEvidenceError("execution_order must enumerate every bound native stage exactly once")
        expected_stages = _report_stages(report)
        if set(expected_stages) != set(binding_map):
            raise CandidateEvidenceError("candidate execution evidence omits or invents a required report stage")
        for stage_id, expected in expected_stages.items():
            job, binding = binding_map[stage_id]
            if any(binding.get(key) != value for key, value in expected.items() if key != "files"):
                raise CandidateEvidenceError(f"native binding does not identify the report stage {stage_id}")
            filemap = binding["_verified_files"]
            for report_key, path in expected["files"].items():
                if not isinstance(path, str) or path not in filemap:
                    raise CandidateEvidenceError(f"native binding {stage_id} does not bind report {report_key}")
            if expected["kind"] in {"production", "extension"}:
                stage_dir = _safe(final, expected["stage_path"])
                actual = {p.relative_to(final).as_posix(): _sha(p) for p in stage_dir.rglob("*")
                          if p.is_file() and not p.is_symlink()}
                if not actual or actual != filemap:
                    raise CandidateEvidenceError(f"production stage manifest differs from report stage {stage_id}")
        ordered_times = [_utc(binding_map[stage_id][1]["started_at_utc"]) for stage_id in order]
        if ordered_times != sorted(ordered_times):
            raise CandidateEvidenceError("execution_order disagrees with native stage start times")
        ledger = final / "resource_usage.csv"
        with ledger.open(newline="", encoding="utf-8") as stream:
            ledger_rows = list(csv.DictReader(stream))
        by_id = {row.get("job_id", ""): row for row in ledger_rows}
        if set(by_id) != set(rows):
            raise CandidateEvidenceError("resource_usage.csv job IDs differ from submitted allocations")
        core_hours = 0.0
        for jid, data in rows.items():
            row = by_id[jid]
            start_text = row.get("start_utc", "").strip()
            ledger_start = _utc(start_text) if start_text else None
            if (int(row["allocated_cores"]) != data["cpus"]
                    or row["status"].strip().upper().split()[0].rstrip("+") != data["state"]
                    or ledger_start != data["started_at"]
                    or _utc(row["end_utc"]) != data["ended_at"]):
                raise CandidateEvidenceError(f"resource ledger differs from scheduler record for {jid}")
            peak_memory = None if not row.get("peak_memory_gib", "").strip() else float(row["peak_memory_gib"])
            ledger_scratch = None if not row.get("scratch_gib", "").strip() else float(row["scratch_gib"])
            expected_peak = data.get("peak_memory_gib")
            p04_projection = data.get("p04_source_schema") == "compchemworld.p04-scheduler-record/v1"
            if (peak_memory is None or ledger_scratch is None):
                resource_measurement_missing = True
            if (peak_memory is not None and ((p04_projection and expected_peak is None) or not math.isfinite(peak_memory)
                    or peak_memory < 0
                    or (p04_projection and not math.isclose(peak_memory, expected_peak, abs_tol=0.01)))
                    or (ledger_scratch is not None and (data["scratch_gib"] is None
                        or not math.isfinite(ledger_scratch) or ledger_scratch < 0
                        or not math.isclose(ledger_scratch, data["scratch_gib"], abs_tol=0.01)))):
                raise CandidateEvidenceError(f"resource memory/scratch differs from scheduler record for {jid}")
            hours = float(row["allocated_core_hours"])
            if not math.isfinite(hours) or hours < 0 or abs(hours-data["cpus"]*data["wall_seconds"]/3600) > 0.05:
                raise CandidateEvidenceError(f"allocated core-hours disagree for {jid}")
            core_hours += hours
        starts = {jid: row["started_at"] for jid, row in rows.items() if row["started_at"] is not None}
        ends = {jid: row["ended_at"] for jid, row in rows.items() if row["started_at"] is not None}
        points = sorted({t for jid in starts for t in (starts[jid], ends[jid])})
        submitted = receipt.get("attempt_started_at_utc")
        report_time = receipt.get("report_submitted_at_utc")
        if submitted is None or report_time is None or _utc(report_time) < _utc(submitted):
            raise CandidateEvidenceError("attempt start and report submission timestamps are required")
        attempt_start, attempt_end = _utc(submitted), _utc(report_time)
        if any(row["submitted_at"] < attempt_start or row["ended_at"] > attempt_end for row in rows.values()):
            raise CandidateEvidenceError("attempt window does not contain all allocation submissions and completions")
        queue_credit = _queue_credit(final, receipt, rows)
        if (attempt_end-attempt_start).total_seconds()-queue_credit > 8*3600:
            raise CandidateEvidenceError("attempt wall-time exceeds eight hours after verified queue-only intervals")
        return {"status": "REVIEW_REQUIRED" if resource_measurement_missing else "PASS",
                "reason": ("resource peak-memory or scratch measurement is missing" if resource_measurement_missing
                           else "candidate execution receipt cross-checks internally"),
                "job_count": len(jobs), "allocated_core_hours": round(core_hours, 4),
                "credited_queue_seconds": round(queue_credit, 1), "attempt_id": attempt_id}
    except (OSError, UnicodeError, json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
        return {"status": "FAIL", "reason": str(exc), "job_count": 0}
