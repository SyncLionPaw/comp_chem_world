#!/usr/bin/env python3
# 人工审核：自动检查结果供参考，科学结论需人工复核。
"""Fail-closed protocol for evaluator-provided scientific review."""
from __future__ import annotations

import hashlib
import base64
import csv
import io
import json
import math
import os
import re
import stat
import sys
import zipfile
from pathlib import Path, PurePosixPath

QUESTION_SHA256 = "02637e207cb60f115ea6c1f1cc11b4910b337c78782505cb2aebb7fac017f7af"
ANSWER_PATH = Path("/app/final/answer.md")
BUNDLE_PATH = Path("/app/final/evidence.zip")
TRUSTED_REVIEW_PATH = Path("/tests/trusted_review.json")
TRUSTED_ATTEMPT_BINDING_PATH = Path("/tests/case09_attempt_binding.json")
TRUSTED_REVIEW_PROVENANCE_PATH = Path("/tests/case09_review_provenance.json")
TRUSTED_REVIEW_ENV = "CASE09_TRUSTED_REVIEW_B64"
TRUSTED_REVIEWER_POLICY_PATH = Path("/tests/_data/trusted-review-policy.json")
DIMENSIONS = (
    "mechanism",
    "roughness_causality",
    "experimental_scope",
    "reproducibility",
    "uncertainty",
)
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
MAX_ANSWER_BYTES = 2_000_000
MAX_BUNDLE_BYTES = 100_000_000
MAX_REVIEW_BYTES = 2_000_000
MAX_ZIP_MEMBERS = 5_000
MAX_UNPACKED_BYTES = 200_000_000
MAX_CURVE_ROWS = 50_000
RESERVED_MEMBER_NAMES = {"review.json", "trusted_review.json"}
LENGTH_TO_NM = {"angstrom": 0.1, "Å": 0.1, "A": 0.1, "nm": 1.0, "um": 1000.0, "µm": 1000.0, "μm": 1000.0}


def _logs_dir() -> Path:
    return Path(os.environ.get("BENCH_LOGS") or os.environ.get("LOGS") or "/logs/verifier")


class CandidateError(Exception):
    """Malformed or unsafe candidate artifacts; this receives reward zero."""


class TrustedReviewError(Exception):
    """Damaged or unbound evaluator-side review; this receives exit code two."""


def _strict_json(text: str):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError(f"duplicate JSON key: {key}")
            result[key] = value
        return result

    def bad_constant(value):
        raise ValueError(f"non-finite JSON constant: {value}")

    return json.loads(text, object_pairs_hook=pairs, parse_constant=bad_constant)


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _regular_file(path: Path, max_bytes: int, description: str) -> bytes:
    try:
        info = path.lstat()
    except OSError as exc:
        raise CandidateError(f"{description} is missing: {exc}") from exc
    if not stat.S_ISREG(info.st_mode) or info.st_size <= 0 or info.st_size > max_bytes:
        raise CandidateError(f"{description} must be a nonempty regular file within its size limit")
    try:
        data = path.read_bytes()
    except OSError as exc:
        raise CandidateError(f"{description} cannot be read: {exc}") from exc
    if len(data) != info.st_size:
        raise CandidateError(f"{description} changed while being read")
    return data


