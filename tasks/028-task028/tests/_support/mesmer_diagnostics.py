"""Optional, bounded diagnostics for submitted native MESMER XML outputs.

These checks describe rates and population traces; they do not establish the
Holy Grail's six core scientific claims or require a MESMER research route.
"""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path, PurePosixPath
from xml.etree import ElementTree as ET

MAX_XML_BYTES = 16 * 1024 * 1024
MAX_RECEIPT_BYTES = 1024 * 1024
MAX_DIAGNOSTIC_XML_FILES = 4
MAX_DIAGNOSTIC_FILES = 8
MAX_DIAGNOSTIC_BYTES = 32 * 1024 * 1024
MESMER_NAMESPACE = "http://www.chem.leeds.ac.uk/mesmer"


class MesmerDiagnosticError(ValueError):
    pass


def _read_candidate_file(final: Path, relative: str, limit: int) -> bytes:
    if not isinstance(relative, str) or not relative.startswith("native_evidence/") or "\\" in relative:
        raise MesmerDiagnosticError("MESMER diagnostic evidence path is outside native_evidence/")
    rel = PurePosixPath(relative)
    if rel.is_absolute() or any(part in {"", ".", ".."} for part in rel.parts):
        raise MesmerDiagnosticError("MESMER diagnostic evidence path is unsafe")
    path = final.joinpath(*rel.parts)
    current = final
    for part in rel.parts:
        current = current / part
        if current.is_symlink():
            raise MesmerDiagnosticError("MESMER diagnostic evidence path contains a symlink")
    if not path.is_file() or path.stat().st_size > limit:
        raise MesmerDiagnosticError("MESMER diagnostic evidence is missing or exceeds its byte limit")
    data = path.read_bytes()
    if len(data) > limit:
        raise MesmerDiagnosticError("MESMER diagnostic evidence changed beyond its byte limit")
    return data


def _finite(value: str | None, label: str) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise MesmerDiagnosticError(f"{label} is not numeric") from exc
    if not math.isfinite(result):
        raise MesmerDiagnosticError(f"{label} is not finite")
    return result


