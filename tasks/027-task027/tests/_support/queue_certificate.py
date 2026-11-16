"""Pure Case07 queue-certificate audit shared by the host and evaluator.

This module has no filesystem, scheduler, subprocess, or candidate-report
dependencies. Callers must supply the evaluator/host-pinned identities and the
complete trusted execution-event ledger they independently collected.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import json
import re
from typing import Any, Mapping, Sequence

SCHEMA = "case07-queue-certificate/v2"
LEDGER_SCHEMA = "case07-host-execution-ledger/v1"
SACCT_COLUMNS = ("JobIDRaw", "State", "ExitCode", "Submit", "Start", "End",
                 "ElapsedRaw", "AllocCPUS", "CPUTimeRAW")
MAX_CERT_BYTES = 8 * 1024 * 1024
MAX_GAP_SECONDS = 20
_HEX = re.compile(r"^[0-9a-f]{64}$")
_JOB = re.compile(r"^[0-9]+(?:_[0-9]+)?$")
_ATTEMPT = re.compile(r"^[0-9a-f]{32}$")


@dataclass(frozen=True)
class QueueAudit:
    status: str
    reason: str
    credited_intervals: tuple[tuple[str, str], ...] = ()

    @property
    def credited_seconds(self) -> int:
        total = 0
        for left, right in self.credited_intervals:
            total += int((_utc(right) - _utc(left)).total_seconds())
        return total


class QueueCertificateError(ValueError):
    """A malformed or incorrectly bound trusted queue certificate."""


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False).encode("utf-8")


def canonical_sha256(value: Any) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _valid_hash(value: Any) -> bool:
    return isinstance(value, str) and _HEX.fullmatch(value) is not None


def _utc(value: Any) -> datetime:
    if not isinstance(value, str):
        raise QueueCertificateError("queue timestamp is not text")
    candidate = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError as exc:
        raise QueueCertificateError("queue timestamp is malformed") from exc
    if parsed.tzinfo is None or parsed.utcoffset() != timedelta(0):
        raise QueueCertificateError("queue timestamp must carry a UTC offset")
    return parsed.astimezone(timezone.utc)


def _fmt(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _parse_sacct(raw: Any, expected_job: str) -> dict[str, str]:
    if not isinstance(raw, str) or not raw or len(raw.encode("utf-8")) > 32_768:
        raise QueueCertificateError("raw queue sacct row is absent or oversized")
    lines = [line for line in raw.splitlines() if line.strip()]
    if lines and tuple(lines[0].split("|")) == SACCT_COLUMNS:
        lines = lines[1:]
    matches = []
    for line in lines:
        cells = line.split("|")
        if len(cells) != len(SACCT_COLUMNS):
            raise QueueCertificateError("raw queue sacct row has an unexpected field count")
        row = dict(zip(SACCT_COLUMNS, cells))
        if row["JobIDRaw"] == expected_job:
            matches.append(row)
    if len(matches) != 1:
        raise QueueCertificateError("raw queue sacct must identify exactly one root allocation")
    row = matches[0]
    for field in ("Submit", "Start"):
        dt = _utc(row[field])
        if _fmt(dt) != row[field]:
            raise QueueCertificateError(f"raw queue sacct {field} must be canonical UTC")
    if row["End"] not in {"", "Unknown", "N/A"}:
        _utc(row["End"])
    try:
        elapsed, cpus, cpu = int(row["ElapsedRaw"]), int(row["AllocCPUS"]), int(row["CPUTimeRAW"])
    except (ValueError, TypeError) as exc:
        raise QueueCertificateError("raw queue sacct CPU counters are not integers") from exc
    if elapsed < 0 or cpus != 8 or cpu != elapsed * cpus:
        raise QueueCertificateError("raw queue sacct root allocation CPU accounting is inconsistent")
    if row["State"].split()[0].rstrip("+") != "RUNNING" or row["End"] not in {"", "Unknown", "N/A"}:
        raise QueueCertificateError("queue sacct evidence is not a live RUNNING root allocation")
    return row


def _parse_scontrol(raw: Any, *, attempt_id: str, job_id: str,
                    workdir: str) -> tuple[str, int, str]:
    if not isinstance(raw, str) or len(raw.encode("utf-8")) > 64 * 1024:
        raise QueueCertificateError("raw scontrol snapshot is absent or oversized")
    wanted = ("JobId", "JobName", "Comment", "WorkDir", "JobState", "StartTime", "Restarts")
    fields: dict[str, str] = {}
    for key in wanted:
        hits = re.findall(r"(?:^|\s)" + re.escape(key) + r"=([^\s]+)", raw)
        if len(hits) != 1:
            raise QueueCertificateError(f"scontrol snapshot needs exactly one {key}")
        fields[key] = hits[0]
    if (fields["JobId"] != job_id or fields["JobName"] != "c07ref-" + attempt_id[:12]
            or fields["Comment"] != "case07:" + attempt_id or fields["WorkDir"] != workdir
            or fields["JobState"] not in {"PENDING", "RUNNING"}
            or not fields["Restarts"].isdigit()):
        raise QueueCertificateError("scontrol snapshot ownership/state differs from this attempt")
    return fields["JobState"], int(fields["Restarts"]), fields["StartTime"]


def _event_key(event: Mapping[str, Any]) -> tuple[datetime, datetime, str]:
    start = _utc(event.get("started_at_utc"))
    end = _utc(event.get("ended_at_utc"))
    if end < start or not isinstance(event.get("event_id"), str) or not event["event_id"]:
        raise QueueCertificateError("trusted event ledger has an invalid event interval or identity")
    return start, end, event["event_id"]


def audit_queue_certificate(
    certificate: Any, *, attempt_id: str, job_id: str, request_sha256: str,
    source_manifest_sha256: str, producer_source_sha256: str, workdir: str,
    attempt_started_at_utc: str, report_submitted_at_utc: str,
    trusted_execution_events: Sequence[Mapping[str, Any]],
    allocated_intervals: Sequence[tuple[str, str, str]] = (),
) -> QueueAudit:
    """Authenticate only observed pending-to-pending intervals before Slurm Start.

    `trusted_execution_events` must come from runner control, not report JSON.
    Missing certificates and incomplete observation coverage return
    REVIEW_REQUIRED with zero credit. Malformed present certificates return
    ENV_INVALID. Intervals that are unobserved or separated by a large gap
    receive no credit.
    """
    if certificate is None:
        return QueueAudit("REVIEW_REQUIRED", "queue certificate is absent; no queue time excluded")
    try:
        if not isinstance(certificate, Mapping):
            raise QueueCertificateError("queue certificate is not an object")
        expected_keys = {"schema", "attempt_id", "job_id", "request_sha256", "source_manifest_sha256",
                         "interval", "sacct", "scontrol_history", "host_execution_ledger",
                         "host_execution_ledger_sha256", "producer_source_sha256", "certificate_sha256"}
        if set(certificate) != expected_keys or certificate.get("schema") != SCHEMA:
            raise QueueCertificateError("queue certificate schema/fields differ from v2")
        for value in (attempt_id,):
            if not isinstance(value, str) or not _ATTEMPT.fullmatch(value):
                raise QueueCertificateError("expected attempt identity is malformed")
        if not isinstance(job_id, str) or not _JOB.fullmatch(job_id):
            raise QueueCertificateError("expected allocation identity is malformed")
        for value in (request_sha256, source_manifest_sha256, producer_source_sha256):
            if not _valid_hash(value):
                raise QueueCertificateError("expected source binding digest is malformed")
        # Eight hours of 15-second raw scontrol polling can approach this
        # bound. Oversized history is incomplete evidence, not a source to
        # truncate or silently summarize.
        raw_size = sum(len(entry.get("raw_text", "").encode("utf-8"))
                       for entry in certificate.get("scontrol_history", [])
                       if isinstance(entry, Mapping) and isinstance(entry.get("raw_text", ""), str))
        if raw_size > MAX_CERT_BYTES:
            return QueueAudit("REVIEW_REQUIRED", "raw scheduler history exceeds 8 MiB; no queue time excluded")
        unsigned = {key: value for key, value in certificate.items() if key != "certificate_sha256"}
        if certificate["certificate_sha256"] != canonical_sha256(unsigned):
            raise QueueCertificateError("queue certificate canonical digest mismatch")
        if len(canonical_bytes(certificate)) > MAX_CERT_BYTES:
            return QueueAudit("REVIEW_REQUIRED", "queue certificate exceeds 8 MiB; no queue time excluded")
        for key, expected in (("attempt_id", attempt_id), ("job_id", job_id),
                              ("request_sha256", request_sha256),
                              ("source_manifest_sha256", source_manifest_sha256),
                              ("producer_source_sha256", producer_source_sha256)):
            if certificate.get(key) != expected:
                raise QueueCertificateError(f"queue certificate {key} is not source-bound")

        interval = certificate.get("interval")
        if not isinstance(interval, Mapping) or set(interval) != {"submit_utc", "start_utc"}:
            raise QueueCertificateError("queue certificate interval is malformed")
        submit, start = _utc(interval["submit_utc"]), _utc(interval["start_utc"])
        if start < submit:
            raise QueueCertificateError("queue Start predates Submit")
        attempt_start, report_end = _utc(attempt_started_at_utc), _utc(report_submitted_at_utc)
        if report_end < attempt_start or submit < attempt_start or start > report_end:
            raise QueueCertificateError("queue interval is outside the active attempt window")

        sacct = certificate.get("sacct")
        if not isinstance(sacct, Mapping) or set(sacct) != {"raw_text", "raw_sha256"}:
            raise QueueCertificateError("queue certificate raw sacct object is malformed")
        raw_sacct = sacct["raw_text"]
        if not isinstance(raw_sacct, str) or not _valid_hash(sacct["raw_sha256"]):
            raise QueueCertificateError("raw queue sacct digest is missing")
        if _sha(raw_sacct.encode("utf-8")) != sacct["raw_sha256"]:
            raise QueueCertificateError("raw queue sacct digest mismatch")
        row = _parse_sacct(raw_sacct, job_id)
        if row["Submit"] != interval["submit_utc"] or row["Start"] != interval["start_utc"]:
            raise QueueCertificateError("queue interval differs from raw UTC sacct Submit/Start")

        history = certificate.get("scontrol_history")
        if not isinstance(history, list) or not history:
            raise QueueCertificateError("scontrol history is absent or malformed")
        observed: list[tuple[datetime, str, int, str]] = []
        previous = None
        for entry in history:
            if (not isinstance(entry, Mapping)
                    or set(entry) != {"observed_at_utc", "raw_text", "raw_sha256"}
                    or not isinstance(entry.get("raw_text"), str)
                    or not _valid_hash(entry.get("raw_sha256"))
                    or _sha(entry["raw_text"].encode("utf-8")) != entry["raw_sha256"]):
                raise QueueCertificateError("scontrol observation bytes/hash are malformed")
            observed_at = _utc(entry["observed_at_utc"])
            if previous is not None and observed_at <= previous:
                raise QueueCertificateError("scontrol observation timestamps are not strictly increasing")
            if observed_at < submit:
                raise QueueCertificateError("scontrol observation predates raw sacct Submit")
            state, restarts, start_time = _parse_scontrol(entry["raw_text"], attempt_id=attempt_id,
                                                          job_id=job_id, workdir=workdir)
            if restarts != 0:
                return QueueAudit("REVIEW_REQUIRED", "Slurm restart observed; no queue time excluded")
            if state == "PENDING" and observed_at >= start:
                raise QueueCertificateError("PENDING snapshot is inconsistent with actual scheduler Start")
            if state == "RUNNING":
                if observed_at < start:
                    raise QueueCertificateError("RUNNING was observed before raw sacct Start")
                if (observed_at - start).total_seconds() > MAX_GAP_SECONDS:
                    return QueueAudit("REVIEW_REQUIRED", "RUNNING transition was observed after the bounded window; no queue time excluded")
                if start_time in {"Unknown", "N/A"}:
                    raise QueueCertificateError("RUNNING snapshot lacks scheduler StartTime")
                try:
                    actual_start = datetime.fromisoformat(start_time.replace("Z", "+00:00"))
                except ValueError as exc:
                    raise QueueCertificateError("scontrol StartTime is malformed") from exc
                if actual_start.tzinfo is None:
                    # The trusted scontrol command is executed with TZ=UTC.
                    actual_start = actual_start.replace(tzinfo=timezone.utc)
                elif actual_start.utcoffset() != timedelta(0):
                    raise QueueCertificateError("scontrol StartTime is not from the UTC query")
                actual_start = actual_start.astimezone(timezone.utc)
                if abs((actual_start - start).total_seconds()) > 1:
                    raise QueueCertificateError("scontrol StartTime differs from raw sacct Start")
            observed.append((observed_at, state, restarts, start_time))
            previous = observed_at
        if observed[-1][1] != "RUNNING" or any(state == "RUNNING" for _, state, _, _ in observed[:-1]):
            raise QueueCertificateError("scontrol history does not show one final RUNNING transition")
        pending_samples = [item[0] for item in observed if item[1] == "PENDING"]

        ledger = certificate.get("host_execution_ledger")
        ledger_keys = {"schema", "attempt_id", "job_id", "scope_end_utc",
                       "execution_events_sha256", "events"}
        if not isinstance(ledger, Mapping) or set(ledger) != ledger_keys:
            raise QueueCertificateError("host execution ledger v2 scope is malformed")
        if (ledger.get("schema") != LEDGER_SCHEMA or ledger.get("attempt_id") != attempt_id
                or ledger.get("job_id") != job_id or ledger.get("scope_end_utc") != interval["start_utc"]):
            raise QueueCertificateError("host event prefix does not end at actual Slurm Start")
        events = ledger.get("events")
        if not isinstance(events, list) or not all(isinstance(event, Mapping) for event in events):
            raise QueueCertificateError("host execution ledger events are malformed")
        if not _valid_hash(ledger.get("execution_events_sha256")) or not _valid_hash(
                certificate.get("host_execution_ledger_sha256")):
            raise QueueCertificateError("host execution ledger digest is malformed")
        if ledger["execution_events_sha256"] != canonical_sha256(events):
            raise QueueCertificateError("host execution event-prefix digest mismatch")
        if certificate["host_execution_ledger_sha256"] != canonical_sha256(ledger):
            raise QueueCertificateError("host execution ledger digest mismatch")
        full = list(trusted_execution_events)
        if not all(isinstance(event, Mapping) for event in full):
            raise QueueCertificateError("trusted execution events are not an array of objects")
        for event in full:
            _event_key(event)
        # The source-bound prefix includes every event begun by actual Start,
        # including an event that straddles the boundary. Such an event cannot
        # disappear merely because it completed later.
        prefix = [event for event in full if _event_key(event)[0] < start]
        if list(events) != prefix:
            raise QueueCertificateError("queue ledger is not the complete trusted event prefix through Start")

        # Only fully observed PENDING-to-PENDING segments earn credit. Edges
        # from Submit to the first sample and from the last PENDING sample to
        # RUNNING are deliberately uncredited.
        credited = []
        if len(pending_samples) < 2:
            return QueueAudit("REVIEW_REQUIRED", "fewer than two observed PENDING samples; no queue time excluded")
        for left, right in zip(pending_samples, pending_samples[1:]):
            gap = (right - left).total_seconds()
            if gap <= 0:
                raise QueueCertificateError("PENDING sample interval is not positive")
            if gap > MAX_GAP_SECONDS:
                continue
            if left < attempt_start or right > report_end or right > start:
                raise QueueCertificateError("credited PENDING interval is outside the attempt")
            if any(left < _utc(alloc_end) and right > _utc(alloc_start)
                   for alloc_start, alloc_end, _ in allocated_intervals):
                raise QueueCertificateError("observed queue interval overlaps an allocation")
            if any(_event_key(event)[0] < right and _event_key(event)[1] > left
                   for event in full):
                return QueueAudit("REVIEW_REQUIRED", "trusted execution overlapped observed queue interval; zero queue credit")
            credited.append((_fmt(left), _fmt(right)))
        if not credited:
            return QueueAudit("REVIEW_REQUIRED", "no adjacent PENDING observations meet the bounded-gap rule; zero queue credit")
        return QueueAudit("PASS", "source-bound raw scheduler and host-event evidence supports adjacent PENDING intervals",
                          tuple(credited))
    except (QueueCertificateError, TypeError, KeyError, ValueError, OverflowError) as exc:
        return QueueAudit("ENV_INVALID", str(exc))
