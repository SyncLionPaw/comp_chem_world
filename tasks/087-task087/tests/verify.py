# 人工审核：自动检查结果供参考，科学结论需人工复核。
"""Machine-check only for open-research submission completeness.

This module never executes candidate commands or assesses scientific claims.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
import stat
from pathlib import Path, PurePosixPath
from typing import Any

SCHEMA = "bench13-open-research-manifest/v1"
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
CLAIM_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


class SubmissionIssue(ValueError):
    pass


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise SubmissionIssue("duplicate JSON key")
        result[key] = value
    return result


def _constant(value):
    raise SubmissionIssue("non-finite JSON number: " + value)


def _json(path: Path) -> Any:
    try:
        parsed = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=_pairs,
                            parse_constant=_constant)
        def check_finite(value):
            if isinstance(value, float) and not math.isfinite(value):
                raise SubmissionIssue("non-finite JSON number")
            if isinstance(value, dict):
                for child in value.values():
                    check_finite(child)
            elif isinstance(value, list):
                for child in value:
                    check_finite(child)
        check_finite(parsed)
        return parsed
    except SubmissionIssue:
        raise
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise SubmissionIssue("research manifest is missing or invalid JSON") from exc


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _nonempty_text(value: Any, maximum: int = 10000) -> bool:
    return isinstance(value, str) and bool(value.strip()) and len(value.encode("utf-8")) <= maximum


def _safe_relative(final: Path, value: Any) -> tuple[str, Path]:
    if (not isinstance(value, str) or not value or "\\" in value or "\x00" in value
            or len(value.encode("utf-8")) > 1024):
        raise SubmissionIssue("artifact path is malformed")
    pure = PurePosixPath(value)
    if (pure.is_absolute() or pure.as_posix() != value or not pure.parts
            or pure.parts[0] != "final" or any(part in {"", ".", ".."} for part in pure.parts)):
        raise SubmissionIssue("artifact path must remain inside final/")
    current = final.parent
    for index, part in enumerate(pure.parts):
        current = current / part
        try:
            mode = current.lstat().st_mode
        except OSError as exc:
            raise SubmissionIssue("declared artifact is missing") from exc
        if stat.S_ISLNK(mode):
            raise SubmissionIssue("artifact path contains a symlink")
        if index < len(pure.parts) - 1 and not stat.S_ISDIR(mode):
            raise SubmissionIssue("artifact path has a non-directory ancestor")
    info = current.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
        raise SubmissionIssue("artifact must be a single-link regular file")
    return pure.as_posix(), current


def _inventory(final: Path) -> set[str]:
    found = set()
    for current, dirs, files in os.walk(final, topdown=True, followlinks=False):
        base = Path(current)
        for name in dirs:
            path = base / name
            mode = path.lstat().st_mode
            if stat.S_ISLNK(mode) or not stat.S_ISDIR(mode):
                raise SubmissionIssue("final contains a linked or special directory")
        for name in files:
            path = base / name
            mode = path.lstat().st_mode
            if not stat.S_ISREG(mode) or stat.S_ISLNK(mode) or path.stat().st_nlink != 1:
                raise SubmissionIssue("final contains a linked or special file")
            found.add(path.relative_to(final.parent).as_posix())
    return found


def validate_submission(app: Path) -> dict[str, Any]:
    """Score submission completeness only; never assess scientific validity."""
    app = Path(app)
    final = app / "final"
    checks = [
        {"name": "report_and_manifest", "passed": False, "detail": "not checked"},
        {"name": "artifact_integrity", "passed": False, "detail": "not checked"},
        {"name": "claim_evidence_links", "passed": False, "detail": "not checked"},
        {"name": "reproducibility_record", "passed": False, "detail": "not checked"},
    ]

    def finish(status: str, summary: str = "") -> dict[str, Any]:
        rubric = []
        earned = 0.0
        for check in checks:
            points = 0.1 if status == "REQUIRE_REVIEW" and check["passed"] else 0.0
            earned += points
            rubric.append({**check, "points": points, "max_points": 0.1})
        return {
            "status": status, "reward": round(earned, 4),
            "reward_scope": "evidence_completeness_only", "require_review": True,
            "scientific_review": "REQUIRE_REVIEW", "scientific_score": None,
            "machine_evidence_passed": status == "REQUIRE_REVIEW" and earned == 0.4,
            "completeness_rubric": rubric,
            "summary": summary or "This score measures submission record completeness only; scientific validity was not reviewed.",
        }
    try:
        if final.is_symlink() or not final.is_dir():
            raise SubmissionIssue("final output directory is missing or redirected")
        report_rel, report = _safe_relative(final, "final/research-report.md")
        manifest_rel, manifest_path = _safe_relative(final, "final/research-manifest.json")
        if report.stat().st_size <= 0 or not report.read_text(encoding="utf-8").strip():
            raise SubmissionIssue("research report is empty")
        manifest = _json(manifest_path)
        required_manifest_fields = {"claims", "artifacts", "reproducibility"}
        allowed_manifest_fields = required_manifest_fields | {"schema"}
        if (not isinstance(manifest, dict)
                or not required_manifest_fields <= set(manifest)
                or not set(manifest) <= allowed_manifest_fields):
            raise SubmissionIssue("research manifest has unknown or missing top-level fields")
        if "schema" in manifest and manifest["schema"] != SCHEMA:
            raise SubmissionIssue("research manifest schema is unsupported")
        checks[0].update(passed=True, detail="non-empty report and supported manifest schema are present")

        artifacts = manifest.get("artifacts")
        if not isinstance(artifacts, list) or not artifacts:
            raise SubmissionIssue("manifest must list the research report artifact")
        declared: dict[str, Path] = {}
        for item in artifacts:
            if (not isinstance(item, dict) or "path" not in item
                    or not set(item) <= {"path", "bytes", "sha256"}):
                raise SubmissionIssue("artifact entry fields are malformed")
            rel, path = _safe_relative(final, item["path"])
            if rel == manifest_rel or rel in declared:
                raise SubmissionIssue("artifact path is duplicated or self-referential")
            actual_bytes = path.stat().st_size
            actual_sha256 = _sha256(path)
            if "bytes" in item and (type(item["bytes"]) is not int
                                    or item["bytes"] < 0
                                    or actual_bytes != item["bytes"]):
                raise SubmissionIssue("artifact byte length is mismatched")
            if "sha256" in item:
                if (not isinstance(item["sha256"], str)
                        or not SHA256_RE.fullmatch(item["sha256"])
                        or actual_sha256 != item["sha256"]):
                    raise SubmissionIssue("artifact bytes do not match the declared hash")
            declared[rel] = path
        if report_rel not in declared:
            raise SubmissionIssue("research report must be included in artifact inventory")
        observed_files = _inventory(final) - {manifest_rel}
        if observed_files != set(declared):
            raise SubmissionIssue("artifact inventory does not exactly match collected files")
        checks[1].update(passed=True, detail="listed artifacts are safe regular files with matching size and SHA-256")

        claims = manifest.get("claims")
        claims_ok = isinstance(claims, list) and bool(claims)
        ids, cited = set(), False
        if claims_ok:
            for claim in claims:
                if (not isinstance(claim, dict) or set(claim) != {"claim_id", "claim_text", "status", "evidence_paths"}
                        or not isinstance(claim.get("claim_id"), str)
                        or not CLAIM_ID_RE.fullmatch(claim["claim_id"])
                        or claim["claim_id"] in ids
                        or not _nonempty_text(claim.get("claim_text"))
                        or claim.get("status") not in {"observed", "inferred", "unresolved"}
                        or not isinstance(claim.get("evidence_paths"), list)):
                    claims_ok = False
                    break
                ids.add(claim["claim_id"])
                evidence = claim["evidence_paths"]
                if any(not isinstance(path, str) for path in evidence) or len(set(evidence)) != len(evidence):
                    claims_ok = False
                    break
                if claim["status"] in {"observed", "inferred"} and not evidence:
                    claims_ok = False
                    break
                for evidence_path in evidence:
                    rel, _path = _safe_relative(final, evidence_path)
                    if rel not in declared:
                        claims_ok = False
                        break
                if not claims_ok:
                    break
                cited |= bool(evidence)
        if claims_ok and cited:
            checks[2].update(passed=True, detail="claim identifiers and statuses are valid; evidence paths resolve to listed files")
        else:
            checks[2]["detail"] = "claims or evidence references are absent or incomplete"

        repro = manifest.get("reproducibility")
        repro_ok = (isinstance(repro, dict)
                    and set(repro) == {"execution_status", "execution_evidence_paths", "commands", "software", "data_sources"}
                    and repro.get("execution_status") in {"not_run", "executed"}
                    and isinstance(repro.get("execution_evidence_paths"), list)
                    and isinstance(repro.get("commands"), list)
                    and isinstance(repro.get("software"), list)
                    and isinstance(repro.get("data_sources"), list))
        if repro_ok:
            repro_ok = all(_nonempty_text(value) for value in repro["commands"] + repro["software"])
            paths = repro["execution_evidence_paths"]
            if repro["execution_status"] == "executed":
                repro_ok = repro_ok and bool(paths) and bool(repro["commands"]) and bool(repro["software"])
            else:
                repro_ok = repro_ok and not paths
            for value in paths:
                if not isinstance(value, str) or _safe_relative(final, value)[0] not in declared:
                    repro_ok = False
                    break
            for source in repro["data_sources"]:
                if (not isinstance(source, dict) or set(source) != {"description", "license"}
                        or not _nonempty_text(source.get("description"))
                        or not _nonempty_text(source.get("license"))):
                    repro_ok = False
                    break
        if repro_ok:
            checks[3].update(passed=True, detail="reproducibility record is complete; not_run earns documentation credit, not execution credit")
        else:
            checks[3]["detail"] = "reproducibility record or execution evidence references are incomplete"

        return finish("REQUIRE_REVIEW")
    except (SubmissionIssue, OSError, UnicodeError, TypeError, ValueError) as exc:
        return finish("INVALID", f"Unsafe or incomplete submission; no completeness points awarded: {exc}")


def main() -> int:
    app = Path(os.environ.get("APP", "/app"))
    logs = Path(os.environ.get("LOGS", "/logs/verifier"))
    logs.mkdir(parents=True, exist_ok=True)
    for stale in ("reward.txt", "reward.json", "verification.json"):
        (logs / stale).unlink(missing_ok=True)
    try:
        result = validate_submission(app)
    except Exception as exc:
        result = {"status": "ERROR", "reward": None,
                  "reward_scope": "evidence_completeness_only", "require_review": True,
                  "scientific_review": "REQUIRE_REVIEW", "scientific_score": None,
                  "summary": f"Verifier failure: {type(exc).__name__}: {exc}"}
        (logs / "verification.json").write_text(json.dumps(result) + "\n", encoding="utf-8")
        print(json.dumps(result))
        return 2
    (logs / "verification.json").write_text(json.dumps(result, ensure_ascii=False) + "\n", encoding="utf-8")
    (logs / "reward.txt").write_text(f"{result['reward']:.4f}\n", encoding="ascii")
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
