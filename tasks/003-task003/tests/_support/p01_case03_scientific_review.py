"""Protected human review transport for Case 03's internal training claims.

This module validates reviewer-supplied judgments and binds them to the exact
submission snapshot and the existing host replay. It never evaluates scientific
criteria and never upgrades a missing or pending judgment to PASS.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import stat
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Any

SCHEMA = "case03-scientific-training-review/v1"
REVIEW_CONTEXT_SCHEMA = "case03-scientific-review-context/v1"
CASE_ID = "case-03-low-data-model-selection"
IMAGE_ID = "sha256:f08436624a70bec6b004102ae91030e38d2be1154c8891055b3594a09b7538cc"
CRITERIA = (
    "train_only_preprocessing",
    "inner_cv_scope",
    "equal_arm_estimator_and_budget",
    "label_and_test_feature_use",
    "implementation_and_seed_identity",
    "figure_auxiliary_interpretation",
    "paired_conclusion_validity",
)
HASH_RE = re.compile(r"[0-9a-f]{64}\Z")
ATTEMPT_RE = re.compile(r"[0-9a-f]{32}\Z")
REVIEW_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,95}\Z")
MAX_REVIEW_BYTES = 1_000_000


class ScientificReviewError(ValueError):
    """Malformed, stale, or unsafe scientific review evidence."""


def _canonical_protected_root() -> Path:
    repo_root = Path(__file__).resolve().parents[4]
    return (repo_root / "01_Activation-Energy-Mechanistic-Modeling"
            / "acceptance/case03-compchembench/protected")


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _canonical_sha(value: Any) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"),
                     ensure_ascii=False, allow_nan=False).encode("utf-8")
    return _sha(raw)


def _read_regular(path: Path, label: str, *, max_bytes: int | None = None) -> bytes:
    if path.is_symlink() or not path.is_file():
        raise ScientificReviewError(f"{label} must be a regular non-symlink file")
    st = path.stat()
    if max_bytes is not None and st.st_size > max_bytes:
        raise ScientificReviewError(f"{label} exceeds its size limit")
    return path.read_bytes()


def parse_review_json(raw: bytes, label: str) -> dict[str, Any]:
    try:
        def no_duplicates(pairs):
            result = {}
            for key, value in pairs:
                if key in result:
                    raise ValueError(f"duplicate JSON key: {key}")
                result[key] = value
            return result
        value = json.loads(raw, object_pairs_hook=no_duplicates,
                           parse_constant=lambda constant: (_ for _ in ()).throw(ValueError(f"invalid constant: {constant}")))
    except (UnicodeError, json.JSONDecodeError, ValueError) as exc:
        raise ScientificReviewError(f"{label} is not valid UTF-8 JSON") from exc
    if not isinstance(value, dict):
        raise ScientificReviewError(f"{label} must be a JSON object")
    return value


def _require_hash(value: Any, label: str) -> str:
    if not isinstance(value, str) or HASH_RE.fullmatch(value) is None:
        raise ScientificReviewError(f"{label} must be a lowercase SHA-256 digest")
    return value


def _safe_relpath(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value or "\\" in value:
        raise ScientificReviewError(f"{label} must be a nonempty POSIX relative path")
    raw_parts = value.split("/")
    if any(part in ("", ".", "..") for part in raw_parts):
        raise ScientificReviewError(f"{label} is not a safe relative path")
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in ("", ".", "..") for part in path.parts):
        raise ScientificReviewError(f"{label} is not a safe relative path")
    return path.as_posix()


def final_snapshot(final_dir: Path) -> dict[str, str]:
    """Hash every regular file under final/, rejecting links and special files."""
    final_dir = Path(final_dir)
    if final_dir.is_symlink() or not final_dir.is_dir():
        raise ScientificReviewError("final submission directory is missing or redirected")
    files: dict[str, str] = {}
    for path in sorted(final_dir.rglob("*")):
        rel = path.relative_to(final_dir).as_posix()
        if path.is_symlink():
            raise ScientificReviewError(f"final snapshot contains a symlink: {rel}")
        if path.is_dir():
            continue
        if not path.is_file():
            raise ScientificReviewError(f"final snapshot contains a special file: {rel}")
        files[rel] = _sha(_read_regular(path, f"final/{rel}"))
    if not files:
        raise ScientificReviewError("final snapshot is empty")
    return files


def replay_grid_digest(receipt: dict[str, Any]) -> str:
    """Digest the complete successful replay grid in stable row order."""
    records = receipt.get("records")
    if not isinstance(records, list) or not records:
        raise ScientificReviewError("replay records are missing")
    rows = []
    seen: set[tuple[str, int, int]] = set()
    for item in records:
        if not isinstance(item, dict):
            raise ScientificReviewError("replay record is malformed")
        arm, n_train, repeat = item.get("representation"), item.get("n_train"), item.get("repeat_index")
        if arm not in {"mechanistic", "no_ts", "fingerprint"} or type(n_train) is not int or type(repeat) is not int:
            raise ScientificReviewError("replay record identity is malformed")
        key = (arm, n_train, repeat)
        if key in seen:
            raise ScientificReviewError("replay grid contains duplicate fit records")
        seen.add(key)
        if (item.get("status") != "ok" or item.get("prediction_replay_verified") is not True
                or item.get("exit_code") != 0):
            raise ScientificReviewError("replay grid includes a failed fit record")
        hashes = ("request_sha256", "response_sha256", "X_train_sha256", "y_train_sha256", "X_test_sha256")
        row = {k: item.get(k) for k in ("representation", "n_train", "repeat_index", *hashes)}
        for name in hashes:
            _require_hash(row[name], f"replay {name}")
        rows.append(row)
    if len(seen) != len(records):
        raise ScientificReviewError("replay grid does not contain unique fits")
    return _canonical_sha(sorted(rows, key=lambda x: (x["representation"], x["n_train"], x["repeat_index"])))


def validate_review(review: dict[str, Any], *, final_dir: Path, context: dict[str, Any],
                    context_sha256: str, receipt: dict[str, Any], receipt_sha256: str) -> dict[str, Any]:
    """Validate format and exact source/runtime bindings; criteria remain human-owned."""
    if review.get("schema") != SCHEMA:
        raise ScientificReviewError("unsupported scientific review schema")
    if (context.get("schema") != "compchembench.runner-context/v1"
            or not isinstance(context.get("task_id"), str)
            or not context["task_id"].endswith(CASE_ID)):
        raise ScientificReviewError("runner context is not the canonical Case 03 attempt")
    if not isinstance(review.get("review_id"), str) or REVIEW_ID_RE.fullmatch(review["review_id"]) is None:
        raise ScientificReviewError("review_id is malformed")
    reviewer = review.get("reviewer")
    if not isinstance(reviewer, dict):
        raise ScientificReviewError("reviewer must be an object")
    for name in ("id", "role"):
        if not isinstance(reviewer.get(name), str) or not reviewer[name].strip():
            raise ScientificReviewError(f"reviewer.{name} must be nonempty")
    independence = reviewer.get("independence")
    if (not isinstance(independence, dict) or independence.get("status") != "independent"
            or not isinstance(independence.get("basis"), str) or not independence["basis"].strip()):
        raise ScientificReviewError("reviewer independence must be explicitly attested with a basis")
    reviewed_at = review.get("reviewed_at")
    if not isinstance(reviewed_at, str):
        raise ScientificReviewError("reviewed_at must be an ISO-8601 timestamp")
    try:
        parsed_time = datetime.fromisoformat(reviewed_at.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ScientificReviewError("reviewed_at must be an ISO-8601 timestamp") from exc
    if parsed_time.tzinfo is None:
        raise ScientificReviewError("reviewed_at must include a timezone")
    if review.get("source_image_id") != context.get("image_id") or context.get("image_id") != IMAGE_ID:
        raise ScientificReviewError("review source image does not match the pinned runner context")

    current_files = final_snapshot(final_dir)
    try:
        protocol = parse_review_json(_read_regular(Path(final_dir) / "protocol.json", "final/protocol.json"),
                                     "final/protocol.json")
        splits = parse_review_json(_read_regular(Path(final_dir) / "splits.json", "final/splits.json"),
                                   "final/splits.json")
    except OSError as exc:
        raise ScientificReviewError("final protocol/splits files are unavailable") from exc
    submitted_files = review.get("submission_files")
    if not isinstance(submitted_files, dict):
        raise ScientificReviewError("submission_files must contain the complete final snapshot")
    normalized: dict[str, str] = {}
    for name, digest in submitted_files.items():
        rel = _safe_relpath(name, "submission file path")
        if rel in normalized:
            raise ScientificReviewError("submission_files contains duplicate normalized paths")
        normalized[rel] = _require_hash(digest, f"submission_files[{rel}]")
    if normalized != current_files:
        raise ScientificReviewError("review submission_files differs from the complete final snapshot")
    for field, filename in (("fit_sha256", "fit.py"), ("protocol_sha256", "protocol.json"),
                            ("splits_sha256", "splits.json"), ("predictions_sha256", "predictions.csv")):
        digest = _require_hash(review.get(field), field)
        if current_files.get(filename) != digest:
            raise ScientificReviewError(f"{field} does not match final/{filename}")

    manifest_sha = _require_hash(review.get("artifact_manifest_sha256"), "artifact_manifest_sha256")
    if manifest_sha != context.get("artifact_manifest_sha256"):
        raise ScientificReviewError("review artifact manifest is stale")
    manifest = context.get("artifact_manifest")
    if _canonical_sha(manifest) != manifest_sha:
        raise ScientificReviewError("runner context artifact manifest digest does not reconcile")
    if (not isinstance(manifest, dict) or manifest.get("missing")
            or not isinstance(manifest.get("collected"), list)):
        raise ScientificReviewError("runner artifact manifest is incomplete")
    manifest_files: dict[str, str] = {}
    for group in manifest["collected"]:
        if not isinstance(group, dict) or not isinstance(group.get("files"), list):
            raise ScientificReviewError("runner artifact manifest has a malformed file group")
        for record in group["files"]:
            if not isinstance(record, dict):
                raise ScientificReviewError("runner artifact manifest has a malformed file record")
            rel = _safe_relpath(record.get("path"), "runner artifact path")
            if not rel.startswith("final/") or rel in manifest_files:
                raise ScientificReviewError("runner artifact manifest must uniquely enumerate final/ files")
            digest = _require_hash(record.get("sha256"), f"runner artifact {rel} SHA-256")
            if type(record.get("bytes")) is not int or record["bytes"] < 0:
                raise ScientificReviewError(f"runner artifact {rel} has an invalid byte count")
            if (Path(final_dir) / rel.removeprefix("final/")).stat().st_size != record["bytes"]:
                raise ScientificReviewError(f"runner artifact {rel} byte count differs from final snapshot")
            manifest_files[rel.removeprefix("final/")] = digest
    if manifest_files != current_files:
        raise ScientificReviewError("complete final snapshot differs from the runner artifact manifest")
    if _require_hash(context_sha256, "runner context SHA-256") != context_sha256:
        raise ScientificReviewError("runner context SHA-256 is malformed")
    if receipt.get("schema") != "p01_case03_fit_replay/v1" or receipt.get("status") != "ok":
        raise ScientificReviewError("existing Case 03 replay is missing or unsuccessful")
    attempt_id = context.get("attempt_id")
    if not isinstance(attempt_id, str) or ATTEMPT_RE.fullmatch(attempt_id) is None:
        raise ScientificReviewError("runner context attempt_id is malformed")
    basis = review.get("execution_basis")
    if not isinstance(basis, dict):
        raise ScientificReviewError("execution_basis must be an object")
    if (basis.get("attempt_id") != attempt_id
            or receipt.get("attempt_id") != attempt_id
            or receipt.get("artifact_manifest_sha256") != manifest_sha):
        raise ScientificReviewError("review, context, and replay attempt bindings disagree")
    if _require_hash(receipt_sha256, "replay receipt SHA-256") != receipt_sha256:
        raise ScientificReviewError("replay receipt SHA-256 is malformed")
    if basis.get("replay_receipt_sha256") != receipt_sha256:
        raise ScientificReviewError("review replay receipt hash is stale")
    replay_binding = context.get("p01_case03_fit_replay")
    if not isinstance(replay_binding, dict) or replay_binding.get("receipt_sha256") != receipt_sha256:
        raise ScientificReviewError("runner context does not bind the replay receipt")
    grid_digest = replay_grid_digest(receipt)
    if (basis.get("grid_digest") != grid_digest
            or basis.get("grid_digest") != review.get("execution_grid_digest")):
        raise ScientificReviewError("review replay grid binding is stale or incomplete")
    split_records = splits.get("records")
    sizes = protocol.get("sizes")
    repeats = protocol.get("repeats_per_size")
    if (not isinstance(split_records, list) or not isinstance(sizes, list) or len(sizes) < 2
            or any(type(n) is not int or n < 1 for n in sizes)
            or len(set(sizes)) != len(sizes) or sizes != sorted(sizes)
            or type(repeats) is not int or repeats < 20
            or splits.get("sizes") != sizes or splits.get("repeats_per_size") != repeats):
        raise ScientificReviewError("final protocol/splits do not declare a replayable grid")
    if any(not isinstance(record, dict) or type(record.get("n_train")) is not int
           or type(record.get("repeat_index")) is not int for record in split_records):
        raise ScientificReviewError("final split records have malformed size/repeat identities")
    expected_splits = {
        (record.get("n_train"), record.get("repeat_index"))
        for record in split_records if isinstance(record, dict)
    }
    if (len(expected_splits) != len(split_records)
            or expected_splits != {(n, rep) for n in sizes for rep in range(repeats)}):
        raise ScientificReviewError("final split metadata does not define a complete size/repeat grid")
    if basis.get("record_count") != 3 * len(expected_splits):
        raise ScientificReviewError("review record_count does not match the complete final split grid")
    actual_grid = {(item["representation"], item["n_train"], item["repeat_index"])
                   for item in receipt["records"]}
    expected_grid = {(arm, n, rep) for arm in ("mechanistic", "no_ts", "fingerprint")
                     for n, rep in expected_splits}
    if actual_grid != expected_grid:
        raise ScientificReviewError("replay records do not cover the exact final size/repeat grid")
    for name, receipt_name in (("fit_sha256", "fit_sha256"), ("protocol_sha256", "protocol_sha256"),
                               ("splits_sha256", "splits_sha256"), ("predictions_sha256", "predictions_sha256")):
        expected = review[name]
        actual = receipt.get(receipt_name)
        if actual != expected.removeprefix("sha256:"):
            raise ScientificReviewError(f"review {name} differs from replay receipt")

    criteria = review.get("criteria")
    if not isinstance(criteria, dict) or set(criteria) != set(CRITERIA):
        raise ScientificReviewError("criteria must declare exactly the seven required review criteria")
    for key in CRITERIA:
        item = criteria[key]
        if not isinstance(item, dict) or item.get("verdict") not in {"PASS", "FAIL", "PENDING"}:
            raise ScientificReviewError(f"{key} must have verdict PASS, FAIL, or PENDING")
        for field in ("source_lines", "evidence_paths"):
            values = item.get(field)
            if not isinstance(values, list) or not values:
                raise ScientificReviewError(f"{key}.{field} must be a nonempty list")
        for line in item["source_lines"]:
            if (not isinstance(line, dict) or not isinstance(line.get("file"), str)
                    or type(line.get("start")) is not int or type(line.get("end")) is not int
                    or line["start"] < 1 or line["end"] < line["start"]):
                raise ScientificReviewError(f"{key}.source_lines contains an invalid line citation")
            source_name = _safe_relpath(line["file"], f"{key}.source_lines.file")
            if source_name not in current_files:
                raise ScientificReviewError(f"{key}.source_lines cites a file outside final/")
            source_bytes = _read_regular(Path(final_dir) / source_name, f"final/{source_name}")
            try:
                line_count = len(source_bytes.decode("utf-8", errors="strict").splitlines())
            except UnicodeError as exc:
                raise ScientificReviewError(f"{key}.source_lines cites non-UTF8 source") from exc
            if line["end"] > line_count:
                raise ScientificReviewError(f"{key}.source_lines exceeds final/{source_name}")
        for evidence_path in item["evidence_paths"]:
            evidence_name = _safe_relpath(evidence_path, f"{key}.evidence_paths")
            if evidence_name.startswith("final/"):
                evidence_name = evidence_name.removeprefix("final/")
            if evidence_name not in current_files:
                raise ScientificReviewError(f"{key}.evidence_paths cites a file outside the current final snapshot")
        for field in ("reason", "library_semantics"):
            if not isinstance(item.get(field), str) or not item[field].strip():
                raise ScientificReviewError(f"{key}.{field} must explain the review judgment")
    limits = review.get("scope_limits")
    if (not isinstance(limits, dict) or limits.get("public_nonblind") is not True
            or limits.get("formal_proof") is not False
            or not isinstance(limits.get("limitations"), list) or not limits["limitations"]
            or any(not isinstance(x, str) or not x.strip() for x in limits["limitations"])):
        raise ScientificReviewError("scope_limits must state public/nonblind and non-formal-proof limits")
    verdicts = {key: criteria[key]["verdict"] for key in CRITERIA}
    review_status = ("PENDING" if "PENDING" in verdicts.values()
                     else "FAIL" if "FAIL" in verdicts.values() else "VERIFIED")
    return {"schema": SCHEMA, "review_id": review["review_id"], "review_sha256": None,
            "reviewer_id": reviewer["id"], "attempt_id": attempt_id,
            "runner_context_sha256": context_sha256,
            "artifact_manifest_sha256": manifest_sha,
            "replay_receipt_sha256": receipt_sha256,
            "execution_grid_digest": grid_digest,
            "criteria_verdicts": verdicts, "review_status": review_status,
            "training_pipeline_scientific_review_verified": review_status == "VERIFIED"}


def _private_file(path: Path, label: str, *, immutable: bool = False) -> None:
    if path.is_symlink() or not path.is_file():
        raise ScientificReviewError(f"{label} must be a regular non-symlink file")
    st = path.stat()
    if st.st_uid != os.getuid() or st.st_mode & 0o077 or (immutable and st.st_mode & 0o222):
        raise ScientificReviewError(f"{label} must be owner-only" + (" and immutable" if immutable else ""))


def _private_source(path: Path, label: str, *, immutable: bool = False) -> bytes:
    raw = _read_regular(path, label)
    st = path.stat()
    if (st.st_uid != os.getuid() or st.st_mode & 0o077
            or (immutable and st.st_mode & 0o222)):
        raise ScientificReviewError(f"{label} is not a host-private" + (" immutable" if immutable else "") + " file")
    return raw


def load_protected_review(path: Path, *, protected_root: Path) -> tuple[dict[str, Any], bytes]:
    """Load only the canonical owner-private acceptance review file."""
    path, protected_root = Path(path), Path(protected_root)
    if protected_root != _canonical_protected_root() or path != protected_root / "training-review.json":
        raise ScientificReviewError("review is not at the canonical protected acceptance path")
    if protected_root.is_symlink() or not protected_root.is_dir():
        raise ScientificReviewError("protected review directory is missing or redirected")
    st = protected_root.stat()
    if st.st_uid != os.getuid() or stat.S_IMODE(st.st_mode) != 0o700:
        raise ScientificReviewError("protected review directory must be owner-only mode 0700")
    if path.is_symlink() or not path.is_file():
        raise ScientificReviewError("protected review file must be a regular non-symlink file")
    if stat.S_IMODE(path.stat().st_mode) != 0o600:
        raise ScientificReviewError("protected review file must have mode 0600")
    _private_file(path, "protected review file")
    raw = _read_regular(path, "protected review", max_bytes=MAX_REVIEW_BYTES)
    return parse_review_json(raw, "protected review"), raw


def _validated_sources(review_path: Path, *, protected_root: Path, final_dir: Path,
                       context_path: Path, receipt_path: Path,
                       expected_context_sha256: str | None):
    review, review_raw = load_protected_review(review_path, protected_root=protected_root)
    context_path, receipt_path = Path(context_path), Path(receipt_path)
    if context_path.name != "runner-context.json" or receipt_path.parent.name != "p01-case03-fit-replay":
        raise ScientificReviewError("review source paths are not the canonical attempt context/replay receipt")
    context_raw = _private_source(context_path, "original runner context", immutable=True)
    receipt_raw = _private_source(receipt_path, "fit replay receipt")
    receipt_root = receipt_path.parent
    if (receipt_root.is_symlink() or not receipt_root.is_dir()
            or receipt_root.stat().st_uid != os.getuid() or receipt_root.stat().st_mode & 0o077):
        raise ScientificReviewError("fit replay receipt directory is not host-private")
    context = parse_review_json(context_raw, "runner context")
    receipt = parse_review_json(receipt_raw, "fit replay receipt")
    context_sha = _sha(context_raw)
    if expected_context_sha256 is not None and context_sha != expected_context_sha256:
        raise ScientificReviewError("original runner context hash differs from the run metadata")
    receipt_sha = _sha(receipt_raw)
    if context.get("image_id") != IMAGE_ID:
        raise ScientificReviewError("source runner context is not the canonical Case 03 attempt")
    replay_binding = context.get("p01_case03_fit_replay")
    if not isinstance(replay_binding, dict) or replay_binding.get("receipt_sha256") != receipt_sha:
        raise ScientificReviewError("original runner context does not bind the fit replay receipt")
    validated = validate_review(review, final_dir=Path(final_dir), context=context,
                                context_sha256=context_sha, receipt=receipt,
                                receipt_sha256=receipt_sha)
    return review, review_raw, context, receipt, receipt_sha, context_sha, validated


def _review_context_bytes(validated: dict[str, Any], review_sha: str) -> bytes:
    body = {
        "schema": REVIEW_CONTEXT_SCHEMA,
        "attempt_id": validated["attempt_id"],
        "review_id": validated["review_id"],
        "reviewer_id": validated["reviewer_id"],
        "review_sha256": review_sha,
        "runner_context_sha256": validated["runner_context_sha256"],
        "artifact_manifest_sha256": validated["artifact_manifest_sha256"],
        "replay_receipt_sha256": validated["replay_receipt_sha256"],
        "execution_grid_digest": validated["execution_grid_digest"],
        "criteria_verdicts": validated["criteria_verdicts"],
        "review_status": validated["review_status"],
        "training_pipeline_scientific_review_verified": validated["training_pipeline_scientific_review_verified"],
    }
    return json.dumps(body, sort_keys=True, ensure_ascii=False,
                      separators=(",", ":"), allow_nan=False).encode("utf-8") + b"\n"


def _trusted_destination(trusted_root: Path) -> None:
    trusted_parent = trusted_root.parent
    if (trusted_root.name != "p01-case03-scientific-review"
            or trusted_parent.name != "trusted" or trusted_parent.is_symlink()
            or not trusted_parent.is_dir() or trusted_parent.stat().st_uid != os.getuid()
            or trusted_parent.stat().st_mode & 0o077):
        raise ScientificReviewError("per-attempt review destination is not under the private trusted root")


def stage_review_transport(review_path: Path, *, protected_root: Path, final_dir: Path,
                           context_path: Path, receipt_path: Path, trusted_root: Path,
                           expected_context_sha256: str | None = None) -> dict[str, Any]:
    """Validate the review and copy it O_EXCL into a private per-attempt transport.

    The caller must pass the original immutable runner context and replay receipt
    paths for the same run. This function never edits either source file.
    """
    review, review_raw, _context, _receipt, receipt_sha, context_sha, validated = _validated_sources(
        review_path, protected_root=protected_root, final_dir=final_dir,
        context_path=context_path, receipt_path=receipt_path,
        expected_context_sha256=expected_context_sha256)
    trusted_root = Path(trusted_root)
    _trusted_destination(trusted_root)
    if trusted_root.exists() or trusted_root.is_symlink():
        raise ScientificReviewError("per-attempt scientific review transport already exists")
    trusted_root.mkdir(parents=True, mode=0o700, exist_ok=False)
    if trusted_root.is_symlink() or stat.S_IMODE(trusted_root.stat().st_mode) != 0o700:
        raise ScientificReviewError("per-attempt scientific review directory is not mode 0700")
    staged_review = trusted_root / "training-review.json"
    fd = os.open(staged_review, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(review_raw)
            stream.flush()
            os.fsync(stream.fileno())
    except BaseException:
        staged_review.unlink(missing_ok=True)
        raise
    review_sha = _sha(review_raw)
    validated["review_sha256"] = review_sha
    context_bytes = _review_context_bytes(validated, review_sha)
    fd = os.open(trusted_root / "review-context.json", os.O_WRONLY | os.O_CREAT | os.O_EXCL |
                 getattr(os, "O_NOFOLLOW", 0), 0o600)
    with os.fdopen(fd, "wb") as stream:
        stream.write(context_bytes)
        stream.flush()
        os.fsync(stream.fileno())
    return {**validated, "review_sha256": review_sha, "trusted_root": str(trusted_root),
            "review_context_sha256": _sha(context_bytes)}


def ensure_review_transport(review_path: Path, *, protected_root: Path, final_dir: Path,
                            context_path: Path, receipt_path: Path, trusted_root: Path,
                            expected_context_sha256: str | None = None) -> dict[str, Any]:
    """Create once, or revalidate an unchanged existing per-attempt transport."""
    trusted_root = Path(trusted_root)
    _trusted_destination(trusted_root)
    if not trusted_root.exists() and not trusted_root.is_symlink():
        return stage_review_transport(
            review_path, protected_root=protected_root, final_dir=final_dir,
            context_path=context_path, receipt_path=receipt_path, trusted_root=trusted_root,
            expected_context_sha256=expected_context_sha256)

    review, review_raw, context, receipt, receipt_sha, context_sha, validated = _validated_sources(
        review_path, protected_root=protected_root, final_dir=final_dir,
        context_path=context_path, receipt_path=receipt_path,
        expected_context_sha256=expected_context_sha256)
    if trusted_root.is_symlink() or not trusted_root.is_dir():
        raise ScientificReviewError("existing trusted review transport is redirected or missing")
    root_stat = trusted_root.stat()
    if (root_stat.st_uid != os.getuid() or stat.S_IMODE(root_stat.st_mode) != 0o700
            or {path.name for path in trusted_root.iterdir()} != {"training-review.json", "review-context.json"}):
        raise ScientificReviewError("existing trusted review transport is incomplete or unsafe")
    staged_review_path = trusted_root / "training-review.json"
    staged_context_path = trusted_root / "review-context.json"
    for path, label in ((staged_review_path, "staged review"), (staged_context_path, "staged review context")):
        _private_file(path, label)
        if stat.S_IMODE(path.stat().st_mode) != 0o600:
            raise ScientificReviewError(f"{label} must have mode 0600")
    staged_review = _read_regular(staged_review_path, "staged review", max_bytes=MAX_REVIEW_BYTES)
    if staged_review != review_raw:
        raise ScientificReviewError("existing staged review differs from the canonical protected review")
    review_sha = _sha(review_raw)
    expected_context = _review_context_bytes(validated, review_sha)
    staged_context = _read_regular(staged_context_path, "staged review context", max_bytes=MAX_REVIEW_BYTES)
    parsed_context = parse_review_json(staged_context, "staged review context")
    expected_parsed_context = parse_review_json(expected_context, "expected review context")
    if staged_context != expected_context or parsed_context != expected_parsed_context:
        raise ScientificReviewError("existing review context is stale or corrupted")
    validated["review_sha256"] = review_sha
    return {**validated, "trusted_root": str(trusted_root),
            "review_context_sha256": _sha(expected_context)}
