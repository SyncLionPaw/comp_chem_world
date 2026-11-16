#!/usr/bin/env bash
set -euo pipefail

APP_DIR="${APP:-/app}"
INPUT_DIR="$APP_DIR/inputs"
if [[ ! -d "$INPUT_DIR" ]]; then
  echo "public input directory not found: $INPUT_DIR" >&2
  exit 2
fi

: "${CASE03_CPUS:?Select the CPU count for your configured execution target}"
: "${CASE03_MEMORY_GB:?Select memory in GiB for your configured execution target}"
: "${CASE03_WALL_SECONDS:?Select wall time up to the 1,200-second task budget}"
: "${CASE03_ACCELERATOR:?Select cpu or gpu for your configured execution target}"
: "${CASE03_GPU_COUNT:?Select GPU count consistent with the accelerator}"
cd "$APP_DIR/workspace"
python3 - --app "$APP_DIR" --cpus "$CASE03_CPUS" --memory-gb "$CASE03_MEMORY_GB" \
  --wall-seconds "$CASE03_WALL_SECONDS" --accelerator "$CASE03_ACCELERATOR" \
  --gpu-count "$CASE03_GPU_COUNT" <<'CASE03_SOLVE'
"""Typed candidate client for the fixed Case03 v2 host broker.

The client transfers only fixed-schema JSON frames through the runner's fixed
ordinary-file inbox. It has no SSH, shell, scheduler, path-forwarding, or
arbitrary-command operation. The standard runner installs the typed broker for
Case03 runs. If its fixed host inbox or trusted resources are unavailable, the
client reports ENV2 and never falls back to direct SSH or scheduler access.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import math
import os
import re
import secrets
import stat
import sys
import time
import uuid
from pathlib import Path
from typing import Any, Callable

RPC_DIRECTORY = Path("/run/ccb-hpc")
MAX_MESSAGE = 1_500_000
BASELINE_SHA = "840834c2b94fc2efdb7c454f11a60f5af3bee917f12594e90ad6a82b3155ecc5"
IMAGE = "sha256:112509d5f553824edc7b83fa11d0fc32ead2be995ad1d4aa8f239f7fa115d8c3"
DECISION_POLICY = "adopt_if_ci_lower_positive_guards_pass_and_COM_centered_only_else_retain"
MAX_TRAINING_WAIT_SECONDS = 6 * 60 * 60
ATTEMPT_BUDGET_ENV = "CCB_CASE03_ATTEMPT_BUDGET_SECONDS"
RPC_OPERATION_CAPS = {
    "freeze_hypothesis": 930.0,  # 900s diagnostic subprocess plus bounded response/cleanup.
    "launch_training": 315.0,  # 300s one-shot upload/submit transaction plus response margin.
    "training_status": 615.0,  # 600s terminal capture maximum plus response margin.
    "score_once": 120.0,
    "get_cached_feedback": 120.0,
    "freeze_decision": 120.0,
}
POLL_STATUSES = {
    "PENDING", "RUNNING", "CONFIGURING", "COMPLETING", "SUSPENDED",
    "SUBMISSION_UNKNOWN_RECONCILING", "RECONCILING", "ACCOUNTING_UNAVAILABLE",
    "SCHEDULER_STATUS_UNKNOWN", "TERMINAL_EVIDENCE_INCOMPLETE",
}


class ClientEnvironmentError(RuntimeError):
    pass


class ClientCandidateError(ValueError):
    pass


def canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False).encode("utf-8")


def digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def strict_json(raw: bytes, label: str) -> dict[str, Any]:
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate JSON key")
            result[key] = value
        return result

    def finite_float(token):
        value = float(token)
        if not math.isfinite(value):
            raise ValueError("non-finite JSON number")
        return value

    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=unique, parse_float=finite_float,
                           parse_constant=lambda _x: (_ for _ in ()).throw(ValueError("non-finite number")))
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise ClientCandidateError(f"{label} is not strict finite JSON") from exc
    if not isinstance(value, dict):
        raise ClientCandidateError(f"{label} must be a JSON object")
    return value


def _write_new(path: Path, raw: bytes, mode: int = 0o600) -> None:
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), mode)
    try:
        view = memoryview(raw)
        while view:
            n = os.write(fd, view)
            view = view[n:]
        os.fsync(fd)
    finally:
        os.close(fd)


def ensure_hypothesis(output_dir: Path, input_root: Path) -> bytes:
    """Create one fixed, public-evidence H if the candidate has not authored it."""
    if output_dir.is_symlink():
        raise ClientCandidateError("outputs directory cannot be a symlink")
    if not output_dir.exists():
        output_dir.mkdir(mode=0o700, parents=False)
    if not output_dir.is_dir() or output_dir.stat().st_mode & 0o077:
        raise ClientCandidateError("outputs directory must be private mode 0700")
    target = output_dir / "hypothesis.json"
    if target.exists() or target.is_symlink():
        st = target.lstat()
        if not stat.S_ISREG(st.st_mode) or target.is_symlink() or st.st_nlink != 1 or st.st_size > 32 * 1024:
            raise ClientCandidateError("existing hypothesis.json is unsafe")
        raw = target.read_bytes()
    else:
        # Compute these from the pinned public training/validation data and
        # baseline. The host independently recomputes them before accepting H.
        try:
            evidence = _evidence_compute_public_evidence(input_root)
        except Exception as exc:
            raise ClientEnvironmentError(f"public hypothesis evidence could not be recomputed: {exc}") from exc
        hypothesis = {
            "schema": "case03-hypothesis/v2", "case_id": "case-03",
            "baseline_sha256": BASELINE_SHA, "model": "painn", "intervention": "nac_head_only",
            "primary_stratum": "low_gap", "expected_delta_sign": "uncertain",
            "application_scope": "COM_centered_only",
            "public_evidence": evidence,
            "decision_policy_id": DECISION_POLICY,
            "predeclared_stop_condition": "retain_if_ci_lower_not_positive_or_registered_guard_fails",
            "primary_risk": "painn_origin_dependent_nac",
        }
        raw = json.dumps(hypothesis, sort_keys=True, separators=(",", ":"), allow_nan=False).encode() + b"\n"
        _write_new(target, raw)
    value = strict_json(raw, "hypothesis.json")
    required = {"schema", "case_id", "baseline_sha256", "model", "intervention", "primary_stratum",
                "expected_delta_sign", "application_scope", "public_evidence", "decision_policy_id",
                "predeclared_stop_condition", "primary_risk"}
    if set(value) != required or value.get("schema") != "case03-hypothesis/v2":
        raise ClientCandidateError("hypothesis.json differs from the Case03 v2 H contract")
    return raw


def _read_bounded_regular(path: Path, limit: int) -> bytes:
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    fd = os.open(path, flags)
    with os.fdopen(fd, "rb") as stream:
        before = os.fstat(stream.fileno())
        # The host publishes by hard-linking a fully fsynced temporary file
        # and then unlinking that temporary name. A brief nlink=2 window is
        # expected; wait for the completed single-link publication below.
        if stat.S_ISREG(before.st_mode) and before.st_nlink == 2:
            raise BlockingIOError("host RPC response publication is in progress")
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1 or before.st_size > limit:
            raise ClientEnvironmentError("host RPC response is not a bounded regular file")
        raw = stream.read(limit + 1)
        after = os.fstat(stream.fileno())
        current = path.lstat()
        identity = (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
        if (len(raw) != before.st_size or len(raw) > limit
                or identity != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)
                or (current.st_dev, current.st_ino) != (after.st_dev, after.st_ino)):
            raise ClientEnvironmentError("host RPC response changed while being read")
        return raw


def make_file_rpc(inbox: Path = RPC_DIRECTORY, timeout: float | None = None,
                  poll_interval: float = 0.05) -> Callable:
    """Use the runner's ordinary-file RPC mount; Docker Desktop cannot bind AF_UNIX."""
    if timeout is None:
        raw_budget = os.environ.get(ATTEMPT_BUDGET_ENV)
        try:
            attempt_budget = float(raw_budget) if raw_budget is not None else float("nan")
        except (TypeError, ValueError):
            attempt_budget = float("nan")
        if not math.isfinite(attempt_budget) or attempt_budget <= 0:
            raise ClientEnvironmentError("runner did not provide a valid Case03 attempt budget")
    else:
        if (isinstance(timeout, bool) or not isinstance(timeout, (int, float))
                or not math.isfinite(timeout) or timeout <= 0):
            raise ClientEnvironmentError("explicit Case03 RPC test timeout is invalid")
        attempt_budget = float(timeout)
    attempt_deadline = time.monotonic() + attempt_budget

    def call(operation: str, payload: dict[str, Any]) -> dict[str, Any]:
        if operation not in {"freeze_hypothesis", "launch_training", "training_status",
                             "score_once", "get_cached_feedback", "freeze_decision"}:
            raise ClientEnvironmentError("unsupported typed host operation")
        request = {"schema": "case03-v2-host-rpc-request/v1", "request_id": uuid.uuid4().hex,
                   "operation": operation, "payload": payload}
        raw = canonical(request) + b"\n"
        if len(raw) > MAX_MESSAGE:
            raise ClientEnvironmentError("typed host request exceeds the fixed size cap")
        try:
            st = inbox.lstat()
            if stat.S_ISLNK(st.st_mode) or not stat.S_ISDIR(st.st_mode) or st.st_mode & 0o077:
                raise ClientEnvironmentError("fixed host RPC inbox is not a private directory")
        except FileNotFoundError as exc:
            raise ClientEnvironmentError("reviewed Case03 v2 typed host file broker is unavailable") from exc
        request_path = inbox / f"{request['request_id']}.request.json"
        response_path = inbox / f"{request['request_id']}.response.json"
        temp_path = inbox / f".{request['request_id']}.{secrets.token_hex(8)}.tmp"
        fd = os.open(temp_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL |
                     getattr(os, "O_NOFOLLOW", 0), 0o600)
        try:
            with os.fdopen(fd, "wb") as stream:
                stream.write(raw)
                stream.flush()
                os.fsync(stream.fileno())
            os.link(temp_path, request_path, follow_symlinks=False)
        finally:
            temp_path.unlink(missing_ok=True)
        remaining_attempt = attempt_deadline - time.monotonic()
        if remaining_attempt <= 0:
            raise ClientEnvironmentError("Case03 runner attempt deadline expired")
        deadline = time.monotonic() + min(RPC_OPERATION_CAPS[operation], remaining_attempt)
        response_raw = None
        while time.monotonic() < deadline:
            try:
                response_raw = _read_bounded_regular(response_path, MAX_MESSAGE)
                break
            except (FileNotFoundError, BlockingIOError):
                time.sleep(min(poll_interval, max(0.0, deadline - time.monotonic())))
            except OSError as exc:
                raise ClientEnvironmentError(f"typed host file RPC failed ({type(exc).__name__})") from exc
        if response_raw is None:
            # Preserve the unresolved request as evidence. Never create a new
            # ID/retry a potentially mutating launch or score phase.
            raise ClientEnvironmentError(f"typed host request unresolved; request_id={request['request_id']}")
        try:
            response = strict_json(response_raw, "host RPC response")
        except ClientCandidateError as exc:
            raise ClientEnvironmentError(str(exc)) from exc
        if (set(response) != {"schema", "request_id", "status", "payload"}
                or response.get("schema") != "case03-v2-host-rpc-response/v1"
                or response.get("request_id") != request["request_id"]
                or not isinstance(response.get("status"), str)
                or not isinstance(response.get("payload"), dict)):
            raise ClientEnvironmentError("host RPC response does not match the typed envelope")
        if response["status"] == "CANDIDATE_INVALID":
            raise ClientCandidateError("host rejected a candidate-authored artifact")
        request_path.unlink(missing_ok=True)
        response_path.unlink(missing_ok=True)
        return response
    call.remaining_seconds = lambda: max(0.0, attempt_deadline - time.monotonic())
    return call


