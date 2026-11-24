#!/usr/bin/env python3
"""Submit maintainer-owned CPU/GPU jobs to the IKKEM SLURM entrances.

Minimal interface: submit / status / wait / logs / cancel / collect / list / probe.
All commands except `logs` and `probe` print a single JSON object to stdout.
Job state is stored per job in .submit-job/<name>.json under the cwd;
run status/logs/cancel/collect from the same directory used at submit time.
Targets (clusters / nodes) are defined in submit-job.json (project root)
or ~/.config/submit-job/config.json.
New submissions are SLURM-only.  Historical state files from the retired
direct-SSH mode can still be inspected or collected, but cannot be used to
create new work.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import re
import shlex
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from pathlib import PurePosixPath

STATE_DIR = Path(".submit-job")
STATE_VERSION = "0.6.0"
SACCT_RECEIPT_SCHEMA = "ikkem-slurm-sacct-receipt/v1"
RESOURCE_EVIDENCE_SCHEMA = "ikkem-slurm-resource-evidence/v1"
DEFAULT_SNAPSHOT_MAX_AGE = 900
MAX_REASON_BYTES = 64 * 1024
HEX64_RE = re.compile(r"^[0-9a-fA-F]{64}$")
LIMIT_FIELDS = (
    "max_nodes", "max_ntasks", "max_ntasks_per_node", "max_cpus_per_task",
    "max_total_cpus", "max_memory_per_node", "max_total_memory",
    "max_walltime", "max_gpus_per_node", "max_total_gpus",
)
CONFIG_PATHS = [
    Path("submit-job.json"),
    Path.home() / ".config" / "submit-job" / "config.json",
]
NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
HOST_RE = re.compile(r"^(?!-)(?:[A-Za-z0-9_.-]+@)?[A-Za-z0-9_.:-]+$")
SLURM_VALUE_RE = re.compile(r"^[A-Za-z0-9._:@,+&|*=-]+$")
GPU_GRES_RE = re.compile(r"^gpu(?::[A-Za-z0-9][A-Za-z0-9._-]*)?:[1-9][0-9]*$")
SSH_OPTS = ["-o", "BatchMode=yes", "-o", "ConnectTimeout=10"]
SSH_TIMEOUT = 30
DEFAULT_TRANSFER_TIMEOUT = 300
MIN_TRANSFER_TIMEOUT = 1
MAX_TRANSFER_TIMEOUT = 3600


def ok(**fields):
    print(json.dumps({"status": "ok", **fields}, ensure_ascii=False))


def fail(message, **fields):
    print(json.dumps({"status": "failed", "error": message, **fields},
                     ensure_ascii=False))
    raise SystemExit(1)


def q(value):
    return shlex.quote(str(value))


def canonical_json(value):
    """Return the v0.5 canonical JSON representation used for bindings."""
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"))


def sha256_text(value):
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def sha256_canonical(value):
    return sha256_text(canonical_json(value))


# Descriptive alias used by callers that persist probe snapshots.
canonical_snapshot_sha256 = sha256_canonical


def captured_at():
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def parse_memory(value):
    """Parse Slurm-like memory into bytes; reject ambiguous or unitless values."""
    if not isinstance(value, str):
        fail("memory must be a string with an explicit unit (K/M/G/T)")
    match = re.fullmatch(r"([1-9][0-9]*)([KMGTPkmgpt])(?:i?[Bb])?", value.strip())
    if not match:
        fail("memory must be a positive integer with unit K/M/G/T")
    scale = {"k": 1024, "m": 1024**2, "g": 1024**3,
             "t": 1024**4, "p": 1024**5}[match.group(2).lower()]
    return int(match.group(1)) * scale


def parse_walltime(value):
    if isinstance(value, bool):
        fail("time must be HH:MM:SS (optionally D-HH:MM:SS)")
    if isinstance(value, int) and value > 0:
        return value
    if not isinstance(value, str):
        fail("time must be HH:MM:SS (optionally D-HH:MM:SS)")
    text = value.strip()
    day = 0
    if "-" in text:
        d, text = text.split("-", 1)
        if not d.isdigit():
            fail("time has invalid day component")
        day = int(d)
    pieces = text.split(":")
    if len(pieces) != 3 or not all(p.isdigit() for p in pieces):
        fail("time must be HH:MM:SS (optionally D-HH:MM:SS)")
    hour, minute, second = map(int, pieces)
    if minute >= 60 or second >= 60 or hour < 0:
        fail("time has invalid minute/second")
    result = day * 86400 + hour * 3600 + minute * 60 + second
    if result <= 0:
        fail("time must be positive")
    return result


def parse_gpu_count(gpus=None, gres=None):
    if gpus is not None:
        if not isinstance(gpus, int) or gpus < 1:
            fail("gpus must be a positive integer")
        return gpus
    if gres:
        match = GPU_GRES_RE.fullmatch(gres)
        if not match:
            fail("gres must be gpu:N or gpu:type:N with a positive count")
        return int(gres.rsplit(":", 1)[1])
    return 0


def read_reason(args):
    supplied = [getattr(args, "reason", None) is not None,
                getattr(args, "reason_file", None) is not None]
    if sum(supplied) != 1:
        fail("exactly one of --reason or --reason-file is required")
    if supplied[0]:
        reason = args.reason
        if not isinstance(reason, str):
            fail("reason must be UTF-8 text")
        encoded = reason.encode("utf-8")
    else:
        path = Path(args.reason_file)
        try:
            encoded = path.read_bytes()
            reason = encoded.decode("utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            fail(f"cannot read UTF-8 reason-file: {exc}")
    if len(encoded) > MAX_REASON_BYTES:
        fail(f"reason is limited to {MAX_REASON_BYTES} bytes")
    if not reason.strip():
        fail("reason must be non-empty")
    return reason, hashlib.sha256(encoded).hexdigest()


def load_probe_snapshot(path, host, partition, expected_hash=None,
                        max_age_seconds=DEFAULT_SNAPSHOT_MAX_AGE):
    try:
        snapshot = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        fail(f"cannot read probe snapshot: {exc}")
    if not isinstance(snapshot, dict):
        fail("probe snapshot must be a JSON object")
    # The digest is over the snapshot object itself; the self-describing
    # snapshot_sha256 member is excluded to avoid a self-referential hash.
    unsigned = dict(snapshot)
    embedded = unsigned.pop("snapshot_sha256", None)
    digest = sha256_canonical(unsigned)
    if not isinstance(embedded, str) or not HEX64_RE.fullmatch(embedded) or embedded.lower() != digest:
        fail("probe snapshot has an invalid embedded snapshot_sha256")
    if snapshot.get("schema_version") not in {"0.5.6", "0.5.7", "0.5.8", STATE_VERSION}:
        fail("probe snapshot has an unsupported schema_version")
    if not isinstance(snapshot.get("captured_at"), str) or not snapshot["captured_at"].strip():
        fail("probe snapshot requires captured_at")
    validate_snapshot_max_age(max_age_seconds)
    try:
        timestamp = datetime.fromisoformat(snapshot["captured_at"].replace("Z", "+00:00"))
        if timestamp.tzinfo is None:
            raise ValueError("timestamp must include a timezone")
        age = (datetime.now(timezone.utc) - timestamp).total_seconds()
    except (ValueError, OverflowError) as exc:
        fail(f"invalid probe captured_at: {exc}")
    if age < -30 or age > max_age_seconds:
        fail("probe snapshot is stale or future-dated; run probe again")
    partitions = snapshot.get("partitions")
    nodes = snapshot.get("nodes")
    queue = snapshot.get("queue")
    if not isinstance(partitions, list) or not isinstance(nodes, list) or not isinstance(queue, list):
        fail("probe snapshot partitions, nodes, and queue must be lists")
    if any(not isinstance(item, dict) or not isinstance(item.get("name"), str)
           or not item["name"].strip() for item in partitions):
        fail("probe snapshot contains an invalid partition entry")
    if any(not isinstance(item, dict) or not isinstance(item.get("partition"), str)
           or not isinstance(item.get("name"), str) for item in nodes):
        fail("probe snapshot contains an invalid node entry")
    if any(not isinstance(item, dict) for item in queue):
        fail("probe snapshot contains an invalid queue entry")
    if expected_hash and expected_hash.lower() != digest:
        fail("snapshot_sha256 does not match --probe-snapshot")
    if snapshot.get("host") != host:
        fail("probe snapshot host does not match the selected target host")
    requested = snapshot.get("request_partition")
    if partition and requested != partition:
        fail("probe snapshot partition does not match the selected partition")
    if not isinstance(requested, str) or not requested.strip():
        fail("probe snapshot requires request_partition")
    if requested not in {item["name"] for item in partitions}:
        fail("probe snapshot does not include the requested partition")
    if not any(item["partition"] == requested for item in nodes):
        fail("probe snapshot has no nodes for the requested partition")
    return snapshot, digest


def require_snapshot_hash(args, cfg):
    expected = getattr(args, "snapshot_sha256", None)
    if not expected or not HEX64_RE.fullmatch(expected):
        fail("--snapshot-sha256 must be a 64-character hexadecimal digest")
    snapshot_path = getattr(args, "probe_snapshot", None)
    if not snapshot_path:
        fail("--probe-snapshot is required for every new submission")
    _, digest = load_probe_snapshot(snapshot_path, cfg["host"],
                                    cfg.get("partition"), expected,
                                    cfg.get("snapshot_max_age_seconds", DEFAULT_SNAPSHOT_MAX_AGE))
    return digest


def qr(path):
    """Quote a validated remote path, expanding only the leading ``~/``."""
    p = validate_remote_path(path)
    if p.startswith("~/"):
        return '"$HOME/' + p[2:] + '"'
    return q(p)


def validate_host(host):
    if not isinstance(host, str) or not HOST_RE.fullmatch(host):
        fail("host must be a single SSH alias/user@host, not an option or command")


def validate_remote_path(path):
    """Allow only absolute POSIX paths or ``~/...`` without variables/traversal."""
    if not isinstance(path, str) or not path or "\\" in path or "$" in path:
        fail("remote path must be absolute or start with ~/ and contain no variables")
    if any(ch.isspace() for ch in path) or ".." in PurePosixPath(path).parts:
        fail("remote path must not contain whitespace or '..'")
    if not (path.startswith("/") or path.startswith("~/")):
        fail("remote path must be absolute or start with ~/")
    if not re.fullmatch(r"(?:/[A-Za-z0-9._/@:+,-]*|~/[A-Za-z0-9._/@:+,-]+)", path):
        fail("remote path contains unsupported shell characters")
    return path


def ssh(host, remote_cmd, check=True, timeout=SSH_TIMEOUT, binary=False):
    validate_host(host)
    try:
        result = subprocess.run(
            ["ssh", *SSH_OPTS, host, remote_cmd],
            capture_output=True, text=not binary, timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        result = subprocess.CompletedProcess(
            ["ssh", *SSH_OPTS, host, remote_cmd], 124,
            b"" if binary else "", b"ssh timeout" if binary else "ssh timeout"
        )
    if check and result.returncode != 0:
        diagnostic = result.stderr.strip() or result.stdout.strip()
        if isinstance(diagnostic, bytes):
            diagnostic = diagnostic.decode("utf-8", errors="replace")
        fail(f"ssh {host} failed: {diagnostic}")
    return result


def validate_transfer_timeout(value):
    if isinstance(value, bool) or not isinstance(value, int):
        fail("transfer_timeout must be an integer from 1 to 3600 seconds")
    if not MIN_TRANSFER_TIMEOUT <= value <= MAX_TRANSFER_TIMEOUT:
        fail("transfer_timeout must be an integer from 1 to 3600 seconds")
    return value


def validate_snapshot_max_age(value):
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 86400:
        fail("snapshot_max_age_seconds must be an integer from 1 to 86400")
    return value


def rsync_up(host, src, workdir, timeout, excludes=()):
    validate_host(host)
    validate_remote_path(workdir)
    cmd = ["rsync", "-az"]
    for pattern in excludes:
        cmd += ["--exclude", pattern]
    cmd += ["--", src.rstrip("/") + "/", f"{host}:{workdir}/"]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True,
                                timeout=timeout)
    except subprocess.TimeoutExpired:
        raise TimeoutError(f"rsync to {host}:{workdir} timed out after {timeout}s")
    if result.returncode != 0:
        fail(f"rsync to {host}:{workdir} failed: {result.stderr.strip()}")


def load_config():
    for path in CONFIG_PATHS:
        if path.is_file():
            try:
                config = json.loads(path.read_text(encoding="utf-8"))
            except json.JSONDecodeError as exc:
                fail(f"invalid JSON in {path}: {exc}")
            return config, path
    return {}, None


def resolve_target(args):
    cfg = {}
    config, path = load_config()
    target = args.target
    profile = getattr(args, "profile", None)
    if args.target and profile:
        fail("use either --target or --profile, not both")
    if args.target or profile:
        if getattr(args, "backend", None) is not None or getattr(args, "host", None) is not None:
            fail("backend and host are fixed by the configured target")
    if profile:
        routes = config.get("profiles", {})
        target = routes.get(profile)
        if not target:
            fail(f"profile '{profile}' must map to a configured target")
        targets = config.get("targets", {})
        if target not in targets:
            known = ", ".join(sorted(targets)) or "(none configured)"
            fail(f"unknown target '{target}' (known: {known}; "
                 f"config: {path or 'no submit-job.json found'})")
        cfg = dict(targets[target])
    elif target:
        targets = config.get("targets", {})
        if target not in targets:
            known = ", ".join(sorted(targets)) or "(none configured)"
            fail(f"unknown target '{target}' (known: {known}; "
                 f"config: {path or 'no submit-job.json found'})")
        cfg = dict(targets[target])
    if not profile and not target:
        fail("new submissions require a configured --target or --profile route")
    configured_partition = cfg.get("partition")
    if cfg.get("resource_class") == "cpu" and cfg.get("allowed_partitions") is None:
        if configured_partition:
            cfg["allowed_partitions"] = [configured_partition]
    for key in ("backend", "host", "base_dir", "time", "partition",
                "nodes", "ntasks", "ntasks_per_node", "cpus", "mem",
                "gpus", "gres", "account", "qos", "constraint"):
        value = getattr(args, key, None)
        if value is not None:
            cfg[key] = value
    if not cfg.get("backend") or not cfg.get("host"):
        fail("configured target must declare backend and host")
    if cfg.get("backend") != "slurm":
        fail("new submissions require the slurm backend; direct SSH is retired")
    resource_class = cfg.get("resource_class")
    if resource_class not in {"cpu", "gpu"}:
        fail("configured targets must declare resource_class as 'cpu' or 'gpu'")
    if profile and resource_class != profile:
        fail(f"profile '{profile}' resolves to resource_class '{resource_class}'")
    cfg["transfer_timeout"] = validate_transfer_timeout(
        cfg.get("transfer_timeout", DEFAULT_TRANSFER_TIMEOUT))
    cfg["snapshot_max_age_seconds"] = validate_snapshot_max_age(
        cfg.get("snapshot_max_age_seconds", DEFAULT_SNAPSHOT_MAX_AGE))
    # The route is fixed by configuration; normal resource sizing remains a
    # caller choice.
    validate_host(str(cfg["host"]))
    cfg["target"] = target
    cfg["profile"] = profile
    validate_resources(cfg)
    return cfg


def validate_resources(cfg):
    resource_class = cfg.get("resource_class", "cpu")
    if resource_class not in {"cpu", "gpu"}:
        fail("resource_class must be 'cpu' or 'gpu'")
    if cfg.get("profile") and cfg["profile"] != resource_class:
        fail("profile and resource_class must select the same resource class")
    for key in ("nodes", "ntasks", "ntasks_per_node", "cpus", "gpus"):
        value = cfg.get(key)
        if value is not None and (isinstance(value, bool) or
                                  not isinstance(value, int) or value < 1):
            fail(f"resource '{key}' must be a positive integer")
    for key in ("time", "partition", "mem", "gres", "account", "qos", "constraint"):
        value = cfg.get(key)
        if value is not None and (not isinstance(value, str) or
                                  not SLURM_VALUE_RE.fullmatch(value)):
            fail(f"resource '{key}' contains unsupported characters")
    if cfg.get("gres") is not None and not GPU_GRES_RE.fullmatch(cfg["gres"]):
        fail("gres must be gpu:N or gpu:type:N with a positive count")
    allow_typed = cfg.get("allow_typed_gres", True)
    if not isinstance(allow_typed, bool):
        fail("allow_typed_gres must be a JSON boolean")
    if not allow_typed and cfg.get("gres") and cfg["gres"].count(":") == 2:
        fail("this target does not allow typed GRES; use --gpus N or --gres gpu:N")
    if cfg.get("gpus") is not None and cfg.get("gres") is not None:
        fail("--gpus and --gres are mutually exclusive")
    if resource_class == "cpu" and (cfg.get("gpus") is not None or cfg.get("gres") is not None):
        fail("CPU targets cannot request --gpus or --gres")
    if resource_class == "gpu":
        allowed = cfg.get("allowed_partitions")
        if not isinstance(allowed, list) or not allowed or any(
                not isinstance(p, str) or not SLURM_VALUE_RE.fullmatch(p) for p in allowed):
            fail("allowed_partitions must be a non-empty list of safe partition names")
        partition = cfg.get("partition")
        if partition is not None and partition not in allowed:
            fail(f"partition '{partition}' is not allowed for this GPU target")
        if cfg.get("gpus") is None and cfg.get("gres") is None:
            fail("GPU targets require explicit --gpus N or --gres gpu[:type]:N")
    else:
        allowed = cfg.get("allowed_partitions")
        if allowed is None:
            default_partition = cfg.get("partition")
            allowed = [default_partition] if default_partition else []
        if not isinstance(allowed, list) or not allowed or any(
                not isinstance(p, str) or not SLURM_VALUE_RE.fullmatch(p) for p in allowed):
            fail("CPU targets require a default partition or allowed_partitions")
        partition = cfg.get("partition")
        if partition is not None and partition not in allowed:
            fail(f"partition '{partition}' is not allowed for this CPU target")


def normalize_resources(cfg):
    """Validate request shape and return deterministic accounting values."""
    for key in ("nodes", "ntasks", "ntasks_per_node", "cpus"):
        value = cfg.get(key)
        if value is not None and (isinstance(value, bool) or
                                  not isinstance(value, int) or value < 1):
            fail(f"resource '{key}' must be a positive integer")
    required = ("nodes", "cpus", "mem", "time")
    for key in required:
        if cfg.get(key) is None:
            fail(f"resource '{key}' must be explicitly requested or target-defaulted")
    if cfg.get("ntasks") is None and cfg.get("ntasks_per_node") is None:
        fail("one of ntasks or ntasks_per_node must be explicitly requested or target-defaulted")
    nodes = cfg["nodes"]
    cpus = cfg["cpus"]
    ntasks = cfg.get("ntasks")
    per_node = cfg.get("ntasks_per_node")
    if ntasks is None:
        ntasks = nodes * per_node
    if per_node is not None and ntasks != nodes * per_node:
        fail("ntasks and nodes*ntasks_per_node are inconsistent")
    mem_bytes = parse_memory(cfg["mem"])
    time_seconds = parse_walltime(cfg["time"])
    gpu_count = parse_gpu_count(cfg.get("gpus"), cfg.get("gres"))
    if cfg.get("resource_class") == "gpu" and gpu_count < 1:
        fail("GPU targets require an explicit positive GPU request")
    if cfg.get("resource_class") == "cpu" and gpu_count:
        fail("CPU targets cannot request GPUs")
    return {
        "nodes": nodes, "ntasks": ntasks,
        "ntasks_per_node": (per_node if per_node is not None else
                             (ntasks + nodes - 1) // nodes),
        "cpus": cpus, "mem": cfg["mem"], "mem_bytes": mem_bytes,
        "time": cfg["time"], "time_seconds": time_seconds,
        "gpus_per_node": gpu_count, "total_cpu": ntasks * cpus,
        "total_memory": nodes * mem_bytes, "total_gpus": nodes * gpu_count,
    }


def _limit_number(value, field):
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        fail(f"partition limit {field} must be a non-negative integer")
    return value


def validate_partition_limits(cfg, normalized):
    limits = cfg.get("partition_limits")
    partition = cfg.get("partition")
    if not isinstance(limits, dict) or not partition or partition not in limits:
        fail(f"no complete operator partition_limits policy for partition '{partition}'")
    policy = limits[partition]
    if not isinstance(policy, dict) or policy.get("enabled") is not True:
        fail(f"operator partition policy for '{partition}' is disabled or invalid")
    missing = [field for field in LIMIT_FIELDS if field not in policy]
    if missing:
        fail(f"partition policy for '{partition}' is missing: {', '.join(missing)}")
    parsed = {}
    for field in ("max_nodes", "max_ntasks", "max_ntasks_per_node",
                  "max_cpus_per_task", "max_total_cpus", "max_gpus_per_node",
                  "max_total_gpus"):
        parsed[field] = _limit_number(policy[field], field)
    if cfg.get("resource_class") == "cpu" and (
            parsed["max_gpus_per_node"] != 0 or parsed["max_total_gpus"] != 0):
        fail("CPU partition policy must cap GPUs at zero")
    try:
        parsed["max_memory_per_node"] = parse_memory(policy["max_memory_per_node"])
        parsed["max_total_memory"] = parse_memory(policy["max_total_memory"])
        parsed["max_walltime"] = parse_walltime(policy["max_walltime"])
    except SystemExit:
        raise
    checks = {
        "max_nodes": normalized["nodes"],
        "max_ntasks": normalized["ntasks"],
        "max_ntasks_per_node": normalized["ntasks_per_node"],
        "max_cpus_per_task": normalized["cpus"],
        "max_total_cpus": normalized["total_cpu"],
        "max_memory_per_node": normalized["mem_bytes"],
        "max_total_memory": normalized["total_memory"],
        "max_walltime": normalized["time_seconds"],
        "max_gpus_per_node": normalized["gpus_per_node"],
        "max_total_gpus": normalized["total_gpus"],
    }
    for field, requested in checks.items():
        if requested > parsed[field]:
            fail(f"request exceeds operator limit {field}: {requested} > {parsed[field]}")
    return policy


def state_path(name):
    if not isinstance(name, str) or not NAME_RE.fullmatch(name):
        raise ValueError("unsafe job name")
    return STATE_DIR / f"{name}.json"


def _atomic_write_json(path, payload):
    """Write state atomically with private permissions."""
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = path.with_name(f".{path.name}.tmp-{os.getpid()}-{time.time_ns()}")
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, indent=2, ensure_ascii=False, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    except Exception:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass
        raise


def reserve_state(state):
    """Atomically reserve a local name before any remote mutation."""
    STATE_DIR.mkdir(parents=True, exist_ok=True, mode=0o700)
    path = state_path(state["name"])
    payload = dict(state)
    payload.setdefault("state_version", STATE_VERSION)
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        fail(f"job '{state['name']}' already has a local state/intent; refusing reuse")
    with os.fdopen(fd, "w", encoding="utf-8") as stream:
        json.dump(payload, stream, indent=2, ensure_ascii=False, sort_keys=True)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())


def save_state(state):
    path = state_path(state["name"])
    payload = dict(state)
    payload.setdefault("state_version", STATE_VERSION)
    _atomic_write_json(path, payload)


def update_phase(state, phase, error=None):
    """Persist a submission phase/error without losing the original intent."""
    state["phase"] = phase
    if error:
        state["error"] = error
    save_state(state)


def load_state(name):
    try:
        path = state_path(name)
    except ValueError:
        fail("unsafe job name; state paths cannot contain traversal or separators")
    try:
        stat_result = path.lstat()
    except FileNotFoundError:
        stat_result = None
    if (stat_result is None or path.is_symlink() or
            not path.is_file() or stat_result.st_nlink != 1):
        fail(f"no state for job '{name}' (expected {path}); jobs are tracked by name. "
             f"Run from the same directory used at submit time.")
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        fail(f"invalid state for job '{name}': {exc}")
    if not isinstance(state, dict):
        fail(f"invalid state for job '{name}': expected a JSON object")
    version = state.get("state_version")
    if version is not None and version not in {"0.2.1", "0.3.0", "0.4.0", "0.5.0", "0.5.1", "0.5.2", "0.5.3", "0.5.4", "0.5.5", "0.5.6", "0.5.7", "0.5.8", STATE_VERSION}:
        fail(f"unsupported state_version for job '{name}': {version}")
    if state.get("name") != name:
        fail(f"state name does not match requested job '{name}'")
    if state.get("backend") not in {"slurm", "ssh"}:
        fail(f"unsupported backend in state for job '{name}'")
    state["transfer_timeout"] = validate_transfer_timeout(
        state.get("transfer_timeout", DEFAULT_TRANSFER_TIMEOUT))
    try:
        validate_host(state.get("host"))
        validate_remote_path(state.get("workdir"))
        if state.get("log") is not None:
            validate_remote_path(state["log"])
    except SystemExit:
        raise
    if state["backend"] == "slurm" and state.get("job_id") is not None:
        if not re.fullmatch(r"[0-9]+", str(state["job_id"])):
            fail(f"invalid Slurm job_id in state for job '{name}'")
    return state


def render_sbatch(name, cmd, res):
    lines = [
        "#!/bin/bash",
        f"#SBATCH --job-name={name}",
        "#SBATCH --output=logs/%x-%j.out",
        "#SBATCH --error=logs/%x-%j.err",
    ]
    if res.get("time"):
        lines.append(f"#SBATCH --time={res['time']}")
    if res.get("partition"):
        lines.append(f"#SBATCH --partition={res['partition']}")
    if res.get("account"):
        lines.append(f"#SBATCH --account={res['account']}")
    if res.get("qos"):
        lines.append(f"#SBATCH --qos={res['qos']}")
    if res.get("constraint"):
        lines.append(f"#SBATCH --constraint={res['constraint']}")
    if res.get("nodes"):
        lines.append(f"#SBATCH --nodes={res['nodes']}")
    if res.get("ntasks"):
        lines.append(f"#SBATCH --ntasks={res['ntasks']}")
    if res.get("ntasks_per_node"):
        lines.append(f"#SBATCH --ntasks-per-node={res['ntasks_per_node']}")
    if res.get("cpus"):
        lines.append(f"#SBATCH --cpus-per-task={res['cpus']}")
    if res.get("mem"):
        lines.append(f"#SBATCH --mem={res['mem']}")
    if res.get("gres"):
        lines.append(f"#SBATCH --gres={res['gres']}")
    elif res.get("gpus"):
        lines.append(f"#SBATCH --gres=gpu:{res['gpus']}")
    lines += ["", "set -euo pipefail", 'cd "$SLURM_SUBMIT_DIR"', cmd, ""]
    return "\n".join(lines)


def build_plan(name, cmd, cfg):
    workdir = cfg.get("workdir") or f"{cfg.get('base_dir', '~/submit-jobs')}/{name}"
    plan = {"backend": cfg["backend"], "host": cfg["host"], "workdir": workdir,
            "target": cfg.get("target"), "profile": cfg.get("profile"),
            "resource_class": cfg.get("resource_class", "cpu")}
    if cfg["backend"] == "slurm":
        plan["script"] = render_sbatch(name, cmd, cfg)
    else:
        plan["remote_command"] = cmd
    return workdir, plan


def cmd_submit(args):
    if len(args.name) > 128 or not NAME_RE.fullmatch(args.name):
        fail(f"invalid job name '{args.name}' (1-128 chars: [A-Za-z0-9._-])")
    cfg = resolve_target(args)
    reason, reason_hash = read_reason(args)
    snapshot_hash = require_snapshot_hash(args, cfg)
    normalized = normalize_resources(cfg)
    validate_partition_limits(cfg, normalized)
    if getattr(args, "src", None) and not Path(args.src).is_dir():
        fail(f"source directory does not exist or is not a directory: {args.src}")
    if getattr(args, "workdir", None):
        cfg["workdir"] = args.workdir
    workdir, plan = build_plan(args.name, args.cmd, cfg)
    validate_remote_path(workdir)
    script_hash = sha256_text(plan["script"]) if cfg["backend"] == "slurm" else None
    plan_summary = {
        "name": args.name,
        "target": cfg.get("target"),
        "profile": cfg.get("profile"),
        "host": cfg["host"],
        "resource_class": cfg.get("resource_class", "cpu"),
        "transfer_timeout": cfg["transfer_timeout"],
        "snapshot_max_age_seconds": cfg["snapshot_max_age_seconds"],
        "allow_typed_gres": cfg.get("allow_typed_gres", True),
        "partition": cfg.get("partition"),
        "normalized_resources": normalized,
        "workdir": workdir,
        "command_sha256": sha256_text(args.cmd),
        "reason_sha256": reason_hash,
        "snapshot_sha256": snapshot_hash,
        "script_sha256": script_hash,
        "source": str(Path(args.src).resolve()) if getattr(args, "src", None) else None,
        "excludes": list(getattr(args, "exclude", []) or []),
    }
    plan_hash = sha256_canonical(plan_summary)
    plan["summary"] = plan_summary
    plan["plan_sha256"] = plan_hash
    if getattr(args, "src", None):
        plan["sync"] = f"{args.src} -> {cfg['host']}:{workdir}"
        if getattr(args, "exclude", None):
            plan["sync_excludes"] = args.exclude

    if getattr(args, "dry_run", False):
        ok(dry_run=True, name=args.name, plan=plan, plan_summary=plan_summary,
           reason_sha256=reason_hash, snapshot_sha256=snapshot_hash,
           script_sha256=script_hash, plan_sha256=plan_hash)
        return

    host = cfg["host"]

    state = {
        "name": args.name, "backend": cfg["backend"], "host": host,
        "workdir": workdir, "cmd": args.cmd,
        "target": cfg.get("target"), "profile": cfg.get("profile"),
        "resource_class": cfg.get("resource_class", "cpu"),
        "transfer_timeout": cfg["transfer_timeout"],
        "resources": {key: cfg[key] for key in (
            "time", "partition", "nodes", "ntasks", "ntasks_per_node",
            "cpus", "mem", "gpus", "gres", "account", "qos", "constraint"
        ) if cfg.get(key) is not None},
        "submitted_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "phase": "SUBMISSION_INTENT",
        "reason_sha256": reason_hash,
        "snapshot_sha256": snapshot_hash,
        "script_sha256": script_hash,
        "plan_summary": plan_summary,
        "plan_sha256": plan_hash,
        "plan": plan,
        "decision": {"reason": reason, "reason_sha256": reason_hash,
                      "snapshot_sha256": snapshot_hash, "plan_sha256": plan_hash},
        "normalized_resources": normalized,
    }
    if getattr(args, "src", None):
        state["source"] = str(Path(args.src).resolve())
        state["excludes"] = list(getattr(args, "exclude", []))

    # Reserve the local name before creating or modifying anything remotely.
    reserve_state(state)
    prep = ssh(host,
               f"d={qr(workdir)}; parent=$(dirname \"$d\"); mkdir -p \"$parent\"; "
               f"mkdir \"$d\" && mkdir \"$d/logs\"",
               check=False)
    if prep.returncode != 0:
        update_phase(state, "REMOTE_PREP_FAILED",
                     prep.stderr.strip() or "remote workdir exists or cannot be created")
        fail(f"cannot prepare unique remote workdir: {state['error']}",
             phase=state["phase"])
    update_phase(state, "REMOTE_PREPARED")
    if getattr(args, "src", None):
        try:
            rsync_up(host, args.src, workdir, timeout=cfg["transfer_timeout"],
                     excludes=getattr(args, "exclude", []))
        except TimeoutError as exc:
            update_phase(state, "REMOTE_SYNC_FAILED", str(exc))
            fail(str(exc), phase=state["phase"])
        except SystemExit:
            update_phase(state, "REMOTE_SYNC_FAILED")
            raise
    # The runner intentionally seals staged source directories read-only.
    # rsync -a preserves that mode at the destination, so restore only the
    # owner-write bit on this exact, validated per-job directory before writing
    # submit.sh. Staged files remain read-only and the directory is not widened
    # for group or other users.
    writable = ssh(host, f"chmod u+w {qr(workdir)}", check=False)
    if writable.returncode != 0:
        detail = writable.stderr.strip() or "remote workdir permission update failed"
        update_phase(state, "REMOTE_DIR_PERMISSION_FAILED", detail)
        fail(f"cannot make unique remote workdir writable: {detail}",
             phase=state["phase"])
    update_phase(state, "READY_TO_SUBMIT")
    submit_script = f"{workdir.rstrip('/')}/submit.sh"
    validate_remote_path(submit_script)

    try:
        result = subprocess.run(
            ["ssh", *SSH_OPTS, host, f"cat > {qr(submit_script)}"],
            input=plan["script"], text=True, capture_output=True,
            timeout=SSH_TIMEOUT,
        )
    except subprocess.TimeoutExpired:
        update_phase(state, "SUBMISSION_UNKNOWN", "timed out writing submit.sh")
        fail("submission preparation timed out; state is SUBMISSION_UNKNOWN and must not be retried",
             phase=state["phase"])
    if result.returncode != 0:
        update_phase(state, "SCRIPT_WRITE_FAILED", result.stderr.strip())
        fail(f"cannot write submit.sh: {result.stderr.strip()}", phase=state["phase"])
    update_phase(state, "SCRIPT_WRITTEN")

    submitted = ssh(host, f"cd {qr(workdir)} && sbatch --parsable submit.sh",
                     check=False)
    if submitted.returncode in (124, 255):
        update_phase(state, "SUBMISSION_UNKNOWN",
                     submitted.stderr.strip() or "sbatch response was ambiguous")
        fail("sbatch result is unknown; do not retry this job name; inspect the scheduler manually",
             phase=state["phase"])
    if submitted.returncode != 0:
        update_phase(state, "SUBMISSION_REJECTED", submitted.stderr.strip())
        fail(f"sbatch rejected the job: {submitted.stderr.strip()}",
             phase=state["phase"])
    match = re.fullmatch(r"\s*(\d+)(?:;[A-Za-z0-9_.:-]+)?\s*",
                         submitted.stdout or "")
    if not match:
        update_phase(state, "SUBMISSION_UNKNOWN", "unexpected sbatch --parsable output")
        fail("sbatch output was not parseable; do not retry this job name",
             phase=state["phase"])
    state["job_id"] = match.group(1)
    state["log"] = f"{workdir}/logs/{args.name}-{state['job_id']}.out"
    state["phase"] = "SUBMITTED"

    save_state(state)
    ok(name=args.name, **{k: v for k, v in state.items() if k not in ("name", "cmd")})


def _remaining(deadline):
    if deadline is None:
        return SSH_TIMEOUT
    return deadline - time.monotonic()


RECEIPT_FIELDS = ("Partition", "ReqTRES", "AllocTRES", "NodeList",
                  "Elapsed", "MaxRSS", "State", "ExitCode")


def parse_sacct_receipt(output, job_id):
    """Parse an exact root row while retaining the command's stdout bytes."""
    if not isinstance(output, bytes) or not output:
        return None, None
    try:
        decoded = output.decode("utf-8", errors="strict")
    except UnicodeDecodeError:
        return None, None
    lines = decoded.splitlines()
    if len(lines) != 1:
        return None, None
    row = lines[0].split("|")
    if len(row) != 9 or row[0] != str(job_id):
        return None, None
    if not row[1].strip() or not row[7].strip() or not re.fullmatch(r"[0-9]+:[0-9]+", row[8].strip()):
        return None, None
    state_name = row[7].strip()
    receipt = {field: (row[index].strip() or None)
               for index, field in enumerate(RECEIPT_FIELDS, start=1)}
    receipt["JobIDRaw"] = str(job_id)
    receipt["receipt_schema"] = SACCT_RECEIPT_SCHEMA
    receipt["captured_at"] = captured_at()
    receipt["sacct_rows_base64"] = base64.b64encode(output).decode("ascii")
    receipt["sacct_rows_sha256"] = hashlib.sha256(output).hexdigest()
    if receipt["MaxRSS"] == "":
        receipt["MaxRSS"] = None
    return receipt, state_name


