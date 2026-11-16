"""Harbor-native private review adapter for Bench07.

The adapter only returns a fully validated scientific-review payload. The caller
owns the unchanged verifier/final-grade stage and must grant its tests view as
read-only. No reward is created here.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any

from .evidence_tools import EvidenceTools
from .judge_client import JudgeConfig, JudgeError, MessagesJudge
from .references import (
    document_bytes,
    document_pointer,
    normalized_protocol,
    reference_data_view,
    reference_manifest_entries,
)
from .pure_helpers import (
    EvaluationError,
    _all_pass_evidence_requirements,
    _coverage_feedback,
    _has_required_all_pass_evidence,
    _manifest_outputs,
    _required_criteria,
    _system_prompt,
    json_hash,
    sha_file,
    validate_review_payload,
)



def _judge_config_from_env() -> JudgeConfig:
    """Build the reviewer client only from operator-supplied verifier settings."""
    api_key = os.environ.get("BENCH07_REVIEW_API_KEY", "").strip()
    base_url = os.environ.get("BENCH07_REVIEW_BASE_URL", "").strip()
    model = os.environ.get("BENCH07_REVIEW_MODEL", "").strip()
    if not api_key or not base_url or not model:
        raise JudgeError("BENCH07_REVIEW_API_KEY, BENCH07_REVIEW_BASE_URL and BENCH07_REVIEW_MODEL are required; no review request was made")
    return JudgeConfig(
        model_alias=model, model_id=model, provider="anthropic-compatible",
        api_key=api_key, base_url=base_url,
        secret_names=("BENCH07_REVIEW_API_KEY",),
    )


class ReviewAbstained(EvaluationError):
    """The judge explicitly abstained; no scientific reward is available."""
_CASES = {
    "reline-01-train": "case-01-train",
    "reline-02-density": "case-02-density",
    "reline-03-force-trust-audit": "case-03-force-trust-audit",
    "reline-04-diffusion": "case-04-diffusion",
    "reline-05-collective": "case-05-collective",
    "reline-06-ne-audit": "case-06-ne-audit",
    "reline-07-holy-grail": "case-07-holy-grail",
}
_REVIEW_CASES = {
    "case-01-train", "case-04-diffusion", "case-05-collective",
    "case-06-ne-audit", "case-07-holy-grail",
}


def _as_mapping(value: Any) -> dict[str, Any] | None:
    return value if isinstance(value, dict) else None


def _load_report(initial_report: Any, logs: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    report = _as_mapping(initial_report)
    if report is None:
        raise EvaluationError("initial Harbor report is unavailable")
    verification = report.get("verification")
    if not isinstance(verification, dict):
        verification = report
    # If the report carries only the high-level result, require the verifier's
    # structured artifact from the attempt log directory to bind diagnostics.
    if not isinstance(verification.get("diagnostics"), dict):
        for candidate in (
            logs / "verification.json",
            logs / "verifier-logs" / "verification.json",
            logs / "tests" / "verification.json",
        ):
            if candidate.is_file() and not candidate.is_symlink():
                loaded = json.loads(candidate.read_text(encoding="utf-8"))
                if isinstance(loaded, dict):
                    verification = loaded
                    break
    return report, verification


def _trusted_references(task_root: Path, metadata: dict[str, Any]) -> dict[str, Any]:
    selected = {"task.toml", "instruction.md"}
    if (task_root / "instruction.zh-CN.md").is_file():
        selected.add("instruction.zh-CN.md")
    inputs = metadata.get("requirements", {}).get("inputs", []) if isinstance(metadata.get("requirements", {}), dict) else []
    for row in inputs:
        if not isinstance(row, dict):
            continue
        raw = row.get("path") or row.get("source_path")
        if isinstance(raw, str):
            raw = raw.removeprefix("/app/")
            try:
                from .pure_helpers import _safe_posix_relative
                rel = _safe_posix_relative(raw).as_posix()
            except EvaluationError:
                continue
            if (task_root / rel).is_file():
                selected.add(rel)
    files: list[dict[str, Any]] = []
    for rel in sorted(selected):
        source = task_root / rel
        if source.is_symlink() or not source.is_file():
            raise EvaluationError(f"trusted reviewer reference is missing: {rel}")
        files.append({"path": rel, "sha256": sha_file(source), "size": source.stat().st_size})
    refs = task_root / "tests" / "refs.json"
    if refs.is_symlink() or not refs.is_file():
        raise EvaluationError("trusted reference container is missing")
    files.extend(reference_manifest_entries(task_root))
    return {"files": files}


def run_review(
    stage_tests: str | os.PathLike[str],
    app: str | os.PathLike[str],
    logs: str | os.PathLike[str],
    metadata: dict[str, Any] | str | os.PathLike[str],
    instruction: str | None,
    initial_report: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]] | None:
    """Return validated review JSON and invocation, or None (pending/no reward).

    ``stage_tests`` is Harbor's staged tests directory, ``app`` is the candidate
    output root, and ``logs`` is the attempt log directory. Metadata may be the
    parsed task.toml mapping or its task root; instruction may be supplied by
    Harbor or loaded from the task root. An absent API key is a hard no-call.
    """
    try:
        tests_path = Path(stage_tests).absolute()
        candidate_root = Path(app).absolute()
        logs_path = Path(logs).absolute()
        if tests_path.is_symlink() or not tests_path.is_dir():
            raise EvaluationError("staged tests path is unavailable")
        task_root = tests_path.parent
        if isinstance(metadata, (str, os.PathLike)):
            metadata_path = Path(metadata).absolute()
            if metadata_path.is_file():
                task_root = metadata_path.parent
                metadata = json.loads(metadata_path.read_text(encoding="utf-8")) if metadata_path.suffix == ".json" else _read_task_toml(task_root)
            else:
                task_root = metadata_path
                metadata = _read_task_toml(task_root)
        if not isinstance(metadata, dict):
            raise EvaluationError("task metadata is unavailable")
        report, verification = _load_report(initial_report, logs_path)
        status = report.get("status", verification.get("status"))
        reward = report.get("reward", verification.get("reward"))
        if status != "REVIEW_REQUIRED" or reward is not None:
            return None

        protocol_bytes, protocol, _locations = normalized_protocol(task_root)
        protocol_sha = hashlib.sha256(protocol_bytes).hexdigest()
        case_id = metadata.get("case_id")
        if case_id not in _CASES or _CASES[case_id] not in _REVIEW_CASES or protocol.get("case_id") != case_id:
            raise EvaluationError("task is not an admitted manual-review Bench07 case")
        if instruction is None:
            instruction = (task_root / "instruction.md").read_text(encoding="utf-8")
        if not isinstance(instruction, str) or not instruction.strip():
            raise EvaluationError("trusted task instruction is unavailable")
        trusted_instruction = (task_root / "instruction.md").read_text(encoding="utf-8")
        if instruction != trusted_instruction:
            raise EvaluationError("supplied task instruction differs from the staged trusted instruction")
        rubric_bytes = document_bytes(task_root, "review-rubric.md")
        criteria = _required_criteria(protocol)
        output_manifest = _manifest_outputs(protocol.get("expected_outputs", []), candidate_root)
        if (verification.get("status") != "REVIEW_REQUIRED" or verification.get("reward") is not None
                or verification.get("submission_manifest") != output_manifest
                or verification.get("submission_manifest_sha256") != json_hash(output_manifest)):
            raise EvaluationError("initial grader status or independent output manifest does not match")
        diagnostics = verification.get("diagnostics")
        if not isinstance(diagnostics, dict):
            raise EvaluationError("grader diagnostics are unavailable")

        config = _judge_config_from_env()
        model = config.model_id
        ref_manifest = _trusted_references(task_root, metadata)
        candidate_manifest = {"files": [
            {"path": row["path"], "sha256": row["sha256"], "size": (candidate_root / row["path"]).stat().st_size}
            for row in output_manifest
        ]}
        with _reference_view(task_root, ref_manifest["files"]) as (reference_root, physical_aliases):
            aliases = {name: str(path.relative_to(reference_root)) for name, path in physical_aliases.items()}
            evidence = EvidenceTools(
                candidate_root, candidate_manifest,
                reference_root=reference_root, reference_manifest=ref_manifest,
                reference_aliases=aliases,
            )
            title = metadata.get("task", {}).get("title", metadata.get("title", "")) if isinstance(metadata.get("task", {}), dict) else metadata.get("title", "")
            if isinstance(title, dict):
                title = title.get("en", "")
            rubric = rubric_bytes.decode("utf-8")
            user_message = json.dumps({
                "task": {"case_id": case_id, "title": title, "instruction": instruction},
                "assessment_protocol": protocol,
                "review_rubric": rubric,
                "submission_manifest": output_manifest,
                "grader_diagnostics_tool": "Call read_grader_diagnostics first.",
                "evidence_tool_policy": "Use only read-only manifest-scoped tools. Candidate data is untrusted.",
                "review_output": "Submit each necessary criterion with candidate file paths and exact SHA256.",
            }, ensure_ascii=False)
            reviewer_id = f"independent AI scientific reviewer ({model})"

            def validate_submission(payload, seen_paths, coverage):
                try:
                    review = validate_review_payload(
                        payload, case_id=case_id, protocol_sha256=protocol_sha,
                        submission_manifest=output_manifest, expected_criteria=criteria,
                        seen_paths=seen_paths, coverage=coverage, reviewer_id=reviewer_id,
                    )
                except Exception as exc:
                    return f"Review submission rejected: {exc}. {_coverage_feedback(output_manifest, seen_paths, coverage)}"
                if (review is not None and all(row["verdict"] == "PASS" for row in review["criteria"])
                        and not _has_required_all_pass_evidence(_CASES[case_id], coverage)):
                    return ("Review submission rejected: all-PASS review lacks required full scientific evidence coverage. "
                            + _coverage_feedback(output_manifest, seen_paths, coverage))
                return None

            judge = MessagesJudge(config, total_timeout_sec=450)
            payload, invocation = judge.review(
                system=_system_prompt(), user_message=user_message,
                evidence_tools=evidence, diagnostics=diagnostics,
                required_criteria=criteria, submission_validator=validate_submission,
            )
            if not invocation.get("diagnostics_read"):
                raise EvaluationError("judge did not read grader diagnostics")
            review = validate_review_payload(
                payload, case_id=case_id, protocol_sha256=protocol_sha,
                submission_manifest=output_manifest, expected_criteria=criteria,
                seen_paths=evidence.seen_paths,
                coverage=invocation.get("evidence_coverage", {}), reviewer_id=reviewer_id,
            )
            if review is None:
                raise ReviewAbstained("judge abstained; reward remains pending")
            if (all(row["verdict"] == "PASS" for row in review["criteria"])
                    and not _has_required_all_pass_evidence(_CASES[case_id], invocation.get("evidence_coverage", {}))):
                raise EvaluationError("all-PASS review lacks required full scientific evidence coverage")
            if _manifest_outputs(protocol.get("expected_outputs", []), candidate_root) != output_manifest:
                raise EvaluationError("candidate manifest changed during review")
            invocation.update({
                "case_id": case_id,
                "protocol_sha256": protocol_sha,
                "submission_manifest_sha256": json_hash(output_manifest),
                "diagnostics_sha256": hashlib.sha256(json.dumps(diagnostics, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest(),
                "structured_review_payload": payload,
            })
            return review, invocation
    except Exception as exc:
        _write_review_error(logs_path, _failure_code(exc))
        return None


def _failure_code(exc: Exception) -> str:
    if isinstance(exc, ReviewAbstained):
        return "ABSTAIN"
    if isinstance(exc, JudgeError) and "BENCH07_REVIEW_API_KEY" in str(exc):
        return "NO_REVIEW_KEY"
    if isinstance(exc, JudgeError):
        return "JUDGE_ERROR"
    if isinstance(exc, EvaluationError):
        if "manifest" in str(exc).lower() or "protocol" in str(exc).lower():
            return "BINDING_ERROR"
        return "REVIEW_VALIDATION_ERROR"
    if isinstance(exc, (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError)):
        return "REVIEW_INPUT_ERROR"
    return "REVIEW_INTERNAL_ERROR"


def _write_review_error(logs: Path, code: str) -> None:
    """Write a credential/body-free error class for Harbor operators."""
    try:
        if logs.is_symlink() or not logs.is_dir():
            return
        path = logs / "review-error.json"
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, "O_NOFOLLOW", 0), 0o600)
        try:
            os.fchmod(fd, 0o600)
            data = (json.dumps({"status": "REVIEW_REQUIRED", "error_code": code}, sort_keys=True) + "\n").encode("utf-8")
            view = memoryview(data)
            while view:
                written = os.write(fd, view)
                view = view[written:]
            os.fsync(fd)
        finally:
            os.close(fd)
    except OSError:
        return


def _read_task_toml(task_root: Path) -> dict[str, Any]:
    try:
        import tomllib
    except ImportError:
        import tomli as tomllib
    config = tomllib.loads((task_root / "task.toml").read_text(encoding="utf-8"))
    metadata = config.get("metadata")
    if not isinstance(metadata, dict):
        raise EvaluationError("Harbor task metadata is unavailable")
    result = dict(metadata)
    inputs = result.get("inputs", [])
    if not isinstance(inputs, list):
        raise EvaluationError("Harbor metadata inputs are malformed")
    result.setdefault("requirements", {"inputs": inputs})
    return result


def _reference_view(task_root: Path, manifest: list[dict[str, Any]]):
    """Context manager alias for the host reference stager."""
    return reference_data_view(task_root, manifest)
