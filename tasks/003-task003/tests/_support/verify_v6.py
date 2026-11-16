#!/usr/bin/env python3
"""Revision 6 checker: public-output validation plus evaluator-owned refits.

Submitted Python is never imported or executed. Only the declared model protocol
is independently fitted; code execution and candidate internals remain unverified.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import case03_independent_refit
import verify as deterministic


SCORER_VERSION = "case03-verifier-6.0.2"


def _report(status: str, **values):
    return {"status": status, "scorer_version": SCORER_VERSION, **values}


def check(submission: Path, assets: Path, refs: Path):
    final = submission / "final"
    static = deterministic.check_submission(submission, assets, refs, internal_static_only=True)
    if static.get("status") != "PASS_STATIC_DIAGNOSTIC":
        return _report("INFRA_ERROR", coverage="NOT_VERIFIED", errors=["deterministic output precheck did not complete"]), 2
    try:
        refit = case03_independent_refit.evaluate(final, assets)
    except case03_independent_refit.ReviewRequired as exc:
        return _report("REVIEW_REQUIRED", coverage="NOT_VERIFIED",
                       submitted_code_execution_verified=False,
                       training_execution_verified=False,
                       candidate_internals_proven=False,
                       declared_protocol_independent_refit_verified=False,
                       errors=[str(exc)]), 2
    except case03_independent_refit.CandidateValidationError as exc:
        return _report("FAIL", coverage="PARTIAL",
                       submitted_code_execution_verified=False,
                       training_execution_verified=False,
                       candidate_internals_proven=False,
                       declared_protocol_independent_refit_verified=False,
                       errors=[f"published candidate protocol violation: {type(exc).__name__}: {exc}"]), 1
    except (OSError, json.JSONDecodeError) as exc:
        return _report("INFRA_ERROR", coverage="NOT_VERIFIED",
                       submitted_code_execution_verified=False,
                       training_execution_verified=False,
                       candidate_internals_proven=False,
                       declared_protocol_independent_refit_verified=False,
                       errors=[f"independent refit inputs unavailable: {type(exc).__name__}: {exc}"]), 2
    if refit.get("status") != "ok" or refit.get("declared_protocol_independent_refit_verified") is not True:
        return _report("FAIL", coverage="PARTIAL",
                       submitted_code_execution_verified=False,
                       training_execution_verified=False,
                       candidate_internals_proven=False,
                       declared_protocol_independent_refit_verified=False,
                       checked=static.get("checked", {}), errors=refit.get("errors", ["independent refit did not match"])), 1
    return _report(
        "PASS",
        coverage="PARTIAL",
        coverage_scope="declared-protocol-independent-refit-over-all-splits; submitted-code-execution-and-arbitrary-internals-unverified",
        submitted_code_execution_verified=False,
        training_execution_verified=False,
        candidate_internals_proven=False,
        declared_protocol_independent_refit_verified=True,
        interval_scope="training_subset_repeat_conditional_on_frozen_test_set",
        checked={**static.get("checked", {}),
                 "independent_refit_records": len(refit.get("records", [])),
                 "model_spec_sha256": refit.get("model_spec_sha256"),
                 "protocol_sha256": refit.get("protocol_sha256"),
                 "splits_sha256": refit.get("splits_sha256"),
                 "predictions_sha256": refit.get("predictions_sha256"),
                 "scikit_learn_version": refit.get("sklearn_version")},
        errors=[], warnings=static.get("warnings", [])), 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--submission", type=Path, required=True)
    parser.add_argument("--assets", type=Path, required=True)
    parser.add_argument("--refs", type=Path, default=Path(__file__).resolve().parent.parent / "refs.json")
    args = parser.parse_args(argv)
    try:
        result, code = check(args.submission.resolve(), args.assets.resolve(), args.refs.resolve())
    except deterministic.ScienceFailure as exc:
        result, code = _report("FAIL", coverage="PARTIAL", submitted_code_execution_verified=False,
                               training_execution_verified=False, candidate_internals_proven=False,
                               declared_protocol_independent_refit_verified=False, errors=[str(exc)]), 1
    except deterministic.InfrastructureFailure as exc:
        result, code = _report("INFRA_ERROR", coverage="NOT_VERIFIED", submitted_code_execution_verified=False,
                               training_execution_verified=False, candidate_internals_proven=False,
                               declared_protocol_independent_refit_verified=False, errors=[str(exc)]), 2
    except Exception as exc:
        result, code = _report("INFRA_ERROR", coverage="NOT_VERIFIED", submitted_code_execution_verified=False,
                               training_execution_verified=False, candidate_internals_proven=False,
                               declared_protocol_independent_refit_verified=False,
                               errors=[f"unexpected verifier error: {type(exc).__name__}: {exc}"]), 2
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
