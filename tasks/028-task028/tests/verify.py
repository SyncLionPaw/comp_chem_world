#!/usr/bin/env python3
# 人工审核：自动检查结果供参考，科学结论需人工复核。
"""Mechanical Case08 evidence checks plus a protected, snapshot-bound review gate.

This verifier does not infer scientific correctness from prose, keywords, or candidate
metadata. A valid submission remains REVIEW_REQUIRED until an evaluator-owned review
assessment addresses the exact file snapshot and independently authenticates receipts.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path, PurePosixPath
import re
import base64
import subprocess
import tempfile
import sys

# Evaluator-only parsing/review helpers; never copied into the image.
sys.path.insert(0, str(Path(__file__).resolve().parent / "_support"))
import stat
from typing import Any
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from mesmer_diagnostics import analyze_submission
import slurm_records

CASE_ID = "case-08-end-to-end-rearrangement-claim"
PROVENANCE_SCHEMA = "compchemworld.case08.provenance/v1"
RUBRIC_SCHEMA = "compchemworld.case08.review-rubric/v1"
ASSESSMENT_SCHEMA = "compchemworld.case08.review-assessment/v3"
REVIEW_CRITERIA = (
    "independent_new_science",
    "representative_scope_and_ring_opening",
    "matched_rate_and_competition",
    "mechanistic_connection_to_aerosol_precursors",
    "route_specific_scientific_validity",
    "uncertainty_and_claim_scope",
)
EXPECTED_SOURCE_DIGEST = "sha256:6839b9f8f46b7488783d3f738b704fb529f37ffee44560e736c3dd0fba10c574"
EXPECTED_RUBRIC_DIGEST = "sha256:23708acf286b170fe4d7eadda1beac4e82b702ef82f6785e491861cd3a760526"
EXPECTED_EVALUATOR_SOURCES = {
    "docs/Iyer 等 - 2023 - Molecular rearrangement of bicyclic peroxy radicals is a key route to aerosol from aromatics.pdf":
        "sha256:1686e5c6526c18824b7f4a48da648afb7bf24ffa9d146078b9c9c0193a60eb9b",
    "docs/41467_2023_40675_MOESM1_ESM.docx":
        "sha256:52c8854e125cac6ea714c61a4e711fea66565cef62d0f176511e819e59fd568a",
    "gold/tables/derived_ibpr_barriers.csv":
        "sha256:765606501de2a2a75f11549af81a4ce5d0ab28c30c67cc445ceda949e8543883",
    "gold/tables/mesmer_tdep_rates.csv":
        "sha256:bdde3c726cb83e709de4e4668c15d2535359dd26c66d351efea084abc196a41b",
    "gold/case04_fate_manifest.json":
        "sha256:050ade4d0888adb2369e34830cc955a79379a6ba5918724dfa4277209b8c5255",
}
SHA256 = re.compile(r"^sha256:[0-9a-f]{64}$")
HEX_SHA256 = re.compile(r"^[0-9a-f]{64}$")


def normalized_sha256(value: Any) -> str | None:
    if isinstance(value, str) and SHA256.fullmatch(value):
        return value
    if isinstance(value, str) and HEX_SHA256.fullmatch(value):
        return "sha256:" + value
    return None


def normalize_condition(condition: dict, kind: str) -> float:
    value = finite_number(condition.get("value"), f"comparison {kind}.value")
    unit = nonempty_string(condition.get("unit"), f"comparison {kind}.unit").casefold().replace(" ", "")
    if kind == "temperature":
        factors = {"k": (1.0, 0.0), "kelvin": (1.0, 0.0), "c": (1.0, 273.15), "°c": (1.0, 273.15)}
    else:
        factors = {"pa": (1.0, 0.0), "kpa": (1000.0, 0.0), "bar": (100000.0, 0.0),
                   "atm": (101325.0, 0.0), "torr": (101325.0 / 760.0, 0.0),
                   "mmhg": (101325.0 / 760.0, 0.0)}
    require(unit in factors, f"unsupported comparison {kind} unit: {unit}")
    factor, offset = factors[unit]
    result = value * factor + offset
    require(math.isfinite(result) and result > 0,
            f"comparison {kind} must convert to a finite positive absolute value")
    return result


def normalized_label(value: str) -> str:
    return " ".join(value.casefold().split())


def rate_to_per_second(value: Any, unit_value: Any) -> float:
    number = finite_number(value, "kinetic comparison value")
    require(number >= 0, "kinetic rates in a comparison group must be nonnegative")
    unit = nonempty_string(unit_value, "kinetic comparison unit").casefold().replace(" ", "")
    factors = {"s^-1": 1.0, "s-1": 1.0, "1/s": 1.0, "sec^-1": 1.0, "second^-1": 1.0,
               "min^-1": 1.0 / 60.0, "min-1": 1.0 / 60.0, "h^-1": 1.0 / 3600.0,
               "hr^-1": 1.0 / 3600.0, "day^-1": 1.0 / 86400.0}
    require(unit in factors, f"unsupported kinetic comparison unit: {unit}")
    result = number * factors[unit]
    require(math.isfinite(result), "kinetic comparison value is outside supported finite range")
    return result


class CandidateError(Exception):
    """Invalid or internally inconsistent candidate evidence."""


class EnvironmentInvalid(Exception):
    """Damaged evaluator inputs, unsupported protocol, or verifier setup failure."""


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return "sha256:" + h.hexdigest()


def json_no_duplicates(path: Path, *, environment: bool = False) -> Any:
    def pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in items:
            if key in result:
                raise ValueError(f"duplicate JSON key: {key}")
            result[key] = value
        return result

    def finite_float(value: str) -> float:
        result = float(value)
        if not math.isfinite(result):
            raise ValueError(f"non-finite JSON number: {value}")
        return result

    try:
        return json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=pairs,
                          parse_float=finite_float,
                          parse_constant=lambda value: (_ for _ in ()).throw(
                              ValueError(f"non-finite JSON constant: {value}")))
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        error = EnvironmentInvalid if environment else CandidateError
        raise error(f"cannot parse {path.name}: {exc}") from exc


def require(condition: bool, message: str, *, environment: bool = False) -> None:
    if not condition:
        error = EnvironmentInvalid if environment else CandidateError
        raise error(message)


def nonempty_string(value: Any, label: str, *, environment: bool = False) -> str:
    require(isinstance(value, str) and bool(value.strip()), f"{label} must be a nonempty string",
            environment=environment)
    return value.strip()


def safe_file(root: Path, relative: Any, label: str) -> Path:
    require(isinstance(relative, str) and relative != "", f"{label}: path must be a string")
    require("\\" not in relative, f"{label}: backslash paths are not allowed")
    rel = PurePosixPath(relative)
    require(not rel.is_absolute() and all(p not in ("", ".", "..") for p in rel.parts),
            f"{label}: path must stay within final/native_evidence")
    path = root.joinpath(*rel.parts)
    current = root
    for part in rel.parts:
        current = current / part
        require(not current.is_symlink(), f"{label}: symlink path is not allowed")
    require(path.is_file() and path.stat().st_size > 0, f"{label}: missing or empty file {relative}")
    return path


def finite_number(value: Any, label: str) -> float:
    require(not isinstance(value, bool) and isinstance(value, (int, float)),
            f"{label} must be a finite number")
    try:
        result = float(value)
    except (OverflowError, ValueError) as exc:
        raise CandidateError(f"{label} must be a finite number") from exc
    require(math.isfinite(result), f"{label} must be a finite number")
    return result


def verify_ed25519_signature(payload: dict, signature_b64: Any, public_key: Path) -> None:
    require(isinstance(signature_b64, str), "protected assessment signature is missing", environment=True)
    try:
        signature = base64.b64decode(signature_b64, validate=True)
    except (ValueError, TypeError) as exc:
        raise EnvironmentInvalid("protected assessment signature encoding is invalid") from exc
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                          allow_nan=False).encode("utf-8")
    try:
        key = serialization.load_pem_public_key(public_key.read_bytes())
        require(isinstance(key, Ed25519PublicKey), "review key must be Ed25519", environment=True)
        key.verify(signature, canonical)
    except EnvironmentInvalid:
        raise
    except Exception as exc:
        raise EnvironmentInvalid(f"protected assessment signature is invalid or unavailable: {exc}") from exc


def candidate_manifest(final: Path) -> dict[str, str]:
    manifest: dict[str, str] = {}
    for path in sorted(final.rglob("*")):
        if path.is_symlink():
            raise CandidateError(f"submission contains symlink: {path.relative_to(final)}")
        if path.is_file():
            manifest[path.relative_to(final).as_posix()] = digest(path)
    require(bool(manifest), "final/ is empty")
    return manifest


def validate_evaluator_inputs(tests: Path, final: Path, review_key_sha256: str | None = None) -> tuple[dict, dict, str]:
    require(tests.resolve() != final.resolve() and not tests.resolve().is_relative_to(final.resolve()),
            "evaluator TESTS must be outside candidate final/", environment=True)
    refs = json_no_duplicates(tests / "refs.json", environment=True)
    require(isinstance(refs, dict) and refs.get("case_id") == CASE_ID,
            "reference file has wrong case_id", environment=True)
    require(refs.get("source_digest") == EXPECTED_SOURCE_DIGEST,
            "pinned Gold manifest digest mismatch", environment=True)
    sources = refs.get("evaluator_sources")
    require(isinstance(sources, list), "missing pinned evaluator sources", environment=True)
    seen: dict[str, str] = {}
    for entry in sources:
        require(isinstance(entry, dict), "invalid evaluator source entry", environment=True)
        path, sha = entry.get("path"), entry.get("sha256")
        require(isinstance(path, str) and path in EXPECTED_EVALUATOR_SOURCES
                and sha == EXPECTED_EVALUATOR_SOURCES.get(path),
                "unexpected evaluator source path or digest", environment=True)
        require(path not in seen, "duplicate evaluator source", environment=True)
        seen[path] = sha
    require(seen == EXPECTED_EVALUATOR_SOURCES, "evaluator source set is incomplete", environment=True)

    rubric_path = tests / "protected" / "review-rubric.json"
    rubric = json_no_duplicates(rubric_path, environment=True)
    require(isinstance(rubric, dict) and rubric.get("schema_version") == RUBRIC_SCHEMA,
            "unsupported protected rubric", environment=True)
    criteria = rubric.get("criteria")
    require(isinstance(criteria, list) and criteria == list(REVIEW_CRITERIA),
            "protected rubric criteria mismatch", environment=True)
    rubric_hash = digest(rubric_path)
    require(EXPECTED_RUBRIC_DIGEST != "TO_BE_PINNED", "review rubric digest is not frozen in verifier",
            environment=True)
    require(rubric_hash == EXPECTED_RUBRIC_DIGEST and refs.get("review_rubric_sha256") == rubric_hash,
            "protected rubric hash differs from pinned evaluator reference", environment=True)
    assessment_path = tests / "protected" / "review-assessment.json"
    assessment = json_no_duplicates(assessment_path, environment=True)
    require(isinstance(assessment, dict) and assessment.get("schema_version") == ASSESSMENT_SCHEMA,
            "unsupported protected review assessment", environment=True)
    status = assessment.get("status")
    require(isinstance(status, str) and status in {"PENDING", "COMPLETE"},
            "assessment status must be PENDING or COMPLETE", environment=True)
    if status == "COMPLETE":
        public_key = tests / "protected" / "review-public-key.pem"
        require(public_key.is_file() and not public_key.is_symlink(),
                "trusted review public key is missing", environment=True)
        key_hash = digest(public_key)
        require(isinstance(review_key_sha256, str)
                and re.fullmatch(r"sha256:[0-9a-f]{64}", review_key_sha256) is not None
                and key_hash == review_key_sha256,
                "review key does not match the evaluator's trusted pin", environment=True)
        payload = dict(assessment)
        signature = payload.pop("signature", None)
        verify_ed25519_signature(payload, signature, public_key)
    return refs, rubric, rubric_hash


def validate_submission(final: Path) -> tuple[dict, dict[str, str]]:
    for name in ("claim.md", "provenance.json"):
        path = final / name
        require(path.is_file() and not path.is_symlink() and path.stat().st_size > 0,
                f"required deliverable missing or empty: final/{name}")
    native = final / "native_evidence"
    require(native.is_dir() and not native.is_symlink(), "final/native_evidence/ is missing")
    claim = (final / "claim.md").read_text(encoding="utf-8").strip()
    require(bool(claim), "final/claim.md is empty")
    provenance = json_no_duplicates(final / "provenance.json")
    require(isinstance(provenance, dict) and provenance.get("schema_version") == PROVENANCE_SCHEMA,
            f"provenance schema_version must be {PROVENANCE_SCHEMA}")
    require(provenance.get("case_id") == CASE_ID, "provenance case_id mismatch")

    evidence_items = provenance.get("evidence")
    require(isinstance(evidence_items, list) and evidence_items, "provenance.evidence must be nonempty")
    evidence: dict[str, dict] = {}
    for entry in evidence_items:
        require(isinstance(entry, dict), "evidence entries must be objects")
        eid = nonempty_string(entry.get("id"), "evidence.id")
        require(eid not in evidence, f"duplicate evidence id: {eid}")
        role = nonempty_string(entry.get("role"), f"evidence[{eid}].role")
        require(role in {"native_input", "native_output", "acquired_source", "execution_receipt", "analysis"},
                f"unsupported evidence role for {eid}")
        relpath = entry.get("path")
        require(isinstance(relpath, str) and relpath.startswith("native_evidence/"),
                f"evidence[{eid}] must be inside native_evidence/")
        path = safe_file(final, relpath, f"evidence[{eid}]")
        declared = entry.get("sha256")
        require(isinstance(declared, str) and SHA256.fullmatch(declared), f"invalid sha256 for {eid}")
        require(digest(path) == declared, f"evidence hash mismatch for {eid}")
        if role == "acquired_source":
            source = entry.get("source")
            require(isinstance(source, dict), f"acquired evidence {eid} needs source provenance")
            nonempty_string(source.get("locator"), f"evidence[{eid}].source.locator")
            nonempty_string(source.get("accessed_at"), f"evidence[{eid}].source.accessed_at")
        evidence[eid] = entry

    executions = provenance.get("executions")
    require(isinstance(executions, list) and executions, "provenance.executions must be nonempty")
    run_map: dict[str, dict] = {}
    for run in executions:
        require(isinstance(run, dict), "execution entries must be objects")
        run_id = nonempty_string(run.get("id"), "execution.id")
        require(run_id not in run_map, f"duplicate execution id: {run_id}")
        kind, status = run.get("kind"), run.get("status")
        require(isinstance(kind, str) and kind in {"new_computation", "analysis"},
                f"invalid execution kind: {run_id}")
        require(isinstance(status, str) and status in {"completed", "failed", "partial"},
                f"execution[{run_id}].status must be completed, failed, or partial")
        nonempty_string(run.get("started_at"), f"execution[{run_id}].started_at")
        nonempty_string(run.get("finished_at"), f"execution[{run_id}].finished_at")
        nonempty_string(run.get("tool"), f"execution[{run_id}].tool")
        nonempty_string(run.get("version"), f"execution[{run_id}].version")
        sets: dict[str, set[str]] = {}
        for field, role in (("input_evidence_ids", "native_input"),
                            ("output_evidence_ids", "native_output"),
                            ("receipt_evidence_ids", "execution_receipt")):
            refs = run.get(field)
            require(isinstance(refs, list) and all(isinstance(x, str) for x in refs),
                    f"execution[{run_id}].{field} must contain string IDs")
            require(len(refs) == len(set(refs)), f"execution[{run_id}].{field} must be unique")
            for ref in refs:
                require(ref in evidence and evidence[ref].get("role") == role,
                        f"execution[{run_id}] has missing/wrong-role {field} reference: {ref}")
            sets[field] = set(refs)
        if kind == "new_computation":
            require(sets["input_evidence_ids"] and sets["output_evidence_ids"],
                    f"new computation {run_id} needs native inputs and outputs")
            require(sets["receipt_evidence_ids"], f"new computation {run_id} needs a receipt file")
            resources = run.get("resources")
            require(isinstance(resources, dict), f"new computation {run_id} needs resource accounting fields")
            cpu_hours = finite_number(resources.get("allocated_cpu_hours"), f"execution[{run_id}].allocated_cpu_hours")
            require(cpu_hours >= 0, f"execution[{run_id}].allocated_cpu_hours cannot be negative")
        run_map[run_id] = run

    decisions = provenance.get("decisions")
    require(isinstance(decisions, list) and decisions, "provenance.decisions must be a nonempty array")
    decision_ids: set[str] = set()
    for decision in decisions:
        require(isinstance(decision, dict), "decision entries must be objects")
        did = nonempty_string(decision.get("id"), "decision.id")
        require(did not in decision_ids, f"duplicate decision id: {did}")
        decision_ids.add(did)
        nonempty_string(decision.get("choice"), f"decision[{did}].choice")
        nonempty_string(decision.get("rationale"), f"decision[{did}].rationale")
        refs = decision.get("evidence_ids", [])
        require(isinstance(refs, list) and all(isinstance(ref, str) for ref in refs),
                f"decision[{did}] evidence references must be string IDs")
        require(all(ref in evidence for ref in refs), f"decision[{did}] references unknown evidence")

    claims = provenance.get("claims")
    require(isinstance(claims, list) and claims, "provenance.claims must be nonempty")
    claim_map: dict[str, dict] = {}
    all_quantity_ids_seen: set[str] = set()
    comparison_groups: dict[str, list[dict]] = {}
    new_science_quantities = 0
    for claim in claims:
        require(isinstance(claim, dict), "claim entries must be objects")
        cid = nonempty_string(claim.get("id"), "claim.id")
        require(cid not in claim_map, f"duplicate claim id: {cid}")
        nonempty_string(claim.get("statement"), f"claim[{cid}].statement")
        quantities = claim.get("quantities", [])
        require(isinstance(quantities, list), f"claim[{cid}].quantities must be an array")
        for quantity in quantities:
            require(isinstance(quantity, dict), f"claim[{cid}] quantity must be an object")
            qid = nonempty_string(quantity.get("id"), f"claim[{cid}].quantity.id")
            require(qid not in all_quantity_ids_seen, f"duplicate quantity id: {qid}")
            all_quantity_ids_seen.add(qid)
            finite_number(quantity.get("value"), f"quantity[{qid}].value")
            nonempty_string(quantity.get("unit"), f"quantity[{qid}].unit")
            nonempty_string(quantity.get("system"), f"quantity[{qid}].system")
            nonempty_string(quantity.get("population"), f"quantity[{qid}].population")
            evidence_refs = quantity.get("evidence_ids")
            run_refs = quantity.get("execution_ids", [])
            require(isinstance(evidence_refs, list) and all(isinstance(x, str) for x in evidence_refs),
                    f"quantity[{qid}].evidence_ids must contain string IDs")
            require(bool(evidence_refs) and all(x in evidence for x in evidence_refs),
                    f"quantity[{qid}] has missing evidence references")
            require(isinstance(run_refs, list) and all(isinstance(x, str) for x in run_refs),
                    f"quantity[{qid}].execution_ids must contain string IDs")
            require(all(x in run_map for x in run_refs), f"quantity[{qid}] has missing execution references")
            origin = quantity.get("origin")
            require(isinstance(origin, str) and origin in {"new_computation", "acquired", "literature"},
                    f"quantity[{qid}] has invalid origin")
            if origin == "new_computation":
                linked_runs = [r for r in run_refs if run_map[r]["kind"] == "new_computation"]
                require(linked_runs, f"new quantity {qid} does not link to a new computation")
                require(any(evidence[x].get("role") == "native_output"
                            and any(x in run_map[r]["output_evidence_ids"] for r in linked_runs)
                            for x in evidence_refs),
                        f"new quantity {qid} must cite an output from its linked computation")
                new_science_quantities += 1
            elif origin in {"acquired", "literature"}:
                require(not run_refs or all(run_map[r]["kind"] != "new_computation" for r in run_refs),
                        f"acquired quantity {qid} cannot claim a new-computation run")
                require(any(evidence[x].get("role") == "acquired_source" for x in evidence_refs),
                        f"acquired quantity {qid} must cite acquired-source evidence")
            conditions = quantity.get("conditions", {})
            require(isinstance(conditions, dict), f"quantity[{qid}].conditions must be an object")
            for key in ("temperature", "pressure"):
                condition = conditions.get(key)
                if condition is not None:
                    require(isinstance(condition, dict), f"quantity[{qid}].{key} must be null or an object")
                    finite_number(condition.get("value"), f"quantity[{qid}].{key}.value")
                    nonempty_string(condition.get("unit"), f"quantity[{qid}].{key}.unit")
            if quantity.get("comparison_group"):
                nonempty_string(quantity.get("comparison_group"), f"quantity[{qid}].comparison_group")
                comparison_groups.setdefault(quantity["comparison_group"], []).append(quantity)
            if quantity.get("comparison_kind") is not None:
                nonempty_string(quantity.get("comparison_kind"), f"quantity[{qid}].comparison_kind")
            deps = quantity.get("depends_on_quantity_ids", [])
            require(isinstance(deps, list) and all(isinstance(x, str) for x in deps),
                    f"quantity[{qid}] dependencies must be string IDs")
            require(len(deps) == len(set(deps)), f"quantity[{qid}] dependency list must be unique")
        deps = claim.get("depends_on_claim_ids", [])
        require(isinstance(deps, list) and all(isinstance(x, str) for x in deps),
                f"claim[{cid}] dependencies must be string IDs")
        require(len(deps) == len(set(deps)), f"claim[{cid}] dependency list must be unique")
        refs = claim.get("evidence_ids", [])
        require(isinstance(refs, list) and all(isinstance(x, str) for x in refs),
                f"claim[{cid}] evidence references must be string IDs")
        require(all(ref in evidence for ref in refs),
                f"claim[{cid}] references unknown evidence")
        claim_map[cid] = claim

    require(new_science_quantities > 0, "no quantitative claim links to a new computation")
    for group, quantities in comparison_groups.items():
        kinds = {q.get("comparison_kind") for q in quantities if q.get("comparison_kind") is not None}
        if "kinetic_rate" not in kinds:
            continue
        require(all(q.get("comparison_kind") == "kinetic_rate" for q in quantities),
                f"comparison group {group} mixes incompatible comparison kinds")
        require(len(quantities) >= 2, f"kinetic comparison group {group} needs at least two quantities")
        first = quantities[0]
        first_conditions = first.get("conditions", {})
        require(first_conditions.get("temperature") is not None,
                f"kinetic comparison group {group} needs temperature")
        ref_population = normalized_label(first["population"])
        t_ref = normalize_condition(first_conditions["temperature"], "temperature")
        p_condition_ref = first_conditions.get("pressure")
        p_ref = normalize_condition(p_condition_ref, "pressure") if p_condition_ref is not None else None
        for quantity in quantities[1:]:
            conditions = quantity.get("conditions", {})
            require(conditions.get("temperature") is not None,
                    f"kinetic comparison group {group} has incomplete temperature")
            require(normalized_label(quantity["population"]) == ref_population,
                    f"kinetic comparison group {group} has mismatched reference populations")
            t_match = math.isclose(normalize_condition(conditions["temperature"], "temperature"), t_ref,
                                   rel_tol=0, abs_tol=1e-8)
            p_condition = conditions.get("pressure")
            p_match = ((p_ref is None and p_condition is None)
                       or (p_ref is not None and p_condition is not None
                           and math.isclose(normalize_condition(p_condition, "pressure"), p_ref,
                                            rel_tol=1e-9, abs_tol=1e-5)))
            require(t_match and p_match,
                    f"kinetic comparison group {group} has mismatched T/P or one-sided pressure applicability")
        for quantity in quantities:
            rate_to_per_second(quantity["value"], quantity["unit"])
    all_quantity_ids = set(all_quantity_ids_seen)
    for claim in claims:
        for dep in claim.get("depends_on_claim_ids", []):
            require(dep in claim_map, f"claim[{claim['id']}] has missing DAG edge target: {dep}")
        for quantity in claim.get("quantities", []):
            for dep in quantity.get("depends_on_quantity_ids", []):
                require(dep in all_quantity_ids, f"quantity[{quantity['id']}] has missing DAG edge target: {dep}")

    def assert_acyclic(nodes: dict[str, list[str]], label: str) -> None:
        visiting: set[str] = set()
        done: set[str] = set()
        def visit(node: str) -> None:
            require(node not in visiting, f"{label} dependency cycle at {node}")
            if node in done:
                return
            visiting.add(node)
            for dep in nodes[node]:
                visit(dep)
            visiting.remove(node)
            done.add(node)
        for node in nodes:
            visit(node)

    assert_acyclic({cid: claim.get("depends_on_claim_ids", []) for cid, claim in claim_map.items()}, "claim")
    quantity_nodes = {q["id"]: q.get("depends_on_quantity_ids", [])
                      for claim in claims for q in claim.get("quantities", [])}
    assert_acyclic(quantity_nodes, "quantity")

    return provenance, candidate_manifest(final)


def _bounded_standard_context(path: Path, limit: int = 4 * 1024 * 1024) -> bytes:
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    try:
        fd = os.open(path, flags)
    except OSError as exc:
        raise EnvironmentInvalid(f"standard Case08 context cannot be opened safely: {exc}") from exc
    try:
        info = os.fstat(fd)
        require(stat.S_ISREG(info.st_mode) and info.st_size <= limit,
                "standard Case08 context is not a bounded regular file", environment=True)
        data = bytearray()
        while len(data) <= limit:
            chunk = os.read(fd, min(65536, limit + 1 - len(data)))
            if not chunk:
                break
            data.extend(chunk)
        require(len(data) <= limit, "standard Case08 context exceeds byte limit", environment=True)
        return bytes(data)
    finally:
        os.close(fd)


def _standard_projection_inventory(root: Path, *, max_entries: int = 20_000,
                                   max_bytes: int = 1_073_741_824) -> dict[str, tuple[str, int, str | None]]:
    """Hash the frozen grader projection without following links or unbounded walks."""
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        root_fd = os.open(root, flags)
    except OSError as exc:
        raise EnvironmentInvalid(f"standard Case08 final projection cannot be opened: {exc}") from exc
    inventory: dict[str, tuple[str, int, str | None]] = {}
    count = total = 0
    pending: list[tuple[int, str]] = [(root_fd, "")]
    try:
        while pending:
            dir_fd, prefix = pending.pop()
            try:
                for name in os.listdir(dir_fd):
                    require(name not in {".", ".."} and "/" not in name and "\\" not in name
                            and "\x00" not in name,
                            "standard Case08 projection contains an unsafe name", environment=True)
                    count += 1
                    require(count <= max_entries, "standard Case08 projection exceeds entry limit", environment=True)
                    rel = f"{prefix}/{name}" if prefix else name
                    try:
                        info = os.stat(name, dir_fd=dir_fd, follow_symlinks=False)
                    except OSError as exc:
                        raise EnvironmentInvalid("standard Case08 projection entry changed during scan") from exc
                    if stat.S_ISDIR(info.st_mode):
                        child_fd = os.open(name, flags, dir_fd=dir_fd)
                        child_info = os.fstat(child_fd)
                        require((child_info.st_dev, child_info.st_ino) == (info.st_dev, info.st_ino),
                                "standard Case08 projection directory changed during scan", environment=True)
                        inventory[rel] = ("directory", 0, None)
                        pending.append((child_fd, rel))
                    elif stat.S_ISREG(info.st_mode):
                        open_flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
                        file_fd = os.open(name, open_flags, dir_fd=dir_fd)
                        try:
                            before = os.fstat(file_fd)
                            require(stat.S_ISREG(before.st_mode) and before.st_nlink == 1
                                    and before.st_size == info.st_size,
                                    "standard Case08 projection file changed during scan", environment=True)
                            digest = hashlib.sha256()
                            size = 0
                            while True:
                                block = os.read(file_fd, min(1024 * 1024, max_bytes + 1 - total))
                                if not block:
                                    break
                                size += len(block); total += len(block); digest.update(block)
                                require(total <= max_bytes, "standard Case08 projection exceeds byte limit", environment=True)
                            after = os.fstat(file_fd)
                            require((before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns)
                                    == (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns)
                                    and size == before.st_size,
                                    "standard Case08 projection file changed during scan", environment=True)
                            inventory[rel] = ("file", size, "sha256:" + digest.hexdigest())
                        finally:
                            os.close(file_fd)
                    else:
                        raise EnvironmentInvalid("standard Case08 projection contains a symlink or special file")
            finally:
                os.close(dir_fd)
        return inventory
    finally:
        for dir_fd, _ in pending:
            try: os.close(dir_fd)
            except OSError: pass


def _verify_standard_receipt(value: Any, public_pem: str, *, kind: str,
                             provider_id: str, key_id: str, expected: dict) -> dict:
    require(isinstance(value, str), f"standard Case08 {kind} receipt missing", environment=True)
    try:
        raw = base64.b64decode(value, validate=True)
        envelope = json.loads(raw.decode("utf-8", "strict"))
    except (ValueError, UnicodeError, json.JSONDecodeError) as exc:
        raise EnvironmentInvalid(f"standard Case08 {kind} receipt malformed") from exc
    require(len(raw) <= 2 * 1024 * 1024 and isinstance(envelope, dict)
            and set(envelope) == {"body", "signature_b64"} and isinstance(envelope.get("body"), dict),
            f"standard Case08 {kind} receipt envelope invalid", environment=True)
    body = envelope["body"]
    fields = {"domain", "provider_id", "key_id", "attempt_id", "run_id", "case_id", "case_path",
        "image_id", "artifact_manifest_sha256", "attempt_binding_sha256", "declarations",
        "missing_declarations", "observed_empty", "answer_started_at_epoch", "answer_ended_at_epoch",
        "answer_outcome", "container_id", "lifecycle_receipt_sha256", "operational_context_sha256",
        "accounting_status", "source_hashes_sha256", "host_source_hashes_sha256", "kind",
        "host_source_root", "bench_source_hashes_sha256", "bench_source_root"}
    if kind == "collection":
        fields |= {"collection_receipt_sha256", "collection_status"}
    require(set(body) == fields and body.get("domain") == "compchembench.p04-case08-host-receipt/v1"
            and body.get("provider_id") == provider_id and body.get("key_id") == key_id
            and body.get("case_id") == CASE_ID and body.get("kind") == kind,
            f"standard Case08 {kind} receipt schema/provider mismatch", environment=True)
    require(isinstance(body.get("image_id"), str) and SHA256.fullmatch(body["image_id"])
            and isinstance(body.get("container_id"), str) and HEX_SHA256.fullmatch(body["container_id"])
            and type(body.get("observed_empty")) is bool
            and isinstance(body.get("declarations"), list)
            and isinstance(body.get("missing_declarations"), list)
            and body.get("accounting_status") in {"NO_SUBMISSION", "SETTLED"}
            and not isinstance(body.get("answer_started_at_epoch"), bool)
            and isinstance(body.get("answer_started_at_epoch"), (int, float))
            and math.isfinite(body["answer_started_at_epoch"])
            and not isinstance(body.get("answer_ended_at_epoch"), bool)
            and isinstance(body.get("answer_ended_at_epoch"), (int, float))
            and math.isfinite(body["answer_ended_at_epoch"])
            and body["answer_ended_at_epoch"] >= body["answer_started_at_epoch"],
            f"standard Case08 {kind} receipt body has invalid fields", environment=True)
    for field in ("artifact_manifest_sha256", "attempt_binding_sha256", "lifecycle_receipt_sha256",
                  "operational_context_sha256", "source_hashes_sha256",
                  "host_source_hashes_sha256", "bench_source_hashes_sha256"):
        require(isinstance(body.get(field), str) and HEX_SHA256.fullmatch(body[field]),
                f"standard Case08 {kind} receipt {field} is malformed", environment=True)
    if kind == "collection":
        collection_hashes = body.get("collection_receipt_sha256")
        require(isinstance(collection_hashes, list)
                and all(isinstance(value, str) and HEX_SHA256.fullmatch(value) for value in collection_hashes)
                and body.get("collection_status") == ("COLLECTED" if collection_hashes else "EMPTY_SIGNED")
                and (body.get("accounting_status") == "SETTLED") == bool(collection_hashes),
                "standard Case08 collection receipt status/hash inventory is invalid", environment=True)
    for key, expected_value in expected.items():
        require(body.get(key) == expected_value, f"standard Case08 {kind} receipt {key} mismatch", environment=True)
    try:
        signature = base64.b64decode(envelope["signature_b64"], validate=True)
        signed = json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                            allow_nan=False).encode("utf-8")
        public_key = serialization.load_pem_public_key(public_pem.encode("ascii"))
        require(isinstance(public_key, Ed25519PublicKey), "Case08 receipt public key is not Ed25519", environment=True)
        public_key.verify(signature, signed)
    except (OSError, UnicodeError, ValueError, TypeError) as exc:
        raise EnvironmentInvalid(f"standard Case08 {kind} signature check failed: {exc}") from exc
    except Exception as exc:
        raise EnvironmentInvalid(f"standard Case08 {kind} signature invalid: {exc}") from exc
    return body


def _validate_standard_case08_context(path: Path, final: Path) -> dict:
    raw = _bounded_standard_context(path)
    require(hashlib.sha256(raw).hexdigest() == os.environ.get("CCB_RUN_CONTEXT_SHA256"),
            "standard Case08 context does not match fixed digest", environment=True)
    try:
        ctx = json.loads(raw.decode("utf-8", "strict"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise EnvironmentInvalid("standard Case08 context JSON invalid") from exc
    provider_id, image_id = os.environ.get("CCB_P04_CASE08_PROVIDER_ID"), os.environ.get("CCB_P04_CASE08_IMAGE_ID")
    require(isinstance(ctx, dict) and ctx.get("schema") == "compchembench.runner-context/v2"
            and ctx.get("task_id") == CASE_ID and ctx.get("provider_id") == provider_id
            and ctx.get("image_id") == image_id and ctx.get("accepted_runtime_context") is True,
            "standard Case08 context is not accepted or bound to the fixed image/provider", environment=True)
    require(isinstance(provider_id, str) and provider_id.startswith("compchembench.p04-case08-host-receipt/v1:")
            and isinstance(image_id, str) and SHA256.fullmatch(image_id),
            "standard Case08 provider/image environment invalid", environment=True)
    pub, key_id = ctx.get("provider_public_key_pem"), ctx.get("provider_key_id")
    receipts = ctx.get("host_receipts")
    require(isinstance(pub, str) and len(pub) <= 8192 and isinstance(key_id, str)
            and provider_id.endswith(":" + key_id) and isinstance(receipts, dict)
            and set(receipts) == {"lifecycle", "collection"},
            "standard Case08 public receipt identity incomplete", environment=True)
    try:
        public_key = serialization.load_pem_public_key(pub.encode("ascii"))
        require(isinstance(public_key, Ed25519PublicKey), "Case08 receipt key is not Ed25519", environment=True)
        der = public_key.public_bytes(serialization.Encoding.DER,
                                      serialization.PublicFormat.SubjectPublicKeyInfo)
        require(hashlib.sha256(der).hexdigest()[:16] == key_id
                and hashlib.sha256(pub.encode("ascii")).hexdigest() == ctx.get("provider_public_key_sha256"),
                "standard Case08 provider key id or fingerprint mismatch", environment=True)
    except EnvironmentInvalid:
        raise
    except Exception as exc:
        raise EnvironmentInvalid(f"standard Case08 public provider key is invalid: {exc}") from exc
    runtime = ctx.get("p04_case08_runtime")
    require(isinstance(runtime, dict) and runtime.get("schema") == "p04-case08-verifier-context/v2"
            and runtime.get("case_id") == CASE_ID and runtime.get("attempt_id") == ctx.get("attempt_id")
            and runtime.get("image_id") == image_id and runtime.get("unresolved_job_count") == 0
            and isinstance(runtime.get("runtime_admission_sha256"), str),
            "standard Case08 lifecycle/admission context is incomplete", environment=True)
    canonical = lambda obj: json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                                       allow_nan=False).encode("utf-8")
    expected = {"attempt_id": ctx.get("attempt_id"), "run_id": ctx.get("run_id"), "case_id": CASE_ID,
        "image_id": image_id, "artifact_manifest_sha256": ctx.get("store_artifact_manifest_sha256"),
        "attempt_binding_sha256": ctx.get("attempt_binding_sha256"),
        "declarations": ctx.get("artifact_declarations"), "missing_declarations": ctx.get("missing_declarations"),
        "answer_outcome": "COMPLETED", "host_source_root": ctx.get("host_source_root"),
        "bench_source_root": ctx.get("bench_source_root")}
    hashes = {"source_hashes_sha256": "source_hashes", "host_source_hashes_sha256": "host_source_hashes",
              "bench_source_hashes_sha256": "bench_source_hashes"}
    for field, source in hashes.items():
        require(isinstance(ctx.get(source), dict), f"standard Case08 {source} missing", environment=True)
        expected[field] = hashlib.sha256(canonical(ctx[source])).hexdigest()
    expected["accounting_status"] = "SETTLED" if runtime.get("collections") else "NO_SUBMISSION"
    life = _verify_standard_receipt(receipts.get("lifecycle"), pub, kind="lifecycle",
        provider_id=provider_id, key_id=key_id, expected=expected)
    collection = _verify_standard_receipt(receipts.get("collection"), pub, kind="collection",
        provider_id=provider_id, key_id=key_id, expected=expected)
    common_fields = set(life) - {"kind"}
    require(all(life.get(field) == collection.get(field) for field in common_fields),
            "standard Case08 lifecycle and collection receipts disagree", environment=True)
    require(life.get("lifecycle_receipt_sha256") == runtime.get("lifecycle_receipt_sha256")
            and life.get("operational_context_sha256") == hashlib.sha256(canonical(runtime)).hexdigest()
            and collection.get("collection_receipt_sha256") == sorted(item.get("host_receipt_sha256")
                for item in runtime.get("collections", [])),
            "standard Case08 receipts differ from the same closed lifecycle/context", environment=True)
    rows = ctx.get("store_artifact_manifest")
    require(isinstance(rows, list) and hashlib.sha256(canonical(rows)).hexdigest()
            == ctx.get("store_artifact_manifest_sha256"),
            "standard Case08 frozen store manifest digest mismatch", environment=True)
    binding = {"schema": "compchembench.standard-attempt-binding/v1",
        "attempt_id": ctx.get("attempt_id"), "run_id": ctx.get("run_id"),
        "run_path": ctx.get("run_path"), "case_path": ctx.get("case_path"),
        "image_digest": image_id, "source_hashes": ctx.get("source_hashes"),
        "host_source_hashes": ctx.get("host_source_hashes"),
        "host_source_root": ctx.get("host_source_root"),
        "bench_source_hashes": ctx.get("bench_source_hashes"),
        "bench_source_root": ctx.get("bench_source_root"),
        "answer_started_at_epoch": ctx.get("answer_started_at_epoch"),
        "answer_ended_at_epoch": ctx.get("answer_ended_at_epoch"),
        "artifact_manifest_sha256": ctx.get("store_artifact_manifest_sha256"),
        "declarations": ctx.get("artifact_declarations"),
        "missing_declarations": ctx.get("missing_declarations"),
        "observed_empty": ctx.get("observed_empty")}
    require(hashlib.sha256(canonical(binding)).hexdigest() == ctx.get("attempt_binding_sha256"),
            "standard Case08 attempt binding does not recompute", environment=True)
    declaration_rows = ctx.get("artifact_declarations")
    require(isinstance(declaration_rows, list) and declaration_rows
            and all(isinstance(item, dict) and item.get("observation") in {"PRESENT", "MISSING"}
                    for item in declaration_rows),
            "standard Case08 signed artifact declaration set is malformed", environment=True)
    expected_files = []
    for row in rows:
        require(isinstance(row, dict) and isinstance(row.get("path"), str)
                and row.get("type") in {"file", "directory"},
                "standard Case08 frozen manifest row is malformed", environment=True)
        if row["type"] == "file":
            root = row["path"].split("/", 1)[0]
            expected_files.append({"path": "final/" + row["path"].removeprefix(root + "/"),
                                   "sha256": "sha256:" + row["sha256"]})
    expected_files.sort(key=lambda item: item["path"])
    expected_manifest = {"declared": declaration_rows,
        "collected": [{"destination": "final", "files": expected_files}]}
    require(ctx.get("artifact_manifest") == expected_manifest,
            "standard Case08 runner projection differs from the signed store snapshot", environment=True)
    require(final.is_dir() and not final.is_symlink(), "standard Case08 projected final/ is missing", environment=True)
    missing = ctx.get("missing_declarations")
    require(isinstance(missing, list), "standard Case08 missing declaration list invalid", environment=True)
    for item in missing:
        require(isinstance(item, dict) and isinstance(item.get("source"), str),
                "standard Case08 missing declaration malformed", environment=True)
        rel = item["source"].removeprefix("/app/")
        target = final.parent / rel if rel.startswith("final/") else final / rel
        require(not target.is_symlink(), "standard Case08 absence mount is a symlink", environment=True)
        if target.is_dir():
            require(not any(target.iterdir()), "standard Case08 empty-directory mask contains files", environment=True)
        else:
            require(target.is_file() and target.stat().st_size == 0,
                    "standard Case08 missing-file mask is not zero bytes", environment=True)
    # Compare every on-disk file and directory against the signed snapshot.
    # Only fixed zero-byte/empty-directory absence masks are removed from the
    # candidate inventory; unexpected files and byte changes are infrastructure
    # failures before the scientific verifier parses candidate reports.
    expected_rows = {normalized: (row["type"], row["bytes"],
        ("sha256:" + row["sha256"] if row["type"] == "file" else None))
        for row in rows if row["path"] != "final"
        and (normalized := row["path"].removeprefix("final/"))}
    allowed_dirs = {path for path, row in expected_rows.items() if row[0] == "directory"}
    for declaration in declaration_rows:
        parts = declaration["destination"].removeprefix("final/").split("/")
        for index in range(1, len(parts)):
            allowed_dirs.add("/".join(parts[:index]))
    missing_file_masks, missing_dir_masks = set(), set()
    for declaration in missing:
        destination = declaration["destination"].removeprefix("final/")
        if destination == "native_evidence":
            missing_dir_masks.add(destination)
            allowed_dirs.add(destination)
        else:
            missing_file_masks.add(destination)
    actual_rows = _standard_projection_inventory(final)
    for path, row in expected_rows.items():
        require(actual_rows.get(path) == row,
                f"standard Case08 projected snapshot row differs at {path}", environment=True)
    for path in missing_file_masks:
        require(actual_rows.get(path) == ("file", 0, "sha256:" + hashlib.sha256(b"").hexdigest()),
                f"standard Case08 missing-file mask changed at {path}", environment=True)
    for path in missing_dir_masks:
        require(actual_rows.get(path) == ("directory", 0, None),
                f"standard Case08 empty-directory mask changed at {path}", environment=True)
    require({path for path, row in actual_rows.items() if row[0] == "file"}
            == {path for path, row in expected_rows.items() if row[0] == "file"} | missing_file_masks,
            "standard Case08 projection contains an unexpected file", environment=True)
    require({path for path, row in actual_rows.items() if row[0] == "directory"} == allowed_dirs,
            "standard Case08 projection contains an unexpected directory", environment=True)
    return ctx


def validate_assessment_v2_host_bound(tests: Path, final: Path, rubric: dict, rubric_hash: str,
                        provenance: dict, manifest: dict[str, str]) -> tuple[dict | None, str | None]:
    context_env = os.environ.get("CCB_RUN_CONTEXT_PATH", "/trusted/runner-context.json")
    context_path = Path(context_env)
    if not context_path.is_file() or context_path.is_symlink():
        return None, "trusted per-attempt runner context is not mounted"
    standard_mode = "CCB_P04_CASE08_PROVIDER_ID" in os.environ
    if standard_mode:
        runner_context = _validate_standard_case08_context(context_path, final)
    else:
        runner_context = json_no_duplicates(context_path, environment=True)
    require(isinstance(runner_context, dict), "trusted runner context must be an object", environment=True)
    context_hash = digest(context_path)
    require(runner_context.get("schema") == ("compchembench.runner-context/v2" if standard_mode else "compchembench.runner-context/v1"),
            "unsupported runner context schema", environment=True)
    require(runner_context.get("task_id") == CASE_ID, "runner context task_id mismatch", environment=True)
    for field in ("attempt_id", "nonce", "task_config_sha256", "instruction_sha256", "image_id"):
        nonempty_string(runner_context.get(field), f"runner_context.{field}", environment=True)
    for field in ("answer_started_at_epoch", "answer_ended_at_epoch"):
        value = runner_context.get(field)
        require(not isinstance(value, bool) and isinstance(value, (int, float)) and math.isfinite(value),
                f"runner_context.{field} must be a finite epoch", environment=True)
    require(runner_context["answer_ended_at_epoch"] >= runner_context["answer_started_at_epoch"],
            "runner context answer window is reversed", environment=True)
    case_runtime = runner_context.get("p04_case08_runtime")
    require(isinstance(case_runtime, dict)
            and case_runtime.get("schema") == ("p04-case08-verifier-context/v2" if standard_mode else "p04-case08-verifier-context/v1")
            and case_runtime.get("case_id") == CASE_ID
            and case_runtime.get("attempt_id") == runner_context["attempt_id"]
            and case_runtime.get("image_id") == runner_context["image_id"]
            and case_runtime.get("unresolved_job_count") == 0
            and isinstance(case_runtime.get("collections"), list),
            "trusted Case08 runtime context is missing or bound to another attempt/image", environment=True)
    artifact_manifest = runner_context.get("artifact_manifest")
    require(isinstance(artifact_manifest, dict), "runner context artifact_manifest is missing", environment=True)
    expected_artifact_digest = hashlib.sha256(
        json.dumps(artifact_manifest, sort_keys=True, separators=(",", ":"),
                   ensure_ascii=False, allow_nan=False).encode("utf-8")).hexdigest()
    require(runner_context.get("artifact_manifest_sha256") == expected_artifact_digest,
            "runner context artifact manifest digest mismatch", environment=True)
    collected = artifact_manifest.get("collected")
    require(isinstance(collected, list), "runner context collected artifacts must be an array", environment=True)
    snapshot_manifest: dict[str, str] = {}
    for artifact in collected:
        require(isinstance(artifact, dict), "runner context artifact entry must be an object", environment=True)
        files = artifact.get("files", [])
        require(isinstance(files, list), "runner context artifact files must be an array", environment=True)
        for item in files:
            require(isinstance(item, dict) and isinstance(item.get("path"), str)
                    and normalized_sha256(item.get("sha256")) is not None,
                    "runner context artifact file entry is invalid", environment=True)
            relpath = item["path"]
            if not relpath.startswith("final/"):
                continue
            rel = relpath[len("final/"):]
            require(rel and rel not in snapshot_manifest,
                    "runner context has duplicate/empty final artifact path", environment=True)
            snapshot_manifest[rel] = normalized_sha256(item["sha256"])
    if snapshot_manifest != manifest:
        return None, "runner context is bound to a different collected candidate snapshot"

    path = tests / "protected" / "review-assessment.json"
    if not path.is_file():
        return None, "protected review assessment is not present"
    assessment = json_no_duplicates(path, environment=True)
    require(isinstance(assessment, dict) and assessment.get("schema_version") == ASSESSMENT_SCHEMA,
            "unsupported protected review assessment", environment=True)
    if assessment.get("status") == "PENDING":
        return None, assessment.get("note", "scientific review is pending")
    require(assessment.get("status") == "COMPLETE", "assessment status must be PENDING or COMPLETE", environment=True)
    require(assessment.get("case_id") == CASE_ID, "assessment case_id mismatch", environment=True)
    require(assessment.get("rubric_sha256") == rubric_hash, "assessment is bound to a different rubric", environment=True)
    refs = json_no_duplicates(tests / "refs.json", environment=True)
    expected_reference_integrity = {
        "source_digest": refs.get("source_digest"),
        "evaluator_sources": {entry.get("path"): entry.get("sha256")
                              for entry in refs.get("evaluator_sources", []) if isinstance(entry, dict)},
    }
    require(assessment.get("reference_integrity") == expected_reference_integrity,
            "signed review does not confirm the pinned source byte check", environment=True)
    if (assessment.get("attempt_id") != runner_context["attempt_id"]
            or assessment.get("runner_context_sha256") != context_hash):
        return None, "signed review is bound to a different runner attempt/context"
    if assessment.get("candidate_manifest") != manifest:
        return None, "signed review is bound to a different candidate snapshot"
    reviewer = assessment.get("reviewer")
    require(isinstance(reviewer, dict), "assessment reviewer record is missing", environment=True)
    for field in ("id", "role", "reviewed_at"):
        nonempty_string(reviewer.get(field), f"reviewer.{field}")

    runs = {run["id"]: run for run in provenance["executions"]}
    evidence = {item["id"]: item for item in provenance["evidence"]}
    receipts = assessment.get("trusted_receipts")
    require(isinstance(receipts, list), "assessment trusted_receipts must be an array", environment=True)
    verified: dict[str, list[dict]] = {}
    host_collections = {item.get("handle"): item for item in case_runtime["collections"]
                        if isinstance(item, dict) and isinstance(item.get("handle"), str)}
    require(len(host_collections) == len(case_runtime["collections"]),
            "trusted Case08 collection context contains malformed/duplicate handles", environment=True)
    for receipt in receipts:
        require(isinstance(receipt, dict), "trusted receipt entries must be objects", environment=True)
        run_id, evidence_id = receipt.get("execution_id"), receipt.get("evidence_id")
        require(run_id in runs and evidence_id in evidence,
                "trusted receipt refers to missing candidate run/evidence", environment=True)
        require(evidence[evidence_id].get("role") == "execution_receipt",
                "trusted receipt evidence has wrong role", environment=True)
        require(evidence_id in runs[run_id].get("receipt_evidence_ids", []),
                "trusted receipt is not linked by its execution record", environment=True)
        require(receipt.get("sha256") == evidence[evidence_id].get("sha256")
                and receipt.get("path") == evidence[evidence_id].get("path"),
                "trusted receipt does not match candidate bytes", environment=True)
        nonempty_string(receipt.get("authority"), "trusted_receipt.authority")
        nonempty_string(receipt.get("checked_at"), "trusted_receipt.checked_at")
        handle = receipt.get("host_collection_handle")
        host_receipt_sha = receipt.get("host_collection_receipt_sha256")
        host_collection = host_collections.get(handle)
        require(isinstance(host_collection, dict)
                and host_collection.get("host_receipt_sha256") == host_receipt_sha
                and any(normalized_sha256(item.get("sha256")) == normalized_sha256(receipt.get("sha256"))
                        for item in host_collection.get("files", []) if isinstance(item, dict)),
                "trusted execution receipt is not among the immutable same-attempt host-collected bytes",
                environment=True)
        verified.setdefault(run_id, []).append(receipt)
    # Hash-check the independent receipt snapshots copied into evaluator-only TESTS.
    for run_id, entries in verified.items():
        for receipt in entries:
            snapshot = receipt.get("evaluator_snapshot")
            snapshot_hash = receipt.get("evaluator_snapshot_sha256")
            require(isinstance(snapshot, str) and snapshot.startswith("protected/receipt-snapshots/"),
                    "trusted receipt snapshot must be inside protected/receipt-snapshots", environment=True)
            try:
                snapshot_path = safe_file(tests, snapshot, f"trusted receipt for {run_id}")
            except CandidateError as exc:
                raise EnvironmentInvalid(str(exc)) from exc
            require(isinstance(snapshot_hash, str) and SHA256.fullmatch(snapshot_hash)
                    and digest(snapshot_path) == snapshot_hash,
                    f"trusted receipt snapshot hash mismatch for {run_id}", environment=True)

    judgments = assessment.get("judgments")
    require(isinstance(judgments, dict) and set(judgments) == set(REVIEW_CRITERIA),
            "assessment must judge every protected rubric criterion", environment=True)
    verdicts: dict[str, str] = {}
    for criterion, judgment in judgments.items():
        require(isinstance(judgment, dict) and judgment.get("verdict") in {"PASS", "FAIL"},
                f"invalid judgment for {criterion}", environment=True)
        nonempty_string(judgment.get("reason"), f"judgment[{criterion}].reason")
        paths = judgment.get("evidence_paths")
        require(isinstance(paths, list), f"judgment[{criterion}] evidence_paths must be a list", environment=True)
        if judgment["verdict"] == "PASS":
            require(bool(paths), f"PASS judgment needs cited candidate evidence: {criterion}", environment=True)
            notes = judgment.get("evidence_notes")
            require(isinstance(notes, list) and bool(notes)
                    and all(isinstance(note, str) and note.strip() for note in notes),
                    f"PASS judgment needs evidence_notes: {criterion}", environment=True)
        for relpath in paths:
            safe_file(final, relpath, f"judgment[{criterion}]")
        verdicts[criterion] = judgment["verdict"]

    authentication = assessment.get("execution_authentication")
    new_runs = {run_id for run_id, run in runs.items() if run.get("kind") == "new_computation"}
    require(isinstance(authentication, dict) and set(authentication) == new_runs,
            "assessment execution_authentication must account for every new computation", environment=True)
    unsubstantiated: list[str] = []
    for run_id, record in authentication.items():
        require(isinstance(record, dict) and set(record) == {"status", "reason", "evidence_paths"},
                f"execution authentication record is malformed: {run_id}", environment=True)
        require(record.get("status") in {"AUTHENTICATED", "UNSUBSTANTIATED"},
                f"execution authentication status is invalid: {run_id}", environment=True)
        nonempty_string(record.get("reason"), f"execution_authentication[{run_id}].reason")
        paths = record.get("evidence_paths")
        require(isinstance(paths, list),
                f"execution_authentication[{run_id}].evidence_paths must be an array", environment=True)
        for relpath in paths:
            safe_file(final, relpath, f"execution_authentication[{run_id}]")
        if record["status"] == "AUTHENTICATED":
            require(run_id in verified,
                    f"authenticated new execution lacks an independent receipt: {run_id}", environment=True)
        else:
            require(run_id not in verified,
                    f"unsubstantiated execution has an evaluator-authenticated receipt: {run_id}", environment=True)
            unsubstantiated.append(run_id)
    if unsubstantiated:
        require(verdicts.get("independent_new_science") == "FAIL"
                and verdicts.get("route_specific_scientific_validity") == "FAIL",
                "unsubstantiated new execution cannot support a PASS scientific judgment", environment=True)

    preflight = assessment.get("preflight")
    require(isinstance(preflight, dict), "assessment preflight is missing", environment=True)
    required_gates = ("reference_integrity_verified", "verifier_isolated_from_candidate_processes",
                      "hpc_execution_cycle_verified", "resources_independently_accounted",
                      "other_case_and_evaluator_isolation_verified", "runner_attempt_binding_verified")
    for gate in required_gates:
        require(isinstance(preflight.get(gate), bool), f"preflight.{gate} must be boolean", environment=True)
    # This gate is derived from the isolated host context comparison above, not trusted
    # from reviewer-supplied metadata. The other operational gates remain reviewer-audited.
    preflight["runner_attempt_binding_verified"] = True
    preflight["reference_integrity_verified"] = True
    return {"reviewer": reviewer, "judgments": judgments, "verdicts": verdicts,
            "preflight": preflight}, None


def validate_assessment(tests: Path, final: Path, rubric: dict, rubric_hash: str,
                        provenance: dict, manifest: dict[str, str]) -> tuple[dict | None, str | None]:
    """Validate a signed, exact-manifest assessment without a host-only runtime context."""
    path = tests / "protected" / "review-assessment.json"
    if not path.is_file() or path.is_symlink():
        raise EnvironmentInvalid("trusted reviewer assessment is missing or unsafe")
    assessment = json_no_duplicates(path, environment=True)
    require(isinstance(assessment, dict) and assessment.get("schema_version") == ASSESSMENT_SCHEMA,
            "unsupported protected review assessment", environment=True)
    if assessment.get("status") == "PENDING":
        return None, assessment.get("note", "scientific review is pending")
    require(assessment.get("status") == "COMPLETE", "assessment status must be PENDING or COMPLETE", environment=True)
    require(assessment.get("case_id") == CASE_ID, "assessment case_id mismatch", environment=True)
    require(assessment.get("rubric_sha256") == rubric_hash, "assessment is bound to a different rubric", environment=True)
    expected_manifest_digest = hashlib.sha256(json.dumps(
        manifest, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()
    require(assessment.get("candidate_manifest") == manifest
            and assessment.get("candidate_manifest_sha256") == expected_manifest_digest,
            "signed review is bound to a different candidate file snapshot", environment=True)
    refs = json_no_duplicates(tests / "refs.json", environment=True)
    expected_integrity = {"source_digest": refs.get("source_digest"),
        "evaluator_sources": {entry.get("path"): entry.get("sha256")
                              for entry in refs.get("evaluator_sources", []) if isinstance(entry, dict)}}
    require(assessment.get("reference_integrity") == expected_integrity,
            "signed review does not confirm pinned literature and source integrity", environment=True)
    reviewer = assessment.get("reviewer")
    require(isinstance(reviewer, dict), "assessment reviewer record is missing", environment=True)
    for field in ("id", "role", "reviewed_at"):
        nonempty_string(reviewer.get(field), f"reviewer.{field}")

    runs = {run["id"]: run for run in provenance["executions"]}
    evidence = {item["id"]: item for item in provenance["evidence"]}
    trusted_receipts = assessment.get("trusted_receipts")
    require(isinstance(trusted_receipts, list), "assessment trusted_receipts must be an array", environment=True)
    verified: dict[str, list[dict]] = {}
    for receipt in trusted_receipts:
        require(isinstance(receipt, dict), "trusted receipt entries must be objects", environment=True)
        run_id, evidence_id = receipt.get("execution_id"), receipt.get("evidence_id")
        require(run_id in runs and evidence_id in evidence
                and runs[run_id].get("kind") == "new_computation",
                "trusted receipt refers to a missing candidate computation/evidence", environment=True)
        item = evidence[evidence_id]
        require(item.get("role") == "execution_receipt"
                and evidence_id in runs[run_id].get("receipt_evidence_ids", [])
                and receipt.get("sha256") == item.get("sha256")
                and receipt.get("path") == item.get("path"),
                "trusted receipt does not match linked candidate receipt bytes", environment=True)
        nonempty_string(receipt.get("authority"), "trusted_receipt.authority")
        nonempty_string(receipt.get("checked_at"), "trusted_receipt.checked_at")
        if receipt.get("status") != "AUTHENTICATED":
            raise EnvironmentInvalid("signed assessment contains a non-authenticated trusted receipt")
        snapshot = receipt.get("evaluator_snapshot")
        snapshot_hash = receipt.get("evaluator_snapshot_sha256")
        require(isinstance(snapshot, str) and snapshot.startswith("protected/receipt-snapshots/"),
                "trusted receipt snapshot must be evaluator-side", environment=True)
        try:
            snapshot_path = safe_file(tests, snapshot, f"trusted receipt for {run_id}")
        except CandidateError as exc:
            raise EnvironmentInvalid(str(exc)) from exc
        require(isinstance(snapshot_hash, str) and SHA256.fullmatch(snapshot_hash)
                and digest(snapshot_path) == snapshot_hash == item.get("sha256"),
                f"independent receipt snapshot differs from candidate bytes for {run_id}", environment=True)
        verified.setdefault(run_id, []).append(receipt)

    judgments = assessment.get("judgments")
    require(isinstance(judgments, dict) and set(judgments) == set(REVIEW_CRITERIA),
            "assessment must judge every protected rubric criterion", environment=True)
    verdicts: dict[str, str] = {}
    for criterion, judgment in judgments.items():
        require(isinstance(judgment, dict) and judgment.get("verdict") in {"PASS", "FAIL"},
                f"invalid judgment for {criterion}", environment=True)
        nonempty_string(judgment.get("reason"), f"judgment[{criterion}].reason")
        paths = judgment.get("evidence_paths")
        require(isinstance(paths, list), f"judgment[{criterion}] evidence_paths must be a list", environment=True)
        if judgment["verdict"] == "PASS":
            require(bool(paths), f"PASS judgment needs cited candidate evidence: {criterion}", environment=True)
            notes = judgment.get("evidence_notes")
            require(isinstance(notes, list) and notes and all(isinstance(x, str) and x.strip() for x in notes),
                    f"PASS judgment needs evidence_notes: {criterion}", environment=True)
        for relpath in paths:
            safe_file(final, relpath, f"judgment[{criterion}]")
        verdicts[criterion] = judgment["verdict"]

    authentication = assessment.get("execution_authentication")
    new_runs = {run_id for run_id, run in runs.items() if run.get("kind") == "new_computation"}
    require(isinstance(authentication, dict) and set(authentication) == new_runs,
            "assessment execution_authentication must account for every new computation", environment=True)
    unsubstantiated = []
    for run_id, record in authentication.items():
        require(isinstance(record, dict) and set(record) == {"status", "reason", "evidence_paths"}
                and record.get("status") in {"AUTHENTICATED", "UNSUBSTANTIATED"},
                f"execution authentication record is malformed: {run_id}", environment=True)
        nonempty_string(record.get("reason"), f"execution_authentication[{run_id}].reason")
        require(isinstance(record.get("evidence_paths"), list),
                f"execution_authentication[{run_id}].evidence_paths must be an array", environment=True)
        for relpath in record["evidence_paths"]:
            safe_file(final, relpath, f"execution_authentication[{run_id}]")
        if record["status"] == "AUTHENTICATED":
            require(run_id in verified, f"authenticated execution has no independently reviewed receipt: {run_id}", environment=True)
        else:
            require(run_id not in verified, f"unsubstantiated execution has an authenticated receipt: {run_id}", environment=True)
            unsubstantiated.append(run_id)
    if unsubstantiated:
        require(verdicts.get("independent_new_science") == "FAIL"
                and verdicts.get("route_specific_scientific_validity") == "FAIL",
                "unsubstantiated execution cannot support a PASS scientific judgment", environment=True)

    preflight = assessment.get("preflight")
    required_gates = ("reference_integrity_verified", "verifier_isolated_from_candidate_processes",
        "resources_independently_accounted", "other_case_and_evaluator_isolation_verified",
        "candidate_manifest_bound", "docker_environment_smoke_verified")
    require(isinstance(preflight, dict) and all(type(preflight.get(k)) is bool for k in required_gates),
            "assessment preflight is missing required boolean gates", environment=True)
    preflight["candidate_manifest_bound"] = True
    preflight["reference_integrity_verified"] = True
    return {"reviewer": reviewer, "judgments": judgments, "verdicts": verdicts,
            "preflight": preflight}, None


def verify(final: Path, tests: Path, *, review_key_sha256: str | None = None) -> dict:
    report = {"schema_version": "case08-verification/v1", "status": "ENV_INVALID",
              "reward": None, "checks": {}, "errors": [],
              "scientific_review": "not completed", "score_mode": "diagnostic-review"}
    try:
        refs, rubric, rubric_hash = validate_evaluator_inputs(tests, final, review_key_sha256)
    except (EnvironmentInvalid, TypeError, ValueError, OverflowError, RecursionError,
            KeyError, IndexError, OSError) as exc:
        report["errors"].append(str(exc) if isinstance(exc, EnvironmentInvalid)
                                else f"malformed evaluator input: {exc}")
        return report

    try:
        provenance, manifest = validate_submission(final)
        report["optional_native_diagnostics"] = analyze_submission(final, provenance)
        try:
            report["slurm_records"] = slurm_records.directory(final, "native_evidence/slurm")
        except (slurm_records.RecordError, OSError, ValueError, TypeError, KeyError) as exc:
            raise CandidateError(str(exc)) from exc
        report["checks"]["deliverables_present"] = "PASS"
        report["checks"]["execution_evidence_traceable"] = "PASS_STRUCTURAL_ONLY"
        report["checks"]["environment_only_boundary"] = "PENDING_REVIEW"
        report["declared_diagnostic_scope"] = [
            "historical local ARM64 MESMER g50/g200 controls are bounded diagnostic evidence",
            "the controls are described as empirical and conditional"]
        report["checked_claims"] = []
        report["unverified_claims"] = list(rubric["criteria"])
        report["claim_assessment_state"] = {
            "checked_claims": "NOT_ASSESSED",
            "unverified_claims": "REVIEW_REQUIRED",
            "bounded_author_diagnostics_are_reference_solution": False}
        report["candidate_manifest"] = manifest
        report["candidate_manifest_sha256"] = hashlib.sha256(
            json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    except (CandidateError, OSError, UnicodeError, RecursionError, TypeError, ValueError, OverflowError,
            KeyError, IndexError) as exc:
        report["status"] = "FAIL"
        report["reward"] = 0
        report["scientific_review"] = "candidate contract/evidence failure"
        report["checks"]["candidate_evidence"] = "FAIL"
        report["errors"].append(str(exc))
        return report

    try:
        assessment, pending = validate_assessment(tests, final, rubric, rubric_hash, provenance, manifest)
    except (EnvironmentInvalid, CandidateError, OSError, UnicodeError, RecursionError, TypeError,
            ValueError, OverflowError, KeyError, IndexError) as exc:
        report["errors"].append(str(exc))
        return report
    if assessment is None:
        report["status"] = "REVIEW_REQUIRED"
        report["scientific_review"] = "trusted evaluator review required"
        report["review_pending_reason"] = pending
        return report

    report["reviewer"] = assessment["reviewer"]
    report["checks"].update(assessment["verdicts"])
    report["judgments"] = assessment["judgments"]
    report["checked_claims"] = [name for name in REVIEW_CRITERIA
                                if assessment["verdicts"].get(name) in {"PASS", "FAIL"}]
    report["unverified_claims"] = [name for name in REVIEW_CRITERIA
                                   if name not in report["checked_claims"]]
    report["claim_assessment_state"] = {
        "checked_claims": "ASSESSED",
        "unverified_claims": "NONE" if not report["unverified_claims"] else "REVIEW_REQUIRED",
        "bounded_author_diagnostics_are_reference_solution": False}
    gates = assessment["preflight"]
    report["preflight"] = gates
    if not all(gates.values()):
        report["status"] = "REVIEW_REQUIRED"
        report["scientific_review"] = "review completed; runtime/evaluator isolation gates remain pending"
        report["review_pending_reason"] = "one or more required trust/resource preflight gates are false"
        return report
    report["checks"]["environment_only_boundary"] = "PASS_PREFLIGHT"
    passed = all(value == "PASS" for value in assessment["verdicts"].values())
    if not passed:
        report["status"] = "FAIL"
        report["reward"] = 0
        report["scientific_review"] = "trusted method-neutral literature-grounded review found an unmet criterion"
        return report
    report["status"] = "PASS" if passed else "FAIL"
    report["reward"] = 1 if passed else 0
    report["scientific_review"] = "trusted method-neutral literature-grounded review"
    return report


def main() -> int:
    app = Path(os.environ.get("APP", "/app")).resolve()
    tests = Path(os.environ.get("TESTS", "/tests")).resolve()
    logs = Path(os.environ.get("LOGS", "/logs/verifier"))
    logs.mkdir(parents=True, exist_ok=True)
    (logs / "reward.txt").unlink(missing_ok=True)
    (logs / "reward.json").unlink(missing_ok=True)
    report = verify(app / "final", tests, review_key_sha256=os.environ.get("CCB_CASE08_REVIEW_KEY_SHA256"))
    if report["status"] == "REVIEW_REQUIRED":
        report.pop("reward", None)
        (logs / "reward.json").write_text("{}\n", encoding="utf-8")
    (logs / "verification.json").write_text(json.dumps(report, indent=2, ensure_ascii=False,
                                                        allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, allow_nan=False))
    if report["status"] == "PASS":
        (logs / "reward.txt").write_text("1\n", encoding="utf-8")
        return 0
    if report["status"] == "FAIL":
        (logs / "reward.txt").write_text("0\n", encoding="utf-8")
        return 1
    if report["status"] == "REVIEW_REQUIRED":
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