def _validate_bundle(data: bytes) -> None:
    import io

    try:
        with zipfile.ZipFile(io.BytesIO(data), "r") as bundle:
            infos = bundle.infolist()
            if not infos or len(infos) > MAX_ZIP_MEMBERS:
                raise CandidateError("evidence.zip must contain between one and 5000 members")
            names = set()
            total_size = 0
            regular_count = 0
            for info in infos:
                name = info.filename
                path = PurePosixPath(name)
                if (not name or "\\" in name or "\x00" in name or path.is_absolute()
                        or any(part in {"", ".", ".."} for part in path.parts)):
                    raise CandidateError("evidence.zip contains an unsafe member path")
                normalized = path.as_posix()
                if normalized in names:
                    raise CandidateError("evidence.zip contains duplicate member names")
                names.add(normalized)
                if path.name.casefold() in RESERVED_MEMBER_NAMES:
                    raise CandidateError("evidence.zip cannot supply evaluator review files")
                if info.flag_bits & 0x1:
                    raise CandidateError("encrypted evidence.zip members are not accepted")
                total_size += info.file_size
                if total_size > MAX_UNPACKED_BYTES:
                    raise CandidateError("evidence.zip expands beyond the 200 MB limit")
                if info.file_size and info.compress_size == 0:
                    raise CandidateError("evidence.zip contains an invalid compressed member")
                if info.compress_size and info.file_size / info.compress_size > 1000:
                    raise CandidateError("evidence.zip contains an excessive compression ratio")
                mode = (info.external_attr >> 16) & 0xFFFF
                file_type = stat.S_IFMT(mode)
                if file_type not in {0, stat.S_IFREG, stat.S_IFDIR}:
                    raise CandidateError("evidence.zip may contain only ordinary files and directories")
                if not info.is_dir():
                    regular_count += 1
            if regular_count == 0:
                raise CandidateError("evidence.zip must contain at least one regular evidence file")
            bad_member = bundle.testzip()
            if bad_member is not None:
                raise CandidateError(f"evidence.zip CRC check failed for {bad_member}")
    except CandidateError:
        raise
    except (OSError, zipfile.BadZipFile, RuntimeError, ValueError) as exc:
        raise CandidateError(f"evidence.zip is invalid: {exc}") from exc