def _call(rpc: Callable, operation: str, payload: dict[str, Any], allowed: set[str]) -> dict[str, Any]:
    response = rpc(operation, payload)
    if not isinstance(response, dict) or response.get("status") not in allowed:
        raise ClientEnvironmentError(f"host RPC returned an invalid {operation} state")
    return response


def build_decision(hypothesis: dict[str, Any], request: dict[str, Any], aggregate_raw: bytes) -> bytes:
    aggregate = strict_json(aggregate_raw, "score-feedback.json")
    required = {"schema", "attempt_id", "lock_sha256", "hypothesis_sha256", "primary_stratum", "n",
                "baseline_primary_nac_mae_au", "tuned_primary_nac_mae_au", "mean_delta_baseline_minus_tuned_au",
                "bootstrap_replicates", "bootstrap_seed", "energy_mae_delta_ev",
                "force_mae_delta_ev_angstrom", "gap_mae_delta_ev",
                "paired_percentile_95_ci_au", "energy_output_max_abs_delta_ha",
                "force_output_max_abs_delta_ha_per_bohr", "gap_output_max_abs_delta_ha",
                "rotation_nac_residual_max_abs_per_bohr", "permutation_nac_residual_max_abs_per_bohr",
                "translation_origin_term_residual_max_abs_ha_per_bohr", "elapsed_before_decision_seconds",
                "scoring_seconds", "budget_cap_seconds", "score_invocation_id", "score_receipt_sha256",
                "energy_guard_pass", "force_guard_pass", "gap_guard_pass", "rotation_guard_pass",
                "permutation_guard_pass", "origin_term_guard_pass", "budget_guard_pass", "aggregate_sha256"}
    if (set(aggregate) != required or aggregate.get("schema") != "case03-private-aggregate/v2"
            or aggregate.get("attempt_id") != request.get("attempt_id")
            or aggregate.get("lock_sha256") != request.get("lock_sha256")
            or aggregate.get("hypothesis_sha256") != request.get("hypothesis_sha256")
            or aggregate.get("primary_stratum") != hypothesis.get("primary_stratum")):
        raise ClientEnvironmentError("trusted feedback does not bind the frozen hypothesis/request")
    # aggregate_sha256 pins its canonical semantic projection. D separately
    # binds the exact immutable feedback file bytes used by the candidate.
    clean = dict(aggregate)
    aggregate_sha = clean.pop("aggregate_sha256")
    if not isinstance(aggregate_sha, str) or digest(canonical(clean)) != aggregate_sha:
        raise ClientEnvironmentError("trusted feedback digest is invalid")
    numeric = (aggregate.get("mean_delta_baseline_minus_tuned_au"), *aggregate.get("paired_percentile_95_ci_au", []),
               aggregate.get("energy_output_max_abs_delta_ha"), aggregate.get("force_output_max_abs_delta_ha_per_bohr"),
               aggregate.get("gap_output_max_abs_delta_ha"))
    if any(isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value)
           for value in numeric) or len(aggregate["paired_percentile_95_ci_au"]) != 2:
        raise ClientEnvironmentError("trusted feedback contains invalid quantitative fields")
    low, high = aggregate["paired_percentile_95_ci_au"]
    if low > high:
        raise ClientEnvironmentError("trusted feedback interval is reversed")
    finding = "improved" if low > 0 else "degraded" if high < 0 else "inconclusive"
    guards = all(aggregate[key] is True for key in (
        "energy_guard_pass", "force_guard_pass", "gap_guard_pass", "rotation_guard_pass",
        "permutation_guard_pass", "origin_term_guard_pass", "budget_guard_pass"))
    if not guards:
        # Record the measured result honestly. The host grader assigns FAIL
        # because a registered guard failed; the client does not claim PASS.
        action = "retain"
    else:
        action = "adopt_restricted" if finding == "improved" and hypothesis["application_scope"] == "COM_centered_only" else "retain"
    mean = float(aggregate["mean_delta_baseline_minus_tuned_au"])
    observed = "positive" if mean > 1e-12 else "negative" if mean < -1e-12 else "uncertain"
    expected = hypothesis["expected_delta_sign"]
    prediction = "not_applicable" if expected == "uncertain" else "matched" if expected == observed else "not_matched"
    primary_reason = "ci_lower_positive" if finding == "improved" else "ci_upper_negative" if finding == "degraded" else "ci_crosses_zero"
    decision_reason = ("positive_ci_and_scope_guards" if action == "adopt_restricted" else
                       "origin_scope_not_supported" if hypothesis["application_scope"] != "COM_centered_only" else
                       "retain_per_preregistered_rule")
    reasons = {primary_reason, "registered_guards_pass" if guards else "registered_guards_failed",
               "painn_translation_origin_dependent", decision_reason}
    if hypothesis["application_scope"] != "COM_centered_only":
        next_computation = "origin_safe_nac_architecture"
    else:
        next_computation = "diagnostic_ablation"
    decision = {
        "schema": "case03-final-decision/v2", "case_id": "case-03",
        "attempt_id": request["attempt_id"], "hypothesis_sha256": request["hypothesis_sha256"],
        "lock_sha256": request["lock_sha256"], "aggregate_sha256": digest(aggregate_raw),
        "reported_primary_n": aggregate["n"],
        "reported_mean_delta_baseline_minus_tuned_au": aggregate["mean_delta_baseline_minus_tuned_au"],
        "reported_percentile_95_ci_au": aggregate["paired_percentile_95_ci_au"],
        "reported_energy_output_max_abs_delta_ha": aggregate["energy_output_max_abs_delta_ha"],
        "reported_force_output_max_abs_delta_ha_per_bohr": aggregate["force_output_max_abs_delta_ha_per_bohr"],
        "reported_gap_output_max_abs_delta_ha": aggregate["gap_output_max_abs_delta_ha"],
        "finding": finding, "action": action, "reason_codes": sorted(reasons),
        "prior_prediction_assessment": prediction, "acknowledged_primary_risk": hypothesis["primary_risk"],
        "claim_scope": "selected_stratum_COM_centered_single_run",
        "limitations": sorted(["selected_stratum_only", "descriptive_paired_resampling",
                                "single_finetune_attempt", "not_long_time_dynamics_validation",
                                "painn_translation_origin_dependence"]),
        "next_computation": next_computation, "next_computation_budget_minutes": 30,
    }
    return json.dumps(decision, sort_keys=True, separators=(",", ":"), allow_nan=False).encode() + b"\n"


