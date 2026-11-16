#!/usr/bin/env python3
# 人工审核：自动检查结果供参考，科学结论需人工复核。
"""Method-neutral integrity gate for Case06 research packets."""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
import stat
import sys
from pathlib import Path, PurePosixPath


class InvalidEnvironment(Exception):
    pass


class InvalidPacket(Exception):
    pass


def fail(message: str) -> None:
    raise InvalidPacket(message)


def sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def object_at(path: Path) -> dict:
    try:
        def unique_pairs(pairs):
            value = {}
            for key, item in pairs:
                if key in value:
                    fail(f"duplicate JSON key: {key}")
                value[key] = item
            return value
        def parse_float(raw: str) -> float:
            value = float(raw)
            if not math.isfinite(value):
                fail("non-finite JSON number")
            return value
        value = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=unique_pairs,
                           parse_constant=lambda x: fail(f"non-finite JSON number: {x}"), parse_float=parse_float)
    except InvalidPacket:
        raise
    except Exception as exc:
        fail(f"invalid JSON {path.name}: {exc}")
    if not isinstance(value, dict):
        fail(f"{path.name} must contain a JSON object")
    forbidden = {"valid_benchmark_answer", "trusted_review", "review_receipt", "reviewer_identity", "verifier_status"}
    def scan(node):
        if isinstance(node, dict):
            if forbidden.intersection(node):
                fail("self-authored review or verifier markers are forbidden")
            for child in node.values():
                scan(child)
        elif isinstance(node, list):
            for child in node:
                scan(child)
    scan(value)
    return value


def strings(value, label: str, nonempty: bool = True) -> list[str]:
    if not isinstance(value, list) or (nonempty and not value) or any(not isinstance(x, str) or not x.strip() for x in value):
        fail(f"{label} must be a {'' if nonempty else 'possibly empty '}list of non-empty strings")
    return value


def safe_regular(root: Path, rel: str) -> Path:
    if not isinstance(rel, str) or not rel or "\\" in rel:
        fail("invalid evidence path")
    p = PurePosixPath(rel)
    if p.is_absolute() or any(part in ("", ".", "..") for part in p.parts):
        fail(f"unsafe evidence path: {rel}")
    cur = root
    for part in p.parts:
        cur = cur / part
        try:
            mode = cur.lstat().st_mode
        except OSError:
            fail(f"missing evidence file: {rel}")
        if stat.S_ISLNK(mode):
            fail(f"symlink evidence path: {rel}")
    if not stat.S_ISREG(cur.lstat().st_mode):
        fail(f"evidence is not a regular file: {rel}")
    try:
        cur.resolve(strict=True).relative_to(root.resolve(strict=True))
    except (OSError, ValueError):
        fail(f"evidence escapes final/: {rel}")
    return cur