def _audit_numeric_checks(bundle_data: bytes, checks: list, answer_text: str) -> dict:
    """Re-fit a reviewer-selected curve directly from a candidate ZIP member."""
    import numpy as np
    from scipy.optimize import curve_fit
    import io as _io

    if not checks:
        return {"status": "INCONCLUSIVE", "checked_claims": [], "unverified_claims": ["no independently recomputable numerical claim was selected"]}
    reports = []
    with zipfile.ZipFile(_io.BytesIO(bundle_data), "r") as bundle:
        for check in checks:
            required = {"claim_id", "dimension", "member", "x_column", "y_column", "model", "x_unit", "claim_unit", "claim_value", "answer_quote", "claim_literal", "relative_tolerance", "minimum_r_squared"}
            if not isinstance(check, dict) or set(check) != required:
                raise TrustedReviewError("trusted review numeric check has invalid keys")
            if check["model"] != "exponential_decay":
                raise TrustedReviewError("trusted review numeric model is unsupported")
            if check["dimension"] not in {"mechanism", "roughness_causality", "experimental_scope", "reproducibility", "uncertainty"}:
                raise TrustedReviewError("trusted review numeric check has an invalid dimension")
            for key in ("claim_id", "member", "x_column", "y_column", "x_unit", "claim_unit", "answer_quote", "claim_literal"):
                _nonempty_text(check[key], f"numeric_check.{key}", 4000)
            quote = check["answer_quote"]
            literal = check["claim_literal"]
            if answer_text.count(quote) != 1 or quote.count(literal) != 1:
                raise TrustedReviewError("trusted numeric claim quote is not an exact, unique span of final/answer.md")
            match = re.fullmatch(r"\s*[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?\s*(angstrom|Å|A|nm|um|µm|μm)\s*", literal)
            if not match:
                raise TrustedReviewError("trusted numeric claim literal must contain one explicit length and supported unit")
            numeric_token = re.match(r"\s*([-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?)", literal)
            if numeric_token is None or float(numeric_token.group(1)) != check["claim_value"] or match.group(1) != check["claim_unit"]:
                raise TrustedReviewError("trusted numeric claim value or unit disagrees with the quoted answer literal")
            if check["member"] not in bundle.namelist():
                reports.append({"claim_id": check["claim_id"], "status": "INCONCLUSIVE", "reason": "referenced curve is absent from evidence.zip"})
                continue
            if check["x_unit"] not in LENGTH_TO_NM or check["claim_unit"] not in LENGTH_TO_NM:
                raise TrustedReviewError("trusted review numeric check uses an unsupported length unit")
            try:
                with bundle.open(check["member"], "r") as raw:
                    with io.TextIOWrapper(raw, encoding="utf-8-sig", newline="") as stream:
                        reader = csv.DictReader(stream)
                        x_values, y_values = [], []
                        for row in reader:
                            if len(x_values) >= MAX_CURVE_ROWS:
                                break
                            x_values.append(float(row[check["x_column"]]))
                            y_values.append(float(row[check["y_column"]]))
                        exceeded_limit = len(x_values) >= MAX_CURVE_ROWS and next(reader, None) is not None
                x = np.asarray(x_values, dtype=float)
                y = np.asarray(y_values, dtype=float)
            except (UnicodeDecodeError, KeyError, TypeError, ValueError, csv.Error) as exc:
                reports.append({"claim_id": check["claim_id"], "status": "INCONCLUSIVE", "reason": f"curve table cannot be parsed: {exc}"})
                continue
            if exceeded_limit:
                reports.append({"claim_id": check["claim_id"], "status": "INCONCLUSIVE", "reason": f"curve exceeds the {MAX_CURVE_ROWS}-row refit limit"})
                continue
            if len(x) < 8 or len(x) != len(y) or not np.isfinite(x).all() or not np.isfinite(y).all() or len(np.unique(x)) < 6:
                reports.append({"claim_id": check["claim_id"], "status": "INCONCLUSIVE", "reason": "curve needs at least eight finite rows and six distinct distances"})
                continue
            # Refit in nm so the claim-unit conversion is checked independently.
            x_nm = x * LENGTH_TO_NM[check["x_unit"]]
            def decay(xx, amplitude, length_nm, offset):
                return offset + amplitude * np.exp(-xx / length_nm)
            span = float(np.ptp(x_nm))
            try:
                params, _ = curve_fit(decay, x_nm, y, p0=(float(y[0]-y[-1]), max(span/3, 1e-6), float(y[-1])), bounds=([-np.inf, 1e-12, -np.inf], [np.inf, np.inf, np.inf]), maxfev=20000)
            except (RuntimeError, ValueError, FloatingPointError) as exc:
                reports.append({"claim_id": check["claim_id"], "status": "INCONCLUSIVE", "reason": f"exponential fit is unresolved: {exc}"})
                continue
            fitted = decay(x_nm, *params)
            denom = float(np.sum((y - float(np.mean(y))) ** 2))
            r_squared = 1.0 - float(np.sum((y-fitted)**2))/denom if denom > 0 else float("nan")
            value_in_claim_unit = float(params[1]) / LENGTH_TO_NM[check["claim_unit"]]
            claim = check["claim_value"]
            tolerance = check["relative_tolerance"]
            min_r2 = check["minimum_r_squared"]
            if not all(isinstance(v, (int, float)) and math.isfinite(v) for v in (claim, tolerance, min_r2)) or tolerance < 0 or tolerance > 0.25 or min_r2 < 0 or min_r2 > 1:
                raise TrustedReviewError("trusted review numeric tolerance or values are invalid")
            if not math.isfinite(r_squared) or r_squared < min_r2:
                status, reason = "INCONCLUSIVE", "curve does not support the selected exponential model at the declared fit threshold"
            elif abs(value_in_claim_unit-claim) > tolerance * max(abs(value_in_claim_unit), 1e-12):
                status, reason = "FAIL", "reported attenuation length disagrees with an independent refit or unit conversion"
            else:
                status, reason = "PASS", "attenuation length agrees with independent exponential refit and unit conversion"
            reports.append({"claim_id": check["claim_id"], "status": status, "fit_length": value_in_claim_unit, "claim_unit": check["claim_unit"], "r_squared": r_squared, "reason": reason})
    all_pass = bool(reports) and all(item["status"] == "PASS" for item in reports)
    has_fail = any(item["status"] == "FAIL" for item in reports)
    return {
        "status": "PASS" if all_pass else ("FAIL" if has_fail else "INCONCLUSIVE"),
        "checked_claims": [f"submitted curve's exponential-fit attenuation length and unit consistency ({x['claim_id']})" for x in reports if x["status"] == "PASS"],
        "unverified_claims": [x["claim_id"] for x in reports if x["status"] != "PASS"],
        "checks": reports,
    }


def _nonempty_text(value, label: str, limit: int = 20_000) -> None:
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise TrustedReviewError(f"trusted review has invalid {label}")