def run_attempt(app_dir: Path, *, resource_request: dict[str, Any],
                rpc: Callable | None = None, poll_interval: float = 5.0,
                max_wait_seconds: float = MAX_TRAINING_WAIT_SECONDS,
                feedback_path: Path | None = None) -> dict[str, Any]:
    output_dir = app_dir / "outputs"
    runtime_inputs = app_dir / "inputs"
    if not runtime_inputs.is_dir():
        raise ClientEnvironmentError("public /app/inputs are unavailable")
    h_raw = ensure_hypothesis(output_dir, runtime_inputs)
    # Local public-only structure validation is not trusted scoring.
    verify_path = app_dir / "tests" / "verify.py"
    if verify_path.is_file():
        import importlib.util
        spec = importlib.util.spec_from_file_location("case03_solve_verify", verify_path)
        verifier = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(verifier)
        verifier.validate_public_outputs(output_dir, "hypothesis")
    rpc = rpc or make_file_rpc()

    if (not isinstance(resource_request, dict)
            or set(resource_request) != {"cpus", "memory_gb", "wall_seconds", "accelerator", "gpu_count"}):
        raise ClientEnvironmentError("an explicit exact resource request is required")
    frozen = _call(rpc, "freeze_hypothesis", {"hypothesis_b64": base64.b64encode(h_raw).decode("ascii"),
                                               "resource_request": resource_request},
                   {"PRELAUNCH_FROZEN"})
    payload = frozen.get("payload", {})
    attempt_id = payload.get("attempt_id")
    if not isinstance(attempt_id, str) or re.fullmatch(r"[A-Za-z0-9_-]{8,64}", attempt_id) is None:
        raise ClientEnvironmentError("host did not return a valid runner attempt ID")
    request_path = output_dir / "strategy_request.json"
    if request_path.is_symlink() or not request_path.is_file():
        raise ClientEnvironmentError("host did not materialize its strategy_request.json")
    request_raw = request_path.read_bytes()
    request = strict_json(request_raw, "strategy_request.json")
    if (request.get("schema") != "case03-strategy-request/v3"
            or request.get("attempt_id") != attempt_id
            or request.get("hypothesis_sha256") != digest(h_raw)
            or request.get("lock_sha256") != payload.get("lock_sha256")
            or request.get("resource_request") != resource_request
            or payload.get("resource_request") != resource_request):
        raise ClientEnvironmentError("host-generated request is not bound to the frozen H/attempt")

    launched = _call(rpc, "launch_training", {"attempt_id": attempt_id},
                     {"SUBMITTED", "RUNNING", "SUBMISSION_UNKNOWN"})
    if launched.get("payload", {}).get("attempt_id") != attempt_id:
        raise ClientEnvironmentError("host launch response changed the selected attempt")
    if isinstance(max_wait_seconds, bool) or not isinstance(max_wait_seconds, (int, float)) or max_wait_seconds <= 0:
        raise ClientEnvironmentError("training wait limit is invalid")
    attempt_remaining = getattr(rpc, "remaining_seconds", None)
    wait_budget = min(float(max_wait_seconds), attempt_remaining()) if callable(attempt_remaining) else float(max_wait_seconds)
    if wait_budget <= 0:
        raise ClientEnvironmentError("Case03 runner attempt deadline expired before training polling")
    deadline = time.monotonic() + wait_budget
    while True:
        status = _call(rpc, "training_status", {"attempt_id": attempt_id},
                       POLL_STATUSES | {"TRAINING_COMPLETE", "TERMINAL_NONZERO",
                                        "TERMINAL_BUDGET_OVERRUN", "ENV2"})
        state = status["status"]
        if state == "TRAINING_COMPLETE":
            break
        if state == "TERMINAL_NONZERO":
            raise ClientCandidateError("the one trusted training job ended with a nonzero Slurm result")
        if state == "TERMINAL_BUDGET_OVERRUN":
            raise ClientCandidateError("the one trusted training job exceeded a measured phase budget")
        if state == "ENV2":
            raise ClientEnvironmentError("trusted training phase lacks valid same-attempt evidence")
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise ClientEnvironmentError("Case03 runner attempt deadline expired during training polling; do not resubmit")
        time.sleep(min(max(0.1, poll_interval), remaining))
    # Exact four-file inventory is required before consuming the single score.
    expected_training = {"hypothesis.json", "strategy_request.json", "training_report.json", "model_state_dict.pt"}
    if {p.name for p in output_dir.iterdir()} != expected_training:
        raise ClientCandidateError("host training artifacts differ from the fixed four-file pre-score set")

    score = _call(rpc, "score_once", {"attempt_id": attempt_id}, {"AGGREGATE_PUBLISHED"})
    if score.get("payload", {}).get("attempt_id") != attempt_id:
        raise ClientEnvironmentError("score invocation response changed the selected attempt")
    feedback_response = _call(rpc, "get_cached_feedback", {"attempt_id": attempt_id}, {"AGGREGATE_PUBLISHED"})
    try:
        feedback = base64.b64decode(feedback_response["payload"]["aggregate_b64"], validate=True)
    except (KeyError, ValueError, TypeError) as exc:
        raise ClientEnvironmentError("host did not return the cached sanitized aggregate") from exc
    aggregate = strict_json(feedback, "score feedback")
    expected_feedback_sha = score.get("payload", {}).get("aggregate_sha256")
    if (not isinstance(expected_feedback_sha, str)
            or re.fullmatch(r"[0-9a-f]{64}", expected_feedback_sha) is None
            or digest(feedback) != expected_feedback_sha):
        raise ClientEnvironmentError("cached feedback bytes differ from the one-shot score receipt")
    target_feedback = feedback_path or (app_dir / "workspace" / ".case03-score-feedback.json")
    if target_feedback.exists() or target_feedback.is_symlink():
        raise ClientCandidateError("refusing to overwrite an existing score feedback handoff")
    _write_new(target_feedback, feedback)

    h = strict_json(h_raw, "hypothesis.json")
    decision = build_decision(h, request, feedback)
    _write_new(output_dir / "final_decision.json", decision)
    if {p.name for p in output_dir.iterdir()} != {"hypothesis.json", "strategy_request.json", "training_report.json",
                                                   "model_state_dict.pt", "final_decision.json"}:
        raise ClientCandidateError("final candidate artifact inventory differs from the five-file v2 contract")
    frozen_decision = _call(rpc, "freeze_decision", {
        "attempt_id": attempt_id, "final_decision_b64": base64.b64encode(decision).decode("ascii")},
        {"DECISION_FROZEN"})
    if frozen_decision.get("payload", {}).get("attempt_id") != attempt_id:
        raise ClientEnvironmentError("host did not freeze the decision for the selected attempt")
    return {"status": "DECISION_FROZEN", "attempt_id": attempt_id,
            "decision_sha256": digest(decision), "aggregate_sha256": digest(feedback)}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--app", type=Path, default=Path.cwd())
    parser.add_argument("--cpus", type=int, required=True)
    parser.add_argument("--memory-gb", type=int, required=True)
    parser.add_argument("--wall-seconds", type=int, required=True)
    parser.add_argument("--accelerator", choices=("cpu", "gpu"), required=True)
    parser.add_argument("--gpu-count", type=int, required=True)
    args = parser.parse_args()
    try:
        result = run_attempt(args.app.absolute(), resource_request={
            "cpus": args.cpus, "memory_gb": args.memory_gb, "wall_seconds": args.wall_seconds,
            "accelerator": args.accelerator, "gpu_count": args.gpu_count})
    except ClientCandidateError as exc:
        print(f"CANDIDATE_FAIL: {exc}", file=sys.stderr)
        return 1
    except (ClientEnvironmentError, OSError, ValueError, KeyError, TypeError) as exc:
        print(f"ENV2: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0

# Public evidence helper, statically merged with a prefixed namespace.
import hashlib
import math
import tempfile
from pathlib import Path
from typing import Any, Callable

import numpy as np

_EVIDENCE_TRAINVAL_SHA256 = "f9035b3ed2b0a89b75e65d594095a6ba3ca6a598ede3f015b31a81bbed9c1634"
_EVIDENCE_BASELINE_SHA256 = "840834c2b94fc2efdb7c454f11a60f5af3bee917f12594e90ad6a82b3155ecc5"
_EVIDENCE_PUBLIC_MANIFEST_SHA256 = "73b3166d6617dc8f76997f4b303a5c08668a4cba943d943e82c4a516744838a7"
_EVIDENCE_CUTOFF_BOHR = 10.0
_EVIDENCE_PHASES = np.asarray([[1, 1, 1], [-1, 1, -1], [1, -1, -1], [-1, -1, 1]], dtype=np.float64)


class _EvidencePublicEvidenceError(RuntimeError):
    pass


def _evidence_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def _evidence_derive_public_evidence(train_energy: np.ndarray, val_energy: np.ndarray,
                           predicted_nac: np.ndarray, reference_nac: np.ndarray,
                           *, tie_band: float = 1e-9) -> dict[str, Any]:
    """Derive low-gap counts and phase-aligned metrics from supplied arrays."""
    train_energy = np.asarray(train_energy, dtype=np.float64).reshape(-1, 3)
    val_energy = np.asarray(val_energy, dtype=np.float64).reshape(-1, 3)
    predicted_nac = np.asarray(predicted_nac, dtype=np.float64).reshape(-1, 6, 3, 3)
    reference_nac = np.asarray(reference_nac, dtype=np.float64).reshape(-1, 6, 3, 3)
    if (len(train_energy) != 4499 or len(val_energy) != 500
            or len(predicted_nac) != 500 or len(reference_nac) != 500
            or not all(np.isfinite(x).all() for x in (train_energy, val_energy, predicted_nac, reference_nac))):
        raise _EvidencePublicEvidenceError("public evidence arrays do not match the frozen finite split")
    train_gaps = np.column_stack((train_energy[:, 0] - train_energy[:, 1],
                                  train_energy[:, 0] - train_energy[:, 2],
                                  train_energy[:, 1] - train_energy[:, 2]))
    threshold = float(np.percentile(np.min(np.abs(train_gaps), axis=1), 10))
    val_gaps = np.column_stack((val_energy[:, 0] - val_energy[:, 1],
                                val_energy[:, 0] - val_energy[:, 2],
                                val_energy[:, 1] - val_energy[:, 2]))
    low = np.min(np.abs(val_gaps), axis=1) <= threshold
    if not low.any():
        raise _EvidencePublicEvidenceError("public low-gap validation stratum is empty")
    # Select one allowed global three-state gauge per structure by the same
    # tensor L2 rule as the trusted protocol, then report elementwise MAE.
    residual = predicted_nac[:, None] * _EVIDENCE_PHASES[None, :, None, :, None] - reference_nac[:, None]
    phase = np.argmin(np.sum(residual ** 2, axis=(2, 3, 4)), axis=1)
    aligned = predicted_nac * _EVIDENCE_PHASES[phase][:, None, :, None]
    row_mae = np.mean(np.abs(aligned - reference_nac), axis=(1, 2, 3))
    primary = float(np.mean(row_mae[low]))
    all_validation = float(np.mean(row_mae))
    return {
        "split": "train=first4499,val=last500", "rule_id": "train_p10_gap",
        "n": int(low.sum()), "baseline_primary_nac_mae_au": primary,
        "baseline_all_validation_nac_mae_au": all_validation,
        "diagnosis": "enriched" if primary - all_validation > tie_band else "not_enriched",
    }


def _evidence_build_model():
    import schnetpack as spk
    import spainn
    basis = spk.nn.GaussianRBF(n_rbf=50, cutoff=_EVIDENCE_CUTOFF_BOHR)
    cutoff = spk.nn.CosineCutoff(_EVIDENCE_CUTOFF_BOHR)
    representation = spk.representation.PaiNN(n_atom_basis=256, n_interactions=3,
        radial_basis=basis, cutoff_fn=cutoff, shared_interactions=False, shared_filters=False)
    outputs = [
        spainn.Atomwise(n_in=256, n_out=3, n_hidden=256, n_layers=3,
            aggregation_mode="sum", output_key="energy"),
        spainn.Forces(energy_key="energy", force_key="forces"),
        spainn.Nacs(n_in=256, n_out=3, n_hidden=256, n_layers=3,
                    nac_key="smooth_nacs", use_vector_repr=True),
    ]
    return spk.model.NeuralNetworkPotential(representation=representation,
        input_modules=[spk.atomistic.PairwiseDistances()], output_modules=outputs, do_postprocessing=False)


def _evidence_compute_public_evidence(input_root: Path, *, predictor: Callable | None = None) -> dict[str, Any]:
    """Infer the pinned baseline on public validation; never reads heldout labels."""
    input_root = Path(input_root)
    trainval = input_root / "trainval_shifted.db"
    baseline = input_root / "painn_baseline_state_dict.pt"
    manifest = input_root / "public_asset_manifest.json"
    if any(path.is_symlink() or not path.is_file() for path in (trainval, baseline, manifest)):
        raise _EvidencePublicEvidenceError("pinned public evidence input is missing or symlinked")
    if (_evidence_sha256(trainval) != _EVIDENCE_TRAINVAL_SHA256 or _evidence_sha256(baseline) != _EVIDENCE_BASELINE_SHA256
            or _evidence_sha256(manifest) != _EVIDENCE_PUBLIC_MANIFEST_SHA256):
        raise _EvidencePublicEvidenceError("public evidence input differs from the task pins")
    import torch
    import schnetpack as spk
    import spainn
    from ase.db import connect
    from schnetpack.transform import MatScipyNeighborList
    with connect(str(trainval), use_lock_file=False) as db:
        rows = list(db.select())
    if len(rows) != 4999:
        raise _EvidencePublicEvidenceError("public train/validation row count differs from the frozen split")
    train, val = rows[:4499], rows[4499:]
    train_energy = np.stack([np.asarray(row.data["energy"], dtype=np.float64).reshape(3) for row in train])
    val_energy = np.stack([np.asarray(row.data["energy"], dtype=np.float64).reshape(3) for row in val])
    val_nac = np.stack([np.asarray(row.data["nacs"], dtype=np.float64).reshape(6, 3, 3) for row in val])
    if not all(np.isfinite(x).all() for x in (train_energy, val_energy, val_nac)):
        raise _EvidencePublicEvidenceError("public validation labels contain nonfinite values")
    if predictor is not None:
        predicted_nac = predictor(train, val, baseline)
    else:
        with tempfile.TemporaryDirectory(prefix="case03-public-hypothesis-") as temp:
            work = Path(temp)
            geometry_db = work / "validation-geometry.db"
            with connect(str(geometry_db)) as db:
                for row in val:
                    atoms = row.toatoms()
                    db.write(atoms, data={"energy": np.zeros(3).tolist(),
                        "forces": np.zeros((6, 3, 3)).tolist(),
                        "nacs": np.zeros((6, 3, 3)).tolist(),
                        "smooth_nacs": np.zeros((6, 3, 3)).tolist()})
                db.metadata = {"_distance_unit": "Bohr", "_property_unit_dict": {
                    "energy": "Hartree", "forces": "Hartree/Bohr",
                    "nacs": "1/Bohr", "smooth_nacs": "Hartree/Bohr"}}
            split = work / "split.npz"
            np.savez(split, train_idx=np.asarray([], dtype=np.int64), val_idx=np.asarray([], dtype=np.int64),
                     test_idx=np.arange(len(val), dtype=np.int64))
            dm = spainn.SPAINN(n_states=3, n_nacs=3, datapath=str(geometry_db), split_file=str(split),
                num_train=0, num_val=0, num_test=len(val), batch_size=32, val_batch_size=32,
                test_batch_size=32, num_workers=0, num_val_workers=0, num_test_workers=0,
                load_properties=["energy", "forces", "smooth_nacs"], distance_unit="Bohr",
                property_units={"energy": "Hartree", "forces": "Hartree/Bohr", "smooth_nacs": "Hartree/Bohr"},
                transforms=[MatScipyNeighborList(cutoff=_EVIDENCE_CUTOFF_BOHR), spk.transform.CastTo32()], pin_memory=False)
            dm.setup("test")
            torch.set_num_threads(1)
            torch.manual_seed(20261007)
            model = _evidence_build_model()
            try:
                payload = torch.load(baseline, map_location="cpu", weights_only=True)
            except Exception as exc:
                raise _EvidencePublicEvidenceError("public baseline weights-only load failed") from exc
            state = payload.get("state_dict") if isinstance(payload, dict) and set(payload) == {"state_dict"} else payload
            expected = model.state_dict()
            if (not isinstance(state, dict) or set(state) != set(expected)
                    or any(not isinstance(v, torch.Tensor) or v.shape != expected[k].shape
                           or v.dtype != expected[k].dtype for k, v in state.items())
                    or any(not bool(torch.isfinite(value).all()) for value in state.values()
                           if isinstance(value, torch.Tensor) and value.is_floating_point())):
                raise _EvidencePublicEvidenceError("public baseline differs from the fixed PaiNN model")
            model.load_state_dict(state, strict=True)
            model.eval()
            predicted_energy = np.empty((len(val), 3), dtype=np.float64)
            predicted_smooth = np.empty((len(val), 6, 3, 3), dtype=np.float64)
            seen = np.zeros(len(val), dtype=bool)
            # Forces differentiates energy, so inference must retain autograd.
            for batch in dm.test_dataloader():
                idx = batch.get("_idx")
                if not isinstance(idx, torch.Tensor):
                    raise _EvidencePublicEvidenceError("validation inference omitted row indices")
                indices = idx.detach().cpu().numpy().astype(np.int64)
                with torch.enable_grad():
                    output = model({key: value.clone() if isinstance(value, torch.Tensor) else value
                                    for key, value in batch.items()})
                if any(key not in output or not bool(torch.isfinite(output[key]).all())
                       for key in ("energy", "forces", "smooth_nacs")):
                    raise _EvidencePublicEvidenceError("baseline produced missing or nonfinite outputs")
                energy = output["energy"].detach().cpu().double().numpy()
                smooth = output["smooth_nacs"].detach().cpu().double().numpy().reshape(-1, 6, 3, 3)
                if (np.any(indices < 0) or np.any(indices >= len(val)) or np.any(seen[indices])
                        or not np.isfinite(energy).all() or not np.isfinite(smooth).all()):
                    raise _EvidencePublicEvidenceError("validation inference produced invalid outputs/indices")
                predicted_energy[indices] = energy
                predicted_smooth[indices] = smooth
                seen[indices] = True
            if not seen.all():
                raise _EvidencePublicEvidenceError("validation inference did not cover every row")
            gaps = np.column_stack((predicted_energy[:, 0] - predicted_energy[:, 1],
                                    predicted_energy[:, 0] - predicted_energy[:, 2],
                                    predicted_energy[:, 1] - predicted_energy[:, 2]))
            if not np.isfinite(gaps).all() or np.any(gaps == 0):
                raise _EvidencePublicEvidenceError("baseline predicted zero or nonfinite state gaps")
            predicted_nac = predicted_smooth / gaps[:, None, :, None]
    return _evidence_derive_public_evidence(train_energy, val_energy, predicted_nac, val_nac)

if __name__ == "__main__":
    raise SystemExit(main())
CASE03_SOLVE