def inspect_mesmer_xml(final: Path, output_path: str, receipt_path: str | None) -> dict | None:
    """Inspect one declared native_output. Return None when it is not MESMER."""
    raw = _read_candidate_file(final, output_path, MAX_XML_BYTES)
    if b"<!DOCTYPE" in raw.upper() or b"<!ENTITY" in raw.upper():
        raise MesmerDiagnosticError("MESMER XML declarations/entities are not accepted")
    try:
        root = ET.fromstring(raw)
    except ET.ParseError as exc:
        if b"mesmer" in raw[:4096].lower():
            raise MesmerDiagnosticError("submitted MESMER XML is malformed") from exc
        return None
    root_name = root.tag.split("}")[-1]
    root_namespace = root.tag[1:].split("}", 1)[0] if root.tag.startswith("{") else None
    if root_name != "mesmer" or root_namespace != MESMER_NAMESPACE:
        return None
    rate_lists = [node for node in root.iter() if node.tag.split("}")[-1] == "rateList"]
    population_lists = [node for node in root.iter() if node.tag.split("}")[-1] == "populationList"]
    if not rate_lists and not population_lists:
        return None
    if len(rate_lists) != 1 or len(population_lists) != 1:
        raise MesmerDiagnosticError("MESMER XML with multiple rate/population conditions is unsupported")

    rate_list = rate_lists[0]
    conditions = {key: rate_list.attrib.get(key) for key in ("T", "conc", "bathGas", "units")}
    rates = {}
    for node in rate_list:
        if node.tag.split("}")[-1] != "firstOrderRate":
            continue
        source, target = node.attrib.get("fromRef"), node.attrib.get("toRef")
        identity = f"{source}->{target}" if source and target else None
        if not source or not target or identity in rates:
            raise MesmerDiagnosticError("MESMER first-order rate identity is missing or duplicated")
        value = _finite((node.text or "").strip(), f"rate {source}->{target}")
        if value < 0:
            raise MesmerDiagnosticError(f"rate {source}->{target} must be nonnegative")
        rates[identity] = {"from": source, "to": target, "value": value}
    if conditions["units"] != "s-1":
        raise MesmerDiagnosticError("MESMER rateList units must be s-1 for first-order rates")
    if not conditions["T"] or not conditions["conc"] or not conditions["bathGas"] or not rates:
        raise MesmerDiagnosticError("MESMER rateList conditions or first-order rates are incomplete")
    temperature = _finite(conditions["T"], "rateList temperature")
    concentration = _finite(conditions["conc"], "rateList concentration")
    if temperature <= 0 or concentration <= 0:
        raise MesmerDiagnosticError("MESMER rateList conditions must be positive")

    points = []
    for node in population_lists[0]:
        if node.tag.split("}")[-1] != "population":
            continue
        at = _finite(node.attrib.get("time"), "population time")
        if at < 0:
            raise MesmerDiagnosticError("MESMER population time cannot be negative")
        values = {}
        for child in node:
            if child.tag.split("}")[-1] != "pop":
                continue
            species = child.attrib.get("ref")
            if not species or species in values:
                raise MesmerDiagnosticError("population species reference is missing or duplicated")
            value = _finite((child.text or "").strip(), f"population {species}")
            if value < 0:
                raise MesmerDiagnosticError(f"population {species} is negative")
            values[species] = value
        if not values:
            raise MesmerDiagnosticError("MESMER population point is empty")
        points.append((at, values))
    if not points or any(a[0] >= b[0] for a, b in zip(points, points[1:])):
        raise MesmerDiagnosticError("MESMER population times must be strictly increasing")
    sums = [sum(values.values()) for _, values in points]
    model_nodes = [node for node in root.iter() if node.tag.split("}")[-1] == "grainSize"]
    model = {
        "grain_size": _finite((model_nodes[0].text or "").strip(), "grain size")
        if len(model_nodes) == 1 else None,
        "grain_size_units": model_nodes[0].attrib.get("units") if len(model_nodes) == 1 else None,
    }

    result = {
        "status": "ASSESSED",
        "evidence": {"path": output_path, "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()},
        "receipt": None,
        "conditions": conditions,
        "model": model,
        "first_order_rates": rates,
        "population": {
            "point_count": len(points), "time_start": points[0][0], "time_end": points[-1][0],
            "all_values_finite_nonnegative": True, "time_strictly_increasing": True,
            "population_sum_min": min(sums), "population_sum_max": max(sums),
            "max_abs_population_sum_error": max(abs(value - 1.0) for value in sums),
            "closure_interpretation": "measured_only; no acceptance threshold or convergence claim",
        },
        "comparison_scope": "single submitted MESMER output; no route or core-claim inference",
    }
    if receipt_path is not None:
        receipt_raw = _read_candidate_file(final, receipt_path, MAX_RECEIPT_BYTES)
        try:
            receipt = json.loads(receipt_raw)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise MesmerDiagnosticError("linked MESMER execution receipt is malformed") from exc
        if not isinstance(receipt, dict):
            raise MesmerDiagnosticError("linked MESMER execution receipt must be an object")
        expected = receipt.get("output_xml_sha256")
        if expected is not None and expected != result["evidence"]["sha256"]:
            raise MesmerDiagnosticError("linked MESMER receipt output_xml_sha256 differs from submitted XML bytes")
        source_digest = receipt.get("source_input_sha256")
        result["receipt"] = {
            "path": receipt_path, "sha256": hashlib.sha256(receipt_raw).hexdigest(),
            "output_hash_matches": expected == result["evidence"]["sha256"] if expected is not None else None,
            "source_input_sha256": source_digest if isinstance(source_digest, str) else None,
            "provenance_class": "candidate_submitted; not independently authenticated by this diagnostic",
        }
    return result


def analyze_submission(final: Path, provenance: dict) -> dict:
    """Run optional diagnostics only on declared MESMER XML native outputs."""
    evidence = {item["id"]: item for item in provenance.get("evidence", []) if isinstance(item, dict)}
    found, issues = [], []
    parsed_files = 0
    parsed_xml_files = 0
    parsed_bytes = 0
    counted_paths: set[str] = set()
    for run in provenance.get("executions", []):
        if not isinstance(run, dict):
            continue
        outputs = [evidence[eid] for eid in run.get("output_evidence_ids", [])
                   if eid in evidence and evidence[eid].get("role") == "native_output"]
        receipts = [evidence[eid] for eid in run.get("receipt_evidence_ids", [])
                    if eid in evidence and evidence[eid].get("role") == "execution_receipt"]
        receipt_path = receipts[0].get("path") if len(receipts) == 1 else None
        if len(receipts) > 1:
            issues.append({"execution_id": run.get("id"), "reason": "multiple linked receipts; no receipt selected"})
        for output in outputs:
            path = output.get("path")
            if not isinstance(path, str) or not path.lower().endswith(".xml"):
                continue
            parsed_xml_files += 1
            if parsed_xml_files > MAX_DIAGNOSTIC_XML_FILES:
                issues.append({"execution_id": run.get("id"), "reason": "diagnostic XML file-count budget reached"})
                break
            try:
                if path not in counted_paths:
                    raw_size = len(_read_candidate_file(final, path, MAX_XML_BYTES))
                    parsed_bytes += raw_size
                    parsed_files += 1
                    counted_paths.add(path)
                if receipt_path is not None and receipt_path not in counted_paths:
                    receipt_size = len(_read_candidate_file(final, receipt_path, MAX_RECEIPT_BYTES))
                    parsed_bytes += receipt_size
                    parsed_files += 1
                    counted_paths.add(receipt_path)
                if parsed_files > MAX_DIAGNOSTIC_FILES:
                    issues.append({"execution_id": run.get("id"), "reason": "diagnostic file-count budget reached"})
                    break
                if parsed_bytes > MAX_DIAGNOSTIC_BYTES:
                    issues.append({"execution_id": run.get("id"), "reason": "diagnostic total-byte budget reached"})
                    break
                inspected = inspect_mesmer_xml(final, path, receipt_path)
                if inspected is not None:
                    found.append({"execution_id": run.get("id"), **inspected})
            except (MesmerDiagnosticError, OSError, UnicodeError, ValueError, TypeError) as exc:
                issues.append({"execution_id": run.get("id"), "path": path, "reason": str(exc)})
    if not found:
        return {"status": "REVIEW_REQUIRED" if issues else "NOT_APPLICABLE", "runs": [], "issues": issues,
                "scope": "No declared native_output MESMER XML was detected; no scientific route is required."}
    if len(found) == 1:
        return {"status": "REVIEW_REQUIRED" if issues else "ASSESSED", "runs": found, "issues": issues,
                "scope": "One native MESMER output was parsed; rates and population trace are diagnostic only."}
    return {"status": "REVIEW_REQUIRED", "runs": found, "issues": issues, "comparison": None,
            "comparison_reason": "submitted hashes do not independently establish model/source identity; no cross-run delta inferred",
            "scope": "MESMER diagnostics do not establish the six core scientific claims."}
