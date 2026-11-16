#!/usr/bin/env python3
"""Deterministic delivery checks plus the fixed Case 02 source replay."""
from __future__ import annotations

import importlib.util
import json
import os
import sys
from pathlib import Path

APP = Path(os.environ.get("APP", "/app")).resolve()
TESTS = Path(os.environ.get("TESTS", "/tests")).resolve()


def main() -> int:
    sys.path.insert(0, str(TESTS))
    import diagnostic

    base = diagnostic.run(APP, TESTS)
    if base.get("status") == "FAIL":
        print(json.dumps(base, ensure_ascii=False, allow_nan=False))
        return 1
    if base.get("status") != "REVIEW_REQUIRED":
        print(json.dumps({"status": "INFRASTRUCTURE_ERROR", "checks": [],
                          "error": "base diagnostic returned an invalid status"}, ensure_ascii=False))
        return 2
    protocol = diagnostic.load(TESTS / "assessment-protocol.json")
    refs = diagnostic.load(TESTS / "refs.json")
    module_path = TESTS / "mvp_numeric.py"
    if module_path.is_symlink() or not module_path.is_file():
        print(json.dumps({"status": "INFRASTRUCTURE_ERROR", "checks": [],
                          "error": "trusted MVP numeric module missing or unsafe"}, ensure_ascii=False))
        return 2
    spec = importlib.util.spec_from_file_location("_case02_mvp_numeric", module_path)
    if spec is None or spec.loader is None:
        print(json.dumps({"status": "INFRASTRUCTURE_ERROR", "checks": [],
                          "error": "trusted MVP numeric module cannot be loaded"}, ensure_ascii=False))
        return 2
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
        checked = module.verify_case02(APP, APP, protocol, refs)
    except Exception as exc:
        if exc.__class__.__name__ in {"CandidateError", "CandidateInputError"}:
            base["status"] = "FAIL"
            base["checks"].append({"criterion": "mvp_case02_numeric_replay", "passed": False,
                                  "error": str(exc)})
            print(json.dumps(base, ensure_ascii=False, allow_nan=False))
            return 1
        print(json.dumps({"status": "INFRASTRUCTURE_ERROR", "checks": [],
                          "error": f"trusted Case 02 replay failed: {exc}"}, ensure_ascii=False))
        return 2
    status = checked.get("status") if isinstance(checked, dict) else None
    if status == "INFRA":
        print(json.dumps({"status": "INFRASTRUCTURE_ERROR", "checks": [],
                          "numeric_evidence": checked}, ensure_ascii=False, allow_nan=False))
        return 2
    if status not in {"PASS", "NEEDS_JUDGE", "JUDGE_REQUIRED", "FAIL"}:
        print(json.dumps({"status": "INFRASTRUCTURE_ERROR", "checks": [],
                          "error": "trusted Case 02 replay returned an invalid status"}, ensure_ascii=False))
        return 2
    if status != "FAIL":
        try:
            from mvp_host_evidence import model_native_affine_summary
            mapping = model_native_affine_summary(module, APP, refs)
            criterion = checked["criteria"]["published_model_forward_and_native_comparison"]
            criterion.setdefault("checked_values", {})["model_native_affine_fits"] = mapping
        except Exception as exc:
            print(json.dumps({"status": "INFRASTRUCTURE_ERROR", "checks": [],
                              "error": f"trusted model/native review summary failed: {exc}"}, ensure_ascii=False))
            return 2
    old_numeric = base.get("numeric_evidence")
    old_criteria = old_numeric.get("criteria") if isinstance(old_numeric, dict) else None
    new_criteria = checked.get("criteria")
    if not isinstance(old_criteria, dict) or not isinstance(new_criteria, dict):
        print(json.dumps({"status": "INFRASTRUCTURE_ERROR", "checks": [],
                          "error": "legacy and MVP numeric criteria are missing"}, ensure_ascii=False))
        return 2
    merged_criteria = dict(old_criteria)
    for key, value in new_criteria.items():
        prior = merged_criteria.get(key)
        if prior is not None and not (prior.get("status") == "JUDGE_REQUIRED" and not prior.get("checked_values") and not prior.get("source_hashes")):
            print(json.dumps({"status": "INFRASTRUCTURE_ERROR", "checks": [],
                              "error": f"legacy numeric evidence conflicts with MVP criterion {key}"}, ensure_ascii=False))
            return 2
        merged_criteria[key] = value
    merged = {**old_numeric, "criteria": merged_criteria}
    necessary = {item.get("criterion") for item in protocol.get("criteria", [])
                 if isinstance(item, dict) and item.get("necessary") is True}
    if not necessary or set(merged["criteria"]) != necessary:
        print(json.dumps({"status": "INFRASTRUCTURE_ERROR", "checks": [],
                          "error": "merged numeric evidence does not match the public necessary criteria"}, ensure_ascii=False))
        return 2
    merged["status"] = ("INFRA" if any(item.get("status") == "INFRA" for item in merged["criteria"].values())
                        else "FAIL" if any(item.get("status") == "FAIL" for item in merged["criteria"].values())
                        else "PASS" if all(item.get("status") == "PASS" for item in merged["criteria"].values())
                        else "NEEDS_JUDGE")
    base["numeric_evidence"] = merged
    if status == "FAIL" or merged["status"] == "FAIL":
        base["status"] = "FAIL"
        base["checks"].append({"criterion": "mvp_case02_numeric_replay", "passed": False,
                              "result": checked})
        print(json.dumps(base, ensure_ascii=False, allow_nan=False))
        return 1
    base["checks"].append({"criterion": "mvp_case02_numeric_replay", "passed": True,
                          "result": checked})
    print(json.dumps(base, ensure_ascii=False, allow_nan=False))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(json.dumps({"status": "INFRASTRUCTURE_ERROR", "checks": [],
                          "error": str(exc)}, ensure_ascii=False))
        raise SystemExit(2)
