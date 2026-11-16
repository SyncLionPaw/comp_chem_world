"""Fail-closed scientific-profile primitives for case06.

The current SI decode is not a same-method error budget. This module validates a
future grader-owned calibration profile and keeps numerical comparison separate
from candidate-provided uncertainty claims. It does not turn a draft profile or
synthetic fixture into a scientific PASS.
"""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path


PROFILE_SCHEMA = "case06-science-profile/v1"
EMPIRICAL_PROFILE_SCHEMA = "case06-science-profile/v2"
EMPIRICAL_ACCEPTANCE_MODE = "empirical-3pm/v1"
EMPIRICAL_RESIDUAL_LIMIT_PM = 3.0
METHOD_COLUMNS = ("PBE0|TZVP", "ADMM|TZVP+tzp", "sTDA@PBE0|TZVP")
SI_ROUNDING_HALF_UNIT_PM = 0.005


def _finite_number(value: object) -> bool:
    """JSON numeric values only; bool is a Python int subclass but not a measurement."""
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


class ProfileError(Exception):
    """Malformed grader-owned profile or calibration dependency."""


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def expected_calibration_keys(refs: dict) -> set[str]:
    """Return each non-null same-method published ES bond target exactly once."""
    expected: set[str] = set()
    for ref_id, item in refs.get("items", {}).items():
        if item.get("state") != "ES" or item.get("quantity") != "bond":
            continue
        values = item.get("values", {})
        for method in METHOD_COLUMNS:
            value = values.get(method)
            if value is not None:
                expected.add(f"{ref_id}|{method}")
    return expected


def validate_profile_document(profile: object, refs: dict, refs_sha256: str) -> tuple[dict | None, str]:
    """Validate a profile document; return active profile or a fail-closed reason.

    A profile may be well-formed but unavailable/unreviewed. In that case callers
    must report UNVERIFIED with no reward. Invalid grader-owned bytes are an
    infrastructure error, not a candidate failure.
    """
    if not isinstance(profile, dict):
        raise ProfileError("science profile has an invalid schema")
    if profile.get("schema") == EMPIRICAL_PROFILE_SCHEMA:
        return _validate_empirical_profile(profile, refs, refs_sha256)
    if profile.get("schema") != PROFILE_SCHEMA:
        raise ProfileError("science profile has an invalid schema")
    if profile.get("reference_sha256") != refs_sha256:
        raise ProfileError("science profile is not bound to the frozen SI reference bytes")
    state = profile.get("status")
    if state == "unavailable":
        reasons = profile.get("unavailable_reasons")
        if not isinstance(reasons, list) or not reasons or any(not isinstance(x, str) or not x.strip() for x in reasons):
            raise ProfileError("unavailable science profile must state concrete missing calibration evidence")
        return None, "; ".join(reasons)
    if state != "reviewed":
        raise ProfileError("science profile status must be unavailable or reviewed")
    review = profile.get("review")
    if not isinstance(review, dict) or not isinstance(review.get("review_id"), str) or not review["review_id"].strip():
        raise ProfileError("reviewed science profile lacks a review identity")
    evidence = review.get("evidence")
    if not isinstance(evidence, list) or not evidence:
        raise ProfileError("reviewed science profile lacks calibration evidence references")
    evidence_ids: set[str] = set()
    for item in evidence:
        if (not isinstance(item, dict) or not isinstance(item.get("id"), str)
                or not item["id"].strip() or item["id"] in evidence_ids
                or not isinstance(item.get("path"), str)):
            raise ProfileError("review evidence entries require unique string IDs, paths, and SHA-256")
        evidence_ids.add(item["id"])
        if not isinstance(item.get("sha256"), str) or not re_full_sha(item["sha256"]):
            raise ProfileError("review evidence entries require a SHA-256")
    calibrations = profile.get("bond_calibrations")
    expected = expected_calibration_keys(refs)
    if not isinstance(calibrations, dict) or set(calibrations) != expected:
        raise ProfileError("reviewed profile must cover every non-null published same-method ES bond exactly once")
    for key, item in calibrations.items():
        if not isinstance(item, dict):
            raise ProfileError(f"calibration {key} must be an object")
        for field in ("max_author_uncertainty_pm", "max_candidate_uncertainty_pm", "max_total_tolerance_pm"):
            value = item.get(field)
            if not _finite_number(value) or value < 0:
                raise ProfileError(f"calibration {key} has invalid {field}")
        if item["max_total_tolerance_pm"] + 1e-12 < SI_ROUNDING_HALF_UNIT_PM:
            raise ProfileError(f"calibration {key} total tolerance omits SI rounding")
        if (not isinstance(item.get("evidence_ids"), list) or not item["evidence_ids"]
                or any(not isinstance(x, str) or x not in evidence_ids for x in item["evidence_ids"])):
            raise ProfileError(f"calibration {key} lacks evidence IDs")

    # A reviewed budget alone cannot establish a minimum or a candidate uncertainty.
    # Until native geometry/curvature and vibrational evidence are parsed and bound,
    # this profile remains non-scoring.
    if profile.get("native_uncertainty_adapter") != "case06-native-geometry/v1":
        return None, "reviewed budget lacks the enabled native geometry/curvature uncertainty adapter"
    return profile, "reviewed profile is structurally valid"


