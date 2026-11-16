"""Evaluator-side validation for fresh Case07 evidence.

The caller MUST pass the runner-reserved read-only context, never candidate JSON.
Candidate report claims alone cannot establish execution authority or review.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import csv
import hashlib
import io
import json
import math
from pathlib import Path, PurePosixPath
import re
from typing import Any, Mapping

import queue_certificate

SCHEMA = "case07-runner-context/v1"
CASE_ID = "case-07-independent-saddle-point-recomputation"
DEFINITION_REVISION = "2.0"
RESOURCE_PROFILE = "case07-8h-v1"
HEX64 = re.compile(r"^[0-9a-f]{64}$")
SACCT_FIELDS = {"JobIDRaw", "State", "ExitCode", "Submit", "Start", "End",
                "ElapsedRaw", "AllocCPUS", "CPUTimeRAW"}
FROZEN_ELEMENTS = ["C"]*6 + ["H"]*4 + ["O"]*4 + ["H", "O", "C"] + ["H"]*4
# Byte-identical to runtimes/hpc/case07/queue_certificate.py. The host bundle
# pins that source; this evaluator copy is checked by the queue auditor tests.
QUEUE_CERTIFICATE_SOURCE_SHA256 = "6238425b50739a984e7a5bae3d5c73a0b18e9fc38935d6518bbcf516bb171934"


@dataclass(frozen=True)
class FreshAudit:
    status: str
    reason: str
    attempt_id: str | None = None
    artifact_manifest: Mapping[str, str] | None = None
    resource_status: str = "REVIEW_REQUIRED"
    resource_reason: str = "resource snapshot not authenticated"
    review_status: str = "REVIEW_REQUIRED"
    decision_review_status: str = "REVIEW_REQUIRED"
    reference_review_status: str = "REVIEW_REQUIRED"
    execution_status: str = "REVIEW_REQUIRED"
    execution_reason: str = "trusted execution-event chain is not authenticated"


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                      allow_nan=False).encode("utf-8")


def canonical_sha256(value: Any) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _valid_hash(value: Any) -> bool:
    return isinstance(value, str) and HEX64.fullmatch(value) is not None


def _safe_relative(name: Any) -> bool:
    if not isinstance(name, str) or not name or "\\" in name:
        return False
    path = PurePosixPath(name)
    return (not path.is_absolute() and name == path.as_posix() and "//" not in name
            and all(part not in ("", ".", "..") for part in path.parts))


def _geometry_matches_coordinates(request_geometry: Any, coordinates: Any, tolerance: float = 1e-8) -> bool:
    if not isinstance(request_geometry, list) or len(request_geometry) != 21:
        return False
    if not isinstance(coordinates, list) or len(coordinates) != 21:
        return False
    for element, requested, actual in zip(FROZEN_ELEMENTS, request_geometry, coordinates):
        if (not isinstance(requested, Mapping) or requested.get("element") != element
                or set(requested) != {"element", "xyz"}):
            return False
        xyz = requested.get("xyz")
        if not isinstance(xyz, list) or len(xyz) != 3 or not isinstance(actual, list) or len(actual) != 3:
            return False
        try:
            if any(abs(float(a)-float(b)) > tolerance for a, b in zip(xyz, actual)):
                return False
        except (TypeError, ValueError, OverflowError):
            return False
    return True


def _xyz_coordinates(path: Path) -> list[list[float]]:
    lines = path.read_text(encoding="utf-8", errors="strict").splitlines()
    if not lines or lines[0].strip() != "21" or len(lines) != 23:
        raise ValueError("execution geometry must be a complete 21-atom XYZ file")
    coords = []
    for element, line in zip(FROZEN_ELEMENTS, lines[2:]):
        fields = line.split()
        if len(fields) != 4 or fields[0] != element:
            raise ValueError("execution geometry breaks the frozen atom mapping")
        row = [float(value) for value in fields[1:]]
        if any(not math.isfinite(value) for value in row):
            raise ValueError("execution geometry contains non-finite coordinates")
        coords.append(row)
    return coords


def _manifest_from_disk(final: Path) -> dict[str, str]:
    if final.is_symlink() or not final.is_dir():
        raise ValueError("final artifact root is missing or unsafe")
    files: dict[str, str] = {}
    for path in sorted(final.rglob("*")):
        if path.is_symlink():
            raise ValueError(f"symlink in submitted final tree: {path.relative_to(final)}")
        if path.is_file():
            files[path.relative_to(final).as_posix()] = file_sha256(path)
        elif not path.is_dir():
            raise ValueError(f"special file in submitted final tree: {path.relative_to(final)}")
    return files


def _parse_utc(value: Any) -> datetime:
    if not isinstance(value, str):
        raise ValueError("timestamp must be ISO-8601 text")
    raw = value[:-1] + "+00:00" if value.endswith("Z") else value
    parsed = datetime.fromisoformat(raw)
    if parsed.tzinfo is None or parsed.utcoffset() != timezone.utc.utcoffset(parsed):
        raise ValueError("timestamp must carry an explicit UTC offset")
    return parsed.astimezone(timezone.utc)


def _finite_nonnegative(value: Any, label: str) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{label} must be numeric, not boolean")
    result = float(value)
    if not math.isfinite(result) or result < 0:
        raise ValueError(f"{label} must be finite and nonnegative")
    return result


def _parse_sacct(text: Any) -> list[dict[str, str]]:
    if not isinstance(text, str) or not text:
        raise ValueError("raw sacct evidence text is missing")
    rows = list(csv.DictReader(io.StringIO(text), delimiter="|"))
    if not rows or not SACCT_FIELDS <= set(rows[0]):
        raise ValueError("raw sacct evidence lacks required fields")
    roots = [r for r in rows if r.get("JobIDRaw", "").strip() and "." not in r["JobIDRaw"].strip()]
    ids = [r["JobIDRaw"].strip() for r in roots]
    if not roots or len(ids) != len(set(ids)):
        raise ValueError("raw sacct evidence lacks unique root allocation rows")
    for row in roots:
        try:
            elapsed = int(row["ElapsedRaw"])
            cores = int(row["AllocCPUS"])
            cpu_raw = int(row["CPUTimeRAW"])
        except (TypeError, ValueError) as exc:
            raise ValueError("raw sacct evidence has malformed accounting fields") from exc
        if elapsed < 0 or cores <= 0 or cpu_raw != elapsed * cores:
            raise ValueError(f"raw sacct CPUTimeRAW mismatch for {row['JobIDRaw']}")
    return roots


def _validate_scheduler_context(context: Mapping[str, Any]) -> list[dict[str, Any]]:
    ledger = context["scheduler_ledger"]
    if (not isinstance(ledger, Mapping) or ledger.get("schema") != "case07-scheduler-ledger/v1"
            or ledger.get("attempt_id") != context["attempt_id"] or not isinstance(ledger.get("rows"), list)):
        raise ValueError("runner scheduler ledger schema or attempt binding is invalid")
    if canonical_sha256(ledger) != context["scheduler_ledger_sha256"]:
        raise ValueError("runner scheduler-ledger digest mismatch")
    evidence = context["raw_sacct_evidence"]
    if not isinstance(evidence, Mapping) or not evidence:
        raise ValueError("read-only raw sacct evidence map is missing")
    parsed_by_job: dict[str, dict[str, str]] = {}
    raw_paths: set[str] = set()
    for path, raw_text in evidence.items():
        if not _safe_relative(path):
            raise ValueError("unsafe raw sacct evidence path")
        rows = _parse_sacct(raw_text)
        raw_digest = hashlib.sha256(raw_text.encode("utf-8")).hexdigest()
        for row in rows:
            jid = row["JobIDRaw"].strip()
            if jid in parsed_by_job:
                raise ValueError("duplicate job in raw sacct evidence")
            parsed_by_job[jid] = row
            raw_paths.add(path)
    normalized = ledger["rows"]
    job_ids = [r.get("job_id") for r in normalized if isinstance(r, Mapping)]
    if len(job_ids) != len(normalized) or len(job_ids) != len(set(job_ids)) or set(job_ids) != set(parsed_by_job):
        raise ValueError("normalized scheduler rows omit or invent root allocations")
    for row in normalized:
        jid = row["job_id"]
        raw = parsed_by_job[jid]
        source_path = row.get("raw_sacct_path")
        source_hash = row.get("raw_sacct_sha256")
        if not _safe_relative(source_path) or source_path not in evidence or not _valid_hash(source_hash):
            raise ValueError(f"raw sacct source binding is malformed for {jid}")
        text = evidence[source_path]
        if hashlib.sha256(text.encode("utf-8")).hexdigest() != source_hash:
            raise ValueError(f"raw sacct byte digest mismatch for {jid}")
        expected = {"state": raw["State"].strip(), "exit_code": raw["ExitCode"].strip(),
                    "submit_utc": raw["Submit"].strip(), "start_utc": raw["Start"].strip(),
                    "end_utc": raw["End"].strip(), "elapsed_raw": int(raw["ElapsedRaw"]),
                    "alloc_cpus": int(raw["AllocCPUS"]), "cpu_time_raw": int(raw["CPUTimeRAW"])}
        if any(row.get(k) != v for k, v in expected.items()):
            raise ValueError(f"normalized scheduler row differs from raw sacct for {jid}")
        if _parse_utc(row["end_utc"]) > _parse_utc(context["collected_at_utc"]):
            raise ValueError(f"terminal allocation {jid} ended after trusted accounting collection")
    return [dict(r) for r in normalized]


ORCA_STAGES = {"pilot_sp", "screen_energy_gradient", "screen_refinement", "optts",
               "ts_frequency", "endpoint_opt", "endpoint_frequency"}
EVENT_STAGES = ORCA_STAGES | {"public_seed", "mode_displacement"}
EVENT_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9:_-]{0,95}$")
REQUEST_ID = re.compile(r"^[a-z][a-z0-9_-]{0,47}$")


def _report_receipt_paths(value: Any) -> set[str]:
    """Collect native receipt references from the candidate report structure."""
    found: set[str] = set()
    if isinstance(value, Mapping):
        receipt = value.get("receipt_path")
        if receipt is not None:
            if not _safe_relative(receipt):
                raise ValueError("candidate report contains an unsafe receipt path")
            found.add(receipt)
        for child in value.values():
            found.update(_report_receipt_paths(child))
    elif isinstance(value, list):
        for child in value:
            found.update(_report_receipt_paths(child))
    return found


def _audit_execution_events(final: Path, context: Mapping[str, Any], manifest: Mapping[str, str],
                            rows: list[dict[str, Any]], public_hashes: Mapping[str, str]) -> tuple[str, str]:
    """Bind native output receipts to an evaluator-only host execution DAG.

    Missing event authority is a review boundary. A malformed trusted ledger is
    an environment error; a well-formed ledger that contradicts candidate files
    is a scientific provenance failure.
    """
    events = context.get("execution_events")
    digest = context.get("execution_events_sha256")
    if events is None or digest is None:
        return "REVIEW_REQUIRED", "evaluator-only execution event chain is absent"
    if not isinstance(events, list) or not events:
        raise ValueError("trusted execution event chain must be a nonempty array")
    if canonical_sha256(events) != digest:
        raise ValueError("trusted execution event chain digest mismatch")
    attempt = context["attempt_id"]
    allocations = {row["job_id"]: row for row in rows}
    event_by_id: dict[str, Mapping[str, Any]] = {}
    request_ids: set[str] = set()
    expected_receipts = {name for name in manifest
                         if name.startswith("native_outputs/") and name.endswith("/receipt.json")}
    event_receipts: set[str] = set()
    report_path = final / "ts_search_report.json"
    try:
        report = json.loads(report_path.read_text(encoding="utf-8"), parse_constant=_reject_json_constant)
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        raise ValueError("candidate report cannot be read for execution-event binding") from exc
    report_receipts = _report_receipt_paths(report)

    def artifact_hash(relative: Any, expected: Any, label: str) -> str:
        if not _safe_relative(relative) or not _valid_hash(expected):
            raise ValueError(f"trusted execution event {label} path/hash is malformed")
        if manifest.get(relative) != expected:
            return f"candidate {label} bytes disagree with the trusted execution event"
        return ""

    for event in events:
        if not isinstance(event, Mapping):
            raise ValueError("trusted execution event is not an object")
        required = {"schema", "event_id", "attempt_id", "request_id", "kind", "stage", "channel",
                    "parent_event_id", "parent_output_sha256", "request", "request_sha256",
                    "template_manifest_sha256", "engine_sha256", "started_at_utc", "ended_at_utc",
                    "status", "returncode", "job_id", "artifacts"}
        if not required <= set(event):
            raise ValueError("trusted execution event lacks required fields")
        if event.get("schema") != "case07-execution-event/v1" or event.get("attempt_id") != attempt:
            raise ValueError("trusted execution event schema/attempt binding is invalid")
        event_id, request_id, stage = event.get("event_id"), event.get("request_id"), event.get("stage")
        if (not isinstance(event_id, str) or not EVENT_ID.fullmatch(event_id) or event_id in event_by_id
                or not isinstance(request_id, str) or not REQUEST_ID.fullmatch(request_id)
                or request_id in request_ids or stage not in EVENT_STAGES):
            raise ValueError("trusted execution event ID, request ID, or stage is invalid/duplicated")
        request_ids.add(request_id)
        if event.get("template_manifest_sha256") != context["template_manifest_sha256"]:
            raise ValueError("execution event template hash differs from trusted controller context")
        if event.get("engine_sha256") != context["engine_sha256"]:
            raise ValueError("execution event engine hash differs from trusted controller context")
        try:
            started, ended = _parse_utc(event.get("started_at_utc")), _parse_utc(event.get("ended_at_utc"))
        except ValueError as exc:
            raise ValueError("trusted execution event timestamps are invalid") from exc
        if ended < started:
            raise ValueError("trusted execution event ends before it starts")
        if started < _parse_utc(context["attempt_started_at_utc"]) or ended > _parse_utc(context["report_submitted_at_utc"]):
            raise ValueError("execution event lies outside the sealed attempt interval")
        kind = event.get("kind")
        if kind not in {"orca_stage", "geometry_transform"}:
            raise ValueError("trusted execution event kind is unsupported")
        if (kind == "orca_stage") != (stage in ORCA_STAGES):
            raise ValueError("trusted execution event kind does not match its stage")
        if event.get("status") not in {"normal", "timeout", "failed"}:
            raise ValueError("trusted execution event status is unsupported")
        if kind == "geometry_transform" and (event.get("status") != "normal" or event.get("returncode") != 0):
            raise ValueError("geometry-transform event must be recorded as successful")
        job_id = event.get("job_id")
        if kind == "orca_stage":
            if not isinstance(job_id, str) or job_id not in allocations:
                raise ValueError("native event job ID is not an authenticated root Slurm allocation")
            allocation = allocations[job_id]
            try:
                alloc_start, alloc_end = _parse_utc(allocation["start_utc"]), _parse_utc(allocation["end_utc"])
            except ValueError as exc:
                raise ValueError("native event allocation UTC interval is unavailable") from exc
            if started < alloc_start or ended > alloc_end:
                raise ValueError("native event interval falls outside its authenticated allocation")
        elif job_id is not None:
            raise ValueError("geometry-transform event must not claim a Slurm job")
        request = event.get("request")
        if not isinstance(request, Mapping) or canonical_sha256(request) != event.get("request_sha256"):
            raise ValueError("trusted event request bytes/digest are invalid")
        if (request.get("attempt_id") != attempt or request.get("request_id") != request_id
                or request.get("stage") != stage or request.get("channel") != event.get("channel")
                or request.get("parent_event_id") != event.get("parent_event_id")):
            raise ValueError("trusted event request identity differs from event fields")
        if stage == "pilot_sp":
            if event.get("channel") is not None:
                raise ValueError("pilot event must be channel neutral")
        elif stage not in {"public_seed"} and event.get("channel") not in {"C1", "C2"}:
            raise ValueError("channel-specific execution event lacks a valid channel")
        artifacts = event.get("artifacts")
        if not isinstance(artifacts, Mapping):
            raise ValueError("trusted execution event artifacts are malformed")
        if kind == "orca_stage":
            required_artifacts = {"input", "output", "start_xyz", "receipt"}
            if stage in {"optts", "endpoint_opt"} or (stage == "screen_refinement" and event.get("status") == "normal"):
                required_artifacts.add("final_geometry")
        elif stage == "mode_displacement":
            required_artifacts = {"output", "native_hess", "displacement"}
        else:
            required_artifacts = {"output"}
        if not required_artifacts <= set(artifacts):
            raise ValueError("trusted execution event omits required artifact bindings")
        for key, item in artifacts.items():
            if not isinstance(item, Mapping) or set(item) != {"path", "sha256"}:
                raise ValueError(f"trusted execution event {key} artifact binding is malformed")
            mismatch = artifact_hash(item["path"], item["sha256"], key)
            if mismatch:
                # A well-formed trusted event that names bytes absent from its
                # sealed candidate snapshot is a proven provenance mismatch.
                return "FAIL", mismatch
        if stage == "public_seed":
            request_geometry = request.get("geometry")
            output_path = final.joinpath(*PurePosixPath(artifacts["output"]["path"]).parts)
            if not _geometry_matches_coordinates(request_geometry, _xyz_coordinates(output_path)):
                return "FAIL", "in-attempt public seed coordinates differ from the trusted seed request"
        if kind == "orca_stage":
            receipt_path = artifacts["receipt"]["path"]
            if receipt_path in event_receipts:
                raise ValueError("multiple execution events claim one native receipt")
            event_receipts.add(receipt_path)
            if request.get("method_id") not in {"orca_r2scan3c", "orca_pbe_d3bj_def2_svp"}:
                return "REVIEW_REQUIRED", "native request uses a method template outside the calibrated Case07 executor"
            try:
                expected_input = _expected_typed_orca_input(request)
            except ValueError as exc:
                return "FAIL", f"native request violates the frozen stage/method template: {exc}"
            input_path = final.joinpath(*PurePosixPath(artifacts["input"]["path"]).parts)
            try:
                actual_input = input_path.read_text(encoding="utf-8", errors="strict")
            except (OSError, UnicodeError):
                return "FAIL", "native typed input is absent or unreadable"
            if actual_input != expected_input:
                return "FAIL", f"native input bytes for {receipt_path} differ from the frozen typed template/request"
            receipt_obj = _load_json_artifact(final, receipt_path)
            if (receipt_obj.get("input_sha256") != artifacts["input"]["sha256"]
                    or receipt_obj.get("output_sha256") != artifacts["output"]["sha256"]
                    or receipt_obj.get("start_xyz_sha256") != artifacts["start_xyz"]["sha256"]):
                return "FAIL", f"native receipt {receipt_path} disagrees with its trusted execution event"
            if receipt_obj.get("status") != event.get("status"):
                return "FAIL", f"native receipt {receipt_path} status differs from trusted execution event"
            if receipt_obj.get("returncode") != event.get("returncode"):
                return "FAIL", f"native receipt {receipt_path} return code differs from trusted execution event"
            if event.get("status") == "normal" and receipt_obj.get("returncode") != 0:
                return "FAIL", f"native receipt {receipt_path} is not a successful execution"
            if "geometry" in request:
                start_path = final.joinpath(*PurePosixPath(artifacts["start_xyz"]["path"]).parts)
                if not _geometry_matches_coordinates(request["geometry"], _xyz_coordinates(start_path)):
                    return "FAIL", f"native start.xyz for {receipt_path} differs from the trusted typed request"
            if "final_geometry" in artifacts:
                if receipt_obj.get("final_geometry_sha256") != artifacts["final_geometry"]["sha256"]:
                    return "FAIL", f"native receipt {receipt_path} does not bind its final optimized geometry"
                geom_path = final.joinpath(*PurePosixPath(artifacts["final_geometry"]["path"]).parts)
                _xyz_coordinates(geom_path)
            if stage in {"ts_frequency", "endpoint_frequency"} and "native_hess" not in artifacts:
                raise ValueError("frequency execution event does not bind its native Hessian")
            if stage == "screen_energy_gradient" and "native_engrad" not in artifacts:
                raise ValueError("energy/gradient execution event does not bind its native engrad")
            for optional_key in ("native_hess", "native_engrad"):
                if optional_key in artifacts:
                    receipt_key = "hess_sha256" if optional_key == "native_hess" else "engrad_sha256"
                    if receipt_obj.get(receipt_key) != artifacts[optional_key]["sha256"]:
                        return "FAIL", f"native receipt {receipt_path} does not bind {optional_key}"
            if stage in {"ts_frequency", "endpoint_frequency"} and "native_hess" not in artifacts:
                raise ValueError("frequency event does not bind the actual native Hessian")
            if stage == "screen_energy_gradient" and "native_engrad" not in artifacts:
                raise ValueError("screen event does not bind the actual native engrad")
        elif stage == "mode_displacement":
            sign = request.get("mode_sign")
            if type(sign) is not int or sign not in (-1, 1):
                raise ValueError("mode event must bind a strict integer signed-mode request")
        event_by_id[event_id] = event

    if event_receipts != expected_receipts or not report_receipts <= event_receipts:
        return "FAIL", "trusted execution events do not cover exactly the snapshot receipts and every report-referenced receipt"
    # Check parent edges after collecting IDs, so input order cannot hide a cycle.
    visited: set[str] = set()
    visiting: set[str] = set()
    def visit(event_id: str) -> bool:
        if event_id in visiting:
            return False
        if event_id in visited:
            return True
        visiting.add(event_id)
        event = event_by_id[event_id]
        parent_id = event.get("parent_event_id")
        parent_hash = event.get("parent_output_sha256")
        if not isinstance(parent_id, str) or not _valid_hash(parent_hash):
            raise ValueError("execution event parent identity/hash is malformed")
        if parent_id in event_by_id:
            parent = event_by_id[parent_id]
            parent_output = parent.get("artifacts", {}).get("output")
            if (parent.get("attempt_id") != attempt or not isinstance(parent_output, Mapping)
                    or parent_output.get("sha256") != parent_hash
                    or _parse_utc(parent["ended_at_utc"]) > _parse_utc(event["started_at_utc"])):
                return False
            if not visit(parent_id):
                return False
        elif parent_id.startswith("public:"):
            source = parent_id.removeprefix("public:")
            if public_hashes.get(source) != parent_hash:
                return False
        else:
            return False
        visiting.remove(event_id)
        visited.add(event_id)
        return True
    for event_id in event_by_id:
        if not visit(event_id):
            return "FAIL", "execution event parent chain is cyclic, cross-attempt, or byte-mismatched"
    selected = report.get("selected_channel")
    if selected not in {"C1", "C2"}:
        return "FAIL", "candidate report does not select a channel for the authenticated execution chain"
    by_stage: dict[str, list[Mapping[str, Any]]] = {}
    for event in events:
        by_stage.setdefault(event["stage"], []).append(event)
    if not any(event.get("status") == "normal" for event in by_stage.get("pilot_sp", [])):
        return "FAIL", "trusted execution chain lacks a successful actual pilot stage"
    screens = by_stage.get("screen_energy_gradient", [])
    for channel in ("C1", "C2"):
        channel_screens = [event for event in screens if event.get("channel") == channel
                           and event.get("status") == "normal"]
        distinct = {event["artifacts"]["start_xyz"]["sha256"] for event in channel_screens}
        if len(channel_screens) < 3 or len(distinct) < 3:
            return "FAIL", f"trusted execution chain lacks three distinct successful {channel} energy/gradient evaluations"
    tsopts = [event for event in by_stage.get("optts", []) if event.get("channel") == selected
              and event.get("status") == "normal"]
    tsfreqs = [event for event in by_stage.get("ts_frequency", []) if event.get("channel") == selected
               and event.get("status") == "normal"]
    modes = [event for event in by_stage.get("mode_displacement", []) if event.get("channel") == selected
             and event.get("status") == "normal"]
    if len(tsopts) != 1 or len(tsfreqs) != 1 or len(modes) != 2:
        return "FAIL", "trusted execution chain lacks a unique selected-channel TS, frequency, or two signed mode events"
    signs = {event.get("request", {}).get("mode_sign") for event in modes}
    if signs != {-1, 1}:
        return "FAIL", "trusted mode events do not cover both signed directions"
    if tsfreqs[0].get("parent_event_id") != tsopts[0].get("event_id"):
        return "FAIL", "TS frequency event is not parented to the selected OptTS output"
    for sign in (-1, 1):
        mode = next(event for event in modes if event.get("request", {}).get("mode_sign") == sign)
        opt = [event for event in by_stage.get("endpoint_opt", [])
               if event.get("channel") == selected and event.get("parent_event_id") == mode.get("event_id")
               and event.get("status") == "normal"]
        if len(opt) != 1:
            return "FAIL", "each signed mode direction must lead to exactly one successful endpoint optimization"
        freq = [event for event in by_stage.get("endpoint_frequency", [])
                if event.get("channel") == selected and event.get("parent_event_id") == opt[0].get("event_id")
                and event.get("status") == "normal"]
        if len(freq) != 1:
            return "FAIL", "each endpoint optimization must lead to exactly one successful frequency calculation"
    # Enforce stage topology, not just acyclic reachability. A signed endpoint
    # must descend from its own mode event, and every selected science stage
    # must be part of this attempt's authenticated DAG.
    for stage, group in by_stage.items():
        for event in group:
            parent_id = event["parent_event_id"]
            if parent_id in event_by_id:
                parent = event_by_id[parent_id]
                parent_stage = parent["stage"]
                ok = {
                    "pilot_sp": {"public_seed"},
                    "screen_energy_gradient": {"public_seed"},
                    "screen_refinement": {"screen_energy_gradient"},
                    "optts": {"screen_energy_gradient", "screen_refinement"},
                    "ts_frequency": {"optts"},
                    "mode_displacement": {"ts_frequency"},
                    "endpoint_opt": {"mode_displacement"},
                    "endpoint_frequency": {"endpoint_opt"},
                    "public_seed": set(),
                }.get(stage, set())
                if parent_stage not in ok or (event.get("channel") is not None
                        and parent.get("channel") not in {None, event.get("channel")}):
                    return "FAIL", f"{stage} event has an invalid stage/channel parent"
                if stage == "optts" and parent_stage == "screen_refinement":
                    if parent.get("status") == "normal":
                        pass
                    elif parent.get("status") in {"timeout", "failed"}:
                        cycle = parent.get("complete_cycle")
                        if not isinstance(cycle, Mapping):
                            return "FAIL", "timed-out refinement lacks trusted complete-cycle evidence for OptTS restart"
                        expected_cycle = {"schema", "cycle_number", "output_sha256", "geometry_offset",
                                          "scf_converged_offset", "energy_offset", "gradient_offset",
                                          "scf_converged", "geometry", "geometry_sha256", "energy_au", "gradient"}
                        if (set(cycle) != expected_cycle or cycle.get("schema") != "case07-complete-cycle/v1"
                                or type(cycle.get("cycle_number")) is not int or cycle["cycle_number"] <= 0
                                or cycle.get("output_sha256") != parent.get("artifacts", {}).get("output", {}).get("sha256")
                                or cycle.get("scf_converged") is not True):
                            return "FAIL", "timed-out refinement complete-cycle evidence is not tied to its raw output"
                        offsets = [cycle.get(k) for k in ("geometry_offset", "scf_converged_offset",
                                                           "energy_offset", "gradient_offset")]
                        if (any(type(offset) is not int or offset < 0 for offset in offsets)
                                or not offsets[0] < offsets[1] < offsets[2] < offsets[3]):
                            return "FAIL", "timed-out refinement cycle source offsets are missing or out of order"
                        geom = cycle.get("geometry")
                        grad = cycle.get("gradient")
                        if (not isinstance(geom, list) or len(geom) != 21
                                or any(not isinstance(row, list) or len(row) != 3
                                       or any(isinstance(x, bool) or not isinstance(x, (int, float))
                                              or not math.isfinite(float(x)) for x in row) for row in geom)
                                or not isinstance(grad, list) or len(grad) != 63
                                or any(isinstance(x, bool) or not isinstance(x, (int, float))
                                       or not math.isfinite(float(x)) for x in grad)):
                            return "FAIL", "timed-out refinement complete cycle lacks 21 coordinates and a complete finite gradient"
                        if (not _valid_hash(cycle.get("geometry_sha256"))
                                or canonical_sha256(geom) != cycle["geometry_sha256"]):
                            return "FAIL", "timed-out refinement cycle geometry digest differs"
                        energy = cycle.get("energy_au")
                        if (isinstance(energy, bool) or not isinstance(energy, (int, float))
                                or not math.isfinite(float(energy))):
                            return "FAIL", "timed-out refinement cycle energy is not finite"
                        if not _geometry_matches_coordinates(request.get("geometry"), geom):
                            return "FAIL", "OptTS restart geometry differs from the last complete refinement cycle"
                    else:
                        return "FAIL", "OptTS parent refinement has no usable native terminal status"
                if "geometry" in event.get("request", {}):
                    source_geometry: list[list[float]] | None = None
                    if parent_stage in {"public_seed", "mode_displacement"}:
                        source_path = parent.get("artifacts", {}).get("output", {}).get("path")
                        if source_path:
                            source_geometry = _xyz_coordinates(final.joinpath(*PurePosixPath(source_path).parts))
                    elif parent_stage == "screen_energy_gradient":
                        source_path = parent.get("artifacts", {}).get("start_xyz", {}).get("path")
                        if source_path:
                            source_geometry = _xyz_coordinates(final.joinpath(*PurePosixPath(source_path).parts))
                    elif parent_stage in {"optts", "endpoint_opt"}:
                        source_path = parent.get("artifacts", {}).get("final_geometry", {}).get("path")
                        if source_path:
                            source_geometry = _xyz_coordinates(final.joinpath(*PurePosixPath(source_path).parts))
                    elif parent_stage == "screen_refinement":
                        if parent.get("status") in {"timeout", "failed"}:
                            cycle = parent.get("complete_cycle", {})
                            source_geometry = cycle.get("geometry") if isinstance(cycle, Mapping) else None
                        else:
                            source_path = parent.get("artifacts", {}).get("final_geometry", {}).get("path")
                            if source_path:
                                source_geometry = _xyz_coordinates(final.joinpath(*PurePosixPath(source_path).parts))
                    if source_geometry is not None and not _geometry_matches_coordinates(
                            event["request"]["geometry"], source_geometry):
                        return "FAIL", f"{stage} request geometry differs from its actual parent geometry"
            else:
                if not parent_id.startswith("public:") or stage not in {"pilot_sp", "public_seed"}:
                    return "FAIL", f"{stage} event bypasses an authenticated public seed or same-attempt native parent"
                if parent_id.removeprefix("public:") not in public_hashes:
                    return "FAIL", "public parent is not in the evaluator-pinned input set"
            if stage == "public_seed" and event.get("status") != "normal":
                return "FAIL", "public seed transformation was not completed successfully"
    for channel in ("C1", "C2"):
        seeds = [event for event in events if event.get("stage") == "public_seed"
                 and event.get("channel") == channel]
        if len({event.get("artifacts", {}).get("output", {}).get("sha256") for event in seeds}) < 3:
            return "FAIL", f"trusted event chain lacks three distinct {channel} public seed geometries"
    selected = report.get("selected_channel")
    mode_events = [event for event in events if event.get("stage") == "mode_displacement"
                   and event.get("channel") == selected]
    for mode in mode_events:
        parent = event_by_id.get(mode.get("parent_event_id"))
        if (parent is None or parent.get("stage") != "ts_frequency"
                or mode.get("artifacts", {}).get("native_hess", {}).get("sha256")
                    != parent.get("artifacts", {}).get("native_hess", {}).get("sha256")):
            return "FAIL", "signed-mode event is not bound to its parent TS Hessian bytes"
    return "PASS", "trusted execution events bind report receipts, attempt, requests, allocations, and acyclic parent provenance"


def _reject_json_constant(value: str) -> None:
    raise ValueError(f"non-finite JSON constant {value} is forbidden")


def _load_json_artifact(final: Path, relative: str) -> Mapping[str, Any]:
    path = final.joinpath(*PurePosixPath(relative).parts)
    if path.is_symlink() or not path.is_file():
        raise ValueError("execution event receipt is absent or unsafe")
    value = json.loads(path.read_text(encoding="utf-8"), parse_constant=_reject_json_constant)
    if not isinstance(value, Mapping):
        raise ValueError("execution event receipt is not a JSON object")
    return value


def _expected_typed_orca_input(request: Mapping[str, Any]) -> str:
    """Independent rendering oracle for the small frozen Case07 template set."""
    methods = {
        "orca_r2scan3c": "UKS r2SCAN-3c DefGrid3",
        "orca_pbe_d3bj_def2_svp": "UKS PBE D3BJ def2-SVP DefGrid3",
    }
    method_id, stage = request.get("method_id"), request.get("stage")
    if method_id not in methods:
        raise ValueError("trusted request selected an unknown frozen method template")
    if stage in {"optts", "ts_frequency", "endpoint_opt", "endpoint_frequency"} and method_id != "orca_r2scan3c":
        raise ValueError("final native stage selected a non-final method template")
    prefix = methods[method_id]
    if stage == "pilot_sp":
        method, extra = f"! {prefix} TightSCF SP", "%scf\n  MaxIter 400\nend\n"
    elif stage == "screen_energy_gradient":
        method, extra = f"! {prefix} TightSCF EnGrad", "%scf\n  MaxIter 400\nend\n"
    elif stage == "screen_refinement":
        constraints = request.get("constraints")
        if not isinstance(constraints, list) or not constraints:
            raise ValueError("refinement request lacks numeric constraints")
        rows = []
        for item in constraints:
            if not isinstance(item, Mapping) or set(item) != {"atoms", "distance_angstrom"}:
                raise ValueError("refinement request constraints are malformed")
            atoms, distance = item["atoms"], item["distance_angstrom"]
            if (not isinstance(atoms, list) or len(atoms) != 2
                    or any(type(index) is not int or not 0 <= index < 21 for index in atoms)
                    or atoms[0] == atoms[1] or isinstance(distance, bool)
                    or not isinstance(distance, (int, float)) or not math.isfinite(float(distance))
                    or not 0.5 <= float(distance) <= 5.0):
                raise ValueError("refinement request constraints exceed the numeric template limits")
            rows.append(f"  {{ B {atoms[0]} {atoms[1]} {float(distance):.6f} C }}\n")
        method = f"! {prefix} TightSCF Opt TightOpt"
        extra = "%scf\n  MaxIter 400\nend\n%geom\n  MaxIter 60\n  Constraints\n" + "".join(rows) + "  end\nend\n"
    elif stage == "optts":
        bond, active = request.get("ts_mode_bond"), request.get("ts_active_atoms")
        if (not isinstance(bond, list) or len(bond) != 2
                or any(type(index) is not int or not 0 <= index < 21 for index in bond)
                or bond[0] == bond[1] or not isinstance(active, list) or not active
                or any(type(index) is not int or not 0 <= index < 21 for index in active)
                or len(set(active)) != len(active)):
            raise ValueError("OptTS request lacks bounded mode-bond or active-atom indices")
        method = f"! {prefix} VeryTightSCF OptTS TightOpt"
        extra = ("%scf\n  MaxIter 400\nend\n%geom\n  Calc_Hess true\n  MaxIter 60\n  Recalc_Hess 10\n"
                 f"  TS_Mode {{ B {bond[0]} {bond[1]} }} end\n  TS_Active_Atoms {{ {' '.join(map(str, active))} }} end\nend\n")
    elif stage in {"ts_frequency", "endpoint_frequency"}:
        method = f"! {prefix} VeryTightSCF AnFreq"
        extra = "%scf\n  MaxIter 400\n  ConvCheckMode 0\n  ConvForced 1\nend\n%method\n  Z_Tol 1e-6\n  Z_MaxIter 128\nend\n"
    elif stage == "endpoint_opt":
        method = f"! {prefix} VeryTightSCF Opt TightOpt"
        extra = "%scf\n  MaxIter 400\nend\n%geom\n  MaxIter 100\nend\n"
    else:
        raise ValueError("request is not an ORCA stage")
    return f"{method}\n%pal nprocs 8 end\n%maxcore 1400\n{extra}* xyzfile 0 2 start.xyz\n"


def _audit_queue_debits(snapshot: Mapping[str, Any], start: datetime, end: datetime,
                        allocations: list[tuple[datetime, datetime, str]]) -> tuple[float, str | None]:
    debits = snapshot.get("queue_debits", [])
    if not isinstance(debits, list):
        return 0, "queue debit records are malformed"
    intervals: list[tuple[datetime, datetime]] = []
    total = 0.0
    for debit in debits:
        if not isinstance(debit, Mapping) or set(debit) != {"job_id", "start_utc", "end_utc"}:
            return 0, "queue debit record is malformed"
        a, b = _parse_utc(debit.get("start_utc")), _parse_utc(debit.get("end_utc"))
        if not isinstance(debit.get("job_id"), str) or not debit["job_id"]:
            return 0, "derived queue debit has no allocation identity"
        if b <= a or a < start or b > end:
            return 0, "queue debit is reversed or outside the active attempt window"
        if any(a < x[1] and b > x[0] for x in intervals):
            return 0, "queue debit intervals overlap"
        if any(a < alloc_end and b > alloc_start for alloc_start, alloc_end, _ in allocations):
            return 0, "queue debit overlaps an executing scheduler allocation"
        intervals.append((a, b))
        total += (b - a).total_seconds()
    return total, None


def _derive_queue_debits(context: Mapping[str, Any], rows: list[dict[str, Any]],
                         attempt_start: str, report_end: str) -> tuple[list[dict[str, str]], str]:
    """Recompute queue intervals from trusted v2 certificates; ignore summaries."""
    module_path = Path(queue_certificate.__file__)
    if (module_path.is_symlink() or not module_path.is_file()
            or file_sha256(module_path) != QUEUE_CERTIFICATE_SOURCE_SHA256):
        raise ValueError("pinned pure queue-certificate auditor bytes changed")
    certificates = context.get("queue_certificates", [])
    if not isinstance(certificates, list):
        raise ValueError("trusted queue certificate list is malformed")
    if not certificates:
        return [], "no source-bound queue certificate; no queue time excluded"
    receipts = context.get("allocation_submission_receipts")
    producer_pin = context.get("queue_certificate_producer_source_sha256")
    events = context.get("execution_events")
    events_sha = context.get("execution_events_sha256")
    if (not isinstance(receipts, Mapping) or not _valid_hash(producer_pin)
            or not isinstance(events, list) or not _valid_hash(events_sha)
            or canonical_sha256(events) != events_sha):
        return [], "queue certificate source/event pins are unavailable; no queue time excluded"
    by_job = {str(row["job_id"]): row for row in rows}
    if len(by_job) != len(rows):
        raise ValueError("scheduler allocation job IDs are not unique")
    seen_jobs: set[str] = set()
    allocation_intervals = [(row["start_utc"], row["end_utc"], row["job_id"]) for row in rows]
    debits: list[dict[str, str]] = []
    review_reasons = []
    for certificate in certificates:
        if not isinstance(certificate, Mapping):
            raise ValueError("trusted queue certificate entry is malformed")
        job = certificate.get("job_id")
        if not isinstance(job, str) or job not in by_job or job in seen_jobs:
            raise ValueError("queue certificate does not uniquely identify a sealed root allocation")
        seen_jobs.add(job)
        receipt = receipts.get(job)
        if not isinstance(receipt, Mapping):
            raise ValueError("queue certificate allocation receipt is absent")
        attempt = context.get("attempt_id")
        workdir = receipt.get("workdir")
        if workdir is None:
            history = certificate.get("scontrol_history")
            first = history[0] if isinstance(history, list) and history else None
            raw = first.get("raw_text") if isinstance(first, Mapping) else None
            match = re.search(r"(?:^|\s)WorkDir=(/\S+)", raw) if isinstance(raw, str) else None
            workdir = match.group(1) if match else None
        if (not isinstance(workdir, str) or not workdir.startswith("/")
                or ".." in Path(workdir).parts):
            raise ValueError("trusted queue certificate has no valid scheduler workdir")
        result = queue_certificate.audit_queue_certificate(
            certificate, attempt_id=attempt, job_id=job,
            request_sha256=receipt.get("request_sha256"),
            source_manifest_sha256=receipt.get("source_manifest_sha256"),
            producer_source_sha256=producer_pin, workdir=workdir,
            attempt_started_at_utc=attempt_start, report_submitted_at_utc=report_end,
            trusted_execution_events=events, allocated_intervals=allocation_intervals)
        if result.status == "ENV_INVALID":
            raise ValueError("trusted queue certificate invalid: " + result.reason)
        if result.status != "PASS":
            review_reasons.append(result.reason)
            continue
        for start_utc, end_utc in result.credited_intervals:
            debits.append({"job_id": job, "start_utc": start_utc, "end_utc": end_utc})
    # The host's queue_debits field is intentionally ignored: only intervals
    # recomputed from the raw v2 certificate enter resource accounting.
    reason = ("source-bound adjacent PENDING samples audited"
              if not review_reasons else "; ".join(review_reasons))
    return debits, reason


def audit_resource_snapshot(snapshot: Any, scheduler_rows: list[dict[str, Any]] | None = None,
                            attempt_started_at_utc: str | None = None,
                            report_submitted_at_utc: str | None = None) -> tuple[str, str]:
    if not isinstance(snapshot, Mapping):
        return "REVIEW_REQUIRED", "authenticated resource snapshot is absent"
    try:
        captured = _parse_utc(snapshot["captured_at_utc"])
        started = _parse_utc(attempt_started_at_utc)
        submitted = _parse_utc(report_submitted_at_utc)
        if captured < submitted:
            return "ENV_INVALID", "resource snapshot predates sealed report submission"
        if not scheduler_rows:
            return "REVIEW_REQUIRED", "scheduler allocation rows are missing"
        # Account every root allocation, including failed/cancelled retries.
        core_hours = 0.0
        intervals = []
        for row in scheduler_rows:
            alloc_start = _parse_utc(row["start_utc"])
            alloc_end = _parse_utc(row["end_utc"])
            if alloc_end < alloc_start or alloc_start < started:
                return "ENV_INVALID", f"allocation {row['job_id']} has an invalid interval"
            elapsed, cores, cpu_raw = int(row["elapsed_raw"]), int(row["alloc_cpus"]), int(row["cpu_time_raw"])
            if cores <= 0 or cpu_raw != elapsed * cores:
                return "ENV_INVALID", f"allocation {row['job_id']} accounting is inconsistent"
            if cores > 8:
                return "FAIL", "an allocation exceeds the 8-core limit"
            core_hours += cpu_raw / 3600
            intervals.append((alloc_start, alloc_end, row["job_id"], cores))
        if core_hours > 64:
            return "FAIL", "allocated core-hours exceed 64"
        boundaries = sorted({point for a, b, *_ in intervals for point in (a, b)})
        if any(sum(x[3] for x in intervals if x[0] < right and x[1] > left) > 8
               for left, right in zip(boundaries, boundaries[1:])):
            return "FAIL", "concurrent allocations exceed eight cores"
        active_window = (submitted - started).total_seconds()
        debit_seconds, queue_error = _audit_queue_debits(
            snapshot, started, submitted, [(a, b, job) for a, b, job, _ in intervals])
        if queue_error:
            return "ENV_INVALID", queue_error
        if active_window - debit_seconds > 8 * 3600:
            return "FAIL", "active attempt wall time exceeds eight hours"
        # A single aggregate cgroup/volume measurement cannot certify multiple
        # jobs, especially failed/retried jobs. Require distinct per-job records.
        if len(scheduler_rows) > 1:
            per_job = snapshot.get("resources_by_job")
            if not isinstance(per_job, Mapping) or set(per_job) != {r["job_id"] for r in scheduler_rows}:
                return "REVIEW_REQUIRED", "per-job resource measurements are required for multiple allocations"
            return "REVIEW_REQUIRED", "per-job resource schema is not yet supported"
        cgroup = snapshot.get("cgroup")
        if not isinstance(cgroup, Mapping):
            return "REVIEW_REQUIRED", "cgroup measurements are missing"
        if cgroup.get("memory_limit_bytes") is None or cgroup.get("peak_bytes") is None:
            return "REVIEW_REQUIRED", "cgroup memory limit or peak measurement is missing"
        raw_cgroup = snapshot.get("cgroup_raw")
        if isinstance(raw_cgroup, str):
            raw_digest = snapshot.get("cgroup_raw_sha256")
            if not _valid_hash(raw_digest):
                return "REVIEW_REQUIRED", "raw current-job cgroup digest is missing"
            if hashlib.sha256(raw_cgroup.encode()).hexdigest() != raw_digest:
                return "ENV_INVALID", "raw current-job cgroup digest mismatch"
            proof = json.loads(raw_cgroup, object_pairs_hook=_unique_pairs)
            if not isinstance(proof, Mapping) or proof.get("schema") != "case07-cgroup-files/v1":
                return "REVIEW_REQUIRED", "raw current-job cgroup schema is unsupported"
            raw_limits = proof.get("memory_limit_file_values")
            raw_cpusets = proof.get("cpuset_file_values")
            if not isinstance(raw_limits, list) or not raw_limits or not isinstance(raw_cpusets, list) or not raw_cpusets:
                return "REVIEW_REQUIRED", "raw ancestor memory/cpuset rows are missing"
            measured_limits = []
            for raw_limit in raw_limits:
                if raw_limit in ("max", ""):
                    continue
                if not isinstance(raw_limit, str) or not raw_limit.isdecimal():
                    return "ENV_INVALID", "raw cgroup memory limit is malformed"
                amount = int(raw_limit)
                if 0 < amount < 1 << 60:
                    measured_limits.append(amount)
            if not measured_limits:
                return "REVIEW_REQUIRED", "raw cgroup has no finite memory limit"
            mem_limit = min(measured_limits)
            parsed_sets = [_cpu_set(value) for value in raw_cpusets]
            if any(not value for value in parsed_sets):
                return "REVIEW_REQUIRED", "raw cgroup cpuset includes an unreadable ancestor"
            effective_set = parsed_sets[0]
            ancestor_set = set.intersection(*parsed_sets)
            if (not ancestor_set or cgroup.get("memory_limit_bytes") != mem_limit
                    or cgroup.get("ancestor_memory_limits_bytes") != sorted(set(measured_limits))
                    or cgroup.get("cpuset_effective") != _format_cpu_set(effective_set)
                    or cgroup.get("ancestor_cpuset") != _format_cpu_set(ancestor_set)):
                return "ENV_INVALID", "cgroup summary disagrees with raw ancestor files"
        else:
            mem_limit = _finite_nonnegative(cgroup["memory_limit_bytes"], "cgroup memory limit")
        mem_peak = _finite_nonnegative(cgroup["peak_bytes"], "cgroup memory peak")
        if mem_limit > 16 * 1024**3:
            return "FAIL", "job cgroup memory limit exceeds 16 GiB"
        ancestor_limits = cgroup.get("ancestor_memory_limits_bytes", cgroup.get("ancestor_limits"))
        if not isinstance(ancestor_limits, list) or not ancestor_limits:
            return "REVIEW_REQUIRED", "ancestor cgroup memory limits are missing"
        finite_limits = []
        for limit in ancestor_limits:
            if limit in (None, "max", "unlimited"):
                continue
            finite_limits.append(_finite_nonnegative(limit, "ancestor cgroup memory limit"))
        effective_limits = [mem_limit] + finite_limits
        effective_limit = min(effective_limits)
        if mem_peak > effective_limit or effective_limit > 16 * 1024**3:
            return "FAIL", "effective ancestor/job cgroup memory limit or peak exceeds 16 GiB"
        cpuset = _cpu_set(cgroup.get("cpuset_effective"))
        ancestor_cpuset = _cpu_set(cgroup.get("ancestor_cpuset"))
        if not cpuset or not ancestor_cpuset:
            return "REVIEW_REQUIRED", "effective or ancestor cpuset is not measurable"
        if len(cpuset) > 8:
            return "FAIL", "effective job cpuset exceeds eight cores"
        if not cpuset <= ancestor_cpuset:
            return "ENV_INVALID", "effective job cpuset is outside ancestor cpuset"
        mount_status, mount_reason = _audit_mount_closure(snapshot)
        if mount_status != "PASS":
            return mount_status, mount_reason
        return "PASS", "sealed attempt and evaluator resource snapshot are within the declared envelope"
    except (KeyError, TypeError, ValueError, OverflowError) as exc:
        return "ENV_INVALID", f"malformed evaluator resource snapshot: {exc}"


def _cpu_set(value: Any) -> set[int]:
    if not isinstance(value, str) or not value.strip():
        return set()
    cpus: set[int] = set()
    for part in value.split(","):
        vals = part.split("-")
        if len(vals) == 1:
            cpus.add(int(vals[0]))
        elif len(vals) == 2:
            low, high = map(int, vals)
            if high < low or high - low > 100000:
                raise ValueError("invalid CPU set range")
            cpus.update(range(low, high + 1))
        else:
            raise ValueError("invalid CPU set")
    return cpus


def _format_cpu_set(values: set[int]) -> str:
    ordered = sorted(values)
    if not ordered:
        return ""
    out, low, high = [], ordered[0], ordered[0]
    for value in ordered[1:]:
        if value == high + 1:
            high = value
        else:
            out.append(str(low) if low == high else f"{low}-{high}")
            low = high = value
    out.append(str(low) if low == high else f"{low}-{high}")
    return ",".join(out)


def _unescape_mount_field(value: str) -> str:
    return re.sub(r"\\([0-7]{3})", lambda m: chr(int(m.group(1), 8)), value)


def _parse_mountinfo(raw: Any) -> dict[int, dict[str, Any]]:
    if not isinstance(raw, str) or not raw:
        raise ValueError("raw mountinfo evidence is missing")
    mounts = {}
    for line in raw.splitlines():
        before, sep, after = line.partition(" - ")
        left, right = before.split(), after.split()
        if not sep or len(left) < 6 or len(right) < 3:
            raise ValueError("raw mountinfo row is malformed")
        mount_id, major_minor = int(left[0]), left[2]
        path = _unescape_mount_field(left[4])
        # Mount writability is controlled by the per-mount VFS flags.  A
        # read-only bind can sit on a read-write superblock, so a union of
        # options incorrectly promotes VFS ``ro`` + superblock ``rw``.
        vfs_options = set(left[5].split(","))
        super_options = set(right[2].split(","))
        row = {"mount_id": mount_id, "parent": int(left[1]), "major_minor": major_minor,
               "root": _unescape_mount_field(left[3]), "path": path,
               "fstype": right[0], "source": _unescape_mount_field(right[1]),
               "vfs_options": vfs_options, "super_options": super_options,
               "rw": "ro" not in vfs_options and "ro" not in super_options}
        if mount_id in mounts:
            raise ValueError("duplicate mount ID in raw mountinfo")
        mounts[mount_id] = row
    if not mounts:
        raise ValueError("raw mountinfo has no mount rows")
    return mounts


def _audit_mount_closure(snapshot: Mapping[str, Any]) -> tuple[str, str]:
    # Production snapshots carry the three evaluator-reparsable proofs emitted
    # by the contained SUID mount audit.  The compact writable_mounts form is
    # retained only for old test fixtures and can never certify the current
    # production resource profile because it has no FD/shadow-parent proof.
    if all(key in snapshot for key in ("container_probe_raw", "mount_audit_raw", "mount_audit")):
        return _audit_driver_mount_closure(snapshot)
    raw, raw_hash = snapshot.get("mountinfo_raw"), snapshot.get("mountinfo_sha256")
    if not isinstance(raw, str) or not _valid_hash(raw_hash):
        return "REVIEW_REQUIRED", "raw mountinfo closure evidence is missing"
    if hashlib.sha256(raw.encode("utf-8")).hexdigest() != raw_hash:
        return "ENV_INVALID", "raw mountinfo digest mismatch"
    mounts = _parse_mountinfo(raw)
    declared = snapshot.get("writable_mounts")
    exclusions = snapshot.get("mount_exclusions")
    if not isinstance(declared, list) or not isinstance(exclusions, list):
        return "REVIEW_REQUIRED", "FD/shadow-parent mount inventory is missing"
    declared_by_id, excluded_by_id = {}, {}
    for item in declared:
        if not isinstance(item, Mapping) or isinstance(item.get("mount_id"), bool):
            return "ENV_INVALID", "writable mount inventory row is malformed"
        mid = int(item["mount_id"])
        if mid in declared_by_id:
            return "ENV_INVALID", "duplicate writable mount inventory ID"
        declared_by_id[mid] = item
    for item in exclusions:
        if not isinstance(item, Mapping) or isinstance(item.get("mount_id"), bool):
            return "ENV_INVALID", "mount exclusion row is malformed"
        mid = int(item["mount_id"])
        if mid in excluded_by_id:
            return "ENV_INVALID", "duplicate mount exclusion ID"
        excluded_by_id[mid] = item
    virtual_fs = {"proc", "sysfs", "cgroup", "cgroup2", "devpts", "mqueue", "securityfs",
                  "debugfs", "tracefs", "configfs", "fusectl", "pstore", "bpf", "autofs",
                  "nsfs", "rpc_pipefs", "hugetlbfs", "binfmt_misc"}
    raw_rw_ids = {mid for mid, row in mounts.items() if row["rw"]}
    if set(declared_by_id) & set(excluded_by_id) or set(declared_by_id) | set(excluded_by_id) != raw_rw_ids:
        return "REVIEW_REQUIRED", "raw mountinfo is not completely classified as writable storage or qualified exclusion"
    unique_sources: dict[str, int] = {}
    for mid, item in declared_by_id.items():
        raw_row = mounts[mid]
        for key in ("path", "fstype", "source", "major_minor"):
            if item.get(key) != raw_row[key]:
                return "ENV_INVALID", f"writable mount inventory differs from mountinfo: {key}"
        if item.get("rw") is not True or item.get("user_writable") is not True:
            return "REVIEW_REQUIRED", "mount lacks a successful user write probe"
        if not _valid_hash(item.get("write_probe_sha256")):
            return "REVIEW_REQUIRED", "user-writable mount lacks a bound write-probe receipt"
        if item.get("capacity_bytes") is None or item.get("available_bytes") is None:
            return "REVIEW_REQUIRED", "writable mount capacity/available measurement is missing"
        capacity, available = int(item["capacity_bytes"]), int(item["available_bytes"])
        if capacity < 0 or available < 0 or available > capacity:
            return "ENV_INVALID", "writable mount capacity measurements are invalid"
        source_key = f"{raw_row['major_minor']}:{raw_row['source']}"
        unique_sources[source_key] = max(unique_sources.get(source_key, 0), capacity)
    for mid, item in excluded_by_id.items():
        raw_row = mounts[mid]
        classification = item.get("classification")
        proof_text, proof_hash = item.get("raw_evidence_text"), item.get("evidence_sha256")
        if not isinstance(proof_text, str) or not _valid_hash(proof_hash):
            return "REVIEW_REQUIRED", "mount exclusion lacks raw access-probe evidence"
        if hashlib.sha256(proof_text.encode()).hexdigest() != proof_hash:
            return "ENV_INVALID", "mount exclusion evidence digest mismatch"
        try:
            proof = json.loads(proof_text)
        except json.JSONDecodeError:
            return "ENV_INVALID", "mount exclusion evidence is malformed"
        if (not isinstance(proof, Mapping) or proof.get("mount_id") != mid
                or proof.get("user_writable") is not False
                or proof.get("classification") != classification):
            return "ENV_INVALID", "mount exclusion evidence does not prove non-writability/classification"
        if raw_row["fstype"] in virtual_fs:
            if classification != "kernel_virtual":
                return "ENV_INVALID", "kernel virtual mount has an invalid exclusion class"
        elif classification == "file_bind_nonwritable":
            if raw_row["root"] == "/" or proof.get("target_type") != "file":
                return "ENV_INVALID", "file-bind exclusion is not a qualified file bind"
        elif classification != "not_user_writable":
            return "REVIEW_REQUIRED", "ordinary writable mount exclusion is not qualified"
    try:
        total_capacity = sum(unique_sources.values())
        declared_total = int(snapshot["scratch_total_bytes"])
    except (KeyError, TypeError, ValueError):
        return "REVIEW_REQUIRED", "total user-writable storage capacity is missing"
    if declared_total != total_capacity:
        return "ENV_INVALID", "scratch_total_bytes differs from deduplicated, probed writable mount capacity"
    if declared_total > 20 * 1024**3:
        return "FAIL", "total user-writable scratch capacity exceeds 20 GiB"
    return "REVIEW_REQUIRED", "legacy mount summary lacks contained FD/shadow-parent closure proof"


def _audit_driver_mount_closure(snapshot: Mapping[str, Any]) -> tuple[str, str]:
    """Independently validate the current mount-audit/v1 transcript.

    Recomputes effective mounts and user-write probes from raw mountinfo and
    the contained FD walk. The parsed JSON summary is only cross-checked; it
    never supplies missing proof.
    """
    raw_keys = (("mountinfo_raw", "mountinfo_sha256"),
                ("container_probe_raw", "container_probe_sha256"),
                ("mount_audit_raw", "mount_audit_sha256"))
    for raw_key, digest_key in raw_keys:
        raw, digest = snapshot.get(raw_key), snapshot.get(digest_key)
        if not isinstance(raw, str) or not _valid_hash(digest):
            return "REVIEW_REQUIRED", f"raw {raw_key} mount proof is missing"
        if hashlib.sha256(raw.encode()).hexdigest() != digest:
            return "ENV_INVALID", f"raw {raw_key} mount proof digest mismatch"
    try:
        audit = json.loads(snapshot["mount_audit_raw"], object_pairs_hook=_unique_pairs)
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        return "ENV_INVALID", f"raw mount audit JSON is invalid: {exc}"
    if not isinstance(audit, Mapping) or audit != snapshot.get("mount_audit"):
        return "ENV_INVALID", "parsed mount audit differs from sealed raw JSON"
    if audit.get("schema") != "case07-mount-audit/v1":
        return "REVIEW_REQUIRED", "current mount audit schema is unsupported"
    mounts = _parse_mountinfo(snapshot["mountinfo_raw"])
    inventory: dict[int, dict[str, Any]] = {}
    results: dict[int, list[list[str]]] = {}
    writes: dict[int, list[list[str]]] = {}
    count = None
    completed = False
    for line in snapshot["container_probe_raw"].splitlines():
        if line.startswith("MOUNT_INVENTORY_COUNT|"):
            try:
                count = int(line.split("|", 1)[1])
            except ValueError:
                return "ENV_INVALID", "contained mount inventory count is malformed"
        elif line == "inside_probe_completed=1":
            completed = True
        elif line.startswith("MOUNT|"):
            f = line.split("|")
            if len(f) != 9:
                return "ENV_INVALID", "contained mount row is malformed"
            try:
                mid = int(f[1])
            except ValueError:
                return "ENV_INVALID", "contained mount ID is malformed"
            if mid in inventory:
                return "ENV_INVALID", "contained mount ID is repeated"
            inventory[mid] = {"parent": f[2], "device": f[3], "path": f[4],
                              "vfs": f[5], "fstype": f[6], "source": f[7], "super": f[8]}
        elif line.startswith("MOUNT_RESULT|"):
            f = line.split("|")
            if len(f) < 5:
                return "ENV_INVALID", "contained FD mount result is malformed"
            try:
                results.setdefault(int(f[1]), []).append(f[1:])
            except ValueError:
                return "ENV_INVALID", "contained FD mount ID is malformed"
        elif line.startswith("WRITE_PROBE|"):
            f = line.split("|")
            if len(f) != 10:
                return "ENV_INVALID", "contained mount write probe is malformed"
            try:
                writes.setdefault(int(f[1]), []).append(f[1:])
            except ValueError:
                return "ENV_INVALID", "contained write-probe mount ID is malformed"
    if not completed or count != len(mounts) or set(inventory) != set(mounts):
        return "REVIEW_REQUIRED", "contained FD inventory does not close over raw mountinfo"
    if audit.get("mountinfo_entry_count") != len(mounts) or audit.get("mount_ids_seen") != len(mounts):
        return "ENV_INVALID", "mount audit counts differ from the raw mount inventory"
    for mid, row in mounts.items():
        seen = inventory[mid]
        if (seen["parent"] != str(row["parent"]) or seen["device"] != row["major_minor"]
                or seen["path"] != row["path"] or seen["vfs"] != ",".join(sorted(row["vfs_options"]))
                or seen["fstype"] != row["fstype"] or seen["source"] != row["source"]
                or seen["super"] != ",".join(sorted(row["super_options"]))):
            # The transcript preserves option order on some kernels. Compare
            # sets, while requiring every other raw field byte-for-byte.
            if (seen["parent"] != str(row["parent"]) or seen["device"] != row["major_minor"]
                    or seen["path"] != row["path"] or set(seen["vfs"].split(",")) != row["vfs_options"]
                    or seen["fstype"] != row["fstype"] or seen["source"] != row["source"]
                    or set(seen["super"].split(",")) != row["super_options"]):
                return "ENV_INVALID", "contained mount row differs from raw mountinfo"
    shadowed: dict[int, int] = {}
    effective: set[int] = set()
    for mid, rows in results.items():
        for row in rows:
            if row[2] == "SHADOWED_BY_EFFECTIVE_MOUNT":
                if len(row) != 5:
                    return "ENV_INVALID", "FD shadow-parent row is malformed"
                try:
                    child_id = int(row[4])
                except ValueError:
                    return "ENV_INVALID", "FD shadow child ID is malformed"
                if (mid not in mounts or child_id not in mounts
                        or mounts[child_id]["parent"] != mid
                        or mounts[child_id]["path"] != row[1]
                        or mounts[mid]["path"] != row[1]):
                    return "ENV_INVALID", "FD shadow-parent chain disagrees with raw mountinfo"
                shadowed[mid] = child_id
            elif row[2] == "EFFECTIVE_MATCH":
                if len(row) != 4 or mid not in mounts or row[1] != mounts[mid]["path"]:
                    return "ENV_INVALID", "FD effective mount proof is malformed"
                effective.add(mid)
            elif row[2] == "EFFECTIVE_ID_UNKNOWN":
                return "REVIEW_REQUIRED", "FD mount ID could not be authenticated"
            elif row[2] == "DEVICE_NODE_NO_DATA_WRITE":
                effective.add(mid)
    ordinary_probe_ids = set()
    fs_caps: dict[tuple[str, str, str], int] = {}
    fs_paths: dict[tuple[str, str, str], set[str]] = {}
    for mid, rows in writes.items():
        if len(rows) != 1:
            return "ENV_INVALID", "mount repeats a user write probe"
        row = rows[0]
        if mid not in mounts or mid in shadowed or mid not in effective:
            return "ENV_INVALID", "write probe is not bound to an effective FD mount"
        mount = mounts[mid]
        if (row[1] != mount["path"] or row[4] != mount["fstype"] or row[5] != mount["major_minor"]
                or not row[3].startswith("PASS")):
            return "REVIEW_REQUIRED", "effective mount lacks a passing bound write probe"
        try:
            fsid = row[6].split()[0]
            capacity = int(row[7]) * 1024
        except (IndexError, ValueError):
            return "ENV_INVALID", "write-probe capacity is malformed"
        if not fsid or capacity <= 0:
            return "REVIEW_REQUIRED", "write-probe capacity is missing"
        key = (mount["major_minor"], fsid, mount["fstype"])
        fs_caps[key] = max(fs_caps.get(key, 0), capacity)
        fs_paths.setdefault(key, set()).add(mount["path"])
        ordinary_probe_ids.add(mid)
    pseudo = {"proc", "sysfs", "devpts", "cgroup", "cgroup2", "bpf", "tracefs",
              "debugfs", "securityfs", "configfs", "fusectl"}
    for mid, mount in mounts.items():
        if mid in shadowed:
            continue
        readonly = ("ro" in mount["vfs_options"] or "ro" in mount["super_options"])
        if readonly or mount["fstype"] in pseudo or mid in ordinary_probe_ids:
            continue
        if mid in effective and mount["fstype"] == "mqueue":
            return "REVIEW_REQUIRED", "writable mqueue lacks a read-only proof"
        return "REVIEW_REQUIRED", "ordinary mount lacks a complete effective write-probe or read-only proof"
    required_paths = {"/work", "/tmp", "/var/tmp", "/home", "/dev/shm"}
    for path in required_paths:
        active = [mid for mid, row in mounts.items() if row["path"] == path and mid not in shadowed]
        if len(active) != 1 or active[0] not in ordinary_probe_ids:
            return "REVIEW_REQUIRED", f"bounded writable volume {path} lacks a unique effective write probe"
    if audit.get("effective_writable_probe_count") != len(writes):
        return "ENV_INVALID", "mount audit effective write-probe count differs"
    volume_bytes = 5 * 3968 * 1024**2
    if (audit.get("configured_five_volume_bytes") != volume_bytes
            or audit.get("session_reserve_bytes") != 64 * 1024**2
            or audit.get("bounded_export_reserve_bytes") != 512 * 1024**2
            or audit.get("bounded_control_reserve_bytes") != 64 * 1024**2
            or audit.get("configured_total_bytes") != volume_bytes + 640 * 1024**2
            or audit.get("production_scratch_cap_bytes") != 20 * 1024**3):
        return "REVIEW_REQUIRED", "bounded scratch or host storage guard profile is incomplete"
    if audit.get("writable_closure_status") != "PASS" or audit.get("capacity_status") != "WITHIN_CAP" or audit.get("unverified"):
        return "REVIEW_REQUIRED", "mount audit did not certify a complete writable closure"
    actual_rows = [{"device": d, "fsid": f, "fstype": fs, "capacity_bytes": cap,
                    "mounts": sorted(fs_paths[(d, f, fs)])}
                   for (d, f, fs), cap in fs_caps.items()]
    actual_rows.sort(key=lambda x: (x["device"], x["fsid"], x["fstype"]))
    summarized_rows = audit.get("unique_writable_filesystems")
    if not isinstance(summarized_rows, list):
        return "REVIEW_REQUIRED", "mount audit lacks unique writable filesystem summary"
    normalized_rows = [{key: item.get(key) for key in
                        ("device", "fsid", "fstype", "capacity_bytes", "mounts")}
                       for item in summarized_rows if isinstance(item, Mapping)]
    normalized_rows.sort(key=lambda x: (x["device"], x["fsid"], x["fstype"]))
    if normalized_rows != actual_rows:
        return "ENV_INVALID", "mount audit filesystem summary differs from raw write probes"
    capacity_total = sum(fs_caps.values())
    if (audit.get("unique_writable_capacity_bytes") != capacity_total
            or snapshot.get("scratch_total_bytes") != capacity_total):
        return "ENV_INVALID", "scratch capacity differs from deduplicated effective write probes"
    if capacity_total > 20 * 1024**3:
        return "FAIL", "total user-writable scratch capacity exceeds 20 GiB"
    return "PASS", "raw mountinfo, FD shadow chain, write probes, and bounded mount summary agree"


def _unique_pairs(pairs):
    out = {}
    for key, value in pairs:
        if key in out:
            raise ValueError("duplicate JSON object key")
        out[key] = value
    return out


def _review_criterion(value: Any, manifest: Mapping[str, str], public: Mapping[str, str]) -> str:
    if not isinstance(value, Mapping) or value.get("status") not in {"PASS", "FAIL", "REVIEW_REQUIRED"}:
        raise ValueError("external review criterion has invalid status")
    evidence = value.get("evidence")
    if not isinstance(evidence, list) or not evidence:
        raise ValueError("external review criterion lacks evidence")
    for item in evidence:
        if not isinstance(item, Mapping) or not _valid_hash(item.get("sha256")) or not _safe_relative(item.get("path")):
            raise ValueError("external review evidence record is malformed")
        found = manifest.get(item["path"], public.get(item["path"]))
        if found != item["sha256"]:
            raise ValueError("external review evidence hash is not bound to sealed artifacts or inputs")
    return value["status"]


def _audit_static_external_deployment(value: Any, context: Mapping[str, Any], attempt: str,
                                     scheduler_rows: list[dict[str, Any]]) -> tuple[str, str]:
    """Recompute the immutable source/assets deployment proof; never trust a status label."""
    if value is None:
        return "REVIEW_REQUIRED", "static deployment manifest and node before/after proof are absent"
    if not isinstance(value, Mapping) or value.get("schema") != "case07-static-deployment-proof/v1":
        return "ENV_INVALID", "static external deployment proof schema is malformed"
    raw = value.get("deployment_manifest_raw")
    raw_sha = value.get("deployment_manifest_raw_sha256")
    sidecar = value.get("deployment_manifest_digest_file_text")
    if (not isinstance(raw, str) or not _valid_hash(raw_sha)
            or hashlib.sha256(raw.encode("utf-8")).hexdigest() != raw_sha
            or not isinstance(sidecar, str)):
        return "ENV_INVALID", "host deployment manifest bytes or external digest are invalid"
    try:
        manifest = json.loads(raw, object_pairs_hook=_unique_pairs,
                              parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)))
    except (ValueError, json.JSONDecodeError) as exc:
        return "ENV_INVALID", f"host deployment manifest is malformed: {exc}"
    if not isinstance(manifest, Mapping):
        return "ENV_INVALID", "host deployment manifest is not an object"
    unsigned = {key: item for key, item in manifest.items() if key != "manifest_sha256"}
    inner_sha = canonical_sha256(unsigned)
    if (manifest.get("schema") != "case07-host-deployment-manifest/v1"
            or manifest.get("manifest_sha256") != inner_sha
            or sidecar != raw_sha + "\n"
            or manifest.get("attempt_id") != attempt
            or value.get("attempt_id") != attempt
            or not _valid_hash(manifest.get("intent_sha256"))
            or not _valid_hash(manifest.get("source_manifest_sha256"))):
        return "ENV_INVALID", "host deployment manifest digest or attempt binding is invalid"
    if (manifest.get("static_cap_bytes") != 16*1024**2
            or manifest.get("control_cap_bytes") != 48*1024**2
            or manifest.get("total_cap_bytes") != 64*1024**2):
        return "ENV_INVALID", "host deployment manifest cap profile differs from Case07"
    files = manifest.get("files")
    if not isinstance(files, Mapping):
        return "ENV_INVALID", "host deployment manifest file map is malformed"
    static_files = {}
    control_baseline_bytes = 0
    total_bytes = 0
    for path, entry in files.items():
        if not _safe_relative(path) or not isinstance(entry, Mapping):
            return "ENV_INVALID", "host deployment manifest contains an unsafe file record"
        if type(entry.get("bytes")) is not int or entry["bytes"] < 0 or not _valid_hash(entry.get("sha256")):
            return "ENV_INVALID", "host deployment manifest file record is malformed"
        total_bytes += entry["bytes"]
        if path.startswith("control/"):
            control_baseline_bytes += entry["bytes"]
        if path.startswith(("bundle/", "assets/")):
            static_files[path] = {"sha256":entry["sha256"],"bytes":entry["bytes"]}
    static_bytes = sum(entry["bytes"] for entry in static_files.values())
    if (not static_files or type(manifest.get("static_bytes")) is not int
            or static_bytes != manifest.get("static_bytes")
            or static_bytes > 16*1024**2
            or type(manifest.get("control_baseline_bytes")) is not int
            or control_baseline_bytes != manifest["control_baseline_bytes"]
            or not 0 <= manifest["control_baseline_bytes"] <= 48*1024**2
            or total_bytes > 64*1024**2):
        return "FAIL", "host deployment source/assets exceed or misstate their reserved bytes"
    job_id = value.get("job_id")
    if (len(scheduler_rows) != 1 or not isinstance(job_id, str)
            or scheduler_rows[0].get("job_id") != job_id):
        return "REVIEW_REQUIRED", "static deployment observation is not scoped to the unique current allocation"
    receipt_map = context.get("allocation_submission_receipts")
    receipt = receipt_map.get(job_id) if isinstance(receipt_map, Mapping) else None
    if (not isinstance(receipt, Mapping)
            or receipt.get("source_manifest_sha256") != manifest.get("source_manifest_sha256")
            or receipt.get("intent_sha256") != manifest.get("intent_sha256")):
        return "ENV_INVALID", "deployment source/intent manifest is not bound to the actual allocation receipt"
    trusted_sources = context.get("trusted_source_hashes")
    source_path, source_sha = value.get("observer_source_path"), value.get("observer_source_sha256")
    if (not _safe_relative(source_path) or not isinstance(trusted_sources, Mapping)
            or not _valid_hash(source_sha) or trusted_sources.get(source_path) != source_sha):
        return "REVIEW_REQUIRED", "node tree observer source is not pinned by trusted source manifest"
    collected = _parse_utc(context["collected_at_utc"])
    terminal_end = max(_parse_utc(row["end_utc"]) for row in scheduler_rows)
    events = context.get("execution_events")
    if not isinstance(events, list) or not events:
        return "REVIEW_REQUIRED", "trusted native event chain is needed to bound the deployment precheck"
    native_starts = [_parse_utc(event.get("started_at_utc")) for event in events
        if isinstance(event, Mapping) and event.get("kind") == "orca_stage"
        and event.get("stage") in ORCA_STAGES]
    if not native_starts:
        return "REVIEW_REQUIRED", "no trusted native stage event bounds the deployment precheck"
    first_native_start = min(native_starts)
    for key in ("observed_before", "observed_after"):
        observation = value.get(key)
        if not isinstance(observation, Mapping):
            return "REVIEW_REQUIRED", f"node deployment {key} observation is absent"
        observed_at = _parse_utc(observation.get("captured_at_utc"))
        expected_files = {}
        for path, entry in static_files.items():
            observed = observation.get("files", {}).get(path) if isinstance(observation.get("files"), Mapping) else None
            if (not isinstance(observed, Mapping) or observed.get("sha256") != entry["sha256"]
                    or type(observed.get("bytes")) is not int or observed.get("bytes") != entry["bytes"]
                    or type(observed.get("link_count")) is not int or observed.get("link_count") != 1):
                return "ENV_INVALID", f"node {key} bytes/hash/link count differ for {path}"
            expected_files[path] = {"sha256":entry["sha256"],"bytes":entry["bytes"],"link_count":1}
        if (type(observation.get("static_bytes")) is not int
                or observation.get("files") != expected_files
                or observation.get("tree_sha256") != canonical_sha256(expected_files)
                or observation.get("static_bytes") != static_bytes):
            return "ENV_INVALID", f"node {key} file set or tree digest differs from the pinned deployment"
        if key == "observed_before" and observed_at > first_native_start:
            return "ENV_INVALID", "node deployment baseline was captured after the first native stage began"
        if key == "observed_after" and (observed_at < terminal_end or observed_at > collected):
            return "ENV_INVALID", "node deployment postcheck is outside terminal collection bounds"
    return "PASS", "immutable source/assets bytes are bound to host manifest and node pre/post observations"


def _final_durable_commits(records: list[Mapping[str, Any]]) -> dict[str, Mapping[str, Any]]:
    """Keep the last installed payload per final path; a rejected overwrite changes nothing."""
    result: dict[str, Mapping[str, Any]] = {}
    for row in records:
        if (row.get("kind") == "COMMIT" and row.get("domain") == "final"
                and row.get("result") == "WRITTEN" and isinstance(row.get("relative_path"), str)):
            result[row["relative_path"]] = row
    return result


def _audit_external_storage_guard(value: Any, final: Path, context: Mapping[str, Any], attempt: str, report_sha: str,
                                 manifest_sha: str, controller_sha: str) -> tuple[str, str]:
    """Require a control-only pre-write journal; final tree size is insufficient."""
    if value is None:
        return "REVIEW_REQUIRED", "external final/control pre-write storage-guard trace is absent"
    if not isinstance(value, Mapping):
        return "REVIEW_REQUIRED", "storage-guard trace schema is unsupported"
    raw_text, raw_sha = value.get("raw_text"), value.get("raw_sha256")
    if not isinstance(raw_text, str) or not _valid_hash(raw_sha):
        return "REVIEW_REQUIRED", "raw storage-guard JSONL evidence is absent"
    if hashlib.sha256(raw_text.encode("utf-8")).hexdigest() != raw_sha:
        return "ENV_INVALID", "storage-guard JSONL byte digest mismatch"
    try:
        lines = raw_text.splitlines()
        if not lines or any(not line for line in lines):
            raise ValueError("empty trace or line")
        parsed = [json.loads(line, object_pairs_hook=_unique_pairs) for line in lines]
    except (ValueError, json.JSONDecodeError) as exc:
        return "ENV_INVALID", f"storage-guard JSONL is malformed: {exc}"
    header, records = parsed[0], parsed[1:]
    if (not isinstance(header, Mapping) or header.get("schema") != "case07-storage-guard-trace/v1"
            or value.get("header") != header):
        return "REVIEW_REQUIRED", "storage-guard trace header schema is unsupported"
    root_binding = context.get("collection_root_binding")
    final_root = Path(final).resolve(strict=True)
    if not isinstance(root_binding, Mapping):
        return "REVIEW_REQUIRED", "source-to-collected final-root binding is absent"
    if (root_binding.get("collected_final_root") != str(final_root)
            or root_binding.get("artifact_manifest_sha256") != manifest_sha
            or header.get("final_root") != root_binding.get("source_final_root")
            or header.get("attempt_id") != attempt or not isinstance(header.get("job_id"), str)
            or header.get("domain_identity") != {"final":header.get("final_root"),"control":header.get("control_root")}
            or header.get("final_cap_bytes") != 512*1024**2
            or header.get("control_cap_bytes") != 64*1024**2
            or header.get("control_static_external_reserve_bytes") != 16*1024**2
            or header.get("control_traced_cap_bytes") != 48*1024**2
            or header.get("control_cap_bytes") != (header.get("control_static_external_reserve_bytes")
                                                       + header.get("control_traced_cap_bytes"))
            or not _valid_hash(header.get("guard_source_sha256"))
            or not _valid_hash(header.get("inventory_sha256"))):
        return "ENV_INVALID", "storage-guard header is not bound to this final root/profile"
    source_text, inventory_text = value.get("guard_source_text"), value.get("inventory_raw_text")
    if (not isinstance(source_text, str) or hashlib.sha256(source_text.encode()).hexdigest() != header["guard_source_sha256"]
            or not isinstance(inventory_text, str) or hashlib.sha256(inventory_text.encode()).hexdigest() != header["inventory_sha256"]):
        return "ENV_INVALID", "storage-guard source or writer inventory digest mismatch"
    try:
        inventory = json.loads(inventory_text, object_pairs_hook=_unique_pairs)
    except (ValueError, json.JSONDecodeError) as exc:
        return "ENV_INVALID", f"writer inventory JSON is malformed: {exc}"
    if inventory != value.get("inventory") or inventory.get("schema") != "case07-writer-inventory/v1":
        return "ENV_INVALID", "parsed writer inventory differs from its protected bytes"
    accounting = inventory.get("control_accounting")
    if (not isinstance(accounting, Mapping)
            or accounting.get("profile_cap_bytes") != 64*1024**2
            or accounting.get("static_external_reserve_bytes") != 16*1024**2
            or accounting.get("traced_runtime_cap_bytes") != 48*1024**2
            or accounting.get("profile_cap_bytes") != (accounting.get("static_external_reserve_bytes")
                                                          + accounting.get("traced_runtime_cap_bytes"))):
        return "ENV_INVALID", "writer inventory control reserve arithmetic is invalid"
    if value.get("capacity_exhausted") is True:
        return "REVIEW_REQUIRED", "storage-guard journal reported exhausted capacity"
    previous = hashlib.sha256(_canonical_bytes(header)).hexdigest()
    seq = 1
    pending: dict[str, Mapping[str, Any]] = {}
    max_bytes = {"final":0,"control":0}
    for line, row in zip(lines[1:], records):
        if not isinstance(row, Mapping):
            return "ENV_INVALID", "storage-guard journal row is malformed"
        if len(line.encode("utf-8")) + 1 > 2048:
            return "ENV_INVALID", "storage-guard journal row exceeds the fixed bound"
        if _canonical_bytes(row).decode("utf-8") != line:
            return "ENV_INVALID", "storage-guard journal row is not canonical JSON"
        if (type(row.get("seq")) is not int or row["seq"] != seq
                or row.get("previous_sha256") != previous):
            return "ENV_INVALID", "storage-guard journal sequence or previous hash is broken"
        if row.get("record_bytes") != len(line.encode("utf-8")) + 1:
            return "ENV_INVALID", "storage-guard journal record byte count is inconsistent"
        unsigned = {k: v for k, v in row.items() if k != "record_sha256"}
        digest = canonical_sha256(unsigned)
        if not _valid_hash(row.get("record_sha256")) or row["record_sha256"] != digest:
            return "ENV_INVALID", "storage-guard journal row digest mismatch"
        domain, kind, path = row.get("domain"), row.get("kind"), row.get("relative_path")
        if domain not in {"final", "control"} or kind not in {"INTENT", "COMMIT"} or not _safe_relative(path):
            return "ENV_INVALID", "storage-guard event has invalid domain, type, or relative path"
        try:
            _parse_utc(row.get("utc"))
            payload_bytes = row.get("payload_bytes")
            pre = row.get("pre_tree_bytes")
            temp_peak = row.get("temp_peak_bytes")
            post = row.get("post_tree_bytes")
            if any(type(x) is not int or x < 0 for x in (payload_bytes, pre, temp_peak, post)):
                raise ValueError("byte counters must be nonnegative integers")
            if not _valid_hash(row.get("payload_sha256")):
                raise ValueError("payload digest is malformed")
        except (ValueError, TypeError) as exc:
            return "ENV_INVALID", f"storage-guard journal payload is invalid: {exc}"
        cap = 512 * 1024**2 if domain == "final" else 48 * 1024**2
        if pre > cap or post > cap:
            return "FAIL", f"{domain} storage writes exceeded its pre-write cap"
        op = row.get("operation_id")
        if not isinstance(op, str) or not op:
            return "ENV_INVALID", "storage-guard operation ID is missing"
        if kind == "INTENT":
            if op in pending or row.get("result") != "PENDING":
                return "ENV_INVALID", "storage-guard intent is duplicated or not marked pending"
            if row.get("target_installed") is not False or row.get("durable") is not False:
                return "ENV_INVALID", "write intent claims a completed target mutation"
            expected_control_peak = (row.get("control_tree_bytes_before", -1)
                + row.get("record_bytes", -1)
                + (payload_bytes if domain == "control" else 0)
                + row.get("terminal_record_reserve_bytes", -1))
            if (row.get("intent_record_bytes") != row.get("record_bytes")
                    or row.get("terminal_record_reserve_bytes") != 2048
                    or type(row.get("control_tree_bytes_before")) is not int
                    or type(row.get("control_peak_bound_bytes")) is not int
                    or row.get("control_peak_bound_bytes") != expected_control_peak):
                return "ENV_INVALID", "storage-guard intent capacity reservation is inconsistent"
            pending[op] = row
        else:
            intent = pending.pop(op, None)
            if intent is None:
                return "ENV_INVALID", "storage-guard commit lacks its preceding intent"
            for field in ("domain", "relative_path", "payload_bytes", "payload_sha256", "pre_tree_bytes", "temp_peak_bytes"):
                if row.get(field) != intent.get(field):
                    return "ENV_INVALID", "storage-guard commit differs from its intent"
            for field in ("journal_bytes_before", "control_tree_bytes_before", "control_peak_bound_bytes",
                          "target_bytes_before", "target_sha256_before", "terminal_record_reserve_bytes"):
                if row.get(field) != intent.get(field):
                    return "ENV_INVALID", "storage-guard commit reserve/target fields differ from its intent"
            if (row.get("intent_record_bytes") != intent.get("record_bytes")
                    or row.get("terminal_record_bytes") != row.get("record_bytes")
                    or row.get("record_bytes", 0) > intent.get("terminal_record_reserve_bytes", 0)):
                return "ENV_INVALID", "storage-guard commit exceeds or misstates its journal reservation"
            if row.get("result") not in {"WRITTEN", "CAPACITY_REJECTED", "IO_FAILED"}:
                return "ENV_INVALID", "storage-guard commit outcome is unknown"
            if row.get("result") == "WRITTEN":
                if pre + temp_peak > cap or row.get("control_peak_bound_bytes", cap+1) > 48*1024**2:
                    return "FAIL", f"{domain} storage write crossed its enforced pre-write cap"
                if (row.get("target_installed") is not True or row.get("durable") is not True
                        or row.get("terminal_record_bytes") != row.get("record_bytes")
                        or row.get("target_sha256_after") != row.get("payload_sha256")
                        or row.get("target_bytes_after") != row.get("payload_bytes")):
                    return "REVIEW_REQUIRED", "storage write lacks a durable-installed receipt"
            elif row.get("result") == "CAPACITY_REJECTED":
                if (row.get("target_installed") is not False or row.get("durable") is not False
                        or row.get("target_bytes_after") != intent.get("target_bytes_before")
                        or row.get("target_sha256_after") != intent.get("target_sha256_before")
                        or row.get("terminal_record_bytes") != row.get("record_bytes")):
                    return "ENV_INVALID", "capacity rejection changed or misreported the target"
            elif row.get("result") == "IO_FAILED":
                installed = row.get("target_installed")
                after_sha = row.get("target_sha256_after")
                if (row.get("durable") is not False or type(installed) is not bool
                        or (installed and after_sha != row.get("payload_sha256"))
                        or (not installed and after_sha != intent.get("target_sha256_before"))):
                    return "ENV_INVALID", "I/O failure target state disagrees with the atomic install receipt"
            if row.get("result") == "IO_FAILED":
                return "REVIEW_REQUIRED", "storage guard recorded an I/O failure"
            max_bytes[domain] = max(max_bytes[domain], post)
        previous, seq = digest, seq + 1
    if pending:
        return "REVIEW_REQUIRED", "storage-guard trace ends with uncommitted write intents"
    if value.get("terminal_sha256") != previous:
        return "ENV_INVALID", "storage-guard terminal trace digest mismatch"
    if not isinstance(inventory.get("uncovered_external_writers"), list):
        return "REVIEW_REQUIRED", "writer inventory does not classify external writers"
    manifest = context.get("artifact_manifest")
    if not isinstance(manifest, Mapping):
        return "REVIEW_REQUIRED", "sealed artifact manifest is unavailable for storage trace reconciliation"
    final_commits = _final_durable_commits(records)
    for relative, expected_sha in manifest.items():
        row = final_commits.get(relative)
        path_on_disk = Path(final) / relative
        if (row is None or row.get("result") != "WRITTEN"
                or row.get("payload_sha256") != expected_sha
                or row.get("payload_bytes") != path_on_disk.stat().st_size):
            return "REVIEW_REQUIRED", "sealed final artifact lacks a matching durable pre-write commit"
    ledger = context.get("scheduler_ledger")
    if not isinstance(ledger, Mapping) or not isinstance(ledger.get("rows"), list):
        return "REVIEW_REQUIRED", "terminal allocation rows are required to audit the static deployment proof"
    scheduler_rows = [dict(row) for row in ledger["rows"] if isinstance(row, Mapping)]
    deployment_status, deployment_reason = _audit_static_external_deployment(
        context.get("external_static_deployment"), context, attempt, scheduler_rows)
    if deployment_status != "PASS":
        return deployment_status, deployment_reason
    if inventory["uncovered_external_writers"]:
        return "REVIEW_REQUIRED", "writer inventory leaves host storage writers without pre-write bounds"
    return "PASS", "hash-chained pre-write storage guard stayed within both host caps"


def audit_fresh_authority(final: Path, context: Mapping[str, Any] | None,
                          expected_public_input_hashes: Mapping[str, str],
                          expected_attempt_id: str | None = None) -> FreshAudit:
    """Validate only evaluator-owned runner context against the sealed final tree."""
    if context is None:
        return FreshAudit("REVIEW_REQUIRED", "no evaluator-only fresh execution authority was supplied")
    if not isinstance(context, Mapping):
        return FreshAudit("ENV_INVALID", "runner context is not an object")
    if context.get("_p04_case07_operational_verified") is True:
        attempt = context.get("attempt_id")
        if expected_attempt_id is not None and attempt != expected_attempt_id:
            return FreshAudit("ENV_INVALID", "Case07 operational context attempt differs")
        return FreshAudit("REVIEW_REQUIRED",
            "Case07 ordinary runtime/accounting is authenticated, but it is not full fresh scientific authority",
            attempt_id=attempt, resource_status="REVIEW_REQUIRED",
            resource_reason="short operational qualification does not establish the canonical scientific budget",
            execution_status="REVIEW_REQUIRED",
            execution_reason="ordinary lifecycle receipts do not constitute a complete author execution-event DAG")
    required = {"schema", "case_id", "definition_revision", "resource_profile", "attempt_id",
                "attempt_started_at_utc", "report_submitted_at_utc", "collected_at_utc",
                "public_input_hashes", "public_input_manifest_sha256", "controller_sha256",
                "template_manifest_sha256", "engine_sha256", "artifact_manifest",
                "artifact_manifest_sha256", "report_sha256", "native_receipt_hashes",
                "scheduler_ledger", "scheduler_ledger_sha256", "raw_sacct_evidence",
                "allocation_submission_receipts", "queue_debits", "task_submission_receipt",
                "resource_snapshot"}
    missing = required - set(context)
    if missing:
        return FreshAudit("ENV_INVALID", "runner context lacks fields: " + ", ".join(sorted(missing)))
    try:
        if (context["schema"] != SCHEMA or context["case_id"] != CASE_ID
                or context["definition_revision"] != DEFINITION_REVISION
                or context["resource_profile"] != RESOURCE_PROFILE):
            raise ValueError("runner context schema, case, definition, or resource profile differs")
        for key in ("controller_sha256", "template_manifest_sha256", "engine_sha256"):
            if not _valid_hash(context[key]):
                raise ValueError(f"runner {key} is malformed")
        attempt = context["attempt_id"]
        if not isinstance(attempt, str) or not attempt.strip():
            raise ValueError("attempt_id is empty")
        if expected_attempt_id is not None and attempt != expected_attempt_id:
            raise ValueError("attempt ID differs from evaluator-selected attempt")
        started = _parse_utc(context["attempt_started_at_utc"])
        submitted = _parse_utc(context["report_submitted_at_utc"])
        collected = _parse_utc(context["collected_at_utc"])
        if submitted < started or collected < submitted:
            raise ValueError("attempt, report seal, and collection times are inconsistent")
        public = context["public_input_hashes"]
        if not isinstance(public, Mapping) or dict(public) != dict(expected_public_input_hashes):
            raise ValueError("public input hash set differs from frozen evaluator inputs")
        if (any(not _valid_hash(v) for v in public.values())
                or context["public_input_manifest_sha256"] != canonical_sha256(expected_public_input_hashes)):
            raise ValueError("public input manifest digest is invalid")
        manifest = context["artifact_manifest"]
        if not isinstance(manifest, Mapping) or canonical_sha256(manifest) != context["artifact_manifest_sha256"]:
            raise ValueError("runner artifact manifest is malformed or digest mismatched")
        manifest = dict(manifest)
        if any(not _safe_relative(k) or not _valid_hash(v) for k, v in manifest.items()):
            raise ValueError("runner artifact manifest contains unsafe path or hash")
        if _manifest_from_disk(final) != manifest:
            raise ValueError("submitted final tree differs from evaluator snapshot")
        report_hash = manifest.get("ts_search_report.json")
        if not _valid_hash(report_hash) or context["report_sha256"] != report_hash:
            raise ValueError("sealed report hash differs from evaluator snapshot")
        receipts = context["native_receipt_hashes"]
        expected_receipts = {k: v for k, v in manifest.items()
                             if k.startswith("native_outputs/") and k.endswith("/receipt.json")}
        if not isinstance(receipts, Mapping) or dict(receipts) != expected_receipts or not expected_receipts:
            raise ValueError("native receipt hashes are incomplete or differ from snapshot")
        rows = _validate_scheduler_context(context)
        receipt_map = context["allocation_submission_receipts"]
        if not isinstance(receipt_map, Mapping) or set(receipt_map) != {r["job_id"] for r in rows}:
            raise ValueError("allocation submission receipts do not cover every root allocation")
        for row in rows:
            receipt = receipt_map[row["job_id"]]
            if not isinstance(receipt, Mapping) or receipt.get("attempt_id") != attempt:
                raise ValueError(f"allocation submission receipt mismatch for {row['job_id']}")
            if receipt.get("schema") == "case07-allocation-submission-receipt/v2":
                if (receipt.get("job_id") != row["job_id"]
                        or receipt.get("submitted_at_utc") != row["submit_utc"]
                        or not _valid_hash(receipt.get("request_sha256"))
                        or not _valid_hash(receipt.get("source_manifest_sha256"))
                        or not _valid_hash(receipt.get("intent_sha256"))
                        or not isinstance(receipt.get("requested_resources"), Mapping)):
                    raise ValueError(f"host allocation submission receipt mismatch for {row['job_id']}")
                submitted_at = _parse_utc(receipt.get("submitted_at_utc"))
                acknowledged_at = _parse_utc(receipt.get("acknowledged_at_utc"))
                if acknowledged_at < submitted_at:
                    raise ValueError(f"allocation acknowledgement predates submission for {row['job_id']}")
            else:
                raise ValueError(f"allocation submission receipt schema is not v2 for {row['job_id']}")
        task_receipt = context["task_submission_receipt"]
        if (not isinstance(task_receipt, Mapping)
                or task_receipt.get("schema") != "case07-task-submission-receipt/v1"
                or task_receipt.get("attempt_id") != attempt
                or task_receipt.get("report_sha256") != report_hash
                or task_receipt.get("artifact_manifest_sha256") != context["artifact_manifest_sha256"]):
            raise ValueError("sealed task submission receipt does not bind attempt/report/snapshot")
        # The controller uses the same verified queue intervals as resource
        # accounting.  Queue time is added to the active deadline; an
        # untrusted queue_debits summary or an unaudited certificate contributes
        # zero seconds.
        derived_debits, queue_reason = _derive_queue_debits(
            context, rows, context["attempt_started_at_utc"], context["report_submitted_at_utc"])
        queue_seconds = sum(
            (_parse_utc(item["end_utc"]) - _parse_utc(item["start_utc"])).total_seconds()
            for item in derived_debits)
        driver_seal = context.get("driver_seal")
        seal_resource_override = None
        if driver_seal is None:
            seal_resource_override = ("REVIEW_REQUIRED", "durable driver seal-persistence authority is absent")
        elif not isinstance(driver_seal, Mapping) or driver_seal.get("schema") != "case07-driver-seal-binding/v1":
            raise ValueError("trusted driver seal binding schema is malformed")
        else:
            for key in ("driver_status_sha256", "seal_persistence_sha256", "task_submission_receipt_sha256",
                        "current_job_qualification_sha256", "driver_context_sha256"):
                if not _valid_hash(driver_seal.get(key)):
                    raise ValueError(f"driver seal binding {key} is malformed")
            if (driver_seal.get("attempt_id") != attempt
                    or driver_seal.get("receipt_persisted_at_utc") != context["report_submitted_at_utc"]
                    or driver_seal.get("task_submission_receipt_sha256") != context.get("task_submission_receipt_sha256")
                    or task_receipt.get("submitted_at_utc") != driver_seal.get("report_sealed_at_utc")):
                raise ValueError("driver persistence binding differs from task receipt or report seal")
            started_dt = _parse_utc(context["attempt_started_at_utc"])
            receipt_dt = _parse_utc(driver_seal.get("receipt_persisted_at_utc"))
            status_dt = _parse_utc(driver_seal.get("status_persisted_at_utc"))
            driver_context_dt = _parse_utc(driver_seal.get("driver_context_persisted_at_utc"))
            deadline = started_dt.timestamp() + 27_600 + queue_seconds
            if (receipt_dt < _parse_utc(driver_seal.get("report_sealed_at_utc"))
                    or status_dt < receipt_dt or driver_context_dt < receipt_dt):
                raise ValueError("driver persistence timestamps are inconsistent")
            if (driver_seal.get("driver_status") != "COMPLETE"
                    or driver_seal.get("deadline_passed") is not True
                    or receipt_dt.timestamp() > deadline or status_dt.timestamp() > deadline
                    or driver_context_dt.timestamp() > deadline):
                seal_resource_override = ("FAIL", "driver report/seal persistence did not complete within the controller deadline")
        external = context.get("external_review")
        if external is None:
            decision_status = reference_status = review_status = "REVIEW_REQUIRED"
        else:
            if not isinstance(external, Mapping) or external.get("schema") != "case07-independent-review/v1":
                raise ValueError("independent scientific review schema is malformed")
            if (external.get("attempt_id") != attempt or external.get("report_sha256") != report_hash
                    or external.get("artifact_manifest_sha256") != context["artifact_manifest_sha256"]):
                raise ValueError("independent review is not bound to attempt, report, and snapshot")
            if not isinstance(external.get("reviewer_id"), str) or not external.get("reviewer_id"):
                raise ValueError("independent review lacks reviewer identity")
            _parse_utc(external.get("reviewed_at_utc"))
            criteria = external.get("criteria")
            expected_criteria = {"budgeted_scientific_decisions", "reference_comparison_and_uncertainty"}
            if not isinstance(criteria, Mapping) or set(criteria) != expected_criteria:
                raise ValueError("independent review must cover the two narrative criteria")
            decision_status = _review_criterion(criteria["budgeted_scientific_decisions"], manifest, public)
            reference_status = _review_criterion(criteria["reference_comparison_and_uncertainty"], manifest, public)
            review_status = "FAIL" if "FAIL" in (decision_status, reference_status) else (
                "REVIEW_REQUIRED" if "REVIEW_REQUIRED" in (decision_status, reference_status) else "PASS")
        snapshot = dict(context["resource_snapshot"])
        snapshot["queue_debits"] = derived_debits
        resource_status, resource_reason = audit_resource_snapshot(
            snapshot, rows, context["attempt_started_at_utc"], context["report_submitted_at_utc"])
        if resource_status == "ENV_INVALID":
            raise ValueError(resource_reason)
        if seal_resource_override is not None:
            resource_status, resource_reason = seal_resource_override
        elif resource_status == "PASS" and queue_reason.startswith("no source-bound"):
            resource_reason += "; " + queue_reason
        guard_status, guard_reason = _audit_external_storage_guard(
            context.get("storage_guard"), final, context, attempt, report_hash, context["artifact_manifest_sha256"],
            context["controller_sha256"])
        if resource_status == "PASS" and guard_status != "PASS":
            resource_status, resource_reason = guard_status, guard_reason
        if resource_status == "PASS":
            # Queue raw credentials are checked by the resource helper.
            pass
        execution_status, execution_reason = _audit_execution_events(
            final, context, manifest, rows, public)
        return FreshAudit("PASS", "fresh execution and sealed artifact snapshot are evaluator-authenticated",
                          attempt, manifest, resource_status, resource_reason, review_status,
                          decision_status, reference_status, execution_status, execution_reason)
    except (ValueError, TypeError, KeyError, OSError) as exc:
        return FreshAudit("ENV_INVALID", str(exc))
