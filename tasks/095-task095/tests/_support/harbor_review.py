#!/usr/bin/env python3
"""Prepare and score one frozen Harbor Case09 trial using trusted host review files."""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
from pathlib import Path, PurePosixPath
import stat
import subprocess
import sys
import tomllib
import zipfile
import io

ROOT = Path(__file__).resolve().parents[2]
TESTS = ROOT / "tests"
POLICY = TESTS / "_data" / "trusted-review-policy.json"
QUESTION = ROOT / "instruction.md"
FILES = ("trusted_review.json", "case09_attempt_binding.json", "case09_review_provenance.json", "case09_review_receipt.json")
ENV_KEY = "CASE09_TRUSTED_REVIEW_B64"
MAX_FILE, MAX_PAYLOAD = 2_000_000, 64 * 1024
MAX_BUNDLE, MAX_ZIP_MEMBERS, MAX_UNPACKED = 100_000_000, 5_000, 200_000_000


class ReviewInputError(Exception):
    pass


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def read_json(path: Path) -> tuple[dict, bytes]:
    try:
        info = path.lstat()
        if not stat.S_ISREG(info.st_mode) or not 0 < info.st_size <= MAX_FILE:
            raise ReviewInputError(f"not a bounded regular file: {path}")
        raw = path.read_bytes()
        if len(raw) != info.st_size:
            raise ReviewInputError(f"file changed while reading: {path}")
        def pairs(items):
            out = {}
            for key, value in items:
                if key in out:
                    raise ValueError(f"duplicate JSON key: {key}")
                out[key] = value
            return out
        doc = json.loads(raw.decode("utf-8"), object_pairs_hook=pairs,
                         parse_constant=lambda x: (_ for _ in ()).throw(ValueError(x)))
    except (OSError, UnicodeDecodeError, ValueError, json.JSONDecodeError) as exc:
        if isinstance(exc, ReviewInputError):
            raise
        raise ReviewInputError(f"invalid JSON {path}: {exc}") from exc
    if not isinstance(doc, dict):
        raise ReviewInputError(f"expected JSON object: {path}")
    return doc, raw


def safe_file(root: Path, relative: str) -> Path:
    current = root
    parts = PurePosixPath(relative).parts
    for index, part in enumerate(parts):
        current = current / part
        info = current.lstat()
        if stat.S_ISLNK(info.st_mode):
            raise ReviewInputError(f"source path contains symlink: {relative}")
        if index < len(parts) - 1 and not stat.S_ISDIR(info.st_mode):
            raise ReviewInputError(f"source path has non-directory parent: {relative}")
        if index == len(parts) - 1 and not stat.S_ISREG(info.st_mode):
            raise ReviewInputError(f"source artifact is not a regular file: {relative}")
    return current


def zip_member_hashes(bundle: bytes) -> set[str]:
    if not bundle or len(bundle) > MAX_BUNDLE:
        raise ReviewInputError("source evidence.zip exceeds the bundle byte limit")
    hashes, names, unpacked = set(), set(), 0
    try:
        with zipfile.ZipFile(io.BytesIO(bundle)) as archive:
            infos = archive.infolist()
            if len(infos) > MAX_ZIP_MEMBERS:
                raise ReviewInputError("evidence.zip has too many members")
            for info in infos:
                name = info.filename
                path = PurePosixPath(name)
                if (not name or "\\" in name or "\x00" in name or path.is_absolute()
                        or any(part in {"", ".", ".."} for part in path.parts) or name in names):
                    raise ReviewInputError("evidence.zip contains an unsafe or duplicate path")
                names.add(name)
                if info.flag_bits & 1:
                    raise ReviewInputError("encrypted evidence.zip members are not accepted")
                mode = (info.external_attr >> 16) & 0xFFFF
                if stat.S_IFMT(mode) not in {0, stat.S_IFREG, stat.S_IFDIR}:
                    raise ReviewInputError("evidence.zip may contain only regular files and directories")
                unpacked += info.file_size
                if unpacked > MAX_UNPACKED or (info.file_size and info.compress_size == 0):
                    raise ReviewInputError("evidence.zip exceeds unpacked-size bounds")
                if info.compress_size and info.file_size / info.compress_size > 1000:
                    raise ReviewInputError("evidence.zip has an excessive compression ratio")
                if info.is_dir():
                    continue
                digest = hashlib.sha256()
                size = 0
                with archive.open(info) as stream:
                    while block := stream.read(1024 * 1024):
                        size += len(block)
                        if size > info.file_size:
                            raise ReviewInputError("evidence.zip member exceeds declared size")
                        digest.update(block)
                if size != info.file_size:
                    raise ReviewInputError("evidence.zip member size mismatch")
                hashes.add(digest.hexdigest())
            bad = archive.testzip()
            if bad is not None:
                raise ReviewInputError("evidence.zip CRC check failed")
    except (OSError, zipfile.BadZipFile, RuntimeError) as exc:
        raise ReviewInputError(f"invalid evidence.zip: {exc}") from exc
    return hashes