def _terminal_from_receipt(receipt):
    if not receipt:
        return "unknown", None
    state_text = (receipt.get("State") or "").strip()
    if not state_text:
        return "unknown", None
    raw = state_text.upper()
    if re.fullmatch(r"CANCELLED(?: BY [0-9]+)?", raw):
        raw = "CANCELLED"
    exit_code = receipt.get("ExitCode")
    if raw == "COMPLETED" and exit_code == "0:0":
        return "completed", 0
    if raw == "CANCELLED":
        return "cancelled", exit_code
    if raw == "COMPLETED":
        return "failed", exit_code
    if raw in {"FAILED", "TIMEOUT", "OUT_OF_MEMORY", "NODE_FAIL",
               "BOOT_FAIL", "DEADLINE", "LAUNCH_FAILED",
               "RECONFIG_FAIL"}:
        return "failed", exit_code
    # squeue/sacct may report base states or state flags. These are not
    # terminal evidence, even if the job has disappeared from the queue.
    if raw in {"PENDING", "RUNNING", "CONFIGURING", "COMPLETING",
               "SUSPENDED", "REQUEUED", "REQUEUE_FED", "REQUEUE_HOLD",
               "RESIZING", "RESV_DEL_HOLD", "REVOKED", "SIGNALING",
               "SPECIAL_EXIT", "STAGE_OUT", "STOPPED", "UPDATE_DB",
               "EXPEDITING", "POWER_UP_NODE"}:
        return raw.lower(), None
    # PREEMPTED may be requeued under site PreemptMode, so it is not
    # sufficient evidence that this job has reached a terminal outcome.
    return "unknown", None


