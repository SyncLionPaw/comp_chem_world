"""Cross-check candidate-submitted execution evidence for Case01.

This checks internal consistency; it cannot authenticate scheduler origin or
prove that same-account artifacts were not forged together.
"""
from __future__ import annotations

import base64
import datetime as dt
import hashlib
import json
import math
import os
import re
import shutil
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


class CandidateEvidenceError(ValueError):
    """Candidate execution evidence is absent, malformed, or inconsistent."""


class CandidateEvidenceUnsupported(CandidateEvidenceError):
    """Evidence is internally coherent but outside the legacy audit coverage."""


MAIN = {
    "production.tpr": ("production.tpr", "production_tpr", "tpr"),
    "production.xtc": ("production.xtc", "production_xtc", "xtc"),
    "production.edr": ("production.edr", "production_edr", "edr"),
    "production.log": ("production.log", "production_log"),
    "npt.gro": ("npt.gro", "npt_gro"),
    "nvt.log": ("nvt.log", "nvt_log"),
    "npt.log": ("npt.log", "npt_log"),
}
SUPPLEMENT = {
    "initial_gro": ("initial_gro", "solvated.gro", "initial.gro"),
    "initial_topology": ("initial_topology", "topol.runtime.top"),
    "initial_batch": ("initial_batch", "workflow_script", "run_case01.sh"),
    "em_tpr": ("em_tpr", "em.tpr"), "em_log": ("em_log", "em.log"),
    "em_gro": ("em_gro", "em.gro"), "em_edr": ("em_edr", "em.edr"),
    "nvt_tpr": ("nvt_tpr", "nvt.tpr"), "nvt_log": ("nvt_log", "nvt.log"),
    "nvt_gro": ("nvt_gro", "nvt.gro"), "npt_tpr": ("npt_tpr", "npt.tpr"),
    "npt_log": ("npt_log", "npt.log"), "npt_gro": ("npt_gro", "npt.gro"),
}


def _sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def _pairs(pairs):
    out = {}
    for key, value in pairs:
        if key in out:
            raise CandidateEvidenceError("duplicate JSON key in candidate evidence")
        out[key] = value
    return out


def _constant(_value):
    raise CandidateEvidenceError("non-finite JSON constant in candidate evidence")


def _float(value):
    result = float(value)
    if not math.isfinite(result):
        raise CandidateEvidenceError("non-finite JSON number in candidate evidence")
    return result


def _json(raw: bytes, label: str) -> dict:
    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=_pairs,
                           parse_constant=_constant, parse_float=_float)
    except CandidateEvidenceError:
        raise
    except Exception as exc:
        raise CandidateEvidenceError(f"invalid {label} JSON") from exc
    if not isinstance(value, dict):
        raise CandidateEvidenceError(f"{label} must be a JSON object")
    return value


def _file(root: Path, item, role: str) -> tuple[Path, str]:
    if not isinstance(item, dict):
        raise CandidateEvidenceError(f"missing file/hash for {role}")
    raw = item.get("relative_path", item.get("path"))
    expected = item.get("sha256")
    if not isinstance(raw, str) or not re.fullmatch(r"[0-9a-fA-F]{64}", str(expected or "")):
        raise CandidateEvidenceError(f"invalid file/hash for {role}")
    rel = Path(raw)
    if rel.is_absolute() or ".." in rel.parts or not rel.parts:
        raise CandidateEvidenceError(f"unsafe candidate path for {role}")
    path = root / rel
    cursor = root
    for part in rel.parts:
        cursor /= part
        if cursor.is_symlink():
            raise CandidateEvidenceError(f"symlink candidate file for {role}")
    try:
        resolved = path.resolve(strict=True)
    except OSError as exc:
        raise CandidateEvidenceError(f"missing candidate file for {role}") from exc
    if not resolved.is_file() or not resolved.is_relative_to(root.resolve()):
        raise CandidateEvidenceError(f"unsafe candidate file for {role}")
    if _sha(resolved).lower() != expected.lower():
        raise CandidateEvidenceError(f"candidate SHA256 mismatch for {role}")
    if item.get("size") is not None and (type(item["size"]) is not int or item["size"] != resolved.stat().st_size):
        raise CandidateEvidenceError(f"candidate size mismatch for {role}")
    return resolved, rel.as_posix()