def source_binding(source: Path):
    if not source.is_dir() or source.is_symlink():
        raise ReviewInputError("source must be a real Harbor trial directory")
    result_path = source / "result.json"
    if not result_path.exists():
        result_path = source / "results.json"
    result, result_raw = read_json(result_path)
    lock, lock_raw = read_json(source / "lock.json")
    task_cfg = tomllib.loads((ROOT / "task.toml").read_text(encoding="utf-8"))
    expected_task_name = task_cfg.get("task", {}).get("name", ROOT.name)
    lock_task = lock.get("task", {})
    recorded_path = Path(lock_task.get("path", ""))
    path_matches = (recorded_path.resolve() == ROOT.resolve()) if recorded_path.is_absolute() else recorded_path.as_posix() == ROOT.name
    result_task_path = Path((result.get("task_id") or {}).get("path", ""))
    result_path_matches = (result_task_path.resolve() == ROOT.resolve()) if result_task_path.is_absolute() else result_task_path.as_posix() == ROOT.name
    if (result.get("task_name") != expected_task_name
            or lock_task.get("name") != expected_task_name
            or not path_matches or not result_path_matches):
        raise ReviewInputError("source trial task_name does not identify Bench14 Case09")
    exception = result.get("exception_info")
    agent_execution = result.get("agent_execution") or {}
    if (result.get("finished_at") is None or not isinstance(result.get("agent_result"), dict)
            or agent_execution.get("finished_at") is None):
        raise ReviewInputError("source is unfinished or has no completed agent result")
    if exception is not None and exception.get("exception_type") != "RewardFileNotFoundError":
        raise ReviewInputError("source records an execution/infrastructure exception")
    manifest_path = safe_file(source, "artifacts/manifest.json")
    try:
        if manifest_path.stat().st_size > MAX_FILE:
            raise ReviewInputError("artifact manifest exceeds its byte limit")
        manifest_raw = manifest_path.read_bytes()
        def unique_pairs(pairs):
            out = {}
            for key, value in pairs:
                if key in out:
                    raise ValueError(f"duplicate JSON key: {key}")
                out[key] = value
            return out
        entries = json.loads(manifest_raw.decode("utf-8"), object_pairs_hook=unique_pairs)
    except (OSError, UnicodeDecodeError, ValueError, json.JSONDecodeError) as exc:
        raise ReviewInputError(f"invalid artifact manifest: {exc}") from exc
    if not isinstance(entries, list):
        raise ReviewInputError("artifact manifest must be a top-level list")
    artifacts = {}
    for src in ("/app/final/answer.md", "/app/final/evidence.zip"):
        rows = [r for r in entries if isinstance(r, dict) and r.get("source") == src]
        expected_dest = "artifacts/" + src.lstrip("/")
        if (len(rows) != 1 or rows[0].get("status") != "ok" or rows[0].get("type") != "file"
                or rows[0].get("destination") != expected_dest or rows[0].get("service") is not None):
            raise ReviewInputError(f"manifest must identify one successful file: {src}")
        path = safe_file(source, "artifacts/" + PurePosixPath(src).as_posix().lstrip("/"))
        limit = MAX_FILE if src.endswith("answer.md") else MAX_BUNDLE
        if path.stat().st_size <= 0 or path.stat().st_size > limit:
            raise ReviewInputError(f"source artifact exceeds its byte limit: {src}")
        artifacts[src] = path.read_bytes()
    binding = {
        "schema": "compchembench.case09-harbor-attempt-binding/v1",
        "trial_id": str(result.get("id", "")), "trial_name": result.get("trial_name"),
        "task_name": result.get("task_name"), "source_task_checksum": result.get("task_checksum"),
        "source_task_lock_digest": lock.get("task", {}).get("digest"),
        "task_source": result.get("source"),
        "answer_sha256": sha(artifacts["/app/final/answer.md"]),
        "evidence_bundle_sha256": sha(artifacts["/app/final/evidence.zip"]),
        "source_result_sha256": sha(result_raw), "source_lock_sha256": sha(lock_raw),
        "image_id_status": "NOT_RECORDED",
    }
    if not all(binding[k] for k in ("trial_id", "trial_name", "task_name", "source_task_checksum", "source_task_lock_digest")):
        raise ReviewInputError("Harbor source result lacks stable trial/task identity or task checksum")
    if not isinstance(lock, dict):
        raise ReviewInputError("Harbor lock.json is invalid")
    verification, _ = read_json(safe_file(source, "verifier/verification.json"))
    if verification.get("status") != "REVIEW_REQUIRED" or "reward" in verification:
        raise ReviewInputError("source verifier record must be an unscored REVIEW_REQUIRED result")
    source_inputs = {}
    input_paths = {
        "instruction": ROOT / "instruction.md", "task": ROOT / "task.toml",
        "verify": TESTS / "verify.py", "test": TESTS / "test.sh",
        "policy": POLICY, "refs": TESTS / "refs.json",
        "host_bridge": Path(__file__).resolve(),
    }
    for path in sorted((ROOT / "environment").rglob("*")):
        if path.is_file() and not path.is_symlink():
            input_paths[f"environment/{path.relative_to(ROOT / 'environment').as_posix()}"] = path
    for label, path in input_paths.items():
        source_inputs[label] = sha(path.read_bytes())
    binding["question_sha256"] = source_inputs["instruction"]
    binding["grading_inputs_sha256"] = source_inputs
    binding["artifact_manifest_sha256"] = sha(manifest_raw)
    return binding, result, artifacts


