"""Bind a human scientific approval to one candidate and scorer version."""
from __future__ import annotations

import hashlib
import json
import stat
from pathlib import Path


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def tree_fingerprints(tests: Path) -> dict[str, str]:
    result = {}
    for p in sorted(tests.rglob("*")):
        rel = p.relative_to(tests).as_posix()
        if p.is_symlink():
            raise RuntimeError(f"trusted tests tree contains a symlink: {rel}")
        if p.is_file() and p.name != "author-review.json" and p.suffix != ".pyc" and "__pycache__" not in p.parts:
            result[rel] = sha(p)
    return result


def output_manifest(app: Path, protocol: dict) -> dict[str, dict[str, object]]:
    """Hash only declared output paths, recursively expanding declared directories."""
    manifest = {}
    selected = set()
    for rel in protocol["output_contract"]["required_paths"]:
        is_dir = rel.endswith("/")
        path = app / rel.rstrip("/")
        try:
            path.relative_to(app)
        except ValueError as exc:
            raise ValueError(f"candidate output path escapes APP: {rel}") from exc
        if any(p.is_symlink() for p in (path, *path.parents) if p == app or app in p.parents):
            raise ValueError(f"candidate output path contains a symlink: {rel}")
        if is_dir:
            if not path.is_dir():
                raise ValueError(f"candidate output directory missing: {rel}")
            descendants = sorted(path.rglob("*"))
            if not descendants or not any(p.is_file() for p in descendants):
                raise ValueError(f"candidate output directory is empty: {rel}")
            for item in descendants:
                if item.is_symlink():
                    raise ValueError(f"candidate output directory contains a symlink: {item.relative_to(app)}")
                if item.is_file():
                    selected.add(item)
                elif not item.is_dir():
                    raise ValueError(f"candidate output directory contains a special file: {item.relative_to(app)}")
        else:
            if not path.is_file():
                raise ValueError(f"candidate output missing: {rel}")
            selected.add(path)
    for path in sorted(selected):
        if not stat.S_ISREG(path.stat().st_mode):
            raise ValueError(f"candidate output is not a regular file: {path.relative_to(app)}")
        manifest[path.relative_to(app).as_posix()] = {"sha256": sha(path), "bytes": path.stat().st_size}
    return manifest


def preflight_trusted_sources(app: Path, tests: Path):
    index = tests / "reference-hashes.json"
    if index.is_symlink() or not index.is_file():
        raise RuntimeError("trusted reference-hashes.json is missing or unsafe")
    try:
        entries = json.loads(index.read_text(encoding="utf-8"))
    except Exception as exc:
        raise RuntimeError(f"trusted reference-hashes.json cannot be decoded: {exc}") from exc
    if not isinstance(entries, dict):
        raise RuntimeError("trusted reference hash index must be a JSON object")
    for rel, expected in entries.items():
        if not isinstance(rel, str) or not isinstance(expected, str):
            raise RuntimeError("trusted reference hash entry is malformed")
        if Path(rel).is_absolute() or ".." in Path(rel).parts:
            raise RuntimeError(f"trusted reference path is unsafe: {rel}")
        if rel.startswith("tests/"):
            path = tests / rel.removeprefix("tests/")
        elif rel.startswith("environment/assets/"):
            path = app / rel
        else:
            raise RuntimeError(f"trusted reference path is outside supported scope: {rel}")
        if path.is_symlink() or not path.is_file() or sha(path) != expected:
            raise RuntimeError(f"trusted reference hash mismatch or missing file: {rel}")
    protocol_path = tests / "assessment-protocol.json"
    if protocol_path.is_symlink() or not protocol_path.is_file():
        raise RuntimeError("trusted assessment protocol is missing or unsafe")
    protocol = json.loads(protocol_path.read_text(encoding="utf-8"))
    for rel, expected in protocol.get("inputs", {}).items():
        path = app / rel
        if path.is_symlink() or not path.is_file() or sha(path) != expected:
            raise RuntimeError(f"trusted public input hash mismatch or missing file: {rel}")
    record_path = tests / "author-review.json"
    if record_path.exists():
        validate_review_record(record_path, tests, protocol)