def _norm(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", value.lower())


def _maps(*documents) -> list[dict]:
    result = []
    for doc in documents:
        if not isinstance(doc, dict):
            continue
        for key in ("native_source_files", "protocol_input_files", "source_files", "files"):
            value = doc.get(key)
            if isinstance(value, dict):
                result.append(value)
    return result


def _find(maps: list[dict], aliases: tuple[str, ...], role: str):
    names = {_norm(name) for name in aliases}
    found = [value for source in maps for key, value in source.items() if _norm(str(key)) in names]
    if not found or any(not isinstance(v, dict) for v in found):
        raise CandidateEvidenceError(f"missing or conflicting candidate path for {role}")
    identities = {(str(v.get("relative_path", v.get("path", ""))), str(v.get("sha256", "")).lower()) for v in found}
    if len(identities) != 1:
        raise CandidateEvidenceError(f"missing or conflicting candidate path for {role}")
    return found[0]


def _timezone(value):
    if not isinstance(value, str) or not value.strip():
        raise CandidateEvidenceError("timestamps need an explicitly declared timezone")
    name = value.strip()
    if name.upper() in ("UTC", "Z", "ETC/UTC"):
        return dt.timezone.utc
    if re.fullmatch(r"[+-]\d{2}:?\d{2}", name):
        compact = name.replace(":", "")
        sign = 1 if compact[0] == "+" else -1
        hours, minutes = int(compact[1:3]), int(compact[3:5])
        if hours > 23 or minutes > 59:
            raise CandidateEvidenceError("invalid declared timezone offset")
        return dt.timezone(dt.timedelta(minutes=sign * (hours * 60 + minutes)))
    try:
        return ZoneInfo(name)
    except ZoneInfoNotFoundError as exc:
        raise CandidateEvidenceError("unrecognized declared timezone") from exc


def _time(value, timezone, label):
    if not isinstance(value, str):
        raise CandidateEvidenceError(f"scheduler record lacks {label}")
    try:
        parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise CandidateEvidenceError(f"invalid {label}") from exc
    if parsed.tzinfo is None:
        if timezone is None:
            raise CandidateEvidenceError(f"{label} needs a declared timezone when no UTC offset is present")
        parsed = parsed.replace(tzinfo=timezone)
    return parsed.astimezone(dt.timezone.utc)


def _pick(record: dict, names: tuple[str, ...], label: str):
    for name in names:
        if record.get(name) is not None:
            return record[name]
    raise CandidateEvidenceError(f"scheduler record lacks {label}")


def _int(value, label, minimum):
    if isinstance(value, bool):
        raise CandidateEvidenceError(f"invalid scheduler {label}")
    try:
        parsed = int(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise CandidateEvidenceError(f"invalid scheduler {label}") from exc
    if parsed < minimum or str(value).strip() != str(parsed):
        raise CandidateEvidenceError(f"invalid scheduler {label}")
    return parsed


def _get(obj, *names):
    for name in names:
        if isinstance(obj, dict) and name in obj:
            return obj[name]
    raise CandidateEvidenceError("missing candidate execution field: " + names[0])


def _mapping(doc, *names):
    value = _get(doc, *names)
    if not isinstance(value, dict):
        raise CandidateEvidenceError("candidate execution field must be an object: " + names[0])
    return value


def _seconds(record, timezone):
    start_value = _get(record, "start_time", "start", "submit_time")
    end_value = _get(record, "end_time", "end", "finish_time")
    start = _time(start_value, timezone, "start time")
    end = _time(end_value, timezone, "end time")
    elapsed = (end - start).total_seconds()
    if elapsed <= 0:
        raise CandidateEvidenceError("scheduler end time must follow start time")
    declared = record.get("elapsed_seconds", record.get("elapsed_time_seconds"))
    if declared is not None:
        if isinstance(declared, bool):
            raise CandidateEvidenceError("invalid scheduler elapsed duration")
        try:
            declared_number = float(declared)
        except (TypeError, ValueError, OverflowError) as exc:
            raise CandidateEvidenceError("invalid scheduler elapsed duration") from exc
        if not math.isfinite(declared_number) or abs(declared_number - elapsed) > 1.0:
            raise CandidateEvidenceError("scheduler elapsed duration is inconsistent")
    return start, end, elapsed


def _check_optional_receipt_times(receipt, scheduler, start, end, elapsed):
    """Cross-check any receipt timestamps/duration it chooses to duplicate."""
    zone_value = receipt.get("timezone", scheduler.get("timezone"))
    zone = _timezone(zone_value) if zone_value is not None else None
    for aliases, expected, label in (
            (("start_time", "start", "submit_time"), start, "start time"),
            (("end_time", "end", "finish_time"), end, "end time")):
        for key in aliases:
            if key in receipt and receipt[key] is not None:
                observed = _time(receipt[key], zone, f"receipt {label}")
                if abs((observed - expected).total_seconds()) > 1.0:
                    raise CandidateEvidenceError(f"receipt and scheduler {label} differ")
    for key in ("elapsed_seconds", "elapsed_time_seconds"):
        if key in receipt and receipt[key] is not None:
            value = receipt[key]
            if isinstance(value, bool):
                raise CandidateEvidenceError("invalid receipt elapsed duration")
            try:
                observed = float(value)
            except (TypeError, ValueError, OverflowError) as exc:
                raise CandidateEvidenceError("invalid receipt elapsed duration") from exc
            if not math.isfinite(observed) or abs(observed - elapsed) > 1.0:
                raise CandidateEvidenceError("receipt and scheduler elapsed duration differ")


def _log_window(path: Path, timezone):
    text = path.read_text(errors="replace")
    pattern = re.compile(r"^(Started|Finished) mdrun on rank \d+ (.+)$", re.M)
    found = {}
    for kind, stamp in pattern.findall(text):
        try:
            parsed = dt.datetime.strptime(stamp.strip(), "%a %b %d %H:%M:%S %Y").replace(tzinfo=timezone)
        except ValueError:
            continue
        found[kind] = parsed.astimezone(dt.timezone.utc)
    if "Finished" not in found:
        raise CandidateEvidenceUnsupported("GROMACS log timestamp format is outside freshness adapter coverage")
    # Some GROMACS logs (notably short EM runs) preserve only the completion
    # line. Their completion can still be bounded by the evaluator/scheduler
    # windows; use that instant as the lower bound for this log.
    found.setdefault("Started", found["Finished"])
    if found["Finished"] < found["Started"]:
        raise CandidateEvidenceError("GROMACS log finish precedes its start")
    return found["Started"], found["Finished"], text


def prepare(root: Path, evidence_root: Path, eval_started_at: str | None = None):
    """Validate candidate consistency and materialize the legacy audit bridge."""
    root = Path(root).resolve(strict=True)
    if not root.is_dir():
        raise CandidateEvidenceError("candidate root is not a directory")
    final = root / "final"
    if final.is_symlink() or not final.is_dir():
        raise CandidateEvidenceError("candidate final directory is missing or unsafe")
    documents = []
    known = (final / "provenance.json", final / "hpc_receipt.json", final / "execution-receipt.json")
    candidates = [path for path in known if path.exists()]
    for path in sorted(final.glob("*.json")):
        if path not in candidates:
            candidates.append(path)
    evidence_keys = {"receipt", "scheduler_record", "accounting", "sacct_receipt", "native_source_files",
                     "protocol_input_files", "execution", "execution_evidence", "source_files", "job_id",
                     "batch_script", "submitted_script", "execution_order", "stage_order"}
    for candidate in candidates:
        if candidate.is_symlink() or not candidate.is_file():
            raise CandidateEvidenceError("candidate evidence JSON must be a regular file")
        if candidate.stat().st_size > 4_000_000:
            if candidate in known or any(word in candidate.name.lower() for word in ("provenance", "receipt", "scheduler", "execution")):
                raise CandidateEvidenceError("candidate execution evidence JSON exceeds the size limit")
            continue
        try:
            doc = _json(candidate.read_bytes(), "execution evidence")
        except CandidateEvidenceError:
            if candidate in known or any(word in candidate.name.lower() for word in ("provenance", "receipt", "scheduler", "execution")):
                raise
            continue
        if candidate in known or evidence_keys.intersection(doc):
            documents.append(doc)
    if not documents:
        raise CandidateEvidenceError("candidate execution provenance is missing")

    # Accept a common envelope while keeping scheduler vocabulary tool-neutral.
    evidence = documents[0]
    receipt_candidates = [doc.get("receipt", doc) for doc in documents]
    receipt = next((candidate for candidate in receipt_candidates if isinstance(candidate, dict)
                   and candidate.get("job_id") is not None
                   and any(candidate.get(name) is not None for name in ("scheduler", "scheduler_name", "cpus", "allocated_cpus"))), None)
    if receipt is None:
        receipt = next((candidate for candidate in receipt_candidates if isinstance(candidate, dict)
                        and candidate.get("job_id") is not None), None)
    scheduler = None
    for doc in documents:
        scheduler = doc.get("scheduler_record", doc.get("accounting", doc.get("sacct_receipt")))
        if scheduler is None and isinstance(doc.get("receipt"), dict):
            scheduler = doc["receipt"].get("scheduler_record", doc["receipt"].get("sacct_receipt"))
        if isinstance(scheduler, dict):
            break
    if receipt is None and len(candidates) == 1:
        receipt = candidates[0]
    if not isinstance(receipt, dict) or not isinstance(scheduler, dict):
        raise CandidateEvidenceError("receipt and scheduler_record are required")
    timezone_value = scheduler.get("timezone", receipt.get("timezone"))
    record_timezone = _timezone(timezone_value) if timezone_value is not None else None
    start, end, elapsed = _seconds(scheduler, record_timezone)
    _check_optional_receipt_times(receipt, scheduler, start, end, elapsed)
    raw_job = _get(receipt, "job_id")
    raw_scheduler_job = _get(scheduler, "job_id")
    if (isinstance(raw_job, bool) or not isinstance(raw_job, (str, int))
            or isinstance(raw_scheduler_job, bool) or not isinstance(raw_scheduler_job, (str, int))):
        raise CandidateEvidenceError("receipt and scheduler job IDs must be strings or integers")
    job = str(raw_job)
    scheduler_job = str(raw_scheduler_job)
    if not job or job != scheduler_job:
        raise CandidateEvidenceError("receipt and scheduler job IDs differ")
    allocation = str(receipt.get("allocation_id", job))
    if allocation != str(scheduler.get("allocation_id", scheduler_job)):
        raise CandidateEvidenceError("receipt and scheduler allocation IDs differ")
    allocation_count = receipt.get("allocation_count", scheduler.get("allocation_count", 1))
    allocations = receipt.get("allocations", scheduler.get("allocations"))
    if (any(x in job for x in ("_", ";")) or receipt.get("array_job") or scheduler.get("array_job")
            or receipt.get("array_task_id") is not None or scheduler.get("array_task_id") is not None
            or type(allocation_count) is not int or allocation_count != 1
            or isinstance(allocations, list) and len(allocations) != 1):
        raise CandidateEvidenceError("array or multi-allocation jobs are unsupported")
    fields = {
        "scheduler": ("scheduler", "scheduler_name"),
        "cluster": ("cluster", "cluster_name"),
        "user": ("user", "username", "submit_user"),
        "cpus": ("cpus", "allocated_cpus", "AllocCPUS"),
        "gpus": ("gpus", "allocated_gpus"),
        "memory_mb": ("memory_mb", "allocated_memory_mb"),
        "walltime_limit_seconds": ("walltime_limit_seconds", "time_limit_seconds", "walltime_seconds"),
        "exit_code": ("exit_code", "exitcode"),
        "final_state": ("final_state", "state", "job_state"),
    }
    facts = {}
    for key, aliases in fields.items():
        a = next((receipt[n] for n in aliases if receipt.get(n) is not None), None)
        b = next((scheduler[n] for n in aliases if scheduler.get(n) is not None), None)
        if key in ("cluster", "user") and a is None and b is None:
            continue
        if a is None or b is None:
            raise CandidateEvidenceError(f"receipt/scheduler record lacks {key}")
        if key in ("scheduler", "cluster", "user", "final_state") and (
                not isinstance(a, str) or not a.strip() or not isinstance(b, str) or not b.strip()):
            raise CandidateEvidenceError(f"receipt/scheduler {key} must be a non-empty string")
        if key == "exit_code":
            normalize_exit = lambda value: "0" if str(value).strip() in ("0", "0:0") else str(value).strip()
            if normalize_exit(a) != normalize_exit(b):
                raise CandidateEvidenceError("receipt and scheduler exit_code differ")
            facts[key] = a
            continue
        if str(a).upper() != str(b).upper():
            raise CandidateEvidenceError(f"receipt and scheduler {key} differ")
        facts[key] = a
    facts["cpus"] = _int(facts["cpus"], "cpus", 1)
    facts["gpus"] = _int(facts["gpus"], "gpus", 0)
    facts["memory_mb"] = _int(facts["memory_mb"], "memory_mb", 1)
    facts["walltime_limit_seconds"] = _int(facts["walltime_limit_seconds"], "walltime limit", 1)
    if facts["final_state"].upper() not in ("COMPLETED", "COMPLETED+") or str(facts["exit_code"]) not in ("0", "0:0"):
        raise CandidateEvidenceError("scheduler job did not complete successfully")
    if elapsed > facts["walltime_limit_seconds"] + 1:
        raise CandidateEvidenceError("scheduler elapsed time exceeds its walltime limit")

    maps = _maps(*documents, receipt, scheduler)
    execution_doc = next((doc for doc in documents if isinstance(doc.get("execution", doc.get("execution_evidence")), dict)), None)
    if execution_doc is None:
        execution_doc = next((doc for doc in documents if any(key in doc for key in
            ("batch_script", "submitted_script", "stdout", "stderr", "execution_order", "stage_order"))), evidence)
    execution = _mapping(execution_doc, "execution", "execution_evidence") if ("execution" in execution_doc or "execution_evidence" in execution_doc) else execution_doc
    batch_item = execution.get("batch_script", execution.get("submitted_script"))
    if batch_item is None:
        batch_item = _find(maps, ("batch_script", "submitted_script", "initial_batch"), "batch script")
    batch_path, batch_rel = _file(root, batch_item, "batch script")
    native = {}
    for alias, aliases in MAIN.items():
        item = _find(maps, aliases, alias)
        path, rel = _file(root, item, alias)
        native[alias] = {"path": rel, "sha256": item["sha256"].lower()}
    supplements = {}
    for role, aliases in SUPPLEMENT.items():
        if role == "initial_batch":
            continue
        item = _find(maps, aliases, role)
        path, rel = _file(root, item, role)
        supplements[role] = {"path": rel, "sha256": _sha(path), "source": path}

    streams = execution.get("streams", {})
    if not isinstance(streams, dict):
        raise CandidateEvidenceError("stdout/stderr mapping is invalid")
    stdout_item = execution.get("stdout", streams.get("stdout"))
    stderr_item = execution.get("stderr", streams.get("stderr"))
    stdout_path, stdout_rel = _file(root, stdout_item, "stdout")
    stderr_path, stderr_rel = _file(root, stderr_item, "stderr")
    order = execution.get("execution_order", execution.get("stage_order"))
    expected_order = ["em", "nvt", "npt", "production"]
    if order != expected_order:
        raise CandidateEvidenceError("execution order must contain em, nvt, npt, production exactly once")
    workflow_item = execution.get("workflow_source")
    if workflow_item is not None:
        workflow_path, workflow_rel = _file(root, workflow_item, "workflow source")
        batch_text = batch_path.read_text(errors="replace")
        if Path(workflow_rel).name not in batch_text and Path(workflow_rel).stem not in batch_text:
            raise CandidateEvidenceError("submitted batch does not identify the declared workflow source")
    else:
        workflow_path, workflow_rel = batch_path, batch_rel
    # Limit science scoring to workflows whose exact artifact lineage can be
    # checked by the existing native auditor. This is an unsupported-coverage
    # result, never a science failure or an implicit script-name requirement.
    workflow_text = workflow_path.read_text(errors="replace")
    lineage_stems = [Path(item["path"]).name.split(".", 1)[0] for item in native.values()]
    lineage_stems += [Path(item["path"]).name.split(".", 1)[0]
                      for role, item in supplements.items() if role != "initial_batch"]
    if not all(stem in workflow_text for stem in lineage_stems):
        raise CandidateEvidenceUnsupported(
            "candidate evidence is consistent but its workflow does not expose the artifact lineage required by the current native audit"
        )
    supplements["initial_batch"] = {"path": workflow_rel, "sha256": _sha(workflow_path), "source": workflow_path}

    # If the candidate declares a replica branch, do not silently drop it.
    if evidence.get("replica_evidence_manifest") or receipt.get("replica_evidence_manifest"):
        raise CandidateEvidenceError("declared replica evidence is not supported by this adapter yet")

    log_item = next(item for key, item in native.items() if key == "production.log")
    production_path = root / log_item["path"]
    log_timezone = execution.get("production_log_timezone", evidence.get("production_log_timezone", receipt.get("production_log_timezone")))
    log_start, log_end, log_text = _log_window(production_path, _timezone(log_timezone))
    if log_start < start - dt.timedelta(seconds=2) or log_end > end + dt.timedelta(seconds=2):
        raise CandidateEvidenceError("production log time window does not match scheduler allocation")
    match = re.search(r"\b(\d+)\s+steps\b.*?\b([0-9.eE+-]+)\s*ps\b", log_text, re.I | re.S)
    if not match:
        raise CandidateEvidenceError("production log lacks native duration fields")
    production_ns = float(match.group(2)) / 1000.0
    if not math.isfinite(production_ns) or production_ns <= 0:
        raise CandidateEvidenceError("invalid production duration")

    order_item = execution.get("execution_order_file", execution.get("order_file"))
    order_path, order_rel = _file(root, order_item, "execution order")
    order_doc = _json(order_path.read_bytes(), "execution order")
    if order_doc.get("stages", order_doc.get("execution_order")) != expected_order:
        raise CandidateEvidenceError("execution order file disagrees with declared order")
    if str(order_doc.get("job_id")) != job or str(order_doc.get("allocation_id", job)) != allocation:
        raise CandidateEvidenceError("execution order is bound to a different allocation")
    if order_doc.get("scheduler") is not None and str(order_doc["scheduler"]) != str(facts["scheduler"]):
        raise CandidateEvidenceError("execution order identifies a different scheduler")
    if order_doc.get("stage_artifacts") is not None:
        bindings = order_doc["stage_artifacts"]
        if not isinstance(bindings, dict):
            raise CandidateEvidenceError("execution order stage_artifacts must be an object")
        for stage, roles in (("em", ("em_tpr", "em_log")), ("nvt", ("nvt_tpr", "nvt_log")), ("npt", ("npt_tpr", "npt_log")), ("production", ("production.tpr", "production.log"))):
            stage_map = bindings.get(stage)
            if not isinstance(stage_map, dict):
                raise CandidateEvidenceError(f"execution order lacks {stage} artifact bindings")
            for role in roles:
                declared = stage_map.get(role, stage_map.get("tpr" if role.endswith("tpr") else "log"))
                expected_sha = (native[role]["sha256"] if role in native else supplements[role]["sha256"])
                if not isinstance(declared, str) or declared.lower() != expected_sha:
                    raise CandidateEvidenceError(f"execution order {stage} binding disagrees for {role}")
    else:
        raise CandidateEvidenceError("execution order must bind the stage TPR/log hashes")

    if not isinstance(eval_started_at, str) or not eval_started_at.strip():
        raise CandidateEvidenceUnsupported("freshness is NOT_VERIFIED because evaluator start context is missing")
    eval_start = _time(eval_started_at, dt.timezone.utc, "evaluator start time")
    grader_now = dt.datetime.now(dt.timezone.utc)
    if eval_start > grader_now or start < eval_start or end > grader_now:
        raise CandidateEvidenceError("candidate scheduler window falls outside the evaluator freshness window")
    stage_logs = [
        ("em", supplements["em_log"]["source"]),
        ("nvt", supplements["nvt_log"]["source"]),
        ("npt", supplements["npt_log"]["source"]),
        ("production", production_path),
    ]
    timezone_map = execution.get("stage_log_timezones", {})
    if not isinstance(timezone_map, dict):
        raise CandidateEvidenceError("stage_log_timezones must be an object")
    stage_windows = []
    for stage, stage_path in stage_logs:
        zone = _timezone(timezone_map.get(stage, log_timezone))
        stage_start, stage_end, _ = _log_window(stage_path, zone)
        if stage_start < eval_start or stage_end > grader_now:
            raise CandidateEvidenceError(f"{stage} log falls outside the evaluator freshness window")
        if stage_start < start - dt.timedelta(seconds=2) or stage_end > end + dt.timedelta(seconds=2):
            raise CandidateEvidenceError(f"{stage} log falls outside the scheduler allocation window")
        stage_windows.append((stage, stage_start, stage_end))
    for previous, current in zip(stage_windows, stage_windows[1:]):
        if current[1] < previous[1] or current[2] < previous[2]:
            raise CandidateEvidenceError("native stage log windows disagree with the declared execution order")

    evidence_root = Path(evidence_root)
    local = evidence_root / "acceptance" / "local"
    native_dir = local / "native"
    native_dir.mkdir(parents=True, exist_ok=True)
    manifest_files = {}
    for role, info in supplements.items():
        source = info.pop("source")
        destination = native_dir / info["path"]
        destination.parent.mkdir(parents=True, exist_ok=True)
        if source.resolve() != destination.resolve():
            shutil.copyfile(source, destination)
        manifest_files[role] = {"path": (Path("acceptance/local/native") / info["path"]).as_posix(), "sha256": info["sha256"]}
    manifest_path = local / "equilibration-manifest.json"
    manifest_path.write_text(json.dumps({"schema": "case01-obtained-equilibration-evidence-v1", "files": manifest_files}, sort_keys=True) + "\n")
    source_files = {key: {"relative_path": value["path"], "sha256": value["sha256"]} for key, value in native.items()}
    for role, info in supplements.items():
        source_files[role] = {"relative_path": info["path"], "sha256": info["sha256"]}
    manifest_doc = _json(manifest_path.read_bytes(), "generated equilibration manifest")
    for role, info in manifest_doc["files"].items():
        info["relative_path"] = (Path("native") / info["path"].split("acceptance/local/native/", 1)[-1]).as_posix()
        info.pop("path", None)
    manifest_path.write_text(json.dumps(manifest_doc, sort_keys=True) + "\n")
    receipt_path = local / "receipt.json"
    receipt_path.write_text(json.dumps({
        "schema": "case01-trusted-execution-receipt-v1", "issuer": "candidate-artifact-consistency-adapter",
        "attempt_id": hashlib.sha256((job + _sha(batch_path)).encode()).hexdigest(), "job_id": job,
        "job_state": "COMPLETED", "exit_code": "0:0", "accounting_verified": True,
        "production_length_ns": production_ns, "source_files": source_files,
        "equilibration_evidence_manifest": "acceptance/local/equilibration-manifest.json",
        "submitted_batch_sha256": _sha(batch_path), "stdout_sha256": _sha(stdout_path),
        "stderr_sha256": _sha(stderr_path), "execution_order_sha256": _sha(order_path),
    }, sort_keys=True) + "\n")
    public = {
        "provenance_status": "CONSISTENT", "provenance_scope": "candidate-artifact-consistency",
        "evidence_basis": "candidate-artifact-consistency", "independent_scheduler_attested": False,
        "execution_origin_attested": False, "scheduler": str(facts["scheduler"]),
        "job_id": job, "allocated_cpus": facts["cpus"], "allocated_gpus": facts["gpus"],
        "allocated_memory_mb": facts["memory_mb"], "walltime_limit_seconds": facts["walltime_limit_seconds"],
        "observed_elapsed_seconds": elapsed, "production_length_ns": production_ns,
        "freshness_status": "WINDOW_CONSISTENT", "evaluation_started_at_utc": eval_start.isoformat(),
        "limitation": "scheduler records and hashes are candidate-submitted; a mutually consistent fabrication cannot be distinguished from scheduler-origin evidence",
    }
    return receipt_path, public