def parse_resource_evidence(output, state):
    """Keep controller bytes; requested GRES alone never proves allocation."""
    if not isinstance(output, bytes) or not output:
        return None
    try:
        decoded = output.decode("utf-8", errors="strict")
    except UnicodeDecodeError:
        return None
    ids = re.findall(r"(?:^|\s)JobId=([^\s]*)", decoded)
    if ids != [str(state.get("job_id"))]:
        return None
    def field(key):
        matches = re.findall(r"(?:^|\s)" + re.escape(key) + r"=([^\s]*)", decoded)
        return matches[0] if len(matches) == 1 else None
    for key in ("AllocTRES", "TresPerNode"):
        if len(re.findall(r"(?:^|\s)" + key + r"=([^\s]*)", decoded)) > 1:
            return None
    partition = field("Partition")
    expected = state.get("resources", {}).get("partition")
    if not partition or (expected and partition != expected):
        return None
    if state.get("name") and field("JobName") != state["name"]:
        return None
    job_state, nodes = field("JobState"), field("NodeList")
    if not job_state or not nodes:
        return None
    evidence = {
        "evidence_schema": RESOURCE_EVIDENCE_SCHEMA,
        "host": state["host"], "JobIDRaw": str(state["job_id"]),
        "Partition": partition, "JobState": job_state, "NodeList": nodes,
        "captured_at": captured_at(),
        "scontrol_rows_base64": base64.b64encode(output).decode("ascii"),
        "scontrol_rows_sha256": hashlib.sha256(output).hexdigest(),
        "requested_gres_per_node": field("TresPerNode"),
        "gpu_allocation_known": False, "gpu_allocated": None,
        "gpu_allocation_source": None,
    }
    # Only allocated GPU TRES or node-bound GRES details count as evidence.
    total = gpu_tres_count(field("AllocTRES"))
    if total is None and re.search(r"(?:^|,)gres/gpu", field("AllocTRES") or ""):
        return None
    node_details = re.findall(r"(?:^|\s)Nodes=([^\s]*)(.*?)(?=\sNodes=|$)", decoded, re.DOTALL)
    if node_details and (any(char in nodes for char in "[]") or any(
            not re.fullmatch(r"[A-Za-z0-9_.-]+", node) for node, _ in node_details)):
        evidence["gpu_allocation_source"] = "unsupported_node_range"
        return evidence
    detail_counts = []
    for node, block in node_details:
        gres = re.findall(r"(?:^|\s)GRES=([^\s]*)", block)
        if len(gres) > 1:
            return None
        if not re.fullmatch(r"[A-Za-z0-9_.-]+", node) or len(gres) != 1:
            detail_counts = []
            break
        count = gpu_gres_count(gres[0])
        if count is None:
            if re.search(r"(?:^|,)gpu", gres[0]):
                return None
            detail_counts = []
            break
        detail_counts.append((node, count))
    detail_total = sum(count for _, count in detail_counts) if detail_counts else None
    if detail_counts and len({node for node, _ in detail_counts}) != len(detail_counts):
        return None
    if detail_counts and not any(char in nodes for char in "[]"):
        if {node for node, _ in detail_counts} != set(nodes.split(",")):
            return None
    if total is not None and detail_total is not None and total != detail_total:
        return None
    allocated = total if total is not None else detail_total
    # Pending/unassigned output can include requests but has no allocation.
    allocated_states = {"RUNNING", "SUSPENDED", "COMPLETING", "COMPLETED", "FAILED",
                        "TIMEOUT", "OUT_OF_MEMORY", "NODE_FAIL", "CANCELLED"}
    if job_state in allocated_states and nodes not in {"(null)", "None", "N/A"} and allocated is not None:
        evidence.update(gpu_allocation_known=True, gpu_allocated=allocated,
                        gpu_allocation_source="AllocTRES" if total is not None else "node_GRES")
    return evidence