def validate_review_record(record_path: Path, tests: Path, protocol: dict) -> dict:
    if record_path.is_symlink() or not record_path.is_file():
        raise RuntimeError("trusted author-review record is unsafe")
    try:
        record = json.loads(record_path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise RuntimeError(f"trusted author-review record cannot be decoded: {exc}") from exc
    required = {x["criterion"] for x in protocol["criteria"] if x.get("necessary") is True}
    review_status = record.get("review_status") if isinstance(record, dict) else None
    if not isinstance(record, dict) or record.get("version") != 1 or record.get("case_id") != protocol.get("case_id") or review_status not in ("PASS", "FAIL"):
        raise RuntimeError("trusted author-review record has invalid identity or status")
    criteria = record.get("criteria")
    valid_statuses = {"PASS", "FAIL", "JUDGE_REQUIRED"}
    if not isinstance(criteria, dict) or set(criteria) != required or any(
        not isinstance(v, dict) or v.get("status") not in valid_statuses or not isinstance(v.get("evidence"), str) or not v["evidence"].strip()
        for v in criteria.values()
    ) or (review_status == "PASS" and any(v["status"] != "PASS" for v in criteria.values())) or (
        review_status == "FAIL" and not any(v["status"] == "FAIL" for v in criteria.values())
    ):
        raise RuntimeError("trusted author-review record does not adjudicate every necessary criterion")
    if record.get("input_hashes") != protocol.get("inputs", {}):
        raise RuntimeError("trusted author-review record is stale for public inputs")
    expected_sources = {"tests/" + key: value for key, value in tree_fingerprints(tests).items()}
    contracts = protocol.get("contract_fingerprints")
    if not isinstance(contracts, dict) or not contracts:
        raise RuntimeError("assessment protocol is missing task-contract fingerprints")
    expected_sources.update({"contract/" + key: value for key, value in contracts.items()})
    if record.get("source_fingerprints") != expected_sources:
        raise RuntimeError("trusted author-review record is stale for task, protocol, references, or scoring code")
    if not isinstance(record.get("reviewer"), str) or not record["reviewer"].strip() or not isinstance(record.get("reviewed_on"), str):
        raise RuntimeError("trusted author-review record lacks reviewer/date")
    if not isinstance(record.get("candidate_manifest"), dict):
        raise RuntimeError("trusted author-review record lacks a candidate manifest")
    return record


def adjudicate(app: Path, tests: Path, diagnostic: dict) -> dict:
    """Return scoring status; stale/invalid trusted review is infrastructure failure."""
    preflight_trusted_sources(app, tests)
    if diagnostic.get("status") == "FAIL":
        return {**diagnostic, "status": "FAIL", "reward": 0}
    if diagnostic.get("status") != "REVIEW_REQUIRED":
        raise RuntimeError("diagnostic did not return a valid candidate/review status")
    protocol = json.loads((tests / "assessment-protocol.json").read_text(encoding="utf-8"))
    required = {x["criterion"] for x in protocol["criteria"] if x.get("necessary") is True}
    try:
        candidate = output_manifest(app, protocol)
    except ValueError as exc:
        return {**diagnostic, "status": "FAIL", "reward": 0, "candidate_error": str(exc)}
    record_path = tests / "author-review.json"
    if not record_path.exists():
        return {**diagnostic, "status": "REVIEW_REQUIRED", "reward_status": "PENDING_REVIEW",
                "candidate_manifest": candidate}
    record = validate_review_record(record_path, tests, protocol)
    reviewed = record.get("candidate_manifest")
    if reviewed != candidate:
        return {**diagnostic, "status": "REVIEW_REQUIRED", "reward_status": "PENDING_REVIEW",
                "candidate_manifest": candidate,
                "review_note": "A trusted scientific review exists, but it is bound to different output bytes."}
    review_status = record["review_status"]
    reward = 1 if review_status == "PASS" else 0
    return {**diagnostic, "status": review_status, "reward": reward, "reward_status": "AWARDED",
            "scientific_review": {"reviewer": record.get("reviewer"), "reviewed_on": record.get("reviewed_on"),
                                  "criteria": record["criteria"]}}


def run_case(app: Path, tests: Path, logs: Path) -> int:
    import sys
    sys.path.insert(0, str(tests))
    try:
        preflight_trusted_sources(app, tests)
        import diagnostic
        result = adjudicate(app, tests, diagnostic.run(app, tests))
        status = result.get("status")
        code = 1 if status == "FAIL" else 0 if status in ("REVIEW_REQUIRED", "PASS") else 2
        if code == 2:
            result = {"status": "INFRA_ERROR", "error": "invalid final status", "diagnostic": result}
    except Exception as exc:
        result = {"status": "INFRA_ERROR", "error": f"{type(exc).__name__}: {exc}"}
        code = 2
    logs.mkdir(parents=True, exist_ok=True)
    (logs / "report.json").write_text(json.dumps(result, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")
    reward = logs / "reward.txt"
    if result.get("status") == "PASS":
        reward.write_text("1\n", encoding="utf-8")
    elif result.get("status") == "FAIL":
        reward.write_text("0\n", encoding="utf-8")
    elif reward.exists():
        reward.unlink()
    print(json.dumps(result, ensure_ascii=False, allow_nan=False))
    return code