def _validate_empirical_profile(profile: dict, refs: dict, refs_sha256: str) -> tuple[dict | None, str]:
    """Validate the grader-owned, Sol/Root reviewed fixed empirical policy.

    This is an empirical task acceptance rule, not a theorem bounding geometry
    error from force or curvature.  The fixed threshold cannot be supplied by a
    candidate and the comparison is recomputed from native final geometries.
    """
    if profile.get("reference_sha256") != refs_sha256:
        raise ProfileError("empirical profile is not bound to the frozen SI references")
    if profile.get("status") != "reviewed" or profile.get("acceptance_mode") != EMPIRICAL_ACCEPTANCE_MODE:
        raise ProfileError("empirical profile must be explicitly reviewed with empirical-3pm/v1 mode")
    if profile.get("same_method_residual_limit_pm") != EMPIRICAL_RESIDUAL_LIMIT_PM:
        raise ProfileError("empirical profile must use the reviewed fixed 3.0 pm residual limit")
    if (type(profile.get("minimum_frequency_review_band_cm1")) not in (int, float)
            or profile.get("minimum_frequency_review_band_cm1") != 10.0):
        raise ProfileError("empirical profile must use the reviewed 10.0 cm^-1 minimum-frequency review band")
    if profile.get("aggregation") != "tracked-SI-bond-rows/equal-weight-after-symmetry-means":
        raise ProfileError("empirical profile aggregation scope is not the reviewed tracked-row convention")
    scope = profile.get("scope")
    if not isinstance(scope, dict) or scope.get("molecules") != ["M2", "M3", "M14", "M19", "M29"]:
        raise ProfileError("empirical profile scope must identify the five tracked case06 molecules")
    if scope.get("excluded_null_targets") != ["M14/ES/stda-pbe0-tzvp"]:
        raise ProfileError("empirical profile must explicitly exclude the null M14 default sTDA target")
    review = profile.get("review")
    if not isinstance(review, dict) or not isinstance(review.get("review_id"), str) or not review["review_id"].strip():
        raise ProfileError("empirical profile lacks a review identity")
    evidence = review.get("evidence")
    if not isinstance(evidence, list) or not evidence:
        raise ProfileError("empirical profile lacks review evidence")
    evidence_ids: set[str] = set()
    for item in evidence:
        if (not isinstance(item, dict) or not isinstance(item.get("id"), str) or not item["id"].strip()
                or item["id"] in evidence_ids or not isinstance(item.get("path"), str)
                or not isinstance(item.get("sha256"), str) or not re_full_sha(item["sha256"])):
            raise ProfileError("empirical review evidence requires unique IDs, paths, and SHA-256")
        evidence_ids.add(item["id"])
    return profile, "reviewed empirical 3 pm task-acceptance policy is structurally valid"