def capture_resource_evidence(state, deadline=None):
    """An optional GPU observation; failure never changes scheduler success."""
    if state.get("resource_class") != "gpu":
        return
    remaining = _remaining(deadline)
    if remaining <= 0:
        return
    result = ssh(state["host"], f"scontrol show job -d -o {q(state['job_id'])}",
                 check=False, timeout=min(SSH_TIMEOUT, remaining), binary=True)
    evidence = parse_resource_evidence(result.stdout, state) if result.returncode == 0 else None
    state["resource_evidence_query"] = {"captured_at": captured_at(),
                                         "status": "valid" if evidence else "unavailable"}
    if evidence:
        state["resource_evidence"] = evidence
        if evidence["gpu_allocation_known"]:
            state["resource_evidence_last_allocation"] = evidence
    else:
        state.pop("resource_evidence", None)
    # Historical allocation is separate from the current query, including requeues.
    previous = state.get("resource_evidence_last_allocation")
    if previous and (previous.get("JobIDRaw") != str(state["job_id"])
                     or previous.get("host") != state["host"]
                     or previous.get("Partition") != state.get("resources", {}).get("partition")):
        state.pop("resource_evidence_last_allocation", None)


def slurm_observation(state, deadline=None):
    host, jid = state["host"], state.get("job_id")
    if not jid or not re.fullmatch(r"[0-9]+", str(jid)):
        return "unknown", None, None
    jid = str(jid)
    jid_arg = q(jid)
    remaining = _remaining(deadline)
    if remaining <= 0:
        return "timeout", None, None
    queue_result = ssh(host, f"squeue -j {jid_arg} -h -o %T", check=False,
                       timeout=min(SSH_TIMEOUT, remaining))
    if queue_result.returncode == 124 and deadline is not None:
        return "timeout", None, None
    queue_stdout = queue_result.stdout if isinstance(queue_result.stdout, str) else ""
    queue_stderr = queue_result.stderr if isinstance(queue_result.stderr, str) else ""
    diagnostic = "\n".join((queue_stdout, queue_stderr)).strip()
    invalid_id = re.fullmatch(
        r"(?i)(?:slurm_load_jobs\s+error:\s*)?invalid job id specified\.?",
        diagnostic) is not None
    if queue_result.returncode != 0:
        # Some Slurm sites remove terminal jobs from squeue immediately and
        # report "Invalid job id specified" instead of an empty queue row.
        # Only that exact diagnostic permits the exact JobIDRaw sacct lookup
        # below; transport/authentication/other scheduler errors stay UNKNOWN.
        if not invalid_id:
            return "unknown", None, None
    queued = queue_result.stdout.strip()
    if not invalid_id and queue_result.returncode == 0:
        # squeue is useful for known live states only. Terminal, malformed,
        # diagnostic, and multi-row output must be checked against sacct.
        if queued and "\n" not in queued and "\r" not in queued:
            active_states = {"PENDING", "RUNNING", "CONFIGURING", "COMPLETING",
                             "SUSPENDED", "REQUEUED", "REQUEUE_FED", "RESIZING",
                             "STAGE_OUT", "STOPPED"}
            if queued.upper() in active_states:
                capture_resource_evidence(state, deadline)
                return queued.lower(), None, None
    # sacct lags behind job completion; retry briefly before giving up
    out = b""
    for _ in range(3):
        remaining = _remaining(deadline)
        if remaining <= 0:
            return "timeout", None, None
        acct_result = ssh(host, f"sacct -j {jid_arg} -X -n -P --format=JobIDRaw,Partition,ReqTRES,AllocTRES,NodeList,Elapsed,MaxRSS,State,ExitCode",
                          check=False, timeout=min(SSH_TIMEOUT, remaining),
                          binary=True)
        if acct_result.returncode == 124 and deadline is not None:
            return "timeout", None, None
        if acct_result.returncode != 0:
            return "unknown", None, None
        out = acct_result.stdout
        if isinstance(out, bytes) and out.strip():
            break
        if not isinstance(out, bytes):
            return "unknown", None, None
        remaining = _remaining(deadline)
        if remaining <= 0:
            return "timeout", None, None
        time.sleep(min(2, remaining))
    if not out.strip():
        return "unknown", None, None
    receipt, raw_state = parse_sacct_receipt(out, jid)
    if receipt is None:
        return "unknown", None, None
    expected_partition = state.get("resources", {}).get("partition")
    if expected_partition and receipt["Partition"] != expected_partition:
        return "unknown", None, None
    terminal, exit_code = _terminal_from_receipt(receipt)
    capture_resource_evidence(state, deadline)
    return terminal, exit_code, receipt


