#!/usr/bin/env bash
set -euo pipefail

# Minimal reference driver for the Case04 host RPC contract. It never talks to
# Slurm or SSH directly; the runner provides same-attempt collection through
# the mounted host RPC channel.
APP_ROOT="${APP:-$(pwd)}"
OUT="$APP_ROOT/outputs"
mkdir -p "$OUT"
exec python3 - "$APP_ROOT" <<'PY'
import hashlib
import json
import os
import pathlib
import stat
import time
import uuid

app = pathlib.Path(os.environ.get("APP", os.sys.argv[1])).resolve()
out = app / "outputs"
plan_path = out / "probe-plan.json"
if not plan_path.is_file() or plan_path.is_symlink():
    plan = {
        "schema": "bench25-case04-probe-plan/v3",
        "model_sha256": "a3b5db7ed33806ac6371ab6fd10511eb2aaf3580f42d2b13ea8e091294e80a87",
        "inference_model_sha256": "6365499f367fdba5d0299ec91632ddfd961fe695809dbed80f5e8ffbc85bc31c",
        "model_source_sha256": "c09b8e3b711ab48d00e68c2222e08ed27b8c50cb42a75747a9ed0733385c3110",
        "runtime_adapter_sha256": "8b00da02f268bbdcdbfc9d5d76d005489476b977924492f94af5c0e5129d98bf",
        "ic_pool_sha256": "96e52569ef2cf7a404a4a84a927a186fd6e510bf19a18088261c8c61a2176a4e",
        "trajectory_indices_zero_based": [4, 2],
        "duration_fs": [10.0, 10.0],
        "dt_fs": 0.5,
        "resource_request": {"cpus": 1, "memory_gb": 4, "wall_seconds": 300,
                             "accelerator": "cpu", "gpu_count": 0},
        "software_environment": {},
        "energy_drift_threshold_ev": 0.5,
        "risk_hypotheses": ["energy_force_consistency", "nac_phase_continuity",
                            "low_gap_coupling", "ood_coverage", "surface_hop_stability"],
        "stop_rules": {"driver_failure": "stop", "non_finite": "stop",
                        "energy_drift": "diagnose", "identity_mismatch": "stop",
                        "missing_records": "stop"},
        "continue_or_stop_rule": {"continue_when": ["all_runs_complete", "all_drifts_below_threshold",
                                                      "all_risks_assessed"],
                                  "otherwise": "diagnose_or_stop"},
    }
    plan_bytes = (json.dumps(plan, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n").encode()
    fd = os.open(plan_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "wb") as stream:
        stream.write(plan_bytes)
        stream.flush()
        os.fsync(stream.fileno())

def env_error(message):
    print("ENV_ERROR: " + message, file=os.sys.stderr)
    raise SystemExit(2)

try:
    rpc = pathlib.Path("/run/ccb-hpc")
    try:
        info = rpc.lstat()
    except FileNotFoundError:
        env_error("host case04 RPC mount is unavailable")
    if not stat.S_ISDIR(info.st_mode) or stat.S_ISLNK(info.st_mode):
        env_error("the host case04 RPC mount is unavailable")
    attempt_env = os.environ.get("CCB_BENCH25_ATTEMPT_ID", "")
    identity_path = pathlib.Path("/run/bench25-capture/public-attempt.json")
    fd = os.open(identity_path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, "rb") as stream:
        before = os.fstat(stream.fileno())
        if (not stat.S_ISREG(before.st_mode) or before.st_uid != 0
                or before.st_mode & 0o222 or before.st_nlink != 1 or before.st_size > 4096):
            env_error("root-published attempt identity is unsafe")
        identity_raw = stream.read(4097)
        after = os.fstat(stream.fileno())
    if len(identity_raw) != before.st_size or before.st_size > 4096 or (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns) != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns):
        env_error("root-published attempt identity changed while being read")
    identity = json.loads(identity_raw.decode("utf-8"))
    attempt = identity.get("attempt_id") if set(identity) == {"schema", "attempt_id", "run_id"} and identity.get("schema") == "bench25/public-attempt/v1" else ""
    run_id = identity.get("run_id", "")
    if (len(attempt) != 32 or any(c not in "0123456789abcdef" for c in attempt)
            or len(run_id) != 32 or any(c not in "0123456789abcdef" for c in run_id)
            or (attempt_env and attempt_env != attempt)):
        env_error("root-published attempt identity is invalid or mismatched")

    def rpc_call(operation, plan_sha=None, timeout=30):
        request_id = uuid.uuid4().hex
        payload = {"plan_sha256": plan_sha} if operation == "submit_probe" else {}
        request = {"schema":"case04-harbor-rpc-request/v1","request_id": request_id,
                   "attempt_id": attempt, "operation": operation, "payload":payload}
        target = rpc / (request_id + ".request.json")
        temporary = rpc / (request_id + ".request.part")
        payload = (json.dumps(request, sort_keys=True, separators=(",", ":")) + "\n").encode()
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.link(temporary, target, follow_symlinks=False)
        temporary.unlink()
        response = rpc / (request_id + ".response.json")
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                response_stat = response.lstat()
            except FileNotFoundError:
                response_stat = None
            if response_stat is not None:
                if not stat.S_ISREG(response_stat.st_mode) or stat.S_ISLNK(response_stat.st_mode) or response_stat.st_size > 65536:
                    env_error("host broker response is not a bounded regular file")
                fd = os.open(response, os.O_RDONLY | os.O_NOFOLLOW)
                with os.fdopen(fd, "rb") as stream:
                    raw_response=stream.read(65537)
                value=json.loads(raw_response.decode("utf-8"))
                if (value.get("schema")!="case04-harbor-rpc-response/v1"
                        or value.get("request_id")!=request_id or value.get("attempt_id")!=attempt):
                    env_error("host RPC response identity mismatch")
                return value.get("payload",{})
            time.sleep(0.1)
        raise TimeoutError("host broker did not answer " + operation)

    facts=rpc_call("inspect_runtime",timeout=90)
    if facts.get("status")!="INSPECTED":
        env_error("host did not provide its actual runtime facts")
    plan=json.loads(plan_path.read_text(encoding="utf-8"))
    plan["software_environment"]=facts["software_environment"]
    capacity=facts["resource_capacity"]
    plan["resource_request"]={"cpus":min(1,capacity["cpus"]),
        "memory_gb":min(4,capacity["memory_gb"]),
        "wall_seconds":min(300,capacity["max_wall_seconds"]),
        "accelerator":"cpu","gpu_count":0}
    canonical=json.dumps(plan,sort_keys=True,separators=(",",":"),ensure_ascii=False,allow_nan=False).encode()
    tmp=plan_path.with_name(".probe-plan.tmp")
    fd=os.open(tmp,os.O_WRONLY|os.O_CREAT|os.O_TRUNC|os.O_NOFOLLOW,0o600)
    with os.fdopen(fd,"wb") as stream:stream.write(canonical+b"\n");stream.flush();os.fsync(stream.fileno())
    os.replace(tmp,plan_path)

    try:
        registered = rpc_call("register_plan", timeout=30)
    except TimeoutError as exc:
        env_error(str(exc))
    if registered.get("status") != "REGISTERED":
        env_error("host broker did not preregister the plan")
    plan_sha = hashlib.sha256(canonical).hexdigest()
    if registered.get("plan_sha256") != plan_sha:
        env_error("host broker returned a different preregistration digest")
    try:
        # The host SSH/Slurm transport is bounded at 90s. This wait covers
        # that transport; a timeout is reconciled by the same plan digest and
        # never causes a second submit request.
        submitted = rpc_call("submit_probe", plan_sha, timeout=120)
    except TimeoutError:
        try:
            submitted = rpc_call("status", plan_sha, timeout=30)
        except TimeoutError as exc:
            env_error("submit outcome is unknown and same-plan status could not reconcile: " + str(exc))
        reconciled_states = {"SUBMITTED", "PENDING", "RUNNING", "COMPLETING", "COMPLETED",
                             "FAILED", "TIMEOUT", "OUT_OF_MEMORY", "CANCELLED", "OUTCOME_UNKNOWN"}
        if (submitted.get("status") not in reconciled_states
                or submitted.get("plan_sha256") != plan_sha
                or submitted.get("execution_backend")!="local"
                or not isinstance(submitted.get("execution_id"),str)):
            env_error("submit outcome is unknown; same-plan status did not confirm one local execution; do not resubmit")
    if (submitted.get("status") not in {"SUBMITTED", "PENDING", "RUNNING", "COMPLETING",
                                         "COMPLETED", "FAILED", "TIMEOUT", "OUT_OF_MEMORY", "CANCELLED"}
            or submitted.get("execution_backend")!="local"
            or not isinstance(submitted.get("execution_id"),str)):
        env_error("host dispatch is unavailable or returned no local execution ID")
    terminal = {"COMPLETED", "FAILED", "TIMEOUT", "OUT_OF_MEMORY", "CANCELLED"}
    deadline = time.monotonic() + 16 * 60
    while True:
        status = rpc_call("status", plan_sha, timeout=30)
        if status.get("execution_id") != submitted.get("execution_id"):
            env_error("host status does not reconcile to the single local execution")
        state = status.get("status")
        if state in terminal:
            break
        if state not in {"SUBMITTED", "PENDING", "RUNNING", "COMPLETING", "OUTCOME_UNKNOWN"}:
            env_error("host returned an unsupported job state; the job will not be resubmitted")
        if time.monotonic() >= deadline:
            env_error("same-attempt probe did not reach a terminal state within the bounded wait")
        time.sleep(2.0)

    collected = rpc_call("collect", plan_sha, timeout=120)
    if (collected.get("status") != "READY" or collected.get("plan_sha256") != plan_sha
            or collected.get("job_id") != submitted.get("execution_id")
            or not isinstance(collected.get("runs"), list)
            or not isinstance(collected.get("execution"), dict)):
        env_error("host did not provide a protected same-attempt native collection")
    runs = collected["runs"]
    execution = collected["execution"]
    if ([row.get("pool_index_zero_based") if isinstance(row, dict) else None for row in runs]
            != plan.get("trajectory_indices_zero_based")):
        env_error("collected native run set/order differs from the preregistered plan")
    result = {"schema": "bench25-case04-probe-result/v1",
              "plan_sha256": plan_sha, "runs": runs}
    risk_set = ["energy_force_consistency", "nac_phase_continuity", "low_gap_coupling",
                "ood_coverage", "surface_hop_stability"]
    risk_findings = {}
    for risk in risk_set:
        metrics = [row.get("audited_risk_metrics", {}).get(risk, {}) for row in runs]
        investigated = any(isinstance(item, dict) and item.get("assessment_complete") is True
                           for item in metrics)
        observed = False
        for item in metrics:
            if not isinstance(item, dict):
                continue
            if risk == "energy_force_consistency":
                observed |= item.get("energy_diagnostics_computed") is True
            elif risk == "low_gap_coupling":
                observed |= type(item.get("minimum_adjacent_state_gap_ev")) in (int, float)
            elif risk == "surface_hop_stability":
                observed |= isinstance(item.get("active_surface_indices_zero_based"), list)
        risk_findings[risk] = {"status": ("investigated" if investigated else
                                            "partially_investigated" if observed else "not_assessed")}
    whole_job_success = (execution.get("terminal_status") == "COMPLETED"
                         and execution.get("job_exit_code") == 0
                         and type(execution.get("elapsed_seconds")) is int
                         and 0 <= execution["elapsed_seconds"] <= 300
                         and all(row.get("complete") is True for row in runs))
    drift_exceeded = any(
        type(row.get("max_total_energy_drift_ev")) in (int, float)
        and type(row.get("drift_threshold_ev")) in (int, float)
        and row["max_total_energy_drift_ev"] > row["drift_threshold_ev"] for row in runs)
    if not whole_job_success:
        reason, priority, action = ("execution_incomplete", "execution_integrity",
                                    "reconcile_or_repair_execution")
        rationale = "The fixed probe did not produce a fully successful bounded execution."
        decision_kind = "stop"
    elif drift_exceeded:
        reason, priority, action = ("energy_drift_exceeded", "energy_force_consistency",
                                    "stop_and_diagnose_energy_drift")
        rationale = "The independently audited energy drift exceeded the preregistered diagnostic threshold."
        decision_kind = ("stop" if plan["stop_rules"]["energy_drift"] == "stop" else "diagnose")
    else:
        reason, priority, action = ("force_accuracy_not_sampled", "energy_force_consistency",
                                    "validate_force_accuracy")
        rationale = "The captured short prefix does not measure force prediction error."
        decision_kind = "diagnose"
    summary = []
    for row in runs:
        metrics = row.get("audited_risk_metrics", {})
        low, hops = metrics.get("low_gap_coupling", {}), metrics.get("surface_hop_stability", {})
        summary.append({key: row.get(key) for key in (
            "pool_index_zero_based", "native_records", "observed_end_fs", "complete",
            "max_total_energy_drift_ev", "energy_sha256", "surface_sha256")}
            | {"expec_sha256": low.get("expec_sha256"),
               "minimum_adjacent_state_gap_ev": low.get("minimum_adjacent_state_gap_ev"),
               "pair_time_samples_at_or_below_cutoff": low.get("pair_time_samples_at_or_below_cutoff"),
               "active_surface_switches": hops.get("active_surface_switches")})
    decision = {
        "schema": "bench25-case04-decision/v1",
        "decision": decision_kind,
        "s1_100fs_lifetime_fs": None,
        "lifetime_identifiability": "not_identifiable_from_short_prefix",
        "plan_sha256": plan_sha,
        "probe_result_sha256": hashlib.sha256(json.dumps(
            result, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
            allow_nan=False).encode()).hexdigest(),
        "evidence_summary": summary,
        "actual_resources": {key: (execution.get(key) if key not in {"execution_backend", "execution_id"}
                                      else execution.get({"execution_backend": "backend",
                                                          "execution_id": "execution_id"}[key])) for key in (
            "execution_backend", "execution_id", "slurm_job_id", "terminal_status", "job_exit_code", "elapsed_seconds",
            "allocated_cpus", "requested_memory", "max_rss", "node_list", "account",
            "qos", "partition", "gpu_count", "time_limit_seconds", "software_environment",
            "software_environment_sha256")},
        "risk_findings": risk_findings,
        "reason_code": reason, "priority_risk": priority, "next_action": action,
        "rationale": rationale,
        "limitations": ["A short prefix cannot establish 100 fs lifetime or calibrated reliability."],
    }
    def write_output(name, value):
        target = out / name
        payload = (json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                              allow_nan=False) + "\n").encode()
        fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
    write_output("probe-result.json", result)
    write_output("decision.json", decision)
    print("WROTE_AUDITABLE_PROBE_RESULT_AND_DECISION")
except SystemExit:
    raise
except Exception as exc:
    env_error("case04 host RPC failed: " + type(exc).__name__)
PY