def accept_empirical_residual(*, candidate_pm: object, published_pm: object,
                              candidate_coordinate_uncertainty_pm: object = 0.0) -> tuple[bool, dict]:
    """Apply the frozen 3 pm rule to a measurement interval, never candidate U claims."""
    if not _finite_number(candidate_pm) or not _finite_number(published_pm):
        raise ValueError("empirical residual inputs must be finite, non-boolean numbers")
    if not _finite_number(candidate_coordinate_uncertainty_pm) or candidate_coordinate_uncertainty_pm < 0:
        raise ValueError("candidate coordinate precision must be a finite nonnegative checker-derived bound")
    signed = float(candidate_pm) - float(published_pm)
    residual = abs(signed)
    interval_width = float(candidate_coordinate_uncertainty_pm) + SI_ROUNDING_HALF_UNIT_PM
    lower = max(0.0, residual - interval_width)
    upper = residual + interval_width
    decision = ("PASS" if upper <= EMPIRICAL_RESIDUAL_LIMIT_PM else
                "FAIL" if lower > EMPIRICAL_RESIDUAL_LIMIT_PM else "UNVERIFIED")
    return decision == "PASS", {
        "signed_residual_pm": signed,
        "absolute_residual_pm": residual,
        "candidate_coordinate_uncertainty_pm": float(candidate_coordinate_uncertainty_pm),
        "published_si_rounding_half_unit_pm": SI_ROUNDING_HALF_UNIT_PM,
        "absolute_residual_interval_pm": [lower, upper],
        "decision": decision,
        "limit_pm": EMPIRICAL_RESIDUAL_LIMIT_PM,
        "acceptance_mode": EMPIRICAL_ACCEPTANCE_MODE,
    }


def evaluate_residual(*, observed_pm: float, published_pm: float,
                      author_uncertainty_pm: float, candidate_uncertainty_pm: float,
                      max_author_uncertainty_pm: float, max_candidate_uncertainty_pm: float,
                      max_total_tolerance_pm: float) -> tuple[bool, dict]:
    """Evaluate one same-method residual after callers authenticate both uncertainties.

    This function intentionally accepts already-derived uncertainty bounds, not
    candidate-declared JSON numbers. The caller must derive them from bound native
    evidence before using this numerical primitive.
    """
    values = (observed_pm, published_pm, author_uncertainty_pm, candidate_uncertainty_pm,
              max_author_uncertainty_pm, max_candidate_uncertainty_pm, max_total_tolerance_pm)
    if any(not _finite_number(value) for value in values):
        raise ValueError("residual inputs must be finite numbers")
    if min(author_uncertainty_pm, candidate_uncertainty_pm, max_author_uncertainty_pm,
           max_candidate_uncertainty_pm, max_total_tolerance_pm) < 0:
        raise ValueError("uncertainty bounds cannot be negative")
    residual = abs(observed_pm - published_pm)
    total_bound = SI_ROUNDING_HALF_UNIT_PM + author_uncertainty_pm + candidate_uncertainty_pm
    within_caps = (author_uncertainty_pm <= max_author_uncertainty_pm
                   and candidate_uncertainty_pm <= max_candidate_uncertainty_pm
                   and total_bound <= max_total_tolerance_pm)
    return residual <= total_bound and within_caps, {
        "observed_residual_pm": residual,
        "si_rounding_half_unit_pm": SI_ROUNDING_HALF_UNIT_PM,
        "author_uncertainty_pm": author_uncertainty_pm,
        "candidate_uncertainty_pm": candidate_uncertainty_pm,
        "total_bound_pm": total_bound,
        "within_profile_caps": within_caps,
    }


def load_profile(path: Path, refs: dict, refs_sha256: str) -> tuple[dict | None, str]:
    if not path.is_file():
        return None, "same-method error budget is not calibrated"
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProfileError(f"science profile is unreadable: {exc}") from exc
    active, reason = validate_profile_document(raw, refs, refs_sha256)
    if active is not None:
        base = path.parent.resolve()
        for item in active["review"]["evidence"]:
            evidence_path = Path(item["path"])
            if evidence_path.is_absolute():
                raise ProfileError("review evidence path must be relative to the grader tests directory")
            try:
                resolved = (base / evidence_path).resolve(strict=True)
            except (OSError, RuntimeError) as exc:
                raise ProfileError(f"review evidence path cannot be resolved: {item['id']}") from exc
            if not resolved.is_relative_to(base) or not resolved.is_file():
                raise ProfileError("review evidence path escapes the grader tests directory or is not a file")
            if sha256(resolved) != item["sha256"]:
                raise ProfileError(f"review evidence hash mismatch: {item['id']}")
    return active, reason


def re_full_sha(value: str) -> bool:
    return len(value) == 64 and all(c in "0123456789abcdef" for c in value.lower())