def slurm_state(state, deadline=None):
    observed = slurm_observation(state, deadline)
    return observed[0], observed[1]


def ssh_state(state, deadline=None):
    host = state["host"]
    if not state.get("exit_file"):
        return "unknown", None
    remaining = _remaining(deadline)
    if remaining <= 0:
        return "timeout", None
    exit_result = ssh(host, f"cat {qr(state['exit_file'])} 2>/dev/null",
                      check=False, timeout=min(SSH_TIMEOUT, remaining))
    if exit_result.returncode == 124 and deadline is not None:
        return "timeout", None
    exit_out = exit_result.stdout.strip()
    if exit_out:
        try:
            code = int(exit_out)
        except ValueError:
            return "unknown", None
        return ("completed" if code == 0 else "failed"), code
    if state.get("session"):
        remaining = _remaining(deadline)
        if remaining <= 0:
            return "timeout", None
        alive = ssh(host, f"tmux has-session -t {q(state['session'])}",
                    check=False, timeout=min(SSH_TIMEOUT, remaining)).returncode == 0
    else:
        remaining = _remaining(deadline)
        if remaining <= 0:
            return "timeout", None
        alive = ssh(host, f"kill -0 {q(state['pid'])}",
                    check=False, timeout=min(SSH_TIMEOUT, remaining)).returncode == 0
    return ("running" if alive else "unknown"), None