def prepare_payload(source: Path, review_dir: Path) -> str:
    binding, _, artifacts = source_binding(source)
    docs, raw_docs = {}, {}
    for name in FILES:
        docs[name], raw_docs[name] = read_json(review_dir / name)
    review = docs[FILES[0]]
    attempt, provenance, receipt = docs[FILES[1]], docs[FILES[2]], docs[FILES[3]]
    policy, raw_policy = read_json(POLICY)
    if (policy.get("schema") != "ihf-case09-reviewer-policy/v1"
            or policy.get("host_provenance_required") is not True
            or not isinstance(policy.get("authorized_reviewers"), list)
            or review.get("reviewer_id") not in policy["authorized_reviewers"]):
        raise ReviewInputError("task policy does not authorize this reviewer")
    answer, bundle = artifacts["/app/final/answer.md"], artifacts["/app/final/evidence.zip"]
    if attempt != binding or review.get("attempt_binding") != binding:
        raise ReviewInputError("review binding does not match recomputed source trial")
    if (review.get("schema") != "ihf-case09-trusted-scientific-review/v3"
            or review.get("review_kind") not in {"scientific_review", "protocol_fixture"}):
        raise ReviewInputError("review must use supported v3 schema and explicit review_kind")
    if (review.get("question_sha256") != sha(QUESTION.read_bytes())
            or review.get("answer_sha256") != sha(answer)
            or review.get("evidence_bundle_sha256") != sha(bundle)):
        raise ReviewInputError("review question/artifact hashes do not match source")
    if review.get("reviewer_id") not in policy.get("authorized_reviewers", []):
        raise ReviewInputError("reviewer is not authorized by task policy")
    review_raw = raw_docs[FILES[0]]
    if (provenance.get("schema") != "compchembench.case09-review-provenance-mount/v1"
            or provenance.get("review_sha256") != sha(review_raw)
            or provenance.get("reviewer_id") != review.get("reviewer_id")
            or provenance.get("attempt_binding") != binding
            or provenance.get("reviewer_policy_sha256") != sha(raw_policy)
            or provenance.get("review_receipt_sha256") != sha(raw_docs[FILES[3]])):
        raise ReviewInputError("provenance does not bind review, policy, receipt, and source trial")
    if (receipt.get("schema") != "compchembench.case09-review-receipt/v1"
            or receipt.get("reviewer_id") != review.get("reviewer_id")
            or receipt.get("reviewed_at") != provenance.get("reviewed_at")
            or receipt.get("review_method") != provenance.get("review_method")
            or receipt.get("review_sha256") != sha(review_raw)
            or receipt.get("attempt_binding") != binding
            or receipt.get("reviewer_policy_sha256") != sha(raw_policy)):
        raise ReviewInputError("review receipt does not bind review, reviewer, policy, and source")
    known = {sha(answer)} | zip_member_hashes(bundle)
    for dimension in review.get("dimensions", {}).values():
        for cite in dimension.get("evidence", []):
            if cite.get("source_sha256") not in known:
                raise ReviewInputError("citation source_sha256 does not match submitted answer/evidence bytes")
    for claim in review.get("numeric_claim_review", {}).get("claims", []):
        for cite in claim.get("evidence", []):
            if cite.get("source_sha256") not in known:
                raise ReviewInputError("numeric citation source_sha256 does not match submitted bytes")
    payload = {"trusted_review": review, "attempt_binding": binding, "provenance": provenance,
               "policy": policy, "receipt": receipt,
               "trusted_review_raw_b64": base64.b64encode(review_raw).decode(),
               "policy_raw_b64": base64.b64encode(raw_policy).decode(),
               "receipt_raw_b64": base64.b64encode(raw_docs[FILES[3]]).decode()}
    encoded = base64.b64encode(json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()).decode()
    if len(encoded) > MAX_PAYLOAD:
        raise ReviewInputError("trusted review exceeds the 64 KiB verifier environment limit")
    return encoded


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)
    prep = sub.add_parser("prepare", help="freeze a binding for a completed Harbor source trial")
    prep.add_argument("source", type=Path)
    prep.add_argument("--out", type=Path, required=True)
    score = sub.add_parser("score", help="preflight host review then run native Harbor regrade")
    score.add_argument("source", type=Path)
    score.add_argument("review", type=Path)
    score.add_argument("--out", type=Path, required=True)
    score.add_argument("--name", default="case09-trusted-regrade")
    args = parser.parse_args()
    try:
        if args.cmd == "prepare":
            binding, _, _ = source_binding(args.source.resolve())
            args.out.mkdir(parents=True, exist_ok=True)
            target = args.out / "case09_attempt_binding.json"
            if target.exists():
                raise ReviewInputError(f"refusing to overwrite {target}")
            target.write_text(json.dumps(binding, indent=2) + "\n", encoding="utf-8")
            print(target)
            return 0
        encoded = prepare_payload(args.source.resolve(), args.review.resolve())
        args.out.mkdir(parents=True, exist_ok=True)
        harbor = str(Path(sys.executable).with_name("harbor"))
        command = [harbor, "trial", "regrade", str(args.source.resolve()),
                   "--task-path", str(ROOT), "--trials-dir", str(args.out.resolve()),
                   "--trial-name", args.name, "--verifier-env", f"{ENV_KEY}={encoded}"]
        result_dir = args.out / args.name
        if result_dir.exists():
            raise ReviewInputError(f"refusing to overwrite regrade output {result_dir}")
        subprocess.run(command, check=False)
        result_path = result_dir / "result.json"
        if not result_path.is_file() or result_path.is_symlink():
            print("ERROR: Harbor regrade did not produce result.json", file=sys.stderr)
            return 2
        result, _ = read_json(result_path)
        verifier_path = result_dir / "verifier" / "verification.json"
        if not verifier_path.is_file() or verifier_path.is_symlink():
            print("ERROR: Harbor regrade did not produce verification.json", file=sys.stderr)
            return 2
        verification, _ = read_json(verifier_path)
        exception = result.get("exception_info")
        if exception is not None and exception.get("exception_type") != "RewardFileNotFoundError":
            print(f"ERROR: Harbor recorded an execution or infrastructure exception; inspect {result_path}", file=sys.stderr)
            return 2
        if verification.get("status") == "REVIEW_REQUIRED" and "reward" not in verification:
            print(f"REVIEW_REQUIRED: regrade completed without a scientific score; native output: {result_path}")
            return 3
        if exception is not None:
            print(f"ERROR: Harbor recorded an exception for a scored verdict; inspect {result_path}", file=sys.stderr)
            return 2
        if verification.get("status") not in {"PASS", "FAIL"} or "reward" not in verification:
            print(f"ERROR: regrade did not produce a scored scientific PASS/FAIL; inspect {result_path}", file=sys.stderr)
            return 2
        expected_reward = 1 if verification["status"] == "PASS" else 0
        native_rewards = (result.get("verifier_result") or {}).get("rewards")
        if (verification["reward"] != expected_reward or not isinstance(native_rewards, dict)
                or native_rewards.get("reward") != verification["reward"]):
            print(f"ERROR: Harbor reward disagrees with verification.json; inspect {result_path}", file=sys.stderr)
            return 2
        print(f"{verification['status']}: native Harbor result at {result_path}")
        return 0
    except (ReviewInputError, OSError, zipfile.BadZipFile) as exc:
        parser.exit(2, f"ERROR: {exc}\n")


if __name__ == "__main__":
    raise SystemExit(main())
