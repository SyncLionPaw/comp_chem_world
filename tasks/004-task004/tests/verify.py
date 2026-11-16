# L1 Deliverables: Check required deliverables for completeness and parseability.
# L2 Execution: No separate execution attestation is implied by checks of submitted results.
# L3 Science: Uncertainty calibration and applicability domain.
"""Case 04 package entry point; prefers the bundled independent grader module."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

HERE = Path(__file__).resolve()
PACKAGE_TESTS = HERE.parent
SUPPORT = PACKAGE_TESTS / "_support"
LOCAL_MODULE = SUPPORT / "case04_verifier.py"
if LOCAL_MODULE.is_file():
    MODULE_PATH = LOCAL_MODULE
    if str(SUPPORT) not in sys.path:
        sys.path.insert(0, str(SUPPORT))
else:
    PACKAGE_TESTS = HERE.parent.parent / "packages/case-04-uncertainty-applicability-domain/tests"
    MODULE_PATH = HERE.parent / "verify_case04.py"
if not MODULE_PATH.is_file():
    raise RuntimeError("could not locate bundled or repository Case 04 grader module")
SPEC = importlib.util.spec_from_file_location("case04_independent_verifier", MODULE_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"could not load independent verifier at {MODULE_PATH}")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def verify(final_dir=None, runtime_root=None, gold_path=None, legacy_audit=False):
    kwargs = {"legacy_audit": legacy_audit}
    if runtime_root is not None:
        kwargs["runtime_root"] = Path(runtime_root)
    if gold_path is not None:
        kwargs["gold_path"] = Path(gold_path)
    return MODULE.verify(Path(final_dir) if final_dir is not None else None, **kwargs)


if __name__ == "__main__":
    import runpy
    runpy.run_path(str(SUPPORT / "case04_bench_verify.py"), run_name="__main__")