def query_state(state, deadline=None):
    return (slurm_state if state["backend"] == "slurm" else ssh_state)(state, deadline)


def observe_state(state, deadline=None):
    if state["backend"] == "slurm":
        return slurm_observation(state, deadline)
    status, code = ssh_state(state, deadline)
    return status, code, None


def persist_terminal(state, job_state, exit_code, receipt):
    """Atomically cache a maintainer-side terminal observation."""
    if job_state not in {"completed", "failed", "cancelled"}:
        if state.get("resource_evidence_query") and state.get("name"):
            save_state(state)
        return
    state["state_version"] = STATE_VERSION
    state["scheduler_state"] = job_state
    state["terminal_observed_at"] = captured_at()
    if receipt is not None:
        state["receipt"] = receipt
        if receipt.get("sacct_rows_sha256"):
            state["sacct_rows_sha256"] = receipt["sacct_rows_sha256"]
    save_state(state)


def cmd_status(args):
    state = load_state(args.job)
    job_state, exit_code, receipt = observe_state(state)
    persist_terminal(state, job_state, exit_code, receipt)
    ok(name=args.job, backend=state["backend"],
       resource_class=state.get("resource_class", "cpu"), state=job_state,
       exit_code=exit_code, receipt=receipt, workdir=state["workdir"],
       resource_evidence=state.get("resource_evidence"),
       resource_evidence_last_allocation=state.get("resource_evidence_last_allocation"),
       resource_evidence_query=state.get("resource_evidence_query"),
       log=state.get("log"))


def cmd_wait(args):
    """Wait for a scheduler terminal state without treating absence as success."""
    if args.poll < 1 or args.timeout < 1 or args.unknown_limit < 1:
        fail("--poll, --timeout and --unknown-limit must be positive; waits are bounded")
    state = load_state(args.job)
    started = time.monotonic()
    unknown = 0
    while True:
        deadline = started + args.timeout
        if time.monotonic() >= deadline:
            fail(f"timeout while waiting for job '{args.job}'",
                 state="timeout", log=state.get("log"))
        job_state, exit_code, receipt = observe_state(state, deadline)
        if job_state not in {"completed", "failed", "cancelled"}:
            persist_terminal(state, job_state, exit_code, receipt)
        if job_state == "timeout":
            fail(f"timeout while waiting for job '{args.job}'",
                 state="timeout", log=state.get("log"))
        if job_state == "completed":
            persist_terminal(state, job_state, exit_code, receipt)
            ok(name=args.job, resource_class=state.get("resource_class", "cpu"),
               state=job_state, exit_code=exit_code,
               scheduler_success=True, scientific_result="not_validated",
               resource_evidence=state.get("resource_evidence"),
               resource_evidence_last_allocation=state.get("resource_evidence_last_allocation"),
               resource_evidence_query=state.get("resource_evidence_query"),
               receipt=receipt, workdir=state["workdir"], log=state.get("log"))
            return
        if job_state in ("failed", "cancelled"):
            persist_terminal(state, job_state, exit_code, receipt)
            fail(f"job '{args.job}' ended in scheduler state {job_state}",
                 state=job_state, exit_code=exit_code, receipt=receipt,
                 resource_evidence=state.get("resource_evidence"),
                 resource_evidence_last_allocation=state.get("resource_evidence_last_allocation"),
                 resource_evidence_query=state.get("resource_evidence_query"),
                 log=state.get("log"))
        if job_state == "unknown":
            unknown += 1
            if unknown >= args.unknown_limit:
                fail(f"job '{args.job}' left the queue but sacct returned no "
                     "terminal state; not assuming success",
                     state="unknown", log=state.get("log"))
        else:
            unknown = 0
        if time.monotonic() >= deadline:
            fail(f"timeout while waiting for job '{args.job}'",
                 state=job_state, log=state.get("log"))
        remaining = args.timeout - (time.monotonic() - started)
        time.sleep(min(args.poll, max(0, remaining)))


def cmd_logs(args):
    if args.lines < 1:
        fail("--lines must be positive")
    state = load_state(args.job)
    if not state.get("log"):
        fail(f"job '{args.job}' has no log yet; state is "
             f"{state.get('phase', 'unknown')}", state="unknown")
    paths = [("stdout", state["log"])]
    if state["backend"] == "slurm" and state["log"].endswith(".out"):
        paths.append(("stderr", state["log"][:-len(".out")] + ".err"))
    parts = []
    for label, path in paths:
        parts.append(f"echo '== {label}: {path} =='")
        parts.append(f"tail -n {args.lines} {qr(path)} 2>/dev/null"
                     f" || echo '(no output yet)'")
    result = ssh(state["host"], "; ".join(parts), check=False)
    if result.returncode != 0:
        fail(f"cannot read logs: {result.stderr.strip()}", log=state["log"])
    print(result.stdout, end="")


def cmd_cancel(args):
    state = load_state(args.job)
    host = state["host"]
    if state["backend"] == "slurm":
        if not state.get("job_id"):
            fail(f"job '{args.job}' has no known scheduler job id; state is "
                 f"{state.get('phase', 'unknown')}; inspect host/workdir manually",
                 state="unknown", workdir=state["workdir"])
        ssh(host, f"scancel {q(state['job_id'])}")
    elif state.get("session"):
        ssh(host, f"tmux kill-session -t {q(state['session'])}", check=False)
    elif state.get("pid"):
        ssh(host, f"kill {q(state['pid'])}", check=False)
    else:
        fail(f"job '{args.job}' has no cancellable remote process; inspect host/workdir manually",
             state="unknown", workdir=state["workdir"])
    ok(name=args.job, cancelled=True)


def cmd_collect(args):
    state = load_state(args.job)
    validate_host(state["host"])
    validate_remote_path(state["workdir"])
    job_state, exit_code, receipt = observe_state(state)
    persist_terminal(state, job_state, exit_code, receipt)
    if (job_state != "completed" or exit_code != 0) and not args.allow_unsuccessful:
        fail(f"job '{args.job}' is {job_state} (exit_code={exit_code}); "
             "refusing normal collection until scheduler success. Use "
             "--allow-unsuccessful only to retrieve diagnostics",
             state=job_state, exit_code=exit_code, receipt=receipt,
             resource_evidence=state.get("resource_evidence"),
             resource_evidence_last_allocation=state.get("resource_evidence_last_allocation"),
             resource_evidence_query=state.get("resource_evidence_query"))
    dest = Path(args.dest or f"./{args.job}").expanduser()
    if dest.exists() or dest.is_symlink():
        fail(f"refusing to overwrite existing collection destination: {dest}")
    dest.parent.mkdir(parents=True, exist_ok=True)
    try:
        result = subprocess.run(
            ["rsync", "-az", "--", f"{state['host']}:{state['workdir']}/", str(dest) + "/"],
            capture_output=True, text=True, timeout=state["transfer_timeout"],
        )
    except subprocess.TimeoutExpired:
        fail(f"rsync collection timed out after {state['transfer_timeout']}s; "
             f"destination may be incomplete. Retry with a new --dest; "
             f"the partial destination was left untouched.")
    if result.returncode != 0:
        fail(f"rsync failed: {result.stderr.strip()}")
    ok(name=args.job, state=job_state, exit_code=exit_code, receipt=receipt,
       resource_evidence=state.get("resource_evidence"),
       resource_evidence_last_allocation=state.get("resource_evidence_last_allocation"),
       resource_evidence_query=state.get("resource_evidence_query"),
       dest=str(dest))


