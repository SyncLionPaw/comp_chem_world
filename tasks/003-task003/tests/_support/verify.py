#!/usr/bin/env python3
"""Deterministic public-output checks retained as the v6 refit's static precheck.

For v6, verify_v6.py invokes this module in internal-static-only mode, then independently refits the declared
model protocol. This module never executes submitted fit.py. Legacy receipt code remains for historical protocols;
it is not part of the v6 verification path.

Exit codes: 0 = checkable contract passes, 1 = scientific/output-contract failure, 2 = infrastructure or invocation
failure. It requires numpy for the published frozen-index arrays and linear empirical quantiles.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
import re
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

import numpy as np
from case03_protocol_compat import normalize_v6_protocol

from p01_case03_scientific_review import (
    REVIEW_CONTEXT_SCHEMA as SCIENTIFIC_REVIEW_CONTEXT_SCHEMA,
    ScientificReviewError,
    parse_review_json,
    validate_review,
)

TOL = 1e-8
SCORER_VERSION = "case03-verifier-5.0.0"
MAX_REPORTED_ERRORS = 50
SCIENTIFIC_REVIEW_MOUNT = Path("/trusted/p01-case03-scientific-review")
REQUIRED_ASSETS = {
    "SC-012-D0SC04896H-s115.csv",
    "SC-012-D0SC04896H-s120.csv",
    "SC-012-D0SC04896H-s138.csv",
    "SC-012-D0SC04896H-s131.csv",
    "SC-012-D0SC04896H-s121.csv",
    "SC-012-D0SC04896H-s090.ipynb",
    "fig8a_learning_curve.csv",
    "SC-012-D0SC04896H-s118.npy",
    "SC-012-D0SC04896H-s119.npy",
}
ARMS = {
    "mechanistic": "SC-012-D0SC04896H-s120.csv",
    "no_ts": "SC-012-D0SC04896H-s138.csv",
    "fingerprint": "SC-012-D0SC04896H-s131.csv",
}
CURVE_COLUMNS = {"representation", "source_matrix_file", "n_train", "repeat_index", "split_kind",
                 "paired_split_id", "mae_kcal_mol", "rmse_kcal_mol"}
PRED_COLUMNS = {"representation", "source_matrix_file", "paired_split_id", "n_train", "repeat_index",
                "row_index", "y_true_kcal_mol", "y_pred_kcal_mol"}


class ScienceFailure(Exception):
    pass


class InfrastructureFailure(Exception):
    pass


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return "sha256:" + h.hexdigest()


def _sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _trusted_bytes(path: Path, label: str, *, required_mode: int | None = None) -> bytes:
    if path.is_symlink() or not path.is_file():
        raise InfrastructureFailure(f"trusted scientific review {label} is missing or redirected")
    st = path.stat()
    if st.st_mode & 0o077 or (required_mode is not None and st.st_mode & 0o777 != required_mode):
        raise InfrastructureFailure(f"trusted scientific review {label} permissions are unsafe")
    try:
        raw = path.read_bytes()
        if len(raw) > 1_000_000:
            raise InfrastructureFailure(f"trusted scientific review {label} exceeds its size limit")
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise InfrastructureFailure(f"trusted scientific review {label} is unreadable") from exc
    return raw


def validate_scientific_review_transport(final: Path, context: dict[str, Any], context_raw: bytes,
                                         receipt: dict[str, Any], receipt_raw: bytes) -> dict[str, Any]:
    """Check the protected review using the same schema/binding validator as host staging."""
    if os.environ.get("CCB_P01_CASE03_SCIENTIFIC_REVIEW_REQUIRED") != "1":
        raise InfrastructureFailure("host did not enable the required Case 03 scientific review")
    root = SCIENTIFIC_REVIEW_MOUNT
    if root.is_symlink() or not root.is_dir():
        raise InfrastructureFailure("trusted Case 03 scientific review mount is unavailable")
    review_raw = _trusted_bytes(root / "training-review.json", "record", required_mode=0o600)
    binding_raw = _trusted_bytes(root / "review-context.json", "context", required_mode=0o600)
    try:
        review = parse_review_json(review_raw, "protected review")
        binding = parse_review_json(binding_raw, "protected review context")
        parsed_context = parse_review_json(context_raw, "runner context")
        parsed_receipt = parse_review_json(receipt_raw, "fit replay receipt")
    except ScientificReviewError as exc:
        raise InfrastructureFailure(str(exc)) from exc
    if parsed_context != context or parsed_receipt != receipt:
        raise InfrastructureFailure("runtime context/receipt parse differs from strict JSON")
    review_sha = _sha256_bytes(review_raw)
    context_sha = _sha256_bytes(context_raw)
    receipt_sha = _sha256_bytes(receipt_raw)
    try:
        validated = validate_review(review, final_dir=final, context=context,
                                    context_sha256=context_sha, receipt=receipt,
                                    receipt_sha256=receipt_sha)
    except ScientificReviewError as exc:
        raise InfrastructureFailure(f"protected review validation failed: {exc}") from exc
    expected_binding = {
        "schema": SCIENTIFIC_REVIEW_CONTEXT_SCHEMA,
        "attempt_id": validated["attempt_id"],
        "review_id": validated["review_id"],
        "review_sha256": review_sha,
        "reviewer_id": validated["reviewer_id"],
        "runner_context_sha256": validated["runner_context_sha256"],
        "artifact_manifest_sha256": validated["artifact_manifest_sha256"],
        "replay_receipt_sha256": validated["replay_receipt_sha256"],
        "execution_grid_digest": validated["execution_grid_digest"],
        "criteria_verdicts": validated["criteria_verdicts"],
        "review_status": validated["review_status"],
        "training_pipeline_scientific_review_verified": validated["training_pipeline_scientific_review_verified"],
    }
    if binding != expected_binding:
        raise InfrastructureFailure("host review context differs from shared schema validation")
    status = validated["review_status"]
    if status == "PENDING":
        raise InfrastructureFailure("Case 03 scientific training review is pending")
    if status == "FAIL":
        raise_science_errors(["independent Case 03 scientific training review found a criterion failure"],
                             checked={"training_pipeline_scientific_review_verified": False,
                                      "scientific_training_review_status": status})
    return {"training_pipeline_scientific_review_verified": True,
            "scientific_training_review_status": status, "scientific_training_review_id": review["review_id"]}


def read_json(path: Path, label: str) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ScienceFailure(f"{label} is missing or invalid JSON: {exc}") from exc


def csv_rows(path: Path, required: set[str], label: str) -> list[dict[str, str]]:
    if not path.is_file() or path.is_symlink():
        raise ScienceFailure(f"required output missing or unsafe: {path.name}")
    try:
        with path.open(encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)
            fields = set(reader.fieldnames or [])
            if not required.issubset(fields):
                raise ScienceFailure(f"{label} missing columns: {sorted(required - fields)}")
            rows = list(reader)
    except (OSError, UnicodeError, csv.Error) as exc:
        raise ScienceFailure(f"cannot read {label}: {exc}") from exc
    if not rows:
        raise ScienceFailure(f"{label} has no rows")
    return rows


def finite(row: dict[str, str], name: str, label: str) -> float:
    try:
        value = float(row[name])
    except (KeyError, TypeError, ValueError) as exc:
        raise ScienceFailure(f"{label}: {name} is not numeric") from exc
    if not math.isfinite(value):
        raise ScienceFailure(f"{label}: {name} is not finite")
    return value


def close(a: float, b: float) -> bool:
    return math.isclose(a, b, rel_tol=0.0, abs_tol=TOL)


def index_list_sha256(indices: list[int]) -> str:
    payload = json.dumps(indices, separators=(",", ":")).encode("ascii")
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def index_hash_matches(declared: Any, indices: list[int]) -> bool:
    """Accept canonical bare hex and sha256:-prefixed index-list digests only."""
    if not isinstance(declared, str):
        return False
    match = re.fullmatch(r"(?:sha256:)?([0-9a-f]{64})", declared)
    return bool(match and match.group(1) == index_list_sha256(indices).removeprefix("sha256:"))


def raise_science_errors(errors: list[str], *, checked: dict[str, Any] | None = None) -> None:
    # Deduplicate while preserving first-cause order and cap noisy row-level cascades.
    unique = list(dict.fromkeys(errors))
    payload = {"status": "FAIL", "scorer_version": SCORER_VERSION,
               "coverage": "PARTIAL", "training_execution_verified": False,
               "errors": unique[:MAX_REPORTED_ERRORS]}
    if len(unique) > MAX_REPORTED_ERRORS:
        payload["errors_truncated"] = len(unique) - MAX_REPORTED_ERRORS
    if checked:
        payload["checked"] = checked
    raise ScienceFailure(json.dumps(payload, ensure_ascii=False))


def check_index_vector(value: Any, label: str, expected: list[int], errors: list[str]) -> list[int] | None:
    if not isinstance(value, list) or any(type(i) is not int for i in value):
        errors.append(f"{label} must be a JSON list of integer indices")
        return None
    if len(value) != len(set(value)):
        errors.append(f"{label} contains duplicate indices")
        return None
    if set(value) != set(expected):
        errors.append(f"{label} members do not match the frozen published index set")
        return None
    return value


def check_index_hash(declared: Any, indices: list[int], label: str, errors: list[str]) -> None:
    if not index_hash_matches(declared, indices):
        errors.append(f"{label} must match the SHA-256 of the submitted index list in its declared order")


def finite_json(value: Any, label: str) -> float:
    if type(value) not in (int, float):
        raise ValueError(f"{label} must be a finite JSON number")
    try:
        number = float(value)
    except (OverflowError, ValueError) as exc:
        raise ValueError(f"{label} must be a finite JSON number") from exc
    if not math.isfinite(number):
        raise ValueError(f"{label} must be a finite JSON number")
    return number


def seed_policy_signature(value: Any) -> tuple[type, str] | None:
    """Canonicalize the documented free-form seed description without coercing types."""
    if type(value) is str:
        if not value.strip():
            return None
    elif type(value) is dict:
        if not value:
            return None
    else:
        return None
    try:
        encoded = json.dumps(value, sort_keys=True, separators=(",", ":"),
                             ensure_ascii=False, allow_nan=False)
    except (TypeError, ValueError):
        return None
    return (type(value), encoded)


def check_assets(assets: Path, refs_path: Path) -> dict[str, str]:
    if not assets.is_dir() or assets.is_symlink():
        raise InfrastructureFailure(f"asset directory unavailable: {assets}")
    if not refs_path.is_file():
        raise InfrastructureFailure(f"refs.json unavailable: {refs_path}")
    try:
        refs = json.loads(refs_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise InfrastructureFailure(f"tests/refs.json unreadable: {exc}") from exc
    expected = refs.get("asset_hashes") if isinstance(refs, dict) else None
    if not isinstance(expected, dict):
        raise InfrastructureFailure("tests/refs.json has no asset_hashes object")
    files: dict[str, str] = {}
    by_name: dict[str, str] = {}
    for key, digest in expected.items():
        if not isinstance(key, str) or not key.startswith("assets/") or Path(key).name != key.removeprefix("assets/"):
            raise InfrastructureFailure(f"unsafe or malformed asset hash key: {key!r}")
        name = Path(key).name
        path = assets / name
        if not path.is_file() or path.is_symlink():
            raise InfrastructureFailure(f"package asset unavailable: {path}")
        actual = sha256(path)
        if actual != digest:
            raise InfrastructureFailure(f"package asset hash mismatch: {name}")
        files[name] = actual
        by_name[name] = actual
    missing = REQUIRED_ASSETS - set(files)
    if missing:
        raise InfrastructureFailure(f"tests/refs.json omits required assets: {sorted(missing)}")
    return by_name


def target_table(path: Path) -> dict[int, float]:
    try:
        with path.open(encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)
            if "exp_activation_energy" not in (reader.fieldnames or []):
                raise InfrastructureFailure("s115 asset lacks exp_activation_energy")
            index_name = reader.fieldnames[0]
            result = {}
            for row in reader:
                idx = int(float(row[index_name]))
                result[idx] = float(row["exp_activation_energy"])
    except (OSError, csv.Error, ValueError, TypeError) as exc:
        raise InfrastructureFailure(f"cannot read the packaged public target table: {exc}") from exc
    if len(result) != 443 or set(result) != set(range(443)):
        raise InfrastructureFailure("s115 must contain the ordered 443-row public target table")
    if not all(math.isfinite(v) for v in result.values()):
        raise InfrastructureFailure("s115 contains a non-finite public target")
    return result


def frozen_indices(assets: Path) -> tuple[list[int], list[int]]:
    try:
        train_arr = np.load(assets / "SC-012-D0SC04896H-s119.npy", allow_pickle=False)
        test_arr = np.load(assets / "SC-012-D0SC04896H-s118.npy", allow_pickle=False)
    except Exception as exc:
        raise InfrastructureFailure(f"cannot load the frozen split arrays: {exc}") from exc
    for label, arr in (("train", train_arr), ("test", test_arr)):
        if arr.ndim != 1 or not np.issubdtype(arr.dtype, np.integer):
            raise InfrastructureFailure(f"frozen {label} array must be a one-dimensional integer index vector")
    train, test = train_arr.astype(int).tolist(), test_arr.astype(int).tolist()
    if len(train) != 354 or len(test) != 89 or len(set(train)) != len(train) or len(set(test)) != len(test):
        raise InfrastructureFailure("published frozen split must have 354 unique train and 89 unique test indices")
    if set(train) & set(test) or set(train) | set(test) != set(range(443)):
        raise InfrastructureFailure("published frozen indices do not partition all 443 rows")
    return train, test


def require_output(final: Path, name: str) -> Path:
    path = final / name
    if not path.is_file() or path.is_symlink() or not path.resolve().is_relative_to(final.resolve()):
        raise ScienceFailure(f"required output missing or unsafe: final/{name}")
    return path


def crossover_state(summaries: dict[tuple[int, str], dict]) -> tuple[str, list[int] | None]:
    sizes = sorted({key[0] for key in summaries})
    # A crossing is supported only when adjacent empirical intervals are strictly on opposite sides of zero.
    comps = sorted({c for _, c in summaries})
    for comp in comps:
        if any((n, comp) not in summaries for n in sizes):
            return "inconclusive", None
        series = [summaries[(n, comp)] for n in sizes]
        for n0, n1, left, right in zip(sizes, sizes[1:], series, series[1:]):
            lo0, hi0 = left["ci95"]
            lo1, hi1 = right["ci95"]
            if (hi0 < 0 and lo1 > 0) or (lo0 > 0 and hi1 < 0):
                return "observed", [n0, n1]
        if all(lo > 0 for lo, _ in [x["ci95"] for x in series]) or all(hi < 0 for _, hi in [x["ci95"] for x in series]):
            continue
        return "inconclusive", None
    return "no_crossover_in_tested_range", None


def accepted_crossover_statuses(summaries: dict[tuple[int, str], dict]) -> tuple[set[str], list[int] | None]:
    """Accept descriptive paired-mean crossings and conservative interval-supported crossings."""
    expected_status, expected_interval = crossover_state(summaries)
    if expected_status == "observed":
        return {"observed"}, expected_interval
    sizes = sorted({key[0] for key in summaries})
    comps = sorted({c for _, c in summaries})
    for comp in comps:
        if any((n, comp) not in summaries for n in sizes):
            return {"inconclusive"}, None
        series = [summaries[(n, comp)] for n in sizes]
        means = [row["mean"] for row in series]
        bracket = next(([n0, n1] for n0, n1, left, right in
                        zip(sizes, sizes[1:], means, means[1:])
                        if left * right < 0), None)
        if bracket is not None:
            return {"observed"}, bracket
        if all(value > 0 for value in means) or all(value < 0 for value in means):
            if any(lo <= 0 <= hi for row in series for lo, hi in (row["ci95"],)):
                return {"no_crossover_in_tested_range", "inconclusive"}, None
            return {"no_crossover_in_tested_range"}, None
    return {"inconclusive"}, None


def check_submission(submission: Path, assets: Path, refs_path: Path, *,
                     internal_static_only: bool = False,
                     legacy_static_diagnostic: bool = False,
                     require_replay: bool = False) -> dict[str, Any]:
    errors: list[str] = []
    warnings: list[str] = []
    conditional_interval_ordering_unresolved: list[str] = []
    asset_hashes = check_assets(assets, refs_path)
    train_pool, frozen_test = frozen_indices(assets)
    frozen_train_set, frozen_test_set = set(train_pool), set(frozen_test)
    truth = target_table(assets / "SC-012-D0SC04896H-s115.csv")
    final = submission / "final"
    if not final.is_dir() or final.is_symlink():
        raise ScienceFailure("missing or unsafe final/ submission directory")
    expected_files = ("predictions.csv", "learning_curves.csv", "splits.json", "protocol.json",
                      "paired_summary.json", "crossover.json", "notes.md")
    for name in expected_files:
        require_output(final, name)

    protocol = read_json(final / "protocol.json", "protocol.json")
    splits_doc = read_json(final / "splits.json", "splits.json")
    paired_doc = read_json(final / "paired_summary.json", "paired_summary.json")
    crossover_doc = read_json(final / "crossover.json", "crossover.json")
    if not isinstance(protocol, dict) or not isinstance(splits_doc, dict):
        raise ScienceFailure("protocol.json and splits.json must be JSON objects")
    if protocol.get("scorer_contract_version") in (4, 5):
        require_output(final, "fit.py")

    # Validate split identity and structure before touching predictions/metrics. This avoids
    # cascading one malformed index list into thousands of secondary errors.
    split_errors: list[str] = []
    repeats_declared = splits_doc.get("repeats_per_size")
    sizes = splits_doc.get("sizes")
    # Revision 6 removes the earlier arbitrary exact-20-repeat and 16-size gate.
    if type(repeats_declared) is not int or repeats_declared < 20:
        split_errors.append("splits.repeats_per_size must be an integer of at least 20")
    if (not isinstance(sizes, list) or len(sizes) < 2 or
            any(type(n) is not int or n <= 0 or n > len(train_pool) for n in sizes) or
            sizes != sorted(sizes) or len(sizes) != len(set(sizes))):
        split_errors.append("splits.sizes must contain at least two sorted, unique, positive training sizes within the frozen pool")
        sizes = []

    declared_pool = check_index_vector(splits_doc.get("train_pool_indices"), "train_pool_indices", train_pool, split_errors)
    declared_test = check_index_vector(splits_doc.get("test_indices"), "test_indices", frozen_test, split_errors)
    if declared_pool is not None:
        if splits_doc.get("train_pool_indices_sha256") is not None:
            check_index_hash(splits_doc["train_pool_indices_sha256"], declared_pool,
                             "splits.train_pool_indices_sha256", split_errors)
    if declared_test is not None:
        if splits_doc.get("test_indices_sha256") is not None:
            check_index_hash(splits_doc["test_indices_sha256"], declared_test,
                             "splits.test_indices_sha256", split_errors)
    records = splits_doc.get("records")
    if not isinstance(records, list) or not records:
        split_errors.append("splits.records must be a nonempty list")
        records = []

    split_by_key: dict[tuple[int, int], dict] = {}
    split_id_to_key: dict[str, tuple[int, int]] = {}
    subset_groups: dict[int, set[tuple[int, ...]]] = defaultdict(set)
    for rec in records:
        if not isinstance(rec, dict):
            split_errors.append("splits.records contains a non-object")
            continue
        try:
            n, rep, split_id = rec["n_train"], rec["repeat_index"], rec["paired_split_id"]
            tr, te = rec["train_indices"], rec["test_indices"]
            if type(n) is not int or type(rep) is not int or not isinstance(split_id, str) or not split_id:
                raise ValueError("invalid size/repeat/split identifier")
            key = (n, rep)
            if key in split_by_key or split_id in split_id_to_key:
                raise ValueError("duplicate size/repeat key or paired_split_id")
            if (not isinstance(tr, list) or any(type(i) is not int for i in tr) or
                    len(tr) != n or len(tr) != len(set(tr))):
                raise ValueError("train_indices must be unique integer members with length n_train")
            if not isinstance(te, list) or any(type(i) is not int for i in te) or len(te) != len(set(te)):
                raise ValueError("test_indices must be a unique integer list")
            if set(te) != frozen_test_set:
                raise ValueError("test_indices members do not match frozen s118 test set")
            if rec.get("train_indices_sha256") is not None:
                check_index_hash(rec["train_indices_sha256"], tr, "record.train_indices_sha256", split_errors)
            if rec.get("test_indices_sha256") is not None:
                check_index_hash(rec["test_indices_sha256"], te, "record.test_indices_sha256", split_errors)
            if type(rec.get("seed")) is not int:
                raise ValueError("split record must declare an integer seed")
            if set(tr) & frozen_test_set or not set(tr).issubset(frozen_train_set):
                raise ValueError("train indices overlap frozen test set or leave frozen training pool")
            if n not in sizes or n > len(train_pool):
                raise ValueError("split size is outside declared grid or frozen pool")
            split_by_key[key] = rec
            split_id_to_key[split_id] = key
            subset_groups[n].add(tuple(sorted(tr)))
        except (KeyError, TypeError, ValueError) as exc:
            split_errors.append(f"invalid split record: {exc}")

    # A malformed record is the root cause; do not report derived missing-grid or
    # duplicate-subset errors for records already rejected above.
    if split_errors:
        raise_science_errors(split_errors)

    if type(repeats_declared) is int and repeats_declared > 0 and sizes:
        for n in sizes:
            keys = {r for nn, r in split_by_key if nn == n}
            if keys != set(range(repeats_declared)):
                split_errors.append(f"n={n}: split records do not cover repeats 0..{repeats_declared - 1}")
            if n == len(train_pool):
                if subset_groups[n] != {tuple(sorted(train_pool))}:
                    split_errors.append(f"n={n}: full-pool repeats must use the complete frozen training pool")
            elif len(subset_groups[n]) != repeats_declared:
                split_errors.append(f"n={n}: subsets must be unique below full-pool size")
        required_split_keys = {(n, r) for n in sizes for r in range(repeats_declared)}
        if set(split_by_key) != required_split_keys:
            split_errors.append("split records do not form the complete declared size/repeat grid")
    if split_errors:
        raise_science_errors(split_errors)

    assert declared_pool is not None and declared_test is not None
    assert type(repeats_declared) is int
    declared_pool_hash = index_list_sha256(declared_pool)
    declared_test_hash = index_list_sha256(declared_test)

    try:
        protocol = normalize_v6_protocol(protocol, ARMS, repeats_declared)
    except ValueError as exc:
        errors.append(f"invalid protocol comparison/representation declaration: {exc}")

    if not isinstance(paired_doc, list):
        raise ScienceFailure("paired_summary.json must be a list")
    if not isinstance(crossover_doc, dict):
        raise ScienceFailure("crossover.json must be an object")

    # Protocol and training-code declarations are independent of row-level predictions.
    contract_version = protocol.get("scorer_contract_version")
    if contract_version not in (None, 2, 3, 4, 5, 6):
        errors.append("protocol.scorer_contract_version is unsupported")
    if contract_version in (4, 5):
        machine_checks = ["frozen_indices", "input_hashes", "row_predictions", "derived_metrics",
                          "paired_intervals", "crossover_status"]
        if contract_version in (4, 5):
            machine_checks.append("same_attempt_fit_replay")
        if contract_version == 5:
            machine_checks.extend(["declared_model_spec", "independent_fold_refit"])
        expected_scope = {
            "schema": "case03-deterministic-scope/v1",
            "machine_checked": machine_checks,
            "training_execution_verified": False,
            "arbitrary_fit_internals_verified": False,
            "free_prose_scored": False,
        }
        if protocol.get("deterministic_scope") != expected_scope:
            errors.append("protocol.deterministic_scope must declare the machine-check boundary for this contract version")
    if contract_version in (5, 6):
        model_spec = protocol.get("model_spec")
        if (not isinstance(model_spec, dict) or model_spec.get("schema") != "case03-model-spec/v1"
                or not isinstance(model_spec.get("arms"), dict) or set(model_spec["arms"]) != set(ARMS)):
            errors.append("protocol.model_spec must declare case03-model-spec/v1 for all scored arms")
        if contract_version == 5 and protocol.get("candidate_internals_proven") is not False:
            errors.append("protocol must state candidate_internals_proven=false")
        if contract_version == 5 and protocol.get("declared_protocol_independent_refit_verified") is not True:
            errors.append("historical v5 protocol must declare its independent-refit request")
        comparison_design = protocol.get("comparison_design")
        if contract_version == 6 and (
                not isinstance(comparison_design, str)
                or comparison_design not in ("controlled_representation", "model_selection_combination")):
            errors.append("protocol.comparison_design must identify the controlled-representation or model-selection-combination scope")
    declared_hashes = protocol.get("input_sha256")
    if declared_hashes is not None and not isinstance(declared_hashes, dict):
        errors.append("protocol.input_sha256 must be a filename-to-SHA256 object when supplied")
    elif isinstance(declared_hashes, dict):
        for name, expected in asset_hashes.items():
            if declared_hashes.get(name) != expected:
                errors.append(f"protocol input hash missing or mismatched: {name}")
        if set(declared_hashes) - set(asset_hashes):
            errors.append("protocol.input_sha256 contains an unknown input")
    if contract_version in (4, 5):
        evidence = protocol.get("training_code_evidence")
        actual_fit_hash = sha256(final / "fit.py")
        if not isinstance(evidence, dict) or evidence.get("file") != "fit.py" or evidence.get("sha256") != actual_fit_hash:
            errors.append("historical training_code_evidence must identify final/fit.py and its exact SHA-256")
        if protocol.get("training_execution_verified") is not False:
            errors.append("historical protocol must state training_execution_verified=false")
    if protocol.get("interval_scope") != "training_subset_repeat_conditional_on_frozen_test_set":
        errors.append("protocol must identify repeat intervals as conditional on the frozen test set")
    reps_declared = protocol.get("scored_representations")
    if (not isinstance(reps_declared, list) or any(not isinstance(r, str) for r in reps_declared) or
            len(reps_declared) != len(ARMS) or
            len(set(reps_declared)) != len(ARMS) or set(reps_declared) != set(ARMS)):
        errors.append("protocol.scored_representations must list each required representation exactly once")
    protocol_seed_policy = seed_policy_signature(protocol.get("seed_policy"))
    split_seed_policy = seed_policy_signature(splits_doc.get("seed_policy"))
    if protocol_seed_policy is None or split_seed_policy != protocol_seed_policy:
        errors.append("protocol and splits must declare the same nonempty seed policy")
    if protocol.get("sizes") != sizes or protocol.get("repeats_per_size") != repeats_declared:
        errors.append("protocol grid/repeat count disagrees with splits.json")
    if ((protocol.get("train_pool_indices_sha256") is not None and not index_hash_matches(protocol.get("train_pool_indices_sha256"), declared_pool)) or
            (protocol.get("test_indices_sha256") is not None and not index_hash_matches(protocol.get("test_indices_sha256"), declared_test))):
        errors.append("protocol frozen split hashes must match submitted frozen index lists")
    if protocol.get("same_sampled_training_indices_across_representations") is not True or protocol.get("same_frozen_test_set_across_representations_and_repeats") is not True:
        errors.append("protocol must declare paired training subsets and one shared frozen test set")
    budget = protocol.get("tuning_budget")
    if (not isinstance(budget, dict) or type(budget.get("same_across_scored_arms")) is not bool or
            not any(isinstance(budget.get(field), str) and budget[field].strip()
                    for field in ("description", "note"))):
        errors.append("tuning_budget must declare its cross-arm equality and a nonempty description")
    elif budget["same_across_scored_arms"]:
        if (type(budget.get("candidate_models_per_arm")) is not int or budget["candidate_models_per_arm"] < 1 or
                type(budget.get("inner_folds")) is not int or budget["inner_folds"] < 2):
            errors.append("shared tuning_budget must declare a positive model count and at least two inner folds")
    elif (not isinstance(budget.get("candidate_models_by_arm"), dict) or
          set(budget["candidate_models_by_arm"]) != set(ARMS) or
          any(type(value) is not int or value < 1 for value in budget["candidate_models_by_arm"].values()) or
          not isinstance(budget.get("inner_folds_by_arm"), dict) or
          set(budget["inner_folds_by_arm"]) != set(ARMS) or
          any(type(value) is not int or value < 2 for value in budget["inner_folds_by_arm"].values())):
        errors.append("arm-specific tuning_budget must state positive model counts and at least two folds for every arm")
    prep = protocol.get("learned_preprocessing")
    if not isinstance(prep, dict) or prep.get("fit_within_training_subset") is not True or not isinstance(prep.get("steps"), list) or not prep["steps"]:
        errors.append("learned_preprocessing must declare nonempty steps fit within each training subset")
    versions = protocol.get("software_versions")
    if versions is not None:
        version_keys = {"python": "python", "numpy": "numpy",
                        "scikit_learn": "scikit-learn"}
        if (not isinstance(versions, dict)
                or not all(isinstance(versions.get(alias) or versions.get(key), str)
                           and (versions.get(alias) or versions.get(key)).strip()
                           for key, alias in version_keys.items())):
            errors.append("optional software_versions must state Python, NumPy and scikit-learn versions")
    disclosure = protocol.get("scientific_disclosures")
    if disclosure is not None and not (
            isinstance(disclosure, dict)
            or (isinstance(disclosure, list) and all(isinstance(item, (str, dict)) for item in disclosure))):
        errors.append("scientific_disclosures must be a structured object or list when supplied")

    pred_rows = csv_rows(final / "predictions.csv", PRED_COLUMNS, "predictions.csv")
    pred_map: dict[tuple[str, int, int, int], dict[str, Any]] = {}
    pred_errors: list[str] = []
    rep_seen: set[str] = set()
    for row in pred_rows:
        try:
            rep = row["representation"]
            n, repeat, row_idx = int(row["n_train"]), int(row["repeat_index"]), int(row["row_index"])
            split_id = row["paired_split_id"]
            if rep not in ARMS:
                raise ValueError("unsupported scored representation")
            pred_key = (rep, n, repeat, row_idx)
            if pred_key in pred_map:
                raise ValueError("duplicate prediction row key")
            if split_id not in split_id_to_key or split_id_to_key[split_id] != (n, repeat):
                raise ValueError("prediction paired_split_id does not match declared split")
            if row["source_matrix_file"] != ARMS[rep]:
                raise ValueError("source_matrix_file does not match assessed representation identity")
            yt, yp = finite(row, "y_true_kcal_mol", "predictions.csv"), finite(row, "y_pred_kcal_mol", "predictions.csv")
            if row_idx not in frozen_test_set or not close(yt, truth[row_idx]):
                raise ValueError("prediction target is forged or row_index is outside frozen test set")
            if n not in sizes or (n, repeat) not in split_by_key:
                raise ValueError("prediction has undeclared size/repeat")
            pred_map[pred_key] = {"y_true": yt, "y_pred": yp, "split_id": split_id}
            rep_seen.add(rep)
        except (KeyError, ValueError, TypeError) as exc:
            pred_errors.append(f"invalid prediction row: {exc}")
    if rep_seen != set(ARMS):
        pred_errors.append(f"scored predictions must contain exactly the three required arms; found {sorted(rep_seen)}")
    expected_indices = frozen_test_set
    missing_groups = 0
    mismatched_split_groups = 0
    for rep in rep_seen:
        for (n, repeat), split in split_by_key.items():
            got = {idx for (r, nn, rr, idx) in pred_map if r == rep and nn == n and rr == repeat}
            if got != expected_indices:
                missing_groups += 1
            elif any(pred_map[(rep, n, repeat, idx)]["split_id"] != split["paired_split_id"] for idx in got):
                mismatched_split_groups += 1
    if missing_groups:
        pred_errors.append(f"prediction grid has {missing_groups} representation/split groups not covering the frozen test-set members exactly")
    if mismatched_split_groups:
        pred_errors.append(f"{mismatched_split_groups} prediction groups use a different paired_split_id")
    if pred_errors:
        raise_science_errors(pred_errors)

    curve_rows = csv_rows(final / "learning_curves.csv", CURVE_COLUMNS, "learning_curves.csv")
    curve_map: dict[tuple[str, int, int], dict[str, Any]] = {}
    seen_curve_rows: set[tuple[str, int, int, str]] = set()
    curve_errors: list[str] = []
    for row in curve_rows:
        try:
            rep, n, repeat = row["representation"], int(row["n_train"]), int(row["repeat_index"])
            key = (rep, n, repeat)
            split_kind = row["split_kind"]
            if (rep, n, repeat, split_kind) in seen_curve_rows:
                raise ValueError("duplicate (representation,n_train,repeat_index,split_kind)")
            seen_curve_rows.add((rep, n, repeat, split_kind))
            if rep not in ARMS or (n, repeat) not in split_by_key:
                raise ValueError("curve row references an undeclared representation or split")
            if row["source_matrix_file"] != ARMS[rep]:
                raise ValueError("curve source_matrix_file does not match assessed representation identity")
            split_id = split_by_key[(n, repeat)]["paired_split_id"]
            if (row["paired_split_id"] != split_id
                    or row["split_kind"] not in {"test", "fixed_test_resampled_train"}):
                raise ValueError("curve split identity or split_kind does not match paired fixed-test protocol")
            pred = [pred_map[(rep, n, repeat, idx)] for idx in frozen_test if (rep, n, repeat, idx) in pred_map]
            mae = sum(abs(x["y_pred"] - x["y_true"]) for x in pred) / len(pred)
            rmse = math.sqrt(sum((x["y_pred"] - x["y_true"]) ** 2 for x in pred) / len(pred))
            if not close(finite(row, "mae_kcal_mol", "learning_curves.csv"), mae) or not close(finite(row, "rmse_kcal_mol", "learning_curves.csv"), rmse):
                raise ValueError(f"MAE/RMSE mismatch: recomputed ({mae:.12g}, {rmse:.12g})")
            previous = curve_map.get(key)
            if previous is not None and (not close(previous["mae"], mae) or not close(previous["rmse"], rmse)):
                raise ValueError("split_kind rows disagree on the same frozen test rows")
            curve_map[key] = {"mae": mae, "rmse": rmse}
        except (KeyError, ValueError, TypeError, ZeroDivisionError) as exc:
            curve_errors.append(f"invalid learning-curve row: {exc}")
    required_curve_keys = {(rep, n, r) for rep in ARMS for n in sizes for r in range(repeats_declared)}
    if set(curve_map) != required_curve_keys:
        curve_errors.append(f"learning_curves.csv coverage mismatch: missing={len(required_curve_keys-set(curve_map))}, extra={len(set(curve_map)-required_curve_keys)}")
    if curve_errors:
        raise_science_errors(curve_errors)

    if not paired_doc:
        raise ScienceFailure("paired_summary.json is empty")
    summary_rows: dict[tuple[int, str], dict[str, Any]] = {}
    summary_errors: list[str] = []
    for item in paired_doc:
        try:
            if not isinstance(item, dict) or type(item.get("n_train")) is not int:
                raise ValueError("summary row must declare integer n_train")
            n = item["n_train"]
            explicit = item.get("comparator")
            legacy = item.get("baseline_minus_mechanistic_mae_kcal_mol")
            if isinstance(explicit, str):
                comparator = explicit
                if isinstance(legacy, str) and legacy != comparator:
                    raise ValueError("explicit comparator conflicts with legacy comparator string")
                if type(legacy) is bool and not legacy:
                    raise ValueError("legacy difference-direction flag contradicts comparator-minus-mechanistic definition")
            elif isinstance(legacy, str):
                comparator = legacy
            else:
                raise ValueError("summary row needs comparator; a legacy boolean requires an explicit comparator")
            definition = item.get("difference_definition")
            if definition is not None and definition != "comparator_mae_minus_mechanistic_mae":
                raise ValueError("difference_definition must be comparator_mae_minus_mechanistic_mae")
            key = (n, comparator)
            if key in summary_rows or comparator not in {"no_ts", "fingerprint"}:
                raise ValueError("duplicate or unsupported paired comparator")
            if n not in sizes:
                raise ValueError("summary references undeclared training size")
            diffs = [curve_map[(comparator, n, r)]["mae"] - curve_map[("mechanistic", n, r)]["mae"]
                     for r in range(repeats_declared)]
            mean = sum(diffs) / len(diffs)
            ci = [float(np.quantile(np.asarray(diffs, dtype=float), q, method="linear")) for q in (0.025, 0.975)]
            submitted_ci = item.get("conditional_repeat_percentile_95_interval")
            submitted_diffs = item.get("repeat_differences")
            if not close(finite_json(item.get("mean"), "paired_summary.mean"), mean):
                raise ValueError("paired mean does not recalculate from per-repeat curves")
            if (not isinstance(submitted_ci, list) or len(submitted_ci) != 2 or
                    not all(close(finite_json(a, "paired interval"), b) for a, b in zip(submitted_ci, ci))):
                raise ValueError("95% empirical repeat interval does not recalculate")
            if (not isinstance(submitted_diffs, list) or len(submitted_diffs) != len(diffs) or
                    not all(close(finite_json(a, "repeat difference"), b) for a, b in zip(submitted_diffs, diffs))):
                raise ValueError("paired repeat differences do not recalculate")
            summary_rows[key] = {"mean": mean, "ci95": ci}
        except (KeyError, ValueError, TypeError, OverflowError) as exc:
            summary_errors.append(f"invalid paired summary: {exc}")
    required_summaries = {(n, c) for n in sizes for c in ("no_ts", "fingerprint")}
    if set(summary_rows) != required_summaries:
        summary_errors.append("paired_summary.json coverage mismatch for declared sizes/comparators")
    if summary_errors:
        raise_science_errors(summary_errors)

    status_map = crossover_doc.get("comparisons")
    if not isinstance(status_map, dict) or set(status_map) != {"no_ts", "fingerprint"}:
        raise ScienceFailure("crossover.json must classify no_ts and fingerprint independently")
    for comp in ("no_ts", "fingerprint"):
        item = status_map[comp]
        if not isinstance(item, dict):
            errors.append(f"crossover comparison {comp} must be an object")
            continue
        if not isinstance(item.get("reason"), str) or not item["reason"].strip():
            errors.append(f"{comp}: crossover status must include a nonempty scientific reason")
        relevant = {(n, c): row for (n, c), row in summary_rows.items() if c == comp}
        allowed_statuses, expected_interval = accepted_crossover_statuses(relevant)
        ordered = [relevant[(n, comp)] for n in sizes]
        means = [row["mean"] for row in ordered]
        same_strict_mean_sign = (all(value > 0 for value in means)
                                 or all(value < 0 for value in means))
        basis = item.get("basis")
        if basis is None:
            reason = item.get("reason", "").lower()
            basis = "mean" if "mean" in reason else "interval"
        if basis not in {"mean", "interval"}:
            errors.append(f"{comp}: crossover basis must be 'mean' or 'interval'")
            basis = "interval"
        if basis == "interval":
            interval_status, interval_bracket = crossover_state(relevant)
            if interval_status == "observed":
                # A sign-changing interval pattern may still be reported as inconclusive
                # when the submitted analysis applies a stricter support test.
                allowed_statuses = {"observed", "inconclusive"}
                expected_interval = interval_bracket
            else:
                # Means without a strict sign change support either the descriptive
                # no-crossover label or the more cautious inconclusive label.
                allowed_statuses = {"no_crossover_in_tested_range", "inconclusive"}
                expected_interval = None
        else:
            mean_bracket = next(
                ([sizes[i], sizes[i + 1]] for i, (left, right) in
                 enumerate(zip(means, means[1:])) if left * right < 0), None)
            if mean_bracket is not None:
                expected_interval = mean_bracket
                allowed_statuses = {"observed", "inconclusive"}
            elif all(value > 0 for value in means) or all(value < 0 for value in means):
                interval_unresolved = any(lo <= 0 <= hi for row in ordered
                                          for lo, hi in (row["ci95"],))
                allowed_statuses = ({"no_crossover_in_tested_range", "inconclusive"}
                                    if interval_unresolved else {"no_crossover_in_tested_range"})
                expected_interval = None
            else:
                # Mixed but not strictly sign-changing (e.g. an exact zero mean):
                # "no crossover in tested range" and "inconclusive" are both defensible.
                allowed_statuses = {"no_crossover_in_tested_range", "inconclusive"}
                expected_interval = None
        if item.get("status") not in allowed_statuses:
            errors.append(f"{comp}: crossover status unsupported; expected one of {sorted(allowed_statuses)}")
        if item.get("status") == "observed":
            if "observed" not in allowed_statuses or expected_interval is None:
                errors.append(f"{comp}: observed crossover has no sign-changing adjacent intervals")
            elif item.get("training_size_bracket") != expected_interval or item.get("supporting_summary_rows") != [f"n={expected_interval[0]}", f"n={expected_interval[1]}"]:
                errors.append(f"{comp}: observed crossover must cite exact adjacent summary rows and bracket")
        else:
            if item.get("training_size_bracket") is not None or item.get("supporting_summary_rows") != [f"n={n}" for n in sizes]:
                errors.append(f"{comp}: non-observed status must cite every paired-summary row and no bracket")
        if same_strict_mean_sign and any(lo <= 0 <= hi for lo, hi in (row["ci95"] for row in ordered)):
            conditional_interval_ordering_unresolved.append(comp)
            warnings.append(f"{comp}: paired means have one strict sign across tested sizes, but conditional repeat intervals include zero; comparative ordering is unresolved. The registered numeric conclusion is checked; arbitrary prose is not automatically assessed.")
    notes = (final / "notes.md").read_text(encoding="utf-8", errors="replace")
    if not notes.strip():
        errors.append("notes.md must contain a scientific interpretation and limitations")
    if pred_map and all(close(x["y_true"], x["y_pred"]) for x in pred_map.values()):
        warnings.append("all predictions exactly reproduce public targets; review provenance, no arbitrary penalty applied")
    if errors:
        raise_science_errors(errors)
    contract_version = protocol.get("scorer_contract_version")
    deterministic_host_scope = os.environ.get("CCB_P01_CASE03_DETERMINISTIC_SCOPE") == "v1"
    if deterministic_host_scope and contract_version not in (4, 5):
        raise ScienceFailure("standard Case 03 deterministic scope requires protocol contract v4 or v5")
    runtime_requires_replay = (require_replay or os.environ.get("CCB_CASE03_REPLAY_REQUIRED") == "1"
                               or contract_version in (3, 4, 5))
    if legacy_static_diagnostic and contract_version != 2:
        raise InfrastructureFailure("legacy static diagnostic is limited to contract v2")
    if not internal_static_only and not runtime_requires_replay and not legacy_static_diagnostic:
        raise InfrastructureFailure("standalone scoring requires explicit --legacy-static-diagnostic for v2")
    replay_summary = None
    scientific_review_summary = None
    host_review_required = os.environ.get("CCB_P01_CASE03_SCIENTIFIC_REVIEW_REQUIRED") == "1"
    if (not internal_static_only and host_review_required and not runtime_requires_replay):
        raise InfrastructureFailure("host-required scientific review cannot run without the standard replay stage")
    if not internal_static_only and runtime_requires_replay:
        context_path = Path(os.environ.get("CCB_RUN_CONTEXT_PATH", "/trusted/runner-context.json"))
        receipt_path = Path("/trusted/p01-case03-fit-replay/receipt.json")
        try:
            if context_path.is_symlink() or receipt_path.is_symlink():
                raise InfrastructureFailure("trusted replay context/receipt cannot be a symlink")
            context_raw = context_path.read_bytes()
            context = json.loads(context_raw)
            receipt_bytes = receipt_path.read_bytes()
            receipt = json.loads(receipt_bytes)
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise InfrastructureFailure(f"trusted replay context/receipt is unavailable: {exc}") from exc
        bound = context.get("p01_case03_fit_replay") if isinstance(context, dict) else None
        if (not isinstance(bound, dict) or bound.get("schema") != "p01_case03_fit_replay/v1"
                or bound.get("attempt_id") != context.get("attempt_id")
                or bound.get("receipt_sha256") != hashlib.sha256(receipt_bytes).hexdigest()
                or receipt.get("schema") != "p01_case03_fit_replay/v1"
                or receipt.get("attempt_id") != context.get("attempt_id")
                or receipt.get("artifact_manifest_sha256") != context.get("artifact_manifest_sha256")
                or receipt.get("image_id") != context.get("image_id")):
            raise InfrastructureFailure("trusted replay receipt is not bound to this attempt and artifact snapshot")
        if receipt.get("status") != "ok":
            raise_science_errors(["submitted fit.py did not complete the trusted replay: " +
                                  str(receipt.get("reason", "candidate replay failed"))],
                                 checked={"submitted_code_execution_verified": False,
                                          "prediction_replay_verified": False,
                                          "training_execution_verified": False})
        records = receipt.get("records")
        expected_grid = {(arm, int(n), int(rep)) for arm in ARMS
                         for n in sizes for rep in range(repeats_declared)}
        observed = set()
        for item in records if isinstance(records, list) else []:
            if not isinstance(item, dict):
                raise InfrastructureFailure("trusted replay record is malformed")
            key = (item.get("representation"), item.get("n_train"), item.get("repeat_index"))
            if key in observed:
                raise InfrastructureFailure("trusted replay receipt repeats a split record")
            observed.add(key)
            split = split_by_key.get((item.get("n_train"), item.get("repeat_index")))
            if split is None or item.get("source_matrix_file") != ARMS.get(item.get("representation")):
                raise InfrastructureFailure("trusted replay record does not map to a declared source arm and split")
            train_digest = hashlib.sha256(json.dumps(split["train_indices"], separators=(",", ":")).encode("ascii")).hexdigest()
            test_digest = hashlib.sha256(json.dumps(split["test_indices"], separators=(",", ":")).encode("ascii")).hexdigest()
            expected = [pred_map[(item["representation"], item["n_train"], item["repeat_index"], i)]["y_pred"]
                        for i in split["test_indices"]]
            expected_digest = hashlib.sha256(json.dumps(expected, separators=(",", ":"), allow_nan=False).encode("ascii")).hexdigest()
            if (item.get("split_seed") != split.get("seed")
                    or item.get("train_indices_sha256") != train_digest
                    or item.get("test_indices_sha256") != test_digest
                    or item.get("expected_predictions_sha256") != expected_digest
                    or not all(isinstance(item.get(k), str) and re.fullmatch(r"[0-9a-f]{64}", item[k])
                               for k in ("request_sha256", "response_sha256", "X_train_sha256", "y_train_sha256", "X_test_sha256"))):
                raise InfrastructureFailure("trusted replay record hashes or split mapping disagree with submitted arrays")
            if (item.get("status") != "ok" or item.get("prediction_replay_verified") is not True
                    or item.get("exit_code") != 0 or not isinstance(item.get("request_sha256"), str)
                    or not isinstance(item.get("response_sha256"), str)):
                raise_science_errors(["submitted fit.py replay failed or differed from final/predictions.csv"],
                                     checked={"submitted_code_execution_verified": False,
                                              "prediction_replay_verified": False,
                                              "training_execution_verified": False})
        if observed != expected_grid:
            raise InfrastructureFailure("trusted replay receipt does not cover the complete submitted split grid")
        if (receipt.get("fit_sha256") != actual_fit_hash.removeprefix("sha256:")
                or receipt.get("protocol_sha256") != hashlib.sha256((final / "protocol.json").read_bytes()).hexdigest()
                or receipt.get("splits_sha256") != hashlib.sha256((final / "splits.json").read_bytes()).hexdigest()
                or receipt.get("predictions_sha256") != hashlib.sha256((final / "predictions.csv").read_bytes()).hexdigest()
                or receipt.get("submitted_code_execution_verified") is not True
                or receipt.get("prediction_replay_verified") is not True
                or receipt.get("training_execution_verified") is not False
                or receipt.get("coverage") != "PARTIAL"):
            raise InfrastructureFailure("trusted replay receipt code/artifact hashes or verification flags disagree")
        replay_summary = {"submitted_code_execution_verified": True,
                          "prediction_replay_verified": True,
                          "training_execution_verified": False}
        if contract_version == 5:
            independent = receipt.get("independent_refit")
            expected_refit_grid = {(arm, int(n), int(rep)) for arm in ARMS
                                   for n in sizes for rep in range(repeats_declared)}
            observed_refit = set()
            if (not isinstance(independent, dict)
                    or independent.get("schema") != "p01-case03-independent-refit/v1"
                    or independent.get("status") != "ok"
                    or independent.get("candidate_internals_proven") is not False
                    or independent.get("declared_protocol_independent_refit_verified") is not True
                    or independent.get("training_execution_verified") is not False
                    or independent.get("coverage") != "PARTIAL"
                    or independent.get("protocol_sha256") != receipt.get("protocol_sha256")
                    or independent.get("splits_sha256") != receipt.get("splits_sha256")
                    or independent.get("predictions_sha256") != receipt.get("predictions_sha256")):
                raise InfrastructureFailure("trusted independent refit receipt is missing or not bound to this snapshot")
            worker = independent.get("worker")
            if (not isinstance(worker, dict) or worker.get("isolated") is not True
                    or worker.get("image_id") != context.get("image_id") or worker.get("network") != "none"
                    or worker.get("user") != "65532:65532" or worker.get("read_only_root") is not True
                    or not isinstance(worker.get("container_id"), str)
                    or not re.fullmatch(r"[0-9a-f]{12,64}", worker["container_id"])
                    or not isinstance(worker.get("trusted_refit_source_sha256"), str)
                    or not re.fullmatch(r"[0-9a-f]{64}", worker["trusted_refit_source_sha256"])):
                raise InfrastructureFailure("trusted independent refit worker identity or isolation evidence is invalid")
            for row in independent.get("records", []) if isinstance(independent.get("records"), list) else []:
                if not isinstance(row, dict):
                    raise InfrastructureFailure("independent refit record is malformed")
                key = (row.get("representation"), row.get("n_train"), row.get("repeat_index"))
                if key in observed_refit or key not in expected_refit_grid or row.get("candidate_match") is not True:
                    raise_science_errors(["declared model protocol refit differs from submitted predictions"],
                                         checked={"declared_protocol_independent_refit_verified": False,
                                                  "candidate_internals_proven": False})
                observed_refit.add(key)
                if (row.get("paired_split_id") != split_by_key[(key[1], key[2])].get("paired_split_id")
                        or not isinstance(row.get("folds"), list)
                        or len(row["folds"]) != model_spec["arms"][key[0]]["cv"]["n_splits"]
                        or any(not isinstance(fold, dict)
                               or type(fold.get("fold")) is not int
                               or not isinstance(fold.get("train_global_indices"), list)
                               or not isinstance(fold.get("validation_global_indices"), list)
                               for fold in row["folds"])):
                    raise InfrastructureFailure("independent refit fold records do not match the declared protocol")
            if observed_refit != expected_refit_grid:
                raise InfrastructureFailure("independent refit receipt does not cover the complete split/arm grid")
            replay_summary.update({"declared_protocol_independent_refit_verified": True,
                                   "candidate_internals_proven": False})
        if ((contract_version == 3 and not deterministic_host_scope)
                or (host_review_required and contract_version != 4)):
            scientific_review_summary = validate_scientific_review_transport(
                final, context, context_raw, receipt, receipt_bytes)
    result = {
        "status": ("PASS_STATIC_DIAGNOSTIC" if internal_static_only or legacy_static_diagnostic else "PASS"),
        "scorer_version": SCORER_VERSION,
        "coverage": "COMPLETE" if scientific_review_summary else "PARTIAL",
        "training_execution_verified": False,
        "interval_scope": "training_subset_repeat_conditional_on_frozen_test_set",
        "conditional_interval_ordering_unresolved": conditional_interval_ordering_unresolved,
        "errors": [], "warnings": warnings,
        "checked": {"representations": sorted(rep_seen), "sizes": sizes,
                    "repeats_per_size": repeats_declared, "prediction_rows": len(pred_rows),
                    "curve_rows": len(curve_rows), "paired_intervals": len(summary_rows),
                    "frozen_test_rows": len(frozen_test)},
    }
    if replay_summary:
        result.update(replay_summary)
        result["checked"].update(replay_summary)
    if scientific_review_summary:
        result.update(scientific_review_summary)
        result["coverage_scope"] = "semi_auto_exact_submission_review"
        result["checked"].update(scientific_review_summary)
    elif contract_version in (4, 5) and replay_summary:
        result["coverage_scope"] = ("deterministic_machine_checks_plus_same_attempt_fit_replay; arbitrary fit internals and free prose are unverified"
                                    if contract_version == 4 else
                                    "deterministic machine checks plus evaluator-owned refit of the declared model protocol; arbitrary candidate internals, all open-ended methods, and free prose are unverified")
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--submission", type=Path, required=True, help="submission root containing final/")
    parser.add_argument("--assets", type=Path, required=True, help="directory containing the package input assets")
    parser.add_argument("--refs", type=Path, default=Path(__file__).resolve().parent.parent / "refs.json", help="package tests/refs.json")
    parser.add_argument("--legacy-static-diagnostic", action="store_true",
                        help="run static-only diagnostic for v2; this is not a runtime reward route")
    args = parser.parse_args(argv)
    try:
        result = check_submission(args.submission.resolve(), args.assets.resolve(), args.refs.resolve(),
                                  legacy_static_diagnostic=args.legacy_static_diagnostic)
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0
    except ScienceFailure as exc:
        try:
            detail = json.loads(str(exc))
        except json.JSONDecodeError:
            detail = {"status": "FAIL", "scorer_version": SCORER_VERSION,
                      "coverage": "PARTIAL", "errors": [str(exc)]}
        detail.setdefault("scorer_version", SCORER_VERSION)
        print(json.dumps(detail, indent=2, ensure_ascii=False))
        return 1
    except InfrastructureFailure as exc:
        print(json.dumps({"status": "INFRA_ERROR", "scorer_version": SCORER_VERSION,
                          "coverage": "NOT_INTEGRATED", "training_execution_verified": False,
                          "errors": [str(exc)]}, indent=2, ensure_ascii=False))
        return 2
    except Exception as exc:  # fail closed: unexpected checker defects are infrastructure errors, never a reward.
        print(json.dumps({"status": "INFRA_ERROR", "scorer_version": SCORER_VERSION,
                          "coverage": "NOT_INTEGRATED", "training_execution_verified": False,
                          "errors": [f"unexpected verifier error: {type(exc).__name__}: {exc}"]}, indent=2, ensure_ascii=False))
        return 2


if __name__ == "__main__":
    import runpy
    runpy.run_module("verify_v6", run_name="__main__")