def _trusted_documents() -> tuple[dict, bytes, dict, dict, dict, dict]:
    """Read reviewer material from verifier-only host env, or legacy fixed paths."""
    payload = os.environ.get(TRUSTED_REVIEW_ENV)
    if payload is not None:
        try:
            raw = base64.b64decode(payload, validate=True)
            if not raw or len(raw) > 64 * 1024:
                raise ValueError("payload size is invalid")
            docs = _strict_json(raw.decode("utf-8"))
            expected = {"trusted_review", "attempt_binding", "provenance", "policy", "receipt",
                        "trusted_review_raw_b64", "policy_raw_b64", "receipt_raw_b64"}
            if not isinstance(docs, dict) or set(docs) != expected:
                raise ValueError("payload document keys are invalid")
            object_keys = expected - {"trusted_review_raw_b64", "policy_raw_b64", "receipt_raw_b64"}
            if any(not isinstance(docs[key], dict) for key in object_keys):
                raise ValueError("payload documents must be objects")
            review_raw = base64.b64decode(docs["trusted_review_raw_b64"], validate=True)
            policy_raw = base64.b64decode(docs["policy_raw_b64"], validate=True)
            receipt_raw = base64.b64decode(docs["receipt_raw_b64"], validate=True)
            if (_strict_json(review_raw.decode("utf-8")) != docs["trusted_review"]
                    or _strict_json(policy_raw.decode("utf-8")) != docs["policy"]
                    or _strict_json(receipt_raw.decode("utf-8")) != docs["receipt"]):
                raise ValueError("raw document bytes do not match parsed documents")
            return docs["trusted_review"], review_raw, docs["attempt_binding"], docs["provenance"], docs["policy"], docs["receipt"], policy_raw, receipt_raw
        except (ValueError, UnicodeDecodeError, json.JSONDecodeError, TypeError) as exc:
            raise TrustedReviewError("host-injected reviewer payload is invalid") from exc

    def read_doc(path: Path, label: str) -> tuple[dict, bytes]:
        info = path.lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_size <= 0 or info.st_size > MAX_REVIEW_BYTES:
            raise TrustedReviewError(f"trusted {label} is not a bounded regular file")
        raw = path.read_bytes()
        if len(raw) != info.st_size:
            raise TrustedReviewError(f"trusted {label} changed while being read")
        doc = _strict_json(raw.decode("utf-8"))
        if not isinstance(doc, dict):
            raise TrustedReviewError(f"trusted {label} must be an object")
        return doc, raw

    try:
        review, review_raw = read_doc(TRUSTED_REVIEW_PATH, "review")
    except FileNotFoundError:
        raise
    if review.get("schema") not in {"ihf-case09-trusted-scientific-review/v3"}:
        return review, review_raw, {}, {}, {}, {}, b"", b""
    try:
        binding, _ = read_doc(TRUSTED_ATTEMPT_BINDING_PATH, "attempt binding")
        provenance, _ = read_doc(TRUSTED_REVIEW_PROVENANCE_PATH, "review provenance")
        policy, policy_raw = read_doc(TRUSTED_REVIEWER_POLICY_PATH, "reviewer policy")
        receipt, receipt_raw = read_doc(Path("/tests/case09_review_receipt.json"), "review receipt")
    except (FileNotFoundError, OSError, UnicodeDecodeError, ValueError, json.JSONDecodeError) as exc:
        raise TrustedReviewError("one or more trusted review companion documents are unavailable or invalid") from exc
    return review, review_raw, binding, provenance, policy, receipt, policy_raw, receipt_raw