def _probe_partition_name(value):
    return value.strip().rstrip("*")


def _gpu_total(entries):
    """Reconcile a generic total with typed counts, never double count it."""
    if not entries or len({kind for kind, _ in entries}) != len(entries):
        return None
    generic = next((count for kind, count in entries if kind is None), None)
    typed = [count for kind, count in entries if kind is not None]
    if generic is not None:
        return generic if not typed or generic == sum(typed) else None
    return sum(typed)


def gpu_tres_count(value):
    """Return an explicit GPU TRES total; absent or malformed means unknown."""
    if not isinstance(value, str) or not value.strip():
        return None
    entries = []
    for token in value.split(","):
        token = token.strip()
        if not token or "=" not in token:
            return None
        key, count = token.split("=", 1)
        if key.startswith("gres/gpu"):
            match = re.fullmatch(r"gres/gpu(?::([A-Za-z0-9_.-]+))?", key)
            if not match or not re.fullmatch(r"[0-9]+", count):
                return None
            entries.append((match.group(1), int(count)))
        elif not key or not count:
            return None
    return _gpu_total(entries)


def gpu_gres_count(value):
    """Parse GRES counts, preserving commas inside Slurm IDX/S annotations."""
    if not isinstance(value, str) or not value.strip():
        return None
    tokens, start, depth = [], 0, 0
    for index, char in enumerate(value):
        if char == "(":
            depth += 1
            if depth > 1:
                return None
        elif char == ")":
            depth -= 1
            if depth < 0:
                return None
        elif char == "," and depth == 0:
            tokens.append(value[start:index].strip())
            start = index + 1
    if depth:
        return None
    tokens.append(value[start:].strip())
    entries = []
    for token in tokens:
        if not token:
            return None
        if token.startswith("gpu"):
            match = re.fullmatch(
                r"gpu(?::([A-Za-z0-9_.-]+))?:([0-9]+)"
                r"(?:\(((?:IDX|S):[0-9]+(?:-[0-9]+)?(?:,[0-9]+(?:-[0-9]+)?)*|IDX:N/A)\))?", token)
            if not match:
                return None
            if match.group(3) == "IDX:N/A" and int(match.group(2)) != 0:
                return None
            annotation = match.group(3)
            if annotation and annotation.startswith("IDX:") and annotation != "IDX:N/A":
                intervals = []
                for item in annotation[4:].split(","):
                    bounds = item.split("-")
                    first, last = int(bounds[0]), int(bounds[-1])
                    if first > last:
                        return None
                    intervals.append((first, last))
                intervals.sort()
                if any(right[0] <= left[1] for left, right in zip(intervals, intervals[1:])):
                    return None
                if sum(last - first + 1 for first, last in intervals) != int(match.group(2)):
                    return None
            entries.append((match.group(1), int(match.group(2))))
        elif not re.fullmatch(
                r"[A-Za-z0-9_.-]+(?::[A-Za-z0-9_.-]+)?:[0-9]+"
                r"(?:\((?:IDX|S):[0-9]+(?:-[0-9]+)?(?:,[0-9]+(?:-[0-9]+)?)*\))?", token):
            return None
    return _gpu_total(entries)


def _probe_gpu_allocation(node):
    capacity = gpu_gres_count(node["gres"])
    shared = any(isinstance(value, str) and re.search(
        r"(?:^|[,\s])(?:gres/)?(?:mps|shard)(?:[:=]|$)", value)
        for value in (node["gres"], node.get("alloc_tres"), node.get("gres_used")))
    counts = []
    malformed = False
    for field, parser in (("alloc_tres", gpu_tres_count),
                          ("gres_used", gpu_gres_count)):
        value = node.get(field)
        count = parser(value)
        if count is not None:
            counts.append((field, count))
        elif isinstance(value, str) and re.search(r"(?:^|[,\s])(?:gres/)?gpu", value):
            malformed = True
    source = "+".join(field for field, _ in counts) or None
    allocated = counts[0][1] if counts else None
    known = bool(counts) and not malformed
    if known and any(count != allocated for _, count in counts):
        known, source = False, "conflict"
    if known and capacity is not None and allocated > capacity:
        known, source = False, "exceeds_capacity"
    if malformed:
        source = "malformed"
    if shared:
        known, source = False, "unsupported_shared_gres"
    node.update(gpu_capacity=capacity, gpu_allocation_known=known,
                gpu_allocated=allocated if known else None,
                gpu_available=capacity - allocated if known and capacity is not None else None,
                gpu_allocation_source=source)


def parse_probe_output(output, host, request_partition=None, include_detail=False):
    """Parse delimiter-safe sinfo/squeue fallback output into a full snapshot."""
    sections = {"partitions": [], "nodes": [], "queue": [], "detail": []}
    seen = set()
    current = None
    for line in (output or "").splitlines():
        marker = line.strip()
        if marker == "__IKKEM_SINFO__":
            current = "partitions"; seen.add(current); continue
        if marker == "__IKKEM_NODES__":
            current = "nodes"; seen.add(current); continue
        if marker == "__IKKEM_QUEUE__":
            current = "queue"; seen.add(current); continue
        if marker == "__IKKEM_DETAIL__":
            current = "detail"; seen.add(current); continue
        if current and marker:
            sections[current].append(line.rstrip("\r"))
    if (not {"partitions", "nodes", "queue"}.issubset(seen)
            or not sections["partitions"] or not sections["nodes"]):
        raise ValueError("probe output is incomplete; all sinfo/node/queue sections are required")
    if include_detail and ("detail" not in seen or not sections["detail"]):
        raise ValueError("probe output is incomplete; node allocation details are required")
    partitions = []
    for line in sections["partitions"]:
        fields = line.split("|", 6)
        if len(fields) != 6:
            raise ValueError("malformed sinfo partition row")
        name, avail, limit, node_count, state, gres = fields
        if not re.fullmatch(r"[0-9]+", node_count):
            raise ValueError("malformed sinfo partition node count")
        partitions.append({"name": _probe_partition_name(name), "availability": avail,
                           "time_limit": limit, "node_count": node_count,
                           "state": state, "gres": gres})
    nodes = []
    node_keys = set()
    for line in sections["nodes"]:
        fields = line.split("|", 6)
        if len(fields) not in (4, 7):
            raise ValueError("malformed sinfo node row")
        part, node, state, gres = fields[:4]
        node_key = (_probe_partition_name(part), node)
        if not node_key[0] or not node or node_key in node_keys:
            raise ValueError("malformed or duplicate sinfo node row")
        node_keys.add(node_key)
        cpus = memory_mb = features = None
        if len(fields) == 7:
            raw_cpus, raw_memory, features = fields[4:]
            try:
                cpus = int(raw_cpus) if raw_cpus else None
                memory_mb = int(raw_memory) if raw_memory else None
            except ValueError as exc:
                raise ValueError("malformed sinfo node CPU/memory row") from exc
            if (cpus is not None and cpus < 0) or (memory_mb is not None and memory_mb < 0):
                raise ValueError("negative sinfo node CPU/memory capacity")
        nodes.append({"partition": _probe_partition_name(part), "name": node,
                      "state": state, "gres": gres, "cpus": cpus,
                      "memory_mb": memory_mb, "features": features})
    queue_counts = {}
    for line in sections["queue"]:
        fields = line.split("|", 2)
        if len(fields) != 3:
            raise ValueError("malformed squeue row")
        part, state, count = fields
        try:
            number = int(count)
        except ValueError as exc:
            raise ValueError("malformed squeue count") from exc
        if number < 0:
            raise ValueError("malformed squeue count")
        key = (_probe_partition_name(part), state)
        queue_counts[key] = queue_counts.get(key, 0) + number
    queue = [{"partition": part, "state": state, "count": count,
              "count_unit": "jobs/entries"}
             for (part, state), count in sorted(queue_counts.items())]
    partitions.sort(key=lambda item: item["name"])
    nodes.sort(key=lambda item: (item["partition"], item["name"], item["gres"]))
    if request_partition:
        wanted = _probe_partition_name(request_partition)
        nodes = [item for item in nodes if item["partition"] == wanted]
    if include_detail:
        details = {}
        for line in sections["detail"]:
            names = re.findall(r"(?:^|\s)NodeName=(\S+)", line)
            if len(names) != 1 or names[0] in details:
                raise ValueError("malformed or duplicate scontrol node detail")
            detail = {}
            for key, field in (("AllocTRES", "alloc_tres"), ("GresUsed", "gres_used")):
                # Count field occurrences including empty values: repeated keys
                # cannot silently select the first (potentially idle) value.
                occurrences = re.findall(r"(?:^|\s)" + key + r"=([^\s]*)", line)
                if len(occurrences) > 1:
                    raise ValueError("duplicate scontrol node allocation field")
                detail[field] = occurrences[0] if occurrences else None
            details[names[0]] = detail
        if any(node["name"] not in details for node in nodes):
            raise ValueError("probe output is missing allocation details for a node")
        for node in nodes:
            node.update(details[node["name"]])
    for node in nodes:
        _probe_gpu_allocation(node)
    return {"schema_version": STATE_VERSION, "captured_at": captured_at(),
            "host": host, "request_partition": request_partition,
            "partitions": partitions, "nodes": nodes, "queue": queue,
            "queue_count_unit": "jobs/entries",
            "queue_wait_time_estimate": None}