def validate_host_ledger(path: Path = Path("/trusted/research-ledger.json"), pin: str | None = None):
    """Return provenance status; candidate files never supply the trust pin."""
    pin = pin if pin is not None else os.environ.get("CCB_RESEARCH_LEDGER_SHA256")
    if not pin and not path.exists():
        return None
    if not pin:
        raise InvalidEnvironment("research ledger is mounted without a host digest pin")
    if not re.fullmatch(r"[0-9a-f]{64}", pin):
        raise InvalidEnvironment("host research ledger digest pin is malformed")
    try:
        mode = path.lstat().st_mode
    except OSError:
        raise InvalidEnvironment("host-pinned research ledger is missing")
    if stat.S_ISLNK(mode) or not stat.S_ISREG(mode) or path.stat().st_size > 8 * 1024 * 1024:
        raise InvalidEnvironment("host research ledger is unsafe or oversized")
    if sha(path) != pin:
        raise InvalidEnvironment("host research ledger digest mismatch")
    try:
        def parse_float(raw: str) -> float:
            value = float(raw)
            if not math.isfinite(value):
                raise ValueError("non-finite host ledger number")
            return value
        ledger = json.loads(path.read_text(encoding="utf-8"), parse_constant=lambda x: fail("non-finite host ledger"), parse_float=parse_float)
    except Exception as exc:
        raise InvalidEnvironment(f"host research ledger is malformed: {exc}")
    if not isinstance(ledger, dict) or ledger.get("schema") != "bench22-research-attempt-ledger/v1":
        raise InvalidEnvironment("host research ledger schema is invalid")
    limits = {"allocations": 12, "concurrent": 1, "cpus": 16, "memory_mib": 61440,
              "job_seconds": 43200, "wall_seconds": 172800, "cpu_seconds": 2764800,
              "output_bytes": 10737418240, "files": 4096}
    if ledger.get("limits") != limits:
        raise InvalidEnvironment("host research resource limits differ from the authorized profile")
    scheduler = ledger.get("scheduler")
    if (not isinstance(scheduler, dict) or set(scheduler) != {"account", "partition"}
            or any(not isinstance(scheduler.get(key), str)
                   or not re.fullmatch(r"[A-Za-z0-9_.-]+", scheduler[key])
                   for key in ("account", "partition"))):
        raise InvalidEnvironment("host ledger scheduler identity is missing or malformed")
    jobs = ledger.get("jobs")
    events = ledger.get("events")
    if not isinstance(jobs, list) or len(jobs) > limits["allocations"] or not isinstance(events, list):
        raise InvalidEnvironment("host research jobs/events inventory is malformed")
    ids = set()
    jobs_by_id = {}
    used_wall = used_cpu = 0
    inventory_file_count = inventory_byte_count = 0
    inventory_by_job = {}
    terminal_states = {"COMPLETED", "FAILED", "CANCELLED", "TIMEOUT", "OUT_OF_MEMORY", "NODE_FAIL", "PREEMPTED"}
    for job in jobs:
        if not isinstance(job, dict) or job.get("dispatch_uncertain") or not isinstance(job.get("job_id"), str) or not job["job_id"].isdigit():
            raise InvalidEnvironment("host ledger contains an uncertain or unowned dispatch")
        if job["job_id"] in ids:
            raise InvalidEnvironment("host ledger repeats a scheduler job")
        ids.add(job["job_id"])
        jobs_by_id[job["job_id"]] = job
        cpus, mem, reserved = (job.get(k) for k in ("cpus", "memory_mib", "reserved_wall_seconds"))
        if (type(cpus) is not int or not 1 <= cpus <= limits["cpus"]
                or type(mem) is not int or not 128 <= mem <= limits["memory_mib"]
                or type(reserved) is not int or not 1 <= reserved <= limits["job_seconds"]):
            raise InvalidEnvironment("host ledger job resources exceed the authorized envelope")
        accounting = job.get("accounting")
        if not isinstance(accounting, dict) or accounting.get("state") not in terminal_states:
            raise InvalidEnvironment("host ledger includes a job without terminal scheduler accounting")
        elapsed = accounting.get("elapsed_seconds")
        if type(elapsed) is not int or not 0 <= elapsed <= reserved + 60 or accounting.get("cpus") != cpus:
            raise InvalidEnvironment("host ledger terminal accounting differs from its reservation")
        raw = accounting.get("raw")
        raw_fields = raw.rstrip("|").split("|") if isinstance(raw, str) else []
        if len(raw_fields) != 10:
            raise InvalidEnvironment("host ledger lacks the original scheduler accounting row")
        jid, state, _exit_code, raw_cpus, raw_elapsed, workdir, account, partition, reqmem, timelimit = raw_fields
        if (jid != job["job_id"] or state.split("+")[0] != accounting["state"]
                or raw_cpus != str(cpus) or raw_elapsed != str(elapsed)
                or workdir != job.get("directory") or account != scheduler["account"]
                or partition != scheduler["partition"]):
            raise InvalidEnvironment("host scheduler accounting identity/resource fields do not match the ledger")
        mem_match = re.fullmatch(r"(\d+)([MG])([cn])?", reqmem)
        wall_match = re.fullmatch(r"(?:(\d+)-)?(\d{1,2}):(\d{2}):(\d{2})", timelimit)
        if not mem_match or not wall_match:
            raise InvalidEnvironment("host scheduler memory or time allocation is malformed")
        try:
            raw_memory = int(mem_match.group(1)) * (1024 if mem_match.group(2) == "G" else 1)
            if mem_match.group(3) == "c":
                raw_memory *= cpus
            raw_wall = ((int(wall_match.group(1) or 0) * 24 + int(wall_match.group(2))) * 3600
                        + int(wall_match.group(3)) * 60 + int(wall_match.group(4)))
        except ValueError:
            raise InvalidEnvironment("host scheduler memory or wall allocation is malformed")
        if raw_memory <= 0 or raw_memory > mem:
            raise InvalidEnvironment("host scheduler memory exceeds its reservation")
        if (int(wall_match.group(2)) > 23 or int(wall_match.group(3)) > 59
                or int(wall_match.group(4)) > 59 or raw_wall <= 0 or raw_wall > reserved):
            raise InvalidEnvironment("host scheduler wall allocation exceeds its reservation")
        inputs = job.get("inputs")
        if not isinstance(inputs, dict) or not inputs or any(not isinstance(v, str) or not re.fullmatch(r"[0-9a-f]{64}", v) for v in inputs.values()):
            raise InvalidEnvironment("host ledger input hashes are malformed")
        used_wall += elapsed
        used_cpu += elapsed * cpus
        inventory = job.get("inventory")
        if not isinstance(inventory, list):
            raise InvalidEnvironment("host ledger job inventory snapshot is missing")
        inventory_by_job[job["job_id"]] = {}
        for item in inventory:
            if (not isinstance(item, dict) or not isinstance(item.get("path"), str)
                    or not item["path"] or PurePosixPath(item["path"]).is_absolute()
                    or PurePosixPath(item["path"]).as_posix() != item["path"]
                    or any(part in ("", ".", "..") for part in PurePosixPath(item["path"]).parts)
                    or type(item.get("bytes")) is not int or item["bytes"] < 0
                    or not isinstance(item.get("sha256"), str)
                    or not re.fullmatch(r"[0-9a-f]{64}", item["sha256"])):
                raise InvalidEnvironment("host ledger job inventory entry is malformed")
            if item["path"] in inventory_by_job[job["job_id"]]:
                raise InvalidEnvironment("host ledger repeats a path in a job inventory")
            inventory_by_job[job["job_id"]][item["path"]] = (item["bytes"], item["sha256"])
            inventory_file_count += 1
            inventory_byte_count += item["bytes"]
    if used_wall > limits["wall_seconds"] or used_cpu > limits["cpu_seconds"]:
        raise InvalidEnvironment("host ledger exceeds cumulative wall or CPU budget")
    if inventory_file_count > limits["files"] or inventory_byte_count > limits["output_bytes"]:
        raise InvalidEnvironment("cross-job output inventory exceeds the 4096-file/10-GiB attempt budget")
    for event_index, event in enumerate(events):
        if not isinstance(event, dict):
            raise InvalidEnvironment("host ledger operation event is malformed")
        operation = event.get("operation")
        if operation == "host_cancel_owned_on_run_exit":
            job_ids = event.get("job_ids")
            if set(event) != {"operation", "job_ids"} or not isinstance(job_ids, list) or any(j not in ids for j in job_ids):
                raise InvalidEnvironment("host cancellation event references an unowned job")
            if any(not isinstance(jobs_by_id[j].get("accounting"), dict)
                   or jobs_by_id[j]["accounting"].get("state") not in terminal_states
                   for j in job_ids):
                raise InvalidEnvironment("host cancellation has not reached terminal accounting")
            continue
        if operation == "host_cleanup_confirmed":
            job_ids = event.get("job_ids")
            if set(event) != {"operation", "job_ids"} or not isinstance(job_ids, list) or set(job_ids) != ids:
                raise InvalidEnvironment("host cleanup confirmation does not cover all owned jobs")
            continue
        if operation == "host_cleanup_unavailable":
            if (set(event) != {"operation", "requires_reconciliation"}
                    or event.get("requires_reconciliation") is not True
                    or not any(isinstance(later, dict) and later.get("operation") == "host_cleanup_confirmed"
                               for later in events[event_index + 1:])):
                raise InvalidEnvironment("host cleanup requires reconciliation; result cannot be reviewed")
            continue
        if operation == "host_slurm_minute_rounding_policy_correction":
            if (set(event) != {"operation", "requested_seconds", "reserved_seconds", "reason"}
                    or type(event.get("requested_seconds")) is not int
                    or type(event.get("reserved_seconds")) is not int
                    or not 1 <= event["requested_seconds"] <= 60
                    or event["reserved_seconds"] != ((event["requested_seconds"] + 59) // 60) * 60
                    or not isinstance(event.get("reason"), str) or not event["reason"].strip()):
                raise InvalidEnvironment("Slurm minute-rounding correction receipt is malformed")
            continue
        if event.get("operation") == "host_reconcile_dispatch":
            if set(event) != {"operation", "job_id"} or event.get("job_id") not in ids:
                raise InvalidEnvironment("host dispatch reconciliation event is malformed")
            continue
        if (event.get("operation") not in {"probe", "status", "submit", "inventory", "fetch", "fetch_chunk"}
                or not isinstance(event.get("request_sha256"), str)
                or not re.fullmatch(r"[0-9a-f]{64}", event["request_sha256"])):
            raise InvalidEnvironment("host ledger operation event chain is malformed")
    collected = ledger.get("collected_sources", [])
    if not isinstance(collected, list):
        raise InvalidEnvironment("host ledger collected_sources inventory is malformed")
    registered = set()
    collected_file_count = collected_byte_count = 0
    for item in collected:
        if (not isinstance(item, dict) or item.get("job_id") not in ids
                or not isinstance(item.get("path"), str) or not item["path"]
                or PurePosixPath(item["path"]).is_absolute()
                or PurePosixPath(item["path"]).as_posix() != item["path"]
                or any(p in ("", ".", "..") for p in PurePosixPath(item["path"]).parts)
                or type(item.get("bytes")) is not int or item["bytes"] < 0
                or not isinstance(item.get("sha256"), str)
                or not re.fullmatch(r"[0-9a-f]{64}", item["sha256"])):
            raise InvalidEnvironment("host ledger collected-source receipt is malformed")
        identity = (item["job_id"], PurePosixPath(item["path"]).as_posix(), item["bytes"], item["sha256"])
        if identity in registered:
            raise InvalidEnvironment("host ledger repeats a collected-source receipt")
        inventory_record = inventory_by_job.get(item["job_id"], {}).get(item["path"])
        if inventory_record != (item["bytes"], item["sha256"]):
            raise InvalidEnvironment("collected source differs from the sealed job inventory")
        registered.add(identity)
        collected_file_count += 1
        collected_byte_count += item["bytes"]
    if collected_file_count > limits["files"] or collected_byte_count > limits["output_bytes"]:
        raise InvalidEnvironment("deduplicated collected output exceeds the 4096-file/10-GiB attempt budget")
    return registered


def protected_scientific_review(final: Path, research: dict):
    """Only a separate, host-pinned independent review can confer research validity."""
    pin = os.environ.get("CCB_RESEARCH_REVIEW_SHA256")
    path = Path("/trusted/scientific-review.json")
    if not pin and not path.exists():
        return None
    if not pin or not re.fullmatch(r"[0-9a-f]{64}", pin):
        raise InvalidEnvironment("independent review pin missing/malformed")
    if path.is_symlink() or not path.is_file() or sha(path) != pin:
        raise InvalidEnvironment("independent review is missing or corrupt")
    try:
        review = json.loads(path.read_text())
    except Exception as exc:
        raise InvalidEnvironment("independent review JSON invalid") from exc
    schema = review.get("schema")
    if schema not in {"bench22-protected-research-review/v1", "bench22-protected-research-review/v2"}:
        raise InvalidEnvironment("independent review schema invalid")
    if research["protocol_fixture"]:
        raise InvalidEnvironment("protocol fixture cannot receive scientific acceptance")
    if review.get("ledger_sha256") != os.environ.get("CCB_RESEARCH_LEDGER_SHA256"):
        raise InvalidEnvironment("independent review ledger binding differs")
    rows=[]
    for p in sorted(final.rglob("*")):
        if p.is_symlink() or (not p.is_file() and not p.is_dir()):
            fail("unsafe reviewed final tree")
        if p.is_file():
            rows.append({"path":p.relative_to(final).as_posix(),"bytes":p.stat().st_size,"sha256":sha(p)})
    tree=hashlib.sha256(json.dumps(rows,sort_keys=True,separators=(",",":")).encode()).hexdigest()
    if review.get("final_tree_sha256") != tree:
        raise InvalidEnvironment("candidate final tree differs from independent reviewed research")
    gates={"research_question","source_quality","method_applicability","comparison",
           "uncertainty_and_stopping","native_provenance_and_budget"}
    body=review.get("review", {})
    if (not isinstance(body, dict) or not isinstance(body.get("gates"), dict)
            or set(body["gates"]) != gates
            or not isinstance(body.get("reviewer"), str) or not body["reviewer"].strip()
            or not isinstance(body.get("evidence"), list) or not body["evidence"]
            or any(not isinstance(item, str) or not item.strip() for item in body["evidence"])
            or type(body.get("joint_improvement_established")) is not bool
            or body["joint_improvement_established"] and research["conclusion"] != "positive"):
        raise InvalidEnvironment("independent scientific validity review incomplete")
    if schema == "bench22-protected-research-review/v1":
        if (review.get("valid_research_answer") is not True
                or review.get("scientific_outcome") != research["conclusion"]
                or body.get("valid_research_answer") is not True
                or body.get("scientific_outcome") != research["conclusion"]
                or any(not isinstance(g, dict) or g.get("status") != "accepted"
                       or not isinstance(g.get("reason"), str) or not g["reason"].strip()
                       for g in body["gates"].values())):
            raise InvalidEnvironment("legacy independent acceptance review is incomplete")
        return {"review": body, "verdict": "accepted"}
    verdict = review.get("verdict")
    if (body.get("schema") != "bench22-independent-research-review/v2"
            or body.get("verdict") != verdict
            or review.get("valid_research_answer") is not (verdict == "accepted")
            or body.get("valid_research_answer") is not (verdict == "accepted")
            or review.get("scientific_outcome") != research["conclusion"]
            or body.get("scientific_outcome") != research["conclusion"]):
        raise InvalidEnvironment("typed independent review binding or outcome is invalid")
    gate_rows = list(body["gates"].values())
    if any(not isinstance(g, dict) or g.get("status") not in {"accepted", "rejected"}
           or not isinstance(g.get("reason"), str) or not g["reason"].strip() for g in gate_rows):
        raise InvalidEnvironment("typed independent review gates are malformed")
    if verdict == "accepted":
        if any(g["status"] != "accepted" for g in gate_rows):
            raise InvalidEnvironment("accepted review must accept every validity gate")
    elif verdict == "rejected":
        if (not any(g["status"] == "rejected" for g in gate_rows)
                or body["joint_improvement_established"]):
            raise InvalidEnvironment("rejected review requires a rejected gate and no joint-improvement claim")
    else:
        raise InvalidEnvironment("unknown independent review verdict")
    return {"review": body, "verdict": verdict}


def run_deterministic_checks(research: dict, sources: dict, final: Path, tests: Path, logs: Path):
    reference = tests / "refs.json"
    if reference.is_symlink() or not reference.is_file():
        raise InvalidEnvironment("deterministic scoring reference is missing or unsafe")
    try:
        module = _make_numeric_checks()
        report = module.evaluate_numeric_evidence(research, sources, final, reference)
    except InvalidEnvironment:
        raise
    except Exception as exc:
        if type(exc).__name__ == "NumericEnvironmentError":
            raise InvalidEnvironment(str(exc)) from exc
        if type(exc).__name__ == "NumericPacketError":
            fail(str(exc))
        raise InvalidEnvironment(f"deterministic scoring error: {exc}") from exc
    if not isinstance(report, dict) or report.get("schema") != "case06-deterministic-checks/v1":
        raise InvalidEnvironment("deterministic scoring report schema is invalid")
    if report.get("overall_scientific_status") not in {"FAIL", "NOT_CHECKED"}:
        raise InvalidEnvironment("deterministic scoring returned an unsafe overall status")
    checks = report.get("checks", [])
    if not isinstance(checks, list) or any(not isinstance(row, dict) or row.get("status") not in {"PASS", "FAIL", "NOT_CHECKED"} for row in checks):
        raise InvalidEnvironment("deterministic scoring checks are malformed")
    counts = report.get("counts")
    expected_counts = {status: sum(row["status"] == status for row in checks)
                       for status in ("PASS", "FAIL", "NOT_CHECKED")}
    expected_research_hash = hashlib.sha256(json.dumps(
        research, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")).hexdigest()
    if (counts != expected_counts or report.get("reference_sha256") != sha(reference)
            or report.get("research_sha256") != expected_research_hash
            or report.get("protocol_fixture") is not research.get("protocol_fixture")):
        raise InvalidEnvironment("deterministic scoring report hashes, counts, or fixture binding are invalid")
    if bool(expected_counts["FAIL"]) != (report["overall_scientific_status"] == "FAIL"):
        raise InvalidEnvironment("deterministic scoring summary disagrees with checks")
    (logs / "deterministic-checks.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return report
    return review

def write_submission_reward(logs: Path, passed: bool) -> None:
    """Write Harbor's packet-integrity metric independently of science status."""
    temporary = logs / "reward.json.tmp"
    try:
        temporary.write_text(
            json.dumps({"submission_checks": int(passed)}) + "\n", encoding="utf-8"
        )
        temporary.replace(logs / "reward.json")
        (logs / "reward.txt").write_text(f"{int(passed)}\n", encoding="utf-8")
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def clear_reward_files(logs: Path) -> None:
    for name in ("reward.txt", "reward.json", "reward.json.tmp"):
        (logs / name).unlink(missing_ok=True)


def main() -> int:
    app = Path(os.environ.get("APP", "/app"))
    tests = Path(os.environ.get("TESTS", "/tests"))
    logs = Path(os.environ.get("LOGS", "/logs/verifier"))
    try:
        logs.mkdir(parents=True, exist_ok=True)
        clear_reward_files(logs)
        if not (tests / "verify.py").is_file() or not (tests / "test.sh").is_file():
            raise InvalidEnvironment("verifier assets are missing")
        final = app / "final"
        report = safe_regular(app, "final/report.md")
        if not report.read_text(encoding="utf-8").strip():
            fail("report.md is empty")
        research = object_at(safe_regular(app, "final/research.json"))
        sources = object_at(safe_regular(app, "final/sources.json"))
        provenance = validate_host_ledger()
        if research.get("schema") != "case06-research/v1":
            fail("unsupported research schema")
        if type(research.get("protocol_fixture")) is not bool:
            fail("protocol_fixture boolean is required")
        if sources.get("schema") != "case06-sources/v1":
            fail("unsupported sources schema")
        if not isinstance(research.get("question"), str) or not research["question"].strip():
            fail("research question is required")
        baseline = research.get("baseline")
        if not isinstance(baseline, dict) or not isinstance(baseline.get("rationale"), str) or not baseline["rationale"].strip():
            fail("baseline rationale is required")
        strings(baseline.get("evidence_source_ids"), "baseline.evidence_source_ids", False)
        strategies = research.get("strategies")
        if not isinstance(strategies, list) or not strategies:
            fail("at least one research strategy is required")
        conclusion_values = {"positive", "negative", "inconclusive"}
        for item in strategies:
            if not isinstance(item, dict) or any(not isinstance(item.get(k), str) or not item[k].strip() for k in ("name", "rationale")):
                fail("each strategy needs a name and rationale")
            if item.get("assessment") not in conclusion_values:
                fail("strategy assessment must be positive, negative, or inconclusive")
            strings(item.get("evidence_source_ids"), "strategy.evidence_source_ids", False)
        if research.get("conclusion") not in conclusion_values:
            fail("conclusion must be positive, negative, or inconclusive")
        if research["protocol_fixture"] and research["conclusion"] != "inconclusive":
            fail("protocol fixtures may only declare an inconclusive conclusion")
        if not isinstance(research.get("comparison"), dict):
            fail("comparison object is required")
        comparison = research["comparison"]
        strings(comparison.get("criteria"), "comparison.criteria")
        strings(comparison.get("limitations"), "comparison.limitations", False)
        stop = research.get("stopping")
        if not isinstance(stop, dict) or any(not isinstance(stop.get(k), str) or not stop[k].strip() for k in ("rule", "reason")):
            fail("stopping rule and reason are required")
        strings(research.get("limitations"), "limitations")
        source_rows = sources.get("sources")
        if not isinstance(source_rows, list) or not source_rows:
            fail("sources must be a non-empty list")
        by_id = {}
        covered = set()
        for row in source_rows:
            if not isinstance(row, dict):
                fail("source entries must be objects")
            required = ("id", "title", "type", "query", "retrieved_at", "access_url", "license_or_access", "availability")
            if any(not isinstance(row.get(k), str) or not row[k].strip() for k in required):
                fail("source provenance fields are required")
            sid = row["id"]
            if sid in by_id:
                fail(f"duplicate source id: {sid}")
            by_id[sid] = row
            if row["availability"] == "retained":
                rel = row.get("path")
                if not isinstance(rel, str) or not rel.startswith("native/"):
                    fail(f"retained source path must be under native/: {sid}")
                path = safe_regular(final, rel)
                size = path.stat().st_size
                digest = sha(path)
                if not isinstance(row.get("bytes"), int) or isinstance(row.get("bytes"), bool) or row["bytes"] != size or row.get("sha256") != digest:
                    fail(f"source size/hash mismatch: {sid}")
                if "job_id" in row:
                    broker_path = row.get("broker_path")
                    receipt = (row["job_id"], broker_path, size, digest)
                    if not isinstance(broker_path, str) or receipt not in (provenance or set()):
                        fail(f"source does not match trusted broker collection: {sid}")
                elif "broker_path" in row:
                    fail(f"broker_path requires job_id: {sid}")
                covered.add(rel)
            elif row["availability"] in {"metadata_only", "unavailable"}:
                if not isinstance(row.get("reason"), str) or not row["reason"].strip():
                    fail(f"source access reason required: {sid}")
            else:
                fail(f"unknown source availability: {sid}")
        cited = set(baseline["evidence_source_ids"])
        for item in strategies:
            cited.update(item["evidence_source_ids"])
        if not cited or not cited.issubset(by_id):
            fail("research evidence cites missing sources or cites none")
        native_root = final / "native"
        if native_root.is_symlink() or not native_root.is_dir():
            fail("final/native must be a real directory")
        actual = set()
        for path in native_root.rglob("*"):
            rel_native = path.relative_to(final).as_posix()
            mode = path.lstat().st_mode
            if stat.S_ISLNK(mode):
                fail(f"symlink in native directory: {rel_native}")
            if stat.S_ISREG(mode):
                actual.add(rel_native)
            elif not stat.S_ISDIR(mode):
                fail(f"special file in native directory: {rel_native}")
        if not actual:
            fail("native evidence directory is empty")
        manifest = research.get("native_manifest")
        if not isinstance(manifest, list):
            fail("native_manifest is required")
        manifest_paths = set()
        for row in manifest:
            if not isinstance(row, dict) or set(("path", "sha256", "bytes")) - row.keys():
                fail("malformed native manifest record")
            rel = row["path"]
            if not isinstance(rel, str) or not rel.startswith("native/") or rel in manifest_paths:
                fail("native manifest paths must be unique native/ paths")
            path = safe_regular(final, rel)
            if (row["sha256"] != sha(path) or isinstance(row["bytes"], bool)
                    or not isinstance(row["bytes"], int) or row["bytes"] != path.stat().st_size):
                fail(f"native manifest hash/size mismatch: {rel}")
            if "job_id" in row:
                receipt = (row["job_id"], row.get("broker_path"), row["bytes"], row["sha256"])
                if not isinstance(row.get("broker_path"), str) or receipt not in (provenance or set()):
                    fail(f"native file does not match trusted broker collection: {rel}")
            elif "broker_path" in row:
                fail(f"broker_path requires job_id: {rel}")
            manifest_paths.add(rel)
        if actual != manifest_paths:
            fail("native manifest does not cover native/ exactly")
        if not covered.issubset(actual):
            fail("retained source files must be included in native_manifest")
        numeric_report = run_deterministic_checks(research, sources, final, tests, logs)
        if numeric_report["overall_scientific_status"] == "FAIL":
            fail("a deterministic numeric check found a determinate contradiction")
        accepted_review = protected_scientific_review(final, research)
        if accepted_review is not None and accepted_review["verdict"] == "rejected":
            (logs / "reward.txt").write_text("0\n", encoding="utf-8")
            (logs / "verification.json").write_text(json.dumps({
                "status": "FAIL", "reward": 0, "valid_research_answer": False,
                "scientific_outcome": research["conclusion"],
                "joint_improvement_established": False,
                "basis": "independent host-pinned human review rejected research validity"
            }, indent=2) + "\n", encoding="utf-8")
            write_submission_reward(logs, True)
            return 1
        if accepted_review is not None:
            (logs / "reward.txt").write_text("1\n")
            (logs / "verification.json").write_text(json.dumps({
                "status":"PASS","reward":1,"valid_research_answer":True,
                "scientific_outcome":research["conclusion"],
                "joint_improvement_established":accepted_review["review"].get("joint_improvement_established",False),
                "basis":"independent host-pinned review; outcome and benchmark validity are separate"
            },indent=2)+"\n")
            write_submission_reward(logs, True)
            return 0
        logs.mkdir(parents=True, exist_ok=True)
        (logs / "verification.json").write_text(json.dumps({
            "status": "REVIEW_REQUIRED", "conclusion": research["conclusion"],
            "reward": None, "provenance": "host-ledger-validated" if provenance is not None else "missing-context",
            "reason": "packet integrity passed; scientific review required",
            "deterministic_status": numeric_report["overall_scientific_status"]
        }, indent=2) + "\n", encoding="utf-8")
        write_submission_reward(logs, True)
        print("REVIEW_REQUIRED: protocol valid; no scientific reward")
        return 0
    except InvalidEnvironment as exc:
        logs.mkdir(parents=True, exist_ok=True)
        clear_reward_files(logs)
        (logs / "verification.json").write_text(json.dumps({"status": "ENV_INVALID", "reward": None, "reason": str(exc)}, indent=2) + "\n")
        print(f"ENV_INVALID: {exc}", file=sys.stderr)
        return 2
    except InvalidPacket as exc:
        logs.mkdir(parents=True, exist_ok=True)
        try:
            (logs / "reward.txt").write_text("0\n", encoding="utf-8")
            (logs / "verification.json").write_text(json.dumps({"status": "FAIL", "reward": 0, "reason": str(exc)}, indent=2) + "\n", encoding="utf-8")
            write_submission_reward(logs, False)
        except Exception as output_exc:
            clear_reward_files(logs)
            (logs / "verification.json").write_text(json.dumps({"status": "ENV_INVALID", "reward": None, "reason": f"verifier output error: {output_exc}"}, indent=2) + "\n", encoding="utf-8")
            print(f"ENV_INVALID: verifier output error: {output_exc}", file=sys.stderr)
            return 2
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:
        logs.mkdir(parents=True, exist_ok=True)
        clear_reward_files(logs)
        (logs / "verification.json").write_text(json.dumps({"status": "ENV_INVALID", "reward": None, "reason": f"verifier error: {exc}"}, indent=2) + "\n")
        print(f"ENV_INVALID: verifier error: {exc}", file=sys.stderr)
        return 2



def _make_numeric_checks():
    from types import SimpleNamespace

    import hashlib
    import json
    import math
    import re
    import stat
    from decimal import Decimal, InvalidOperation
    from pathlib import Path, PurePosixPath
    from typing import Any


    class NumericEnvironmentError(Exception):
        """The grader's pinned private reference is missing or invalid."""


    class NumericPacketError(Exception):
        """The submitted numeric extension is structurally invalid."""


    SCHEMA = "case06-deterministic-checks/v1"
    CONTRACT = "case06-numeric/v1"
    PAPER_SHA = "14a1ebe10c7b4e0ec9f8865bd3dfa4551483e1dc5c7cb724644d7575a2267e90"
    AUDIT_SHA = "eff22fe1954083da2d14dc55574bc1e1fa30bf23d250b97a7714b00769b93839"
    REFERENCE_SHA = "bc94367345dddc826fd3f807e72b065aa2266db56fa9e05b3845eb0c4c33dfb8"
    _SHA_RE = re.compile(r"^[0-9a-f]{64}$")
    _REQUIRED_EVIDENCE = {
        "id", "quantity", "subject", "source_kind", "value_kind", "unit",
        "source_id", "locator", "conditions", "quantity_definition", "claim_role",
    }
    _CONDITION_FIELDS = ("temperature_K", "medium_or_phase", "method", "time_regime", "initial_state")
    _SUPPORTED_ASSERTION_ROLES = {"citation", "numerical_reproduction", "own_prediction"}


    def _canonical_hash(value: Any) -> str:
        try:
            raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
                             allow_nan=False).encode("utf-8")
        except (TypeError, ValueError) as exc:
            raise NumericPacketError(f"research JSON is not canonicalizable: {exc}") from exc
        return hashlib.sha256(raw).hexdigest()


    def _sha_file(path: Path) -> str:
        h = hashlib.sha256()
        with path.open("rb") as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                h.update(block)
        return h.hexdigest()


    def _finite_number(value: Any, label: str) -> float:
        if isinstance(value, bool) or not isinstance(value, (int, float, Decimal)):
            raise NumericPacketError(f"{label} must be a finite JSON number (boolean is not numeric)")
        try:
            result = float(value)
        except (ValueError, OverflowError) as exc:
            raise NumericPacketError(f"{label} is not a finite number") from exc
        if not math.isfinite(result):
            raise NumericPacketError(f"{label} must be finite")
        return result


    def _value_shape(entry: dict, label: str) -> tuple[str, float, float | None]:
        kind = entry.get("value_kind")
        if kind == "scalar":
            if "value" not in entry or "lower" in entry or "upper" in entry:
                raise NumericPacketError(f"{label} scalar requires only value")
            return kind, _finite_number(entry["value"], f"{label}.value"), None
        if kind == "interval":
            if "lower" not in entry or "upper" not in entry or "value" in entry:
                raise NumericPacketError(f"{label} interval requires lower and upper")
            lo = _finite_number(entry["lower"], f"{label}.lower")
            hi = _finite_number(entry["upper"], f"{label}.upper")
            if lo > hi:
                raise NumericPacketError(f"{label} interval lower exceeds upper")
            return kind, lo, hi
        raise NumericPacketError(f"{label}.value_kind must be scalar or interval")


    def _read_reference(path: Path) -> tuple[dict, str]:
        try:
            st = path.lstat()
            if stat.S_ISLNK(st.st_mode) or not stat.S_ISREG(st.st_mode) or st.st_size > 2_000_000:
                raise NumericEnvironmentError("private paper reference is unsafe or oversized")
            digest = _sha_file(path)
            ref = json.loads(path.read_text(encoding="utf-8"), parse_constant=lambda x: (_ for _ in ()).throw(ValueError(x)))
        except NumericEnvironmentError:
            raise
        except Exception as exc:
            raise NumericEnvironmentError(f"private paper reference is unavailable or malformed: {exc}") from exc
        if digest != REFERENCE_SHA:
            raise NumericEnvironmentError("private paper reference does not match the pinned registry digest")
        if not isinstance(ref, dict) or ref.get("schema") != "case06-private-paper-reference/v1":
            raise NumericEnvironmentError("private paper reference schema is invalid")
        paper = ref.get("paper")
        registry = ref.get("registry")
        if (not isinstance(paper, dict) or paper.get("sha256") != PAPER_SHA or
                ref.get("audit_sha256") != AUDIT_SHA or not isinstance(registry, list)):
            raise NumericEnvironmentError("private paper reference identity or registry is invalid")
        ids = set()
        for row in registry:
            if not isinstance(row, dict) or not isinstance(row.get("reference_id"), str) or row["reference_id"] in ids:
                raise NumericEnvironmentError("private paper reference entries are malformed or duplicated")
            ids.add(row["reference_id"])
            if row.get("trusted_source_sha256") != PAPER_SHA:
                raise NumericEnvironmentError("private paper reference contains an untrusted source identity")
        if len(registry) != 48:
            raise NumericEnvironmentError("private paper reference record count is unexpected")
        return ref, digest


    def _check(status: str, check: str, reason: str, **extra: Any) -> dict:
        item = {"status": status, "check": check, "reason": reason}
        item.update(extra)
        return item


    def _safe_native_file(final: Path, rel: Any) -> Path | None:
        if not isinstance(rel, str) or "\\" in rel:
            return None
        p = PurePosixPath(rel)
        if p.is_absolute() or not p.parts or p.parts[0] != "native" or any(x in ("", ".", "..") for x in p.parts):
            return None
        cur = final
        try:
            for part in p.parts:
                cur = cur / part
                mode = cur.lstat().st_mode
                if stat.S_ISLNK(mode):
                    return None
            if not stat.S_ISREG(cur.lstat().st_mode):
                return None
            cur.resolve(strict=True).relative_to(final.resolve(strict=True))
        except (OSError, ValueError):
            return None
        return cur


    def _verified_paper_source(source: Any, research: dict, final: Path) -> bool:
        """Require the retained source bytes and both submitted indexes to agree."""
        if not isinstance(source, dict):
            return False
        rel = source.get("path")
        digest = source.get("sha256")
        if digest != PAPER_SHA or not isinstance(source.get("bytes"), int) or isinstance(source.get("bytes"), bool):
            return False
        path = _safe_native_file(final, rel)
        if path is None:
            return False
        try:
            if path.stat().st_size != source["bytes"] or _sha_file(path) != PAPER_SHA:
                return False
        except OSError:
            return False
        manifest = research.get("native_manifest")
        if not isinstance(manifest, list):
            return False
        matches = [x for x in manifest if isinstance(x, dict) and x.get("path") == rel]
        return len(matches) == 1 and matches[0].get("sha256") == PAPER_SHA and matches[0].get("bytes") == source["bytes"]


    def _locator_matches(actual: Any, expected: dict) -> bool:
        if isinstance(actual, dict):
            aliases = {"page": "page", "printed_page": "printed_page", "table": "table", "row": "row", "quantity_column": "quantity_column"}
            return all(actual.get(k) == expected.get(v) for k, v in aliases.items())
        if isinstance(actual, str):
            text = " ".join(actual.lower().replace("page", "p").replace("printed", "").replace(" ", "").split())
            return "p.3" in text and "table1" in text
        return False


    def _rounded_contains(raw: str, candidate: float) -> bool:
        try:
            d = Decimal(raw)
            c = Decimal(str(candidate))
        except (InvalidOperation, ValueError):
            return False
        quantum = Decimal(1).scaleb(d.as_tuple().exponent)
        half = abs(quantum) / Decimal(2)
        return d - half <= c <= d + half


    def _reference_check(entry: dict, source: Any, refs: list[dict], research: dict, final: Path) -> dict:
        if entry["claim_role"] != "citation":
            return _check("NOT_CHECKED", "reference_citation", "only explicit citation claims are compared with a paper value", claim_id=entry["id"])
        if not _verified_paper_source(source, research, final):
            return _check("NOT_CHECKED", "reference_citation", "retained source bytes are not independently verified as the registered paper", claim_id=entry["id"])
        if entry["source_kind"] not in ("theoretical_prediction", "experimental"):
            return _check("NOT_CHECKED", "reference_citation", "paper Table 1 source kind is not established", claim_id=entry["id"])
        candidates = [r for r in refs if r.get("subject") == entry["subject"] and r.get("quantity") == entry["quantity"] and _locator_matches(entry["locator"], r["locator"])]
        if len(candidates) != 1:
            return _check("NOT_CHECKED", "reference_citation", "source, locator, subject, quantity, kind, unit, or value shape is not uniquely registered", claim_id=entry["id"])
        ref = candidates[0]
        if ref.get("record_status") == "not_reported":
            return _check("FAIL", "reference_citation", "the verified Table 1 cell is explicitly blank; a numeric citation is unsupported", claim_id=entry["id"], reference_id=ref["reference_id"], scope="citation identity only")
        if entry["source_kind"] != ref["source_kind"]:
            return _check("FAIL", "reference_citation", "verified Table 1 citation is labeled with the wrong source kind", claim_id=entry["id"], reference_id=ref["reference_id"], scope="citation identity only")
        if entry["value_kind"] != ref["value_kind"]:
            return _check("NOT_CHECKED", "reference_citation", "scalar/interval shape differs; this checker does not interpret a point as reproducing a printed range", claim_id=entry["id"], reference_id=ref["reference_id"])
        factor = _unit_factor(entry["quantity"], entry["unit"], ref["unit"])
        if factor is None:
            return _check("NOT_CHECKED", "reference_citation", "citation unit has no supported conversion to the registered reference unit", claim_id=entry["id"], reference_id=ref["reference_id"])
        if entry["value_kind"] == "scalar":
            candidate = _finite_number(entry["value"], f"{entry['id']}.value") * factor
            ok = _rounded_contains(ref["value"], candidate)
        else:
            candidate_lo = _finite_number(entry["lower"], f"{entry['id']}.lower") * factor
            candidate_hi = _finite_number(entry["upper"], f"{entry['id']}.upper") * factor
            ok = (_rounded_contains(ref["lower"], candidate_lo) and _rounded_contains(ref["upper"], candidate_hi))
        return _check("PASS" if ok else "FAIL", "reference_citation",
                      "printed Table 1 value agrees within its displayed rounding interval" if ok else "claim differs from the registered printed Table 1 value/interval",
                      claim_id=entry["id"], reference_id=ref["reference_id"], scope="citation consistency only",
                      converted_to_reference_unit=entry["unit"] != ref["unit"], conversion_factor=factor)


    def _unit_factor(quantity: str, src: str, dst: str) -> float | None:
        factors = {
            "effective_total_RISC_rate": {"s^-1": 1.0, "ms^-1": 1e-3, "us^-1": 1e-6},
            "elementary_RISC_rate": {"s^-1": 1.0, "ms^-1": 1e-3, "us^-1": 1e-6},
            "kF": {"s^-1": 1.0, "ms^-1": 1e-3, "us^-1": 1e-6},
            "FWHM": {"nm": 1.0, "um": 1e-3},
            "single_exciton_PLQY": {"1": 1.0, "%": 100.0, "percent": 100.0},
            "state_population": {"1": 1.0, "%": 100.0, "percent": 100.0},
        }
        mapping = factors.get(quantity)
        if not mapping or src not in mapping or dst not in mapping:
            return None
        return mapping[dst] / mapping[src]


    def _entry_value(entry: dict) -> tuple[float, float | None]:
        kind, lo, hi = _value_shape(entry, entry["id"])
        return lo, hi


    def _numeric_claims(research: dict) -> tuple[list[dict], list[dict]]:
        if not any(key in research for key in ("numeric_contract", "numeric_evidence", "derivations")):
            return [], []
        if research.get("numeric_contract") != CONTRACT:
            raise NumericPacketError("numeric extension requires numeric_contract case06-numeric/v1")
        evidence = research.get("numeric_evidence")
        derivations = research.get("derivations")
        if not isinstance(evidence, list) or not isinstance(derivations, list):
            raise NumericPacketError("numeric_evidence and derivations must both be arrays")
        seen = set()
        for i, entry in enumerate(evidence):
            label = f"numeric_evidence[{i}]"
            if not isinstance(entry, dict) or not _REQUIRED_EVIDENCE.issubset(entry):
                raise NumericPacketError(f"{label} is missing required contract fields")
            if not isinstance(entry["id"], str) or not entry["id"].strip() or entry["id"] in seen:
                raise NumericPacketError(f"{label}.id must be a unique non-empty string")
            seen.add(entry["id"])
            if not isinstance(entry["quantity"], str) or not entry["quantity"].strip():
                raise NumericPacketError(f"{label}.quantity must be a non-empty string")
            for key in ("subject", "source_kind", "unit", "source_id", "claim_role"):
                if not isinstance(entry[key], str) or not entry[key].strip():
                    raise NumericPacketError(f"{label}.{key} must be a non-empty string")
            if entry["source_kind"] not in ("theoretical_prediction", "experimental", "independent_reproduction", "other"):
                raise NumericPacketError(f"{label}.source_kind is invalid")
            if not isinstance(entry["claim_role"], str) or not entry["claim_role"].strip():
                raise NumericPacketError(f"{label}.claim_role must be a non-empty string")
            if not isinstance(entry["locator"], (str, dict)):
                raise NumericPacketError(f"{label}.locator must be a string or object")
            if not isinstance(entry["quantity_definition"], (str, dict)):
                raise NumericPacketError(f"{label}.quantity_definition must be a string or object")
            conditions = entry["conditions"]
            if not isinstance(conditions, dict) or any(k not in conditions for k in _CONDITION_FIELDS):
                raise NumericPacketError(f"{label}.conditions must explicitly list all condition fields")
            for key in _CONDITION_FIELDS:
                value = conditions[key]
                if value is not None and not isinstance(value, (str, int, float)):
                    raise NumericPacketError(f"{label}.conditions.{key} must be scalar or null")
                if isinstance(value, bool):
                    raise NumericPacketError(f"{label}.conditions.{key} cannot be boolean")
                if isinstance(value, (int, float)) and not math.isfinite(float(value)):
                    raise NumericPacketError(f"{label}.conditions.{key} must be finite")
                if value is None and not isinstance(conditions.get("unknown_reason"), str):
                    raise NumericPacketError(f"{label}.conditions nulls require unknown_reason")
            _value_shape(entry, label)
        derivation_ids = set()
        for i, derivation in enumerate(derivations):
            label = f"derivations[{i}]"
            required = {"id", "operation", "input_claim_ids", "output_claim_id", "formula_id"}
            if not isinstance(derivation, dict) or not required.issubset(derivation):
                raise NumericPacketError(f"{label} is missing required contract fields")
            if not isinstance(derivation["id"], str) or not derivation["id"].strip():
                raise NumericPacketError(f"{label}.id must be a non-empty string")
            if derivation["id"] in derivation_ids:
                raise NumericPacketError("derivation IDs must be unique")
            derivation_ids.add(derivation["id"])
            if not isinstance(derivation["operation"], str) or not derivation["operation"].strip():
                raise NumericPacketError(f"{label}.operation must be a non-empty string")
            if not isinstance(derivation["formula_id"], str) or not derivation["formula_id"].strip():
                raise NumericPacketError(f"{label}.formula_id must be non-empty")
            if not isinstance(derivation["input_claim_ids"], list) or any(x not in seen for x in derivation["input_claim_ids"]):
                raise NumericPacketError(f"{label}.input_claim_ids must reference existing claims")
            if derivation.get("output_claim_id") not in seen:
                raise NumericPacketError(f"{label}.output_claim_id must reference an existing claim")
        return evidence, derivations


    def _math_checks(evidence: list[dict], derivations: list[dict]) -> tuple[list[dict], list[str]]:
        by_id = {x["id"]: x for x in evidence}
        checks: list[dict] = []
        manual: list[str] = []
        for d in derivations:
            op, ids = d["operation"], d["input_claim_ids"]
            out = by_id[d["output_claim_id"]]
            involved = [by_id[cid] for cid in ids] + [out]
            unsupported_roles = [x["id"] for x in involved if x["claim_role"] not in _SUPPORTED_ASSERTION_ROLES]
            if unsupported_roles:
                checks.append(_check("NOT_CHECKED", op, "diagnostic/failed-estimate claim roles are not treated as asserted numeric results", derivation_id=d["id"], claims=unsupported_roles))
                manual.append(f"Derivation {d['id']} contains claims with non-assertion roles; review manually.")
                continue
            if op == "unit_conversion":
                if len(ids) != 1:
                    raise NumericPacketError(f"derivation {d['id']} unit_conversion requires one input")
                src = by_id[ids[0]]
                factor = _unit_factor(src["quantity"], src["unit"], out["unit"])
                if d["formula_id"] not in ("explicit_supported_unit_conversion", "unit_scale") or factor is None or src["quantity"] != out["quantity"]:
                    checks.append(_check("NOT_CHECKED", op, "unit or quantity conversion is outside the finite supported map", derivation_id=d["id"]))
                    manual.append(f"Unit conversion {d['id']} is outside the supported map.")
                    continue
                sk, sv, shi = _value_shape(src, src["id"])
                okind, ov, ohi = _value_shape(out, out["id"])
                expected = (sv * factor, shi * factor if shi is not None else None)
                ok = sk == okind and math.isclose(ov, expected[0], rel_tol=1e-12, abs_tol=1e-15) and ((expected[1] is None and ohi is None) or (expected[1] is not None and ohi is not None and math.isclose(ohi, expected[1], rel_tol=1e-12, abs_tol=1e-15)))
                checks.append(_check("PASS" if ok else "FAIL", op, "unit conversion arithmetic recomputed" if ok else "converted value does not match supported unit factor", derivation_id=d["id"], arithmetic_only=True))
                manual.append(f"Unit conversion {d['id']} does not establish source validity or physical applicability.")
            elif op == "ratio":
                if len(ids) != 2:
                    raise NumericPacketError(f"derivation {d['id']} ratio requires two inputs")
                a, b = (by_id[x] for x in ids)
                if d["formula_id"] != "numerator_over_denominator" or a["unit"] != b["unit"] or out["unit"] != "1" or a["value_kind"] != "scalar" or b["value_kind"] != "scalar" or out["value_kind"] != "scalar":
                    checks.append(_check("NOT_CHECKED", op, "ratio operands/formula are outside the supported scalar same-unit ratio", derivation_id=d["id"]))
                    manual.append(f"Ratio {d['id']} has unsupported units or value shape.")
                    continue
                av, bv, ov = (_finite_number(x["value"], x["id"] + ".value") for x in (a, b, out))
                if bv == 0:
                    checks.append(_check("NOT_CHECKED", op, "zero denominator is undefined and is not replaced by zero", derivation_id=d["id"]))
                    manual.append(f"Ratio {d['id']} has zero denominator.")
                    continue
                ok = math.isclose(ov, av / bv, rel_tol=1e-12, abs_tol=1e-15)
                checks.append(_check("PASS" if ok else "FAIL", op, "ratio arithmetic recomputed" if ok else "reported ratio does not equal numerator divided by denominator", derivation_id=d["id"], arithmetic_only=True))
                manual.append(f"Ratio {d['id']} is arithmetic only; it does not establish physical comparability or improvement.")
            elif op == "weighted_total2":
                checks.append(_weighted_total_check(d, by_id))
                manual.append(f"Weighted-total derivation {d['id']} verifies arithmetic on declared inputs only; provenance, same-time/state identity, causality, and physical applicability were not established.")
            else:
                checks.append(_check("NOT_CHECKED", op, "operation is not in the finite deterministic math registry", derivation_id=d["id"]))
                manual.append(f"Derivation {d['id']} uses an unsupported operation and requires human review.")
        return checks, manual


    def _weighted_total_check(d: dict, by_id: dict[str, dict]) -> dict:
        if len(d["input_claim_ids"]) != 4 or d["formula_id"] != "population_weighted_T1_T2_to_S1":
            return _check("NOT_CHECKED", "weighted_total2", "requires four declared operands and the registered finite formula", derivation_id=d["id"], arithmetic_only=True, physical_applicability_status="NOT_CHECKED")
        claims = [by_id[x] for x in d["input_claim_ids"]]
        pops = [x for x in claims if x["quantity"] == "state_population"]
        rates = [x for x in claims if x["quantity"] == "elementary_RISC_rate"]
        out = by_id[d["output_claim_id"]]
        if len(pops) != 2 or len(rates) != 2 or out["quantity"] != "effective_total_RISC_rate" or out["unit"] != "s^-1" or out["value_kind"] != "scalar":
            return _check("NOT_CHECKED", "weighted_total2", "operands do not have the required two populations, two elementary rates, and scalar total output", derivation_id=d["id"], arithmetic_only=True, physical_applicability_status="NOT_CHECKED")
        def state(x):
            qd = x.get("quantity_definition")
            if isinstance(qd, dict):
                return qd.get("state")
            if isinstance(qd, str):
                text = qd.upper().replace(" ", "")
                return "T1" if "T1" in text else "T2" if "T2" in text else None
            return None
        pop_by_state = {state(x): x for x in pops}
        rate_by_state = {state(x): x for x in rates}
        if set(pop_by_state) != {"T1", "T2"} or set(rate_by_state) != {"T1", "T2"} or any(x["unit"] != "1" or x["value_kind"] != "scalar" for x in pops) or any(x["unit"] != "s^-1" or x["value_kind"] != "scalar" for x in rates):
            return _check("NOT_CHECKED", "weighted_total2", "state/channel labels, units, or scalar operand shapes do not unambiguously fit the declared formula", derivation_id=d["id"], arithmetic_only=True, physical_applicability_status="NOT_CHECKED")
        p1 = _finite_number(pop_by_state["T1"]["value"], "T1 population")
        p2 = _finite_number(pop_by_state["T2"]["value"], "T2 population")
        k1 = _finite_number(rate_by_state["T1"]["value"], "T1->S1 rate")
        k2 = _finite_number(rate_by_state["T2"]["value"], "T2->S1 rate")
        if p1 < 0 or p2 < 0 or p1 + p2 <= 0 or k1 < 0 or k2 < 0:
            return _check("FAIL", "weighted_total2", "declared populations/rates violate the finite nonnegative operand domain", derivation_id=d["id"], arithmetic_only=True, physical_applicability_status="NOT_CHECKED")
        value = _finite_number(out["value"], "weighted total output")
        expected = (p1 * k1 + p2 * k2) / (p1 + p2)
        ok = math.isclose(value, expected, rel_tol=1e-12, abs_tol=1e-15)
        return _check("PASS" if ok else "FAIL", "weighted_total2", "arithmetic on declared inputs matches" if ok else "output differs from the declared weighted-total arithmetic", derivation_id=d["id"], arithmetic_only=True, physical_applicability_status="NOT_CHECKED", reported_value=value, recomputed_value=expected)


    def evaluate_numeric_evidence(research: dict, sources: dict, final: Path, reference_path: Path) -> dict:
        """Evaluate finite citation and arithmetic checks; never produce science PASS."""
        if not isinstance(research, dict) or not isinstance(sources, dict) or not isinstance(final, Path):
            raise NumericPacketError("research/sources must be objects and final must be pathlib.Path")
        reference, reference_hash = _read_reference(reference_path)
        research_hash = _canonical_hash(research)
        if not any(key in research for key in ("numeric_contract", "numeric_evidence", "derivations")):
            manual = ["No revision-3 numeric extension was supplied; the open scientific result requires human review."]
            if research.get("protocol_fixture") is True:
                manual.append("Protocol fixture is not a scientific submission and cannot receive an overall scientific PASS.")
            checks = [_check("NOT_CHECKED", "numeric_contract", "optional numeric extension is absent")]
            return {"schema": SCHEMA, "contract_version": None, "reference_sha256": reference_hash,
                    "research_sha256": research_hash, "checks": checks,
                    "counts": {"PASS": 0, "FAIL": 0, "NOT_CHECKED": 1},
                    "manual_review_reasons": manual, "overall_scientific_status": "NOT_CHECKED",
                    "protocol_fixture": research.get("protocol_fixture") is True}
        evidence, derivations = _numeric_claims(research)
        if not isinstance(sources.get("sources"), list):
            raise NumericPacketError("sources.sources must be an array")
        source_rows = {}
        for row in sources["sources"]:
            if not isinstance(row, dict) or not isinstance(row.get("id"), str):
                raise NumericPacketError("sources entries require string id")
            if row["id"] in source_rows:
                raise NumericPacketError("sources IDs must be unique")
            source_rows[row["id"]] = row
        manual = []
        checks = []
        if research.get("protocol_fixture") is True:
            manual.append("Protocol fixture is not a scientific submission and cannot receive an overall scientific PASS.")
        for entry in evidence:
            source = source_rows.get(entry["source_id"])
            checks.append(_reference_check(entry, source, reference["registry"], research, final))
            if entry["quantity"] == "single_exciton_PLQY":
                qd = entry["quantity_definition"]
                if entry["claim_role"] not in _SUPPORTED_ASSERTION_ROLES:
                    checks.append(_check("NOT_CHECKED", "PLQY_bounds", "claim role is diagnostic/failed-estimate and is not treated as a valid numeric assertion", claim_id=entry["id"]))
                    manual.append(f"PLQY claim {entry['id']} has a non-assertion role.")
                elif entry["value_kind"] == "interval":
                    checks.append(_check("NOT_CHECKED", "PLQY_bounds", "interval may represent statistical uncertainty and is not clipped or physically rejected", claim_id=entry["id"]))
                    manual.append(f"PLQY interval {entry['id']} requires human interpretation of its uncertainty model.")
                elif not (isinstance(qd, dict) and qd.get("kind") == "single_exciton_linear_PLQY" and isinstance(qd.get("denominator"), str) and bool(qd["denominator"].strip())):
                    checks.append(_check("NOT_CHECKED", "PLQY_bounds", "the single-exciton PLQY denominator/definition is not explicit", claim_id=entry["id"]))
                    manual.append(f"PLQY claim {entry['id']} has no explicit single-exciton denominator.")
                else:
                    lo, hi = _entry_value(entry)
                    factor = _unit_factor("single_exciton_PLQY", entry["unit"], "1")
                    if factor is None:
                        checks.append(_check("NOT_CHECKED", "PLQY_bounds", "unit has no supported normalization to fractional PLQY", claim_id=entry["id"]))
                        manual.append(f"PLQY claim {entry['id']} uses an unsupported unit; its bounds were not inferred.")
                    else:
                        lo *= factor
                        hi = hi * factor if hi is not None else None
                        valid = 0 <= lo <= 1 and (hi is None or 0 <= hi <= 1)
                        checks.append(_check("PASS" if valid else "FAIL", "PLQY_bounds", "explicit single-exciton linear PLQY normalized to fraction lies in [0,1]" if valid else "explicit single-exciton linear PLQY normalized to fraction lies outside [0,1]", claim_id=entry["id"], normalized_unit="1", normalized_lower=lo, normalized_upper=hi))
            elif entry["quantity"] == "FWHM" and entry["claim_role"] != "citation":
                checks.append(_check("NOT_CHECKED", "spectrum_FWHM", "raw spectrum and independently specified axis/peak convention are not part of this checker", claim_id=entry["id"]))
                manual.append(f"FWHM claim {entry['id']} requires review of spectrum data and method applicability.")
            if entry["quantity"] in ("effective_total_RISC_rate", "kF", "elementary_RISC_rate"):
                manual.append(f"Rate claim {entry['id']} condition/method applicability is not inferred from a citation or numeric value.")
        math_checks, math_manual = _math_checks(evidence, derivations)
        checks.extend(math_checks)
        manual.extend(math_manual)
        if not evidence and not derivations:
            checks.append(_check("NOT_CHECKED", "numeric_evidence", "numeric extension arrays are present but empty"))
            manual.append("The packet supplied no numeric claims to evaluate.")
        counts = {s: sum(1 for c in checks if c["status"] == s) for s in ("PASS", "FAIL", "NOT_CHECKED")}
        overall = "FAIL" if counts["FAIL"] else "NOT_CHECKED"
        return {"schema": SCHEMA, "contract_version": CONTRACT, "reference_sha256": reference_hash,
                "research_sha256": research_hash, "checks": checks, "counts": counts,
                "manual_review_reasons": sorted(set(manual)), "overall_scientific_status": overall,
                "protocol_fixture": research.get("protocol_fixture") is True}
    return SimpleNamespace(evaluate_numeric_evidence=evaluate_numeric_evidence, NumericEnvironmentError=NumericEnvironmentError, NumericPacketError=NumericPacketError)

if __name__ == "__main__":
    raise SystemExit(main())