def _load_trusted_review(answer_hash: str, bundle_hash: str, answer_text: str = "") -> dict:
    try:
        review, raw_review, attempt_binding, provenance, policy, receipt, raw_policy, raw_receipt = _trusted_documents()
    except FileNotFoundError:
        raise
    except TrustedReviewError:
        raise
    except (OSError, UnicodeDecodeError, ValueError, json.JSONDecodeError) as exc:
        raise TrustedReviewError(f"trusted review cannot be inspected: {exc}") from exc
    base_top = {
        "schema", "review_kind", "review_id", "reviewer_id", "question_sha256",
        "answer_sha256", "evidence_bundle_sha256", "dimensions",
    }
    if not isinstance(review, dict) or review.get("schema") not in {
            "ihf-case09-trusted-scientific-review/v1",
            "ihf-case09-trusted-scientific-review/v2",
            "ihf-case09-trusted-scientific-review/v3"}:
        raise TrustedReviewError("trusted review schema keys are invalid")
    if review["schema"].endswith("/v1"):
        expected_top = base_top
    elif review["schema"].endswith("/v2"):
        expected_top = base_top | {"checked_claims", "unverified_claims", "independent_numeric_checks"}
    else:
        expected_top = base_top | {
            "checked_claims", "unverified_scope", "independent_numeric_checks",
            "attempt_binding", "numeric_claim_review",
        }
    if set(review) != expected_top:
        raise TrustedReviewError("trusted review schema keys are invalid")
    if review["review_kind"] not in {"scientific_review", "protocol_fixture"}:
        raise TrustedReviewError("trusted review kind is invalid")
    _nonempty_text(review["review_id"], "review_id", 256)
    _nonempty_text(review["reviewer_id"], "reviewer_id", 256)
    for key in ("question_sha256", "answer_sha256", "evidence_bundle_sha256"):
        if not isinstance(review[key], str) or not SHA256_RE.fullmatch(review[key]):
            raise TrustedReviewError(f"trusted review {key} is not a lowercase SHA-256")
    bound = (review["question_sha256"], review["answer_sha256"], review["evidence_bundle_sha256"])
    if bound != (QUESTION_SHA256, answer_hash, bundle_hash):
        raise TrustedReviewError("trusted review hash binding does not match this question and submission")
    dimensions = review["dimensions"]
    if not isinstance(dimensions, dict) or set(dimensions) != set(DIMENSIONS):
        raise TrustedReviewError("trusted review must assess all five scientific dimensions")
    for name in DIMENSIONS:
        row = dimensions[name]
        if not isinstance(row, dict) or set(row) != {"status", "reason", "evidence"}:
            raise TrustedReviewError(f"trusted review dimension {name} has invalid schema")
        if row["status"] not in {"PASS", "FAIL", "REVIEW_REQUIRED"}:
            raise TrustedReviewError(f"trusted review dimension {name} has invalid status")
        _nonempty_text(row["reason"], f"{name}.reason", 20_000)
        evidence = row["evidence"]
        if not isinstance(evidence, list) or not 1 <= len(evidence) <= 20:
            raise TrustedReviewError(f"trusted review dimension {name} needs one to twenty evidence citations")
        for index, item in enumerate(evidence):
            citation_keys = {"citation", "locator", "supports"}
            if review["schema"].endswith("/v3"):
                citation_keys.add("source_sha256")
            if not isinstance(item, dict) or set(item) != citation_keys:
                raise TrustedReviewError(f"trusted review dimension {name} citation {index} has invalid schema")
            for field in ("citation", "locator", "supports"):
                _nonempty_text(item[field], f"{name}.evidence[{index}].{field}", 4000)
            if review["schema"].endswith("/v3") and (
                    not isinstance(item["source_sha256"], str)
                    or not SHA256_RE.fullmatch(item["source_sha256"])):
                raise TrustedReviewError(f"trusted review dimension {name} citation {index} has invalid source hash")
    if review["schema"].endswith("/v2"):
        for field in ("checked_claims", "unverified_claims"):
            values = review[field]
            if not isinstance(values, list) or len(values) > 100 or any(not isinstance(value, str) or not value.strip() for value in values):
                raise TrustedReviewError(f"trusted review {field} must be a list of nonempty claim descriptions")
        if not review["unverified_claims"]:
            raise TrustedReviewError("trusted review must name claims or scope that remain unverified")
        checks = review["independent_numeric_checks"]
        if not isinstance(checks, list) or len(checks) > 20:
            raise TrustedReviewError("trusted review independent_numeric_checks must be a bounded list")
    if review["schema"].endswith("/v3"):
        for field in ("checked_claims", "unverified_scope"):
            values = review[field]
            if not isinstance(values, list) or len(values) > 100 or any(not isinstance(value, str) or not value.strip() for value in values):
                raise TrustedReviewError(f"trusted review {field} must be a bounded list of nonempty descriptions")
        if not isinstance(review["independent_numeric_checks"], list) or len(review["independent_numeric_checks"]) > 20:
            raise TrustedReviewError("trusted review independent_numeric_checks must be a bounded list")
        if review["attempt_binding"] != attempt_binding:
            raise TrustedReviewError("trusted review attempt binding does not match evaluator context")
        if (policy.get("schema") != "ihf-case09-reviewer-policy/v1"
                or policy.get("host_provenance_required") is not True
                or not isinstance(policy.get("authorized_reviewers"), list)
                or review["reviewer_id"] not in policy["authorized_reviewers"]):
            raise TrustedReviewError("reviewer policy does not authorize this reviewer")
        try:
            policy_path = TRUSTED_REVIEWER_POLICY_PATH
            policy_info = policy_path.lstat()
            if not stat.S_ISREG(policy_info.st_mode) or policy_info.st_size <= 0 or policy_info.st_size > MAX_REVIEW_BYTES:
                raise TrustedReviewError("task reviewer policy is not a bounded regular file")
            task_policy_raw = policy_path.read_bytes()
        except OSError as exc:
            raise TrustedReviewError("task reviewer policy is unavailable") from exc
        if task_policy_raw != raw_policy:
            raise TrustedReviewError("host-injected reviewer policy differs from task policy")
        if (provenance.get("reviewer_policy_sha256") != _sha256(raw_policy)
                or provenance.get("review_receipt_sha256") != _sha256(raw_receipt)):
            raise TrustedReviewError("host reviewer provenance policy or receipt hash mismatch")
        if (receipt.get("schema") != "compchembench.case09-review-receipt/v1"
                or receipt.get("reviewer_id") != review["reviewer_id"]
                or receipt.get("review_sha256") != _sha256(raw_review)
                or receipt.get("attempt_binding") != attempt_binding
                or receipt.get("reviewer_policy_sha256") != provenance.get("reviewer_policy_sha256")
                or not isinstance(receipt.get("reviewed_at"), str) or not receipt["reviewed_at"].strip()
                or not isinstance(receipt.get("review_method"), str) or not receipt["review_method"].strip()):
            raise TrustedReviewError("host review receipt does not bind reviewer, review, policy, and attempt")
        if (provenance.get("schema") != "compchembench.case09-review-provenance-mount/v1"
                or provenance.get("review_sha256") != _sha256(raw_review)
                or provenance.get("reviewer_id") != review["reviewer_id"]
                or not isinstance(provenance.get("reviewed_at"), str)
                or not provenance["reviewed_at"].strip()
                or not isinstance(provenance.get("review_method"), str)
                or not provenance["review_method"].strip()
                or provenance.get("attempt_binding") != attempt_binding
                or not isinstance(provenance.get("reviewer_policy_sha256"), str)
                or not SHA256_RE.fullmatch(provenance["reviewer_policy_sha256"])
                or not isinstance(provenance.get("review_receipt_sha256"), str)
                or not SHA256_RE.fullmatch(provenance["review_receipt_sha256"])):
            raise TrustedReviewError("host reviewer provenance does not bind this review and attempt")
        disposition = review["numeric_claim_review"]
        if not isinstance(disposition, dict) or set(disposition) != {"status", "claims"} or not isinstance(disposition["claims"], list):
            raise TrustedReviewError("trusted numeric claim disposition has invalid schema")
        if disposition["status"] == "NO_MATERIAL_NUMERIC_CLAIMS":
            if disposition["claims"] or review["independent_numeric_checks"]:
                raise TrustedReviewError("no-numeric-claims disposition conflicts with listed claims/checks")
        elif disposition["status"] == "CLAIMS_REVIEWED":
            if not disposition["claims"] or len(disposition["claims"]) > 100:
                raise TrustedReviewError("reviewed numeric claims must be nonempty and bounded")
            for index, claim in enumerate(disposition["claims"]):
                if not isinstance(claim, dict) or set(claim) != {"claim_id", "answer_quote", "status", "reason", "evidence"}:
                    raise TrustedReviewError(f"numeric claim {index} has invalid schema")
                for key in ("claim_id", "answer_quote", "reason"):
                    _nonempty_text(claim[key], f"numeric_claim[{index}].{key}", 4000)
                if answer_text.count(claim["answer_quote"]) != 1:
                    raise TrustedReviewError("numeric claim quote is not an exact unique span of the answer")
                if claim["status"] not in {"PASS", "FAIL", "REVIEW_REQUIRED"}:
                    raise TrustedReviewError("numeric claim status is invalid")
                if not isinstance(claim["evidence"], list) or not claim["evidence"]:
                    raise TrustedReviewError("reviewed numeric claim needs evidence")
                for item in claim["evidence"]:
                    if (not isinstance(item, dict) or set(item) != {"citation", "locator", "supports", "source_sha256"}
                            or not isinstance(item["source_sha256"], str) or not SHA256_RE.fullmatch(item["source_sha256"])):
                        raise TrustedReviewError("numeric claim evidence must bind a source hash and locator")
                    for key in ("citation", "locator", "supports"):
                        _nonempty_text(item[key], f"numeric_claim[{index}].evidence.{key}", 4000)
        else:
            raise TrustedReviewError("numeric claim disposition is invalid")
    return review