def cmd_probe(args):
    """Read-only cluster probe with a deterministic JSON snapshot mode."""
    host = args.host
    if getattr(args, "detail", False) and (
            not getattr(args, "json", False) or not args.partition):
        fail("probe --detail requires --json and --partition")
    if args.partition and not SLURM_VALUE_RE.fullmatch(args.partition):
        fail("partition contains unsupported characters")
    validate_host(host)
    if getattr(args, "json", False):
        script = ("set -eu; printf '%s\\n' __IKKEM_SINFO__; "
                  "sinfo -h -o '%P|%a|%l|%D|%T|%G'; "
                  "printf '%s\\n' __IKKEM_NODES__; "
                  "sinfo -h -N -o '%P|%n|%T|%G|%c|%m|%f'; "
                  "printf '%s\\n' __IKKEM_QUEUE__; "
                  "squeue -h -o '%P|%T|1'")
        if getattr(args, "detail", False):
            partition = q(args.partition)
            script += ("; printf '%s\\n' __IKKEM_DETAIL__; "
                       f"sinfo -p {partition} -h -N -o %n | sort -u | "
                       "while IFS= read -r node; do scontrol show node \"$node\" -o; done")
    else:
        script = "echo '== sinfo -s =='; sinfo -s; echo; echo '== squeue =='; squeue"
        if args.partition:
            p = q(args.partition)
            script += (f"; echo; echo '== scontrol show partition {args.partition} =='; "
                       f"scontrol show partition {p}")
    result = ssh(host, script, check=False)
    if result.returncode != 0:
        fail(f"probe failed: {result.stderr.strip() or 'scheduler query failed'}")
    if getattr(args, "json", False):
        try:
            snapshot = parse_probe_output(result.stdout, host, args.partition,
                                          include_detail=getattr(args, "detail", False))
        except ValueError as exc:
            fail(f"probe failed: {exc}")
        print(canonical_json({**snapshot,
                              "snapshot_sha256": sha256_canonical(snapshot)}))
        return
    print(result.stdout, end="")


def cmd_list(args):
    jobs = []
    if STATE_DIR.is_dir():
        for path in sorted(STATE_DIR.glob("*.json")):
            try:
                state = json.loads(path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                continue
            jobs.append({"name": state.get("name"),
                         "backend": state.get("backend"),
                         "host": state.get("host"),
                         "target": state.get("target"),
                         "profile": state.get("profile"),
                         "resource_class": state.get("resource_class", "cpu"),
                         "job_id": state.get("job_id"),
                         "submitted_at": state.get("submitted_at"),
                         "workdir": state.get("workdir")})
    ok(jobs=jobs)


def main():
    parser = argparse.ArgumentParser(
        prog="submit.py",
        description="Submit maintainer CPU or GPU jobs through an IKKEM SLURM target.")
    sub = parser.add_subparsers(dest="command", required=True)

    p_submit = sub.add_parser("submit", help="submit a job")
    p_submit.add_argument("--target", help="named target from submit-job.json")
    p_submit.add_argument("--profile", choices=["cpu", "gpu"],
                          help="route through a locked CPU or GPU profile")
    p_submit.add_argument("--base-dir", dest="base_dir",
                          help="remote base directory (default: ~/submit-jobs)")
    p_submit.add_argument("--name", required=True, help="job name; this is the handle")
    p_submit.add_argument("--cmd", required=True, help="command to run remotely")
    reason_group = p_submit.add_mutually_exclusive_group(required=True)
    reason_group.add_argument("--reason", help="non-empty UTF-8 decision rationale")
    reason_group.add_argument("--reason-file", help="UTF-8 file containing decision rationale")
    p_submit.add_argument("--snapshot-sha256", required=True,
                          help="SHA-256 of canonical probe snapshot JSON")
    p_submit.add_argument("--probe-snapshot",
                          help="snapshot JSON to hash and validate against host/partition")
    p_submit.add_argument("--workdir", help="remote workdir (default: <base-dir>/<name>)")
    p_submit.add_argument("--src", help="local directory to rsync into the workdir")
    p_submit.add_argument("--exclude", action="append", default=[], metavar="PATTERN",
                          help="rsync exclude pattern for --src, repeatable "
                               "(e.g. --exclude .venv --exclude '__pycache__')")
    p_submit.add_argument("--time", help="slurm wall limit, e.g. 24:00:00; "
                          "verify the target cluster's QOS limit")
    p_submit.add_argument("--partition", help="slurm partition")
    p_submit.add_argument("--nodes", type=int, help="slurm node count")
    p_submit.add_argument("--ntasks", type=int, help="total slurm MPI task count")
    p_submit.add_argument("--ntasks-per-node", dest="ntasks_per_node", type=int,
                          help="slurm MPI tasks per node")
    p_submit.add_argument("--cpus", type=int, help="slurm cpus-per-task")
    p_submit.add_argument("--mem", help="slurm memory, e.g. 32G")
    p_submit.add_argument("--gpus", type=int, help="slurm GPUs (--gres=gpu:N)")
    p_submit.add_argument("--gres", help="slurm raw gres spec, e.g. gpu:tesla:1 "
                          "(mutually exclusive with --gpus; for typed/MIG gres)")
    p_submit.add_argument("--account", help="slurm account")
    p_submit.add_argument("--qos", help="slurm QOS")
    p_submit.add_argument("--constraint", help="slurm node constraint")
    p_submit.add_argument("--dry-run", action="store_true",
                          help="print the plan (incl. sbatch script) without executing")
    p_submit.set_defaults(func=cmd_submit)

    p_status = sub.add_parser("status", help="job state + exit code")
    p_status.add_argument("--job", required=True)
    p_status.set_defaults(func=cmd_status)

    p_wait = sub.add_parser("wait", help="wait for a sacct-confirmed terminal state")
    p_wait.add_argument("--job", required=True)
    p_wait.add_argument("--poll", type=int, default=60,
                        help="poll interval in seconds (default: 60)")
    p_wait.add_argument("--timeout", type=int, default=3600,
                        help="maximum wait in seconds (default: 3600; bounded)")
    p_wait.add_argument("--unknown-limit", type=int, default=3,
                        help="consecutive unknown states before stopping (default: 3)")
    p_wait.set_defaults(func=cmd_wait)

    p_logs = sub.add_parser("logs", help="print stdout+stderr log tails")
    p_logs.add_argument("--job", required=True)
    p_logs.add_argument("--lines", type=int, default=50)
    p_logs.set_defaults(func=cmd_logs)

    p_cancel = sub.add_parser("cancel", help="cancel a running/pending job")
    p_cancel.add_argument("--job", required=True)
    p_cancel.set_defaults(func=cmd_cancel)

    p_collect = sub.add_parser("collect", help="rsync remote workdir back locally")
    p_collect.add_argument("--job", required=True)
    p_collect.add_argument("--dest", help="local destination (default: ./<name>)")
    p_collect.add_argument("--allow-unsuccessful", action="store_true",
                           help="collect a failed/unknown job for diagnostics")
    p_collect.set_defaults(func=cmd_collect)

    p_list = sub.add_parser("list", help="list locally tracked jobs (cached info)")
    p_list.set_defaults(func=cmd_list)

    p_probe = sub.add_parser("probe", help="read-only cluster probe "
                             "(sinfo/squeue/scontrol via ssh)")
    p_probe.add_argument("--host", required=True,
                         help="ssh destination (alias or user@host)")
    p_probe.add_argument("--partition",
                         help="also show partition details and node gres")
    p_probe.add_argument("--json", action="store_true",
                         help="emit one canonical JSON snapshot object")
    p_probe.add_argument("--detail", action="store_true",
                         help="include each node's allocated TRES (requires --json and --partition)")
    p_probe.set_defaults(func=cmd_probe)

    args = parser.parse_args()
    if args.command == "probe" and args.detail and (not args.json or not args.partition):
        parser.error("probe --detail requires --json and --partition")
    args.func(args)


if __name__ == "__main__":
    main()
