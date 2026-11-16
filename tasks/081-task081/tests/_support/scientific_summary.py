"""Canonical, checker-recomputed summary for case06 native bond evidence.

This module reports comparison quantities; it does not establish a scientific
tolerance, a geometry minimum, or physical M14 dissociation.
"""
from __future__ import annotations

from collections import defaultdict
from decimal import Decimal, InvalidOperation


ROUTES = {
    "pbe0-tzvp": "PBE0|TZVP",
    "admm-tzvp-tzp": "ADMM|TZVP+tzp",
    "stda-pbe0-tzvp": "sTDA@PBE0|TZVP",
}


def pending_science_sections(remedy_record: dict | None = None) -> tuple[dict, dict]:
    """Canonical summary states while the native M14/minimum adapters are pending."""
    remedy = remedy_record if isinstance(remedy_record, dict) else {}
    return (
        {"status": "pending_native_m14_classification", "aex": 0.2,
         "comparison_target": "null_target_excluded"},
        {"status": "native_traceable_minimum_pending", "route": remedy.get("route"),
         "aex": remedy.get("aex")},
    )


def _decimal(value: object) -> Decimal:
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError("summary measurement is not numeric") from exc
    if not result.is_finite():
        raise ValueError("summary measurement is not finite")
    return result


def _fmt(value: Decimal) -> str:
    # Summary fields normally use fixed 1e-9 precision.  Avoid Decimal's default
    # context precision failure for finite but implausibly large candidate values;
    # those are rejected by the scientific comparison gate before summary use,
    # while diagnostics and direct callers still get a deterministic representation.
    if value and value.adjusted() > 18:
        return str(value)
    try:
        return format(value.quantize(Decimal("0.000000001")), "f")
    except InvalidOperation:
        return str(value)


def summaries_match(expected: dict, candidate: object) -> bool:
    """Compare canonical summary structure with 9-place numeric serialization tolerance."""
    numeric_tolerance = Decimal("0.0000000005")

    def compare(want, got, key: str = "") -> bool:
        if want is None:
            return got is None
        if isinstance(want, dict):
            return (isinstance(got, dict) and set(got) == set(want)
                    and all(compare(value, got[name], name) for name, value in want.items()))
        if key.endswith("_pm"):
            if isinstance(got, bool) or not isinstance(got, (str, int, float, Decimal)):
                return False
            try:
                actual = _decimal(got)
                target = _decimal(want)
            except ValueError:
                return False
            return abs(actual - target) <= numeric_tolerance
        if key == "count":
            return type(got) is int and got == want
        if key == "worst_ref_ids":
            return (isinstance(got, list) and all(isinstance(x, str) for x in got)
                    and len(got) == len(set(got)) and set(got) == set(want))
        if isinstance(want, list):
            return isinstance(got, list) and len(got) == len(want) and all(
                compare(a, b) for a, b in zip(want, got))
        return type(got) is type(want) and got == want

    return compare(expected, candidate)


def _stats(rows: list[tuple[str, Decimal]]) -> dict:
    if not rows:
        return {"count": 0, "signed_mean_pm": None, "mae_pm": None,
                "max_abs_pm": None, "worst_ref_ids": []}
    vals = [value for _, value in rows]
    maxabs = max(abs(x) for x in vals)
    worst = sorted(key for key, value in rows if abs(value) == maxabs)
    return {"count": len(rows), "signed_mean_pm": _fmt(sum(vals) / Decimal(len(vals))),
            "mae_pm": _fmt(sum(abs(x) for x in vals) / Decimal(len(vals))),
            "max_abs_pm": _fmt(maxabs), "worst_ref_ids": worst}


def build_summary(refs: dict, native_bonds: dict[tuple[str, str, str], object],
                  *, m14_default: dict | None = None, m14_remedy: dict | None = None,
                  minimum_status: dict | None = None) -> dict:
    """Compute published/EOM, same-method residuals and ADMM-PBE0 differences.

    `native_bonds` must be recomputed from hash-checked native final XYZ files by
    the caller. No candidate-provided aggregate is accepted here.
    """
    items = refs.get("items")
    if not isinstance(items, dict):
        raise ValueError("reference item mapping missing")
    measured = {}
    for ref_id, item in items.items():
        if item.get("state") != "ES" or item.get("quantity") != "bond":
            continue
        mol, label = item.get("molecule"), item.get("label")
        if not isinstance(mol, str) or not isinstance(label, str):
            raise ValueError("reference bond identity malformed")
        for route, column in ROUTES.items():
            published = item.get("values", {}).get(column)
            if published is None:
                continue
            key = (mol, route, label)
            if key not in native_bonds:
                raise ValueError(f"missing recomputed native bond: {ref_id}/{route}")
            val = _decimal(native_bonds[key])
            measured[key] = (ref_id, val, _decimal(published), _decimal(item["values"]["CCSD"]))
    methods = {}
    for route, column in ROUTES.items():
        eom_rows, paper_rows = [], []
        for (mol, r, label), (ref_id, val, published, eom) in measured.items():
            if r != route:
                continue
            eom_rows.append((ref_id, val - eom))
            paper_rows.append((ref_id, val - published))
        methods[route] = {
            "published_method_column": column,
            "vs_eom_ccsd": _stats(eom_rows),
            "same_method_paper_residual": _stats(paper_rows),
        }
    admm_delta = []
    for ref_id, item in items.items():
        if item.get("state") != "ES" or item.get("quantity") != "bond":
            continue
        mol, label = item["molecule"], item["label"]
        keys = ((mol, "admm-tzvp-tzp", label), (mol, "pbe0-tzvp", label))
        if all(key in measured for key in keys):
            admm_delta.append((ref_id, measured[keys[0]][1] - measured[keys[1]][1]))
    return {
        "schema": "case06-scientific-summary/v1",
        "units": {"bond_length": "pm", "signed_delta": "candidate minus reference"},
        "summary_basis": {
            "source": "checker-recomputed from native final XYZ and frozen tests/refs.json",
            "scope": "five tracked case06 molecules, not the full paper dataset",
            "tracked_rows": 13,
            "aggregation": "tracked-SI-bond-rows/equal-weight-after-symmetry-means",
            "method_counts": {"PBE0|TZVP": 13, "ADMM|TZVP+tzp": 13, "sTDA@PBE0|TZVP": 10},
            "m14_default_stda": "null target excluded; remedy reported separately",
            "interpretation": "aggregates are descriptive; only rowwise reviewed policy gates reward",
        },
        "methods": methods,
        "admm_minus_pbe0": _stats(admm_delta),
        "m14": {"default": m14_default or {"status": "not_validated"},
                "remedy": m14_remedy or {"status": "not_validated"}},
        "minimum_status": minimum_status or {"status": "not_validated"},
    }