def _validate_review_source_hashes(review: dict, answer: bytes, bundle: bytes) -> None:
    allowed = {_sha256(answer)}
    with zipfile.ZipFile(io.BytesIO(bundle), "r") as archive:
        for item in archive.infolist():
            if not item.is_dir():
                with archive.open(item) as stream:
                    allowed.add(_sha256(stream.read()))
    for dimension in review["dimensions"].values():
        for citation in dimension["evidence"]:
            if "source_sha256" in citation and citation["source_sha256"] not in allowed:
                raise TrustedReviewError("scientific review citation source hash does not match submitted bytes")
    for claim in review.get("numeric_claim_review", {}).get("claims", []):
        for citation in claim["evidence"]:
            if citation["source_sha256"] not in allowed:
                raise TrustedReviewError("numeric citation source hash does not match submitted bytes")


def _write_status(logs: Path, status: str, message: str, reward: int | None = None) -> int:
    logs.mkdir(parents=True, exist_ok=True)
    reward_path = logs / "reward.txt"
    verification_path = logs / "verification.json"
    reward_path.unlink(missing_ok=True)
    report = {"status": status, "message": message}
    if reward is not None:
        reward_path.write_text(f"{reward}\n", encoding="utf-8")
        report["reward"] = reward
    verification_path.write_text(json.dumps(report, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")
    if status == "ERROR":
        return 2
    return 0


def main() -> int:
    logs = _logs_dir()
    try:
        answer = _regular_file(ANSWER_PATH, MAX_ANSWER_BYTES, "final/answer.md")
        try:
            decoded = answer.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise CandidateError("final/answer.md must be UTF-8 text") from exc
        if not decoded.strip():
            raise CandidateError("final/answer.md must be nonempty")
        bundle = _regular_file(BUNDLE_PATH, MAX_BUNDLE_BYTES, "final/evidence.zip")
        _validate_bundle(bundle)
    except CandidateError as exc:
        print(f"FAIL: {exc}")
        return _write_status(logs, "FAIL", str(exc), reward=0)

    answer_hash = _sha256(answer)
    bundle_hash = _sha256(bundle)
    try:
        review = _load_trusted_review(answer_hash, bundle_hash, decoded)
        if review["schema"].endswith("/v3"):
            _validate_review_source_hashes(review, answer, bundle)
    except FileNotFoundError:
        print("REVIEW_REQUIRED: no evaluator-provided scientific review is mounted")
        return _write_status(logs, "REVIEW_REQUIRED", "trusted scientific review is not connected")
    except TrustedReviewError as exc:
        print(f"ERROR: {exc}")
        return _write_status(logs, "ERROR", str(exc))

    if review["review_kind"] != "scientific_review":
        print("REVIEW_REQUIRED: protocol-only fixture cannot establish scientific correctness")
        return _write_status(logs, "REVIEW_REQUIRED", "protocol fixture is not a scientific review")
    if review["schema"].endswith("/v1"):
        print("REVIEW_REQUIRED: scientific review lacks independently recomputed numeric evidence")
        return _write_status(logs, "REVIEW_REQUIRED", "trusted review v1 has no independent numeric checks")
    try:
        if review["schema"].endswith("/v3"):
            disposition = review["numeric_claim_review"]
            claims = disposition["claims"]
            claim_statuses = [row["status"] for row in claims]
            if "FAIL" in claim_statuses:
                numeric = {"status": "FAIL", "checked_claims": [row["claim_id"] for row in claims if row["status"] == "PASS"], "unverified_claims": []}
            elif "REVIEW_REQUIRED" in claim_statuses:
                numeric = {"status": "INCONCLUSIVE", "checked_claims": [row["claim_id"] for row in claims if row["status"] == "PASS"], "unverified_claims": [row["claim_id"] for row in claims if row["status"] != "PASS"]}
            else:
                numeric = {"status": "PASS", "checked_claims": [row["claim_id"] for row in claims], "unverified_claims": []}
            if disposition["status"] == "NO_MATERIAL_NUMERIC_CLAIMS":
                numeric = {"status": "PASS", "checked_claims": [], "unverified_claims": []}
            if review["independent_numeric_checks"]:
                computed = _audit_numeric_checks(bundle, review["independent_numeric_checks"], decoded)
                if computed["status"] == "FAIL":
                    numeric["status"] = "FAIL"
                elif computed["status"] != "PASS" and numeric["status"] == "PASS":
                    numeric["status"] = "INCONCLUSIVE"
                numeric["machine_checks"] = computed
        else:
            numeric = _audit_numeric_checks(bundle, review["independent_numeric_checks"], decoded)
    except TrustedReviewError as exc:
        print(f"ERROR: {exc}")
        return _write_status(logs, "ERROR", str(exc))
    report = {
        "checked_claims": review["checked_claims"] + numeric["checked_claims"],
        "unverified_claims": list(dict.fromkeys(
            (review["unverified_scope"] if review["schema"].endswith("/v3") else review["unverified_claims"])
            + numeric["unverified_claims"])),
        "local_numeric_check": numeric,
        "overall_scope": "partial scientific review; this verifier does not establish causal mechanism or complete SFA literature coverage",
    }
    logs.mkdir(parents=True, exist_ok=True)
    (logs / "case09-scientific-scope.json").write_text(json.dumps(report, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")
    if numeric["status"] == "FAIL":
        print("FAIL: independently recomputed numerical claim disagrees with the submitted evidence")
        return _write_status(logs, "FAIL", "independent numeric consistency check failed", reward=0)
    statuses = [review["dimensions"][name]["status"] for name in DIMENSIONS]
    if review["schema"].endswith("/v3") and "FAIL" in statuses:
        print("FAIL: trusted scientific review rejected one or more dimensions")
        return _write_status(logs, "FAIL", "trusted scientific review rejected one or more dimensions", reward=0)
    if numeric["status"] != "PASS":
        print("REVIEW_REQUIRED: no independently checkable scientific numeric claim was established")
        return _write_status(logs, "REVIEW_REQUIRED", "no independently checkable scientific numeric claim was established")
    if "FAIL" in statuses:
        print("FAIL: trusted scientific review rejected one or more dimensions")
        return _write_status(logs, "FAIL", "trusted scientific review rejected one or more dimensions", reward=0)
    if "REVIEW_REQUIRED" in statuses:
        print("REVIEW_REQUIRED: one or more scientific dimensions remain unresolved")
        return _write_status(logs, "REVIEW_REQUIRED", "trusted review leaves one or more dimensions unresolved")
    if review["schema"].endswith("/v3"):
        print("PASS: independent scientific review and all claimed numeric evidence passed")
        return _write_status(logs, "PASS", "all requested dimensions and material claims passed independent review", reward=1)
    print("REVIEW_REQUIRED: local numeric check passed, but the overall scientific question remains outside automatic verification")
    return _write_status(logs, "REVIEW_REQUIRED", "local numeric evidence passed; causal mechanism and complete SFA scope remain unverified")


if __name__ == "__main__":
    try:
        code = main()
    except Exception as exc:
        # Unexpected verifier faults are infrastructure errors, never passes.
        logs = _logs_dir()
        code = _write_status(logs, "ERROR", f"verifier exception: {type(exc).__name__}: {exc}")
    sys.exit(code)
