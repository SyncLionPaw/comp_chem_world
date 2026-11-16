#!/bin/bash
set -euo pipefail
oracle_dir=$(mktemp -d)
cleanup() { rm -rf -- "$oracle_dir"; }
trap cleanup EXIT
trap 'exit 129' HUP
trap 'exit 130' INT
trap 'exit 143' TERM
cat > "$oracle_dir/capture_native_events.py" <<'CCW_141_capture_native_events_py_cbef400db7b2_END'
"""Attach native per-call payload capture to the case-owned Sella runner."""
import json
from pathlib import Path
import numpy as np

def attach(module):
    original_class=module.Instrumentation
    state={'current':None}
    class CapturingInstrumentation(original_class):
        def __init__(self):
            super().__init__();self.event_inputs={};state['current']=self
        def evaluation(self,atoms,*,hessian,stage,evaluator):
            positions=np.asarray(atoms.get_positions(),dtype='<f8').copy()
            numbers=np.asarray(atoms.get_atomic_numbers(),dtype='<i4').copy()
            result=super().evaluation(atoms,hessian=hessian,stage=stage,evaluator=evaluator)
            sequence=len(self.events)-1
            self.event_inputs[sequence]={'sequence':sequence,'atomic_numbers':numbers.tolist(),'positions_A':positions.tolist(),
              'energy_eV':float(result.energy_eV),'forces_eV_A':np.asarray(result.forces_eV_A,dtype=float).tolist(),
              'hessian_requested':bool(hessian),'hessian_eV_A2':None if result.hessian_eV_A2 is None else np.asarray(result.hessian_eV_A2,dtype=float).tolist()}
            return result
    module.Instrumentation=CapturingInstrumentation
    original_trial=module.run_trial
    def capture_trial(rid,repeat,arm,initial,evaluator,protocol,output):
        original_calc=evaluator.force_calc.calculate;ef_inputs={}
        def capture_calc(atoms_arg=None,properties=('energy',),system_changes=None):
            result=original_calc(atoms_arg,properties,system_changes)
            inst=state['current'];sequence=len(inst.events)
            values=evaluator.force_calc.results
            positions=np.asarray(atoms_arg.get_positions(),dtype='<f8').copy();numbers=np.asarray(atoms_arg.get_atomic_numbers(),dtype='<i4').copy()
            ef_inputs[sequence]={'sequence':sequence,'atomic_numbers':numbers.tolist(),'positions_A':positions.tolist(),
              'energy_eV':float(values['energy']),'forces_eV_A':np.asarray(values['forces'],dtype=float).tolist(),'hessian_requested':False}
            return result
        evaluator.force_calc.calculate=capture_calc
        try: record=original_trial(rid,repeat,arm,initial,evaluator,protocol,output)
        finally: evaluator.force_calc.calculate=original_calc
        inst=state['current'];captured={**ef_inputs,**inst.event_inputs}
        expected={int(event['sequence']) for event in record.get('event_stream',[])}
        if set(captured)!=expected:raise RuntimeError(f'captured call payloads differ from event stream: {sorted(set(captured)^expected)}')
        with (output/'event_evaluations.jsonl').open('w',encoding='utf-8') as stream:
            for sequence in sorted(captured):stream.write(json.dumps(captured[sequence],separators=(',',':'),allow_nan=False)+'\n')
        return record
    module.run_trial=capture_trial
    return module
CCW_141_capture_native_events_py_cbef400db7b2_END
test "$(sha256sum "$oracle_dir/capture_native_events.py" | cut -d ' ' -f 1)" = "cbef400db7b2bbf412d33e3c7e086bc7537f5bb7f19b32897b8fbb87b3132eb4"

cat > "$oracle_dir/case04_controlled_runner.py" <<'CCW_141_case04_controlled_runner_py_331507873e73_END'
#!/usr/bin/env python3
"""Run protected, instrumented case-04 full-Hessian/QN trials.

This runner accepts data-only JSON protocols. It never imports or executes a
submitter supplied program. Run it inside the pinned NewtonNet image with the
runner, checkpoint, model spec, and initial-guess file mounted read-only.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import platform
import shutil
import stat
import sys
import time
from pathlib import Path
from typing import Any

SCHEMA = "case04-controlled-run/v1"
PROTOCOL_SCHEMA = "case04-controlled-protocol/v1"
EXPECTED_INITIAL_GUESSES_SHA256 = "9343f7b420fa9f99c1b394be1b71658eb1374d470efdc7521785bb966f6c854a"
EXPECTED_CHECKPOINT_SHA256 = "a8efa83fa760076377d1be644309eaf22935f620b2c8d46cd837989dc49728d3"
EXPECTED_MODEL_SPEC_SHA256 = "eef241bd191da59fae309fd995f61a567f89d403c1d784c9280e72b38c862ddf"
NEGATIVE_MODE_THRESHOLD_EV_A2 = -1.0 / 23.06055


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def canonical_json(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def read_only_mount(path: Path) -> bool:
    """Check the actual mount flags covering a protected input path."""
    target = path.resolve()
    best = None
    try:
        lines = Path("/proc/self/mountinfo").read_text().splitlines()
    except OSError:
        return False
    for line in lines:
        left, _, right = line.partition(" - ")
        fields = left.split()
        if len(fields) < 6:
            continue
        mountpoint = Path(fields[4].replace("\\040", " "))
        try:
            target.relative_to(mountpoint)
        except ValueError:
            continue
        if best is None or len(str(mountpoint)) > len(str(best[0])):
            best = (mountpoint, fields[5].split(","))
    return bool(best and "ro" in best[1])


def validate_protocol(raw: bytes, mode: str) -> dict[str, Any]:
    try:
        p = json.loads(raw)
    except Exception as exc:
        raise ValueError(f"protocol is not valid JSON: {exc}") from exc
    if not isinstance(p, dict) or p.get("schema") != PROTOCOL_SCHEMA:
        raise ValueError(f"protocol schema must be {PROTOCOL_SCHEMA}")
    allowed = {"schema", "reaction_ids", "repeats", "optimizer", "scientific_criteria", "arms"}
    if set(p) != allowed:
        raise ValueError(f"protocol keys must be exactly {sorted(allowed)}")
    ids = p["reaction_ids"]
    if not isinstance(ids, list) or not ids or any(not isinstance(x, str) or len(x) != 3 or not x.isdigit() for x in ids):
        raise ValueError("reaction_ids must be nonempty three-digit IDs from the selected geometry set")
    if len(set(ids)) != len(ids):
        raise ValueError("reaction_ids must be unique")
    if type(p["repeats"]) is not int or p["repeats"] < 2:
        raise ValueError("repeats must be an integer of at least 2")
    if mode == "calibration" and len(ids) > 2:
        raise ValueError("calibration mode is limited to one or two IDs")
    opt = p["optimizer"]
    if not isinstance(opt, dict) or set(opt) != {"order", "internal", "fmax_eV_A", "delta0_A", "max_steps", "restart", "refine_initial_hessian"}:
        raise ValueError("optimizer must declare only the supported Sella settings")
    if opt != {"order": 1, "internal": False, "fmax_eV_A": 0.04, "delta0_A": 0.12,
               "max_steps": opt.get("max_steps"), "restart": False, "refine_initial_hessian": 0}:
        raise ValueError("Sella order/internal/fmax/delta0/restart/refinement settings are fixed for paired arms")
    if type(opt["max_steps"]) is not int:
        raise ValueError("max_steps must be an integer")
    if mode == "calibration" and not 2 <= opt["max_steps"] <= 30:
        raise ValueError("calibration max_steps must be 2..30")
    if mode == "full" and (opt["max_steps"] != 200 or len(ids) != 240 or p["repeats"] < 2):
        raise ValueError("full mode requires exactly 200 steps, all 240 IDs, and at least two repeats")
    criteria = p["scientific_criteria"]
    if criteria != {"maximum_force_eV_A": 0.04,
                    "negative_mode_threshold_eV_A2": NEGATIVE_MODE_THRESHOLD_EV_A2,
                    "required_projected_negative_modes": 1}:
        raise ValueError("scientific criteria are frozen at max force 0.04 eV/A and one mode below -1/23.06055 eV/A2")
    if criteria["maximum_force_eV_A"] != opt["fmax_eV_A"]:
        raise ValueError("optimizer fmax must match the frozen final-force threshold")
    arms = p["arms"]
    if not isinstance(arms, dict) or set(arms) != {"full_hessian", "quasi_newton"}:
        raise ValueError("protocol must define full_hessian and quasi_newton arms")
    if arms["full_hessian"] != {"hessian_strategy": "exact_callback", "diag_every_n": 0} or arms["quasi_newton"] != {"hessian_strategy": "sella_qn", "diag_every_n": None}:
        raise ValueError("only Sella exact hessian_function and native QN update strategies are permitted")
    return p


def load_assets(asset_root: Path):
    from ase.io import read
    guesses = read(str(asset_root / "initial_guesses.extxyz"), index=":")
    by_id = {}
    for atoms in guesses:
        rid = atoms.info.get("reaction_id")
        if rid is None:
            raise ValueError("initial guess lacks reaction_id metadata")
        key = f"{int(rid):03d}"
        if key in by_id:
            raise ValueError(f"duplicate reaction_id {key}")
        by_id[key] = atoms
    if len(by_id) != 240 or sha256(asset_root / "initial_guesses.extxyz") != EXPECTED_INITIAL_GUESSES_SHA256:
        raise ValueError("initial guesses do not match the hash-bound canonical selected 240 geometries")
    return by_id


class Instrumentation:
    def __init__(self):
        self.events: list[dict[str, Any]] = []
        self.qn_updates = 0
        self.qn_diagonalizations = 0
        self.started_ns = time.monotonic_ns()

    def evaluation(self, atoms, *, hessian: bool, stage: str, evaluator):
        import numpy as np
        begin = time.monotonic_ns()
        numbers = np.asarray(atoms.get_atomic_numbers(), dtype="<i4")
        positions = np.asarray(atoms.get_positions(), dtype="<f8")
        input_hashes = {"atomic_numbers_sha256": hashlib.sha256(numbers.tobytes()).hexdigest(),
                        "positions_sha256": hashlib.sha256(positions.tobytes()).hexdigest()}
        try:
            result = evaluator(atoms, hessian=hessian)
        except Exception as exc:
            end = time.monotonic_ns()
            self.events.append({
                "sequence": len(self.events), "kind": "model_evaluation", "stage": stage,
                "monotonic_start_ns": begin, "monotonic_end_ns": end,
                "call_status": "failed", "failure": f"{type(exc).__name__}: {exc}",
                "energy_evaluations": 1, "force_evaluations": 1,
                "hessian_evaluations": 1 if hessian else 0,
                "hessian_source": "newtonnet_autograd" if hessian else None,
                "atoms": len(atoms), "input_hashes": input_hashes,
                "output_hashes": {"energy_sha256": None, "forces_sha256": None, "hessian_sha256": None},
            })
            raise
        end = time.monotonic_ns()
        output_hashes = {
            "energy_sha256": hashlib.sha256(np.asarray([result.energy_eV], dtype="<f8").tobytes()).hexdigest(),
            "forces_sha256": hashlib.sha256(np.asarray(result.forces_eV_A, dtype="<f8").tobytes()).hexdigest(),
            "hessian_sha256": hashlib.sha256(np.asarray(result.hessian_eV_A2, dtype="<f8").tobytes()).hexdigest() if hessian else None,
        }
        self.events.append({
            "sequence": len(self.events), "kind": "model_evaluation", "stage": stage,
            "monotonic_start_ns": begin, "monotonic_end_ns": end,
            "energy_evaluations": 1, "force_evaluations": 1,
            "hessian_evaluations": 1 if hessian else 0,
            "hessian_source": "newtonnet_autograd" if hessian else None,
            "atoms": len(atoms),
            "call_status": "completed", "input_hashes": input_hashes,
            "output_hashes": output_hashes,
        })
        return result


def _run_trial_impl(rid: str, repeat: int, arm: str, initial, evaluator, protocol, output: Path, inst):
    import numpy as np
    from ase.io import Trajectory
    from sella import Sella
    from newtonnet_evaluator import projected_internal_spectrum

    atoms = initial.copy()
    atoms.calc = evaluator.force_calc
    # Count actual Energy/Force requests through the same evaluator path used
    # for Sella. ASE cache semantics apply: repeated reads of the same state do
    # not count as a new model call.
    original_calculate = evaluator.force_calc.calculate

    def counted_calculate(atoms_arg=None, properties=("energy",), system_changes=None):
        import numpy as np
        begin = time.monotonic_ns()
        positions = np.asarray(atoms_arg.get_positions(), dtype="<f8")
        numbers = np.asarray(atoms_arg.get_atomic_numbers(), dtype="<i4")
        input_hashes = {"atomic_numbers_sha256": hashlib.sha256(numbers.tobytes()).hexdigest(),
                        "positions_sha256": hashlib.sha256(positions.tobytes()).hexdigest()}
        try:
            result = original_calculate(atoms_arg, properties, system_changes)
        except Exception as exc:
            end = time.monotonic_ns()
            inst.events.append({
                "sequence": len(inst.events), "kind": "model_evaluation", "stage": "optimization",
                "monotonic_start_ns": begin, "monotonic_end_ns": end,
                "call_status": "failed", "failure": f"{type(exc).__name__}: {exc}",
                "energy_evaluations": 1, "force_evaluations": 1, "hessian_evaluations": 0,
                "hessian_source": None, "atoms": len(atoms_arg), "input_hashes": input_hashes,
                "output_hashes": {"energy_sha256": None, "forces_sha256": None, "hessian_sha256": None},
            })
            raise
        end = time.monotonic_ns()
        result_values = evaluator.force_calc.results
        inst.events.append({
            "sequence": len(inst.events), "kind": "model_evaluation", "stage": "optimization",
            "monotonic_start_ns": begin, "monotonic_end_ns": end,
            # NewtonNet's ASE calculate computes both values on each cache miss,
            # even if ASE requested just one of them.
            "energy_evaluations": 1, "force_evaluations": 1,
            "hessian_evaluations": 0,
            "hessian_source": None,
            "atoms": len(atoms_arg) if atoms_arg is not None else len(atoms),
            "call_status": "completed", "input_hashes": input_hashes,
            "output_hashes": {"energy_sha256": hashlib.sha256(np.asarray([result_values["energy"]], dtype="<f8").tobytes()).hexdigest(),
                              "forces_sha256": hashlib.sha256(np.asarray(result_values["forces"], dtype="<f8").tobytes()).hexdigest(),
                              "hessian_sha256": None},
        })
        return result

    evaluator.force_calc.calculate = counted_calculate
    hcb = None
    if arm == "full_hessian":
        def hcb(a):
            return inst.evaluation(a, hessian=True, stage="optimization", evaluator=evaluator.evaluate).hessian_eV_A2
    traj_path = output / "native.traj"
    opt = Sella(atoms, order=1, internal=False, hessian_function=hcb,
                trajectory=str(traj_path), logfile=str(output / "sella.log"),
                delta0=protocol["optimizer"]["delta0_A"], restart=False,
                refine_initial_hessian=0,
                diag_every_n=protocol["arms"][arm]["diag_every_n"])
    # Capture Sella's own accepted quasi-Newton updates and finite-difference
    # diagonalizations while leaving the optimizer's implementation intact.
    original_update = opt.pes._update_H
    def count_update(*args, **kwargs):
        inst.qn_updates += 1
        return original_update(*args, **kwargs)
    opt.pes._update_H = count_update
    original_diag = opt.pes.diag
    def count_diag(*args, **kwargs):
        inst.qn_diagonalizations += 1
        return original_diag(*args, **kwargs)
    opt.pes.diag = count_diag

    t0 = time.monotonic_ns()
    try:
        converged = bool(opt.run(fmax=protocol["optimizer"]["fmax_eV_A"], steps=protocol["optimizer"]["max_steps"]))
        result_state = "converged" if converged else "max_steps_or_not_converged"
    except Exception as exc:
        converged = False
        result_state = "failed"
        failure = f"{type(exc).__name__}: {exc}"
    t1 = time.monotonic_ns()
    try:
        opt.close()
    finally:
        evaluator.force_calc.calculate = original_calculate
    # Independent fixed-checkpoint audit runs after optimization and is marked
    # separately in the stream; its counters are included in total calls.
    audit = inst.evaluation(atoms, hessian=True, stage="independent_final_audit", evaluator=evaluator.evaluate)
    max_force = float(np.max(np.linalg.norm(audit.forces_eV_A, axis=1)))
    spectrum = projected_internal_spectrum(audit.hessian_eV_A2, atoms.positions)
    neg = int(np.count_nonzero(spectrum["internal_eigenvalues_eV_A2"] < protocol["scientific_criteria"]["negative_mode_threshold_eV_A2"]))
    frames = Trajectory(str(traj_path), "r")
    frame_count = len(frames)
    frames.close()
    count_keys = ("energy_evaluations", "force_evaluations", "hessian_evaluations")
    by_stage = {stage: {k: sum(e[k] for e in inst.events if e["stage"] == stage) for k in count_keys}
                for stage in ("optimization", "independent_final_audit")}
    totals = {k: sum(v[k] for v in by_stage.values()) for k in count_keys}
    force_pass = max_force <= protocol["optimizer"]["fmax_eV_A"]
    mode_pass = neg == 1
    scientific_success = bool(converged and force_pass and mode_pass)
    record = {
        "reaction_id": rid, "repeat": repeat, "arm": arm,
        "optimizer": "Sella 2.5.0", "strategy": "hessian_function exact callback" if arm == "full_hessian" else "Sella native quasi-Newton updates",
        "status": "scientific_success" if scientific_success else result_state,
        "optimizer_converged": converged, "scientific_success": scientific_success,
        "native_trajectory_frames": frame_count,
        "native_trajectory_semantics": "Sella PES.save coordinate snapshots written during optimizer steps; frame count is not an independent acceptance/rejection count",
        "optimizer_steps": int(opt.nsteps),
        "max_steps": protocol["optimizer"]["max_steps"], "optimizer_walltime_ns": t1 - t0,
        "trial_walltime_ns": time.monotonic_ns() - inst.started_ns,
        "counts": {"optimization": by_stage["optimization"],
                   "independent_final_audit": by_stage["independent_final_audit"],
                   "total": totals, "model_evaluate_calls": len(inst.events),
                   "sella_hessian_update_events": inst.qn_updates,
                   "quasi_newton_updates": inst.qn_updates if arm == "quasi_newton" else 0,
                   "quasi_newton_finite_difference_diagonalizations": inst.qn_diagonalizations,
                   "unreconstructed_hessian_updates_are_not_inferred_free": True},
        "final_audit": {"energy_eV": audit.energy_eV, "max_force_eV_A": max_force,
                        "negative_mode_threshold_eV_A2": protocol["scientific_criteria"]["negative_mode_threshold_eV_A2"],
                        "projected_internal_negative_modes": neg,
                        "one_negative_mode": mode_pass,
                        "force_within_threshold": force_pass},
        "event_stream": inst.events,
        "native_trajectory": {"path": str(traj_path.name), "sha256": sha256(traj_path), "frames": frame_count},
    }
    if not converged:
        record["failure"] = locals().get("failure", "Sella or independent scientific endpoint checks did not pass")
    (output / "trial.json").write_text(json.dumps(record, indent=2, sort_keys=True) + "\n")
    return record


def run_trial(rid: str, repeat: int, arm: str, initial, evaluator, protocol, output: Path):
    """Run one arm and always restore the shared ASE calculator hook.

    Unexpected trial-level failures still emit a failure row, preserving the
    paired denominator; environment-wide asset/backend errors fail before this
    loop and do not produce a score.
    """
    original_calculate = evaluator.force_calc.calculate
    started = time.monotonic_ns()
    inst = Instrumentation()
    try:
        return _run_trial_impl(rid, repeat, arm, initial, evaluator, protocol, output, inst)
    except Exception as exc:
        keys = ("energy_evaluations", "force_evaluations", "hessian_evaluations")
        stages = {stage: {k: sum(e[k] for e in inst.events if e["stage"] == stage) for k in keys}
                  for stage in ("optimization", "independent_final_audit")}
        totals = {k: sum(v[k] for v in stages.values()) for k in keys}
        native = output / "native.traj"
        native_record = {"path": native.name, "sha256": sha256(native), "frames": None} if native.is_file() else None
        record = {
            "reaction_id": rid, "repeat": repeat, "arm": arm,
            "optimizer": "Sella 2.5.0", "status": "failed", "optimizer_converged": False,
            "scientific_success": False, "native_trajectory_frames": 0,
            "native_trajectory_semantics": "no native frame completed before trial exception",
            "optimizer_steps": inst.qn_updates, "max_steps": protocol["optimizer"]["max_steps"],
            "optimizer_walltime_ns": 0, "trial_walltime_ns": time.monotonic_ns() - started,
            "counts": {"optimization": stages["optimization"],
                       "independent_final_audit": stages["independent_final_audit"],
                       "total": totals, "model_evaluate_calls": len(inst.events),
                       "sella_hessian_update_events": inst.qn_updates,
                       "quasi_newton_updates": inst.qn_updates if arm == "quasi_newton" else 0,
                       "quasi_newton_finite_difference_diagonalizations": inst.qn_diagonalizations,
                       "unreconstructed_hessian_updates_are_not_inferred_free": True},
            "final_audit": None, "event_stream": inst.events, "native_trajectory": native_record,
            "failure": f"{type(exc).__name__}: {exc}",
        }
        (output / "trial.json").write_text(json.dumps(record, indent=2, sort_keys=True) + "\n")
        return record
    finally:
        evaluator.force_calc.calculate = original_calculate


CCW_141_case04_controlled_runner_py_331507873e73_END
test "$(sha256sum "$oracle_dir/case04_controlled_runner.py" | cut -d ' ' -f 1)" = "331507873e739472f25410d963117ffc5b7fe229f4521c0100e16fc450ab098d"

cat > "$oracle_dir/run_case04.py" <<'CCW_141_run_case04_py_3c147ec16e83_END'
#!/usr/bin/env python3
"""Protected, bounded v2 case-04 comparison for two predeclared small systems.

This runner only accepts a fixed data protocol. It reuses the immutable v1
trial instrumentation and writes its own v2 envelope and audit. It never runs a
submitter program, and its native trajectory frame count is not an accepted-step
count. A failed or unconverged trial stays in the four-trial denominator.
"""
from __future__ import annotations
import argparse
import hashlib
import importlib.util
import json
import math
import os
import platform
import sys
import time
from pathlib import Path

SCHEMA = "case04-compact-run/v2"
PROTOCOL_SCHEMA = "case04-compact-protocol/v2"
IMAGE_ID = "case-container"
EXPECTED_IDS = ["001", "079"]
EXPECTED_ATOMS = {"001": 10, "079": 11}
EXPECTED_GEOMETRY_SHA256 = "a7e8abaa64bae363e5859244d78a1c0372e28ef6e382b1c1e0dc9fcfbf5a8590"
EXPECTED_CHECKPOINT_SHA256 = "a8efa83fa760076377d1be644309eaf22935f620b2c8d46cd837989dc49728d3"
EXPECTED_MODEL_SPEC_SHA256 = "eef241bd191da59fae309fd995f61a567f89d403c1d784c9280e72b38c862ddf"
EXPECTED_V1_RUNNER_SHA256 = "e2c4dcf4e5cc64c259a3374cfeb4370fea4f9cbddae5380d56cc4a569a38b6af"
EXPECTED_EVALUATOR_SHA256 = "b40ba9954b54b4a1bba88f20c976da63fda1f5c7683656f42019d804e100f57f"
OUTPUT_ROOT = Path("/app/final/runner_output")
NEGATIVE_MODE_THRESHOLD = -1.0 / 23.06055
V1 = None


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def hash_tree(root: Path) -> dict[str, str]:
    return {str(p.relative_to(root)): sha256(p) for p in sorted(root.rglob("*"))
            if p.is_file() and p.name not in {"envelope.json", "audit.json"}}


def readonly(path: Path) -> bool:
    # Use the v1 instrumentation's actual mount check after loading that module.
    return V1.read_only_mount(path)


def load_v1(path: Path):
    spec = importlib.util.spec_from_file_location("case04_controlled_runner_v1", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load the pinned v1 runner")
    module = importlib.util.module_from_spec(spec)
    import sys
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    from capture_native_events import attach
    return attach(module)


def protocol_for_trial(raw: bytes) -> dict:
    p = json.loads(raw)
    required = {"schema", "reaction_ids", "repeats", "optimizer", "scientific_criteria", "arms"}
    if not isinstance(p, dict) or set(p) != required or p.get("schema") != PROTOCOL_SCHEMA:
        raise ValueError("protocol schema/keys mismatch")
    if p["reaction_ids"] != EXPECTED_IDS or p["repeats"] != 1:
        raise ValueError("v2 is fixed to IDs 001/079, one repeat per ID")
    if p["optimizer"] != {"order": 1, "internal": False, "fmax_eV_A": 0.04, "delta0_A": 0.12,
                          "max_steps": 24, "restart": False, "refine_initial_hessian": 0}:
        raise ValueError("optimizer settings differ from frozen v2 protocol")
    if p["scientific_criteria"] != {"maximum_force_eV_A": 0.04,
            "negative_mode_threshold_eV_A2": NEGATIVE_MODE_THRESHOLD,
            "required_projected_negative_modes": 1}:
        raise ValueError("scientific criteria differ from frozen v2 protocol")
    if p["arms"] != {"full_hessian": {"hessian_strategy": "exact_callback", "diag_every_n": 0},
                      "quasi_newton": {"hessian_strategy": "sella_qn", "diag_every_n": None}}:
        raise ValueError("only paired exact-Hessian and native Sella QN arms are supported")
    return p


def load_geometries(path: Path):
    import numpy as np
    from ase.io import read
    frames = read(str(path), index=":")
    by_id = {}
    for atoms in frames:
        raw_id = atoms.info.get("reaction_id", "")
        rid = f"{int(raw_id):03d}" if isinstance(raw_id, (int, float)) and float(raw_id).is_integer() else str(raw_id).zfill(3)
        if rid in by_id:
            raise ValueError(f"duplicate reaction ID {rid}")
        by_id[rid] = atoms
    if list(by_id) != EXPECTED_IDS or {k: len(v) for k, v in by_id.items()} != EXPECTED_ATOMS:
        raise ValueError("geometry asset IDs/counts do not match frozen v2 selection")
    return by_id


def validate_trial(d: dict, path: Path, rid: str, arm: str) -> list[str]:
    errors = []
    if d.get("reaction_id") != rid or d.get("repeat") != 1 or d.get("arm") != arm:
        errors.append(f"identity mismatch in {path.name}")
    events = d.get("event_stream", [])
    counts = d.get("counts", {})
    if len(events) != counts.get("model_evaluate_calls"):
        errors.append(f"event count mismatch in {path.name}")
    stage_counts = {}
    keys = ("energy_evaluations", "force_evaluations", "hessian_evaluations")
    for stage in ("optimization", "independent_final_audit"):
        stage_counts[stage] = {k: sum(e.get(k, 0) for e in events if e.get("stage") == stage) for k in keys}
    if counts.get("optimization") != stage_counts["optimization"] or counts.get("independent_final_audit") != stage_counts["independent_final_audit"]:
        errors.append(f"stage counter mismatch in {path.name}")
    if counts.get("total") != {k: sum(stage_counts[s][k] for s in stage_counts) for k in keys}:
        errors.append(f"total counter mismatch in {path.name}")
    if not d.get("failure") and d.get("native_trajectory_frames", 0) < 1:
        errors.append(f"missing native frames in {path.name}")
    traj = path.parent / "native.traj"
    ntraj = d.get("native_trajectory")
    if ntraj and (not traj.is_file() or sha256(traj) != ntraj.get("sha256")):
        errors.append(f"native trajectory hash mismatch in {path.name}")
    if not d.get("failure"):
        if stage_counts["independent_final_audit"]["hessian_evaluations"] != 1:
            errors.append(f"independent final H audit absent in {path.name}")
        if arm == "quasi_newton" and stage_counts["optimization"]["hessian_evaluations"] != 0:
            errors.append(f"unexpected optimization H in QN arm {path.name}")
        if arm == "full_hessian" and stage_counts["optimization"]["hessian_evaluations"] != d.get("optimizer_steps"):
            errors.append(f"exact H event/step mismatch in {path.name}")
        if d.get("optimizer_steps", 0) > 24:
            errors.append(f"optimizer step cap exceeded in {path.name}")
        if traj.is_file() and arm == "full_hessian":
            try:
                import numpy as np
                from ase.io import read
                frame_hashes = {hashlib.sha256(np.asarray(frame.get_positions(), dtype="<f8").tobytes()).hexdigest()
                                for frame in read(str(traj), index=":")}
                callback_hashes = [e.get("input_hashes", {}).get("positions_sha256") for e in events
                                   if e.get("stage") == "optimization" and e.get("hessian_evaluations", 0) == 1]
                if any(h not in frame_hashes for h in callback_hashes):
                    errors.append(f"Hessian callback coordinates are absent from native trajectory in {path.name}")
            except Exception as exc:
                errors.append(f"native trajectory replay failed in {path.name}: {type(exc).__name__}: {exc}")
    for e in events:
        if not e.get("input_hashes", {}).get("positions_sha256") or e.get("monotonic_end_ns", 0) <= e.get("monotonic_start_ns", 0):
            errors.append(f"invalid event provenance/timing in {path.name}")
        if e.get("call_status") == "completed" and (not e.get("output_hashes", {}).get("energy_sha256") or not e.get("output_hashes", {}).get("forces_sha256")):
            errors.append(f"completed event lacks E/F hashes in {path.name}")
    audit = d.get("final_audit") or {}
    success = bool(d.get("optimizer_converged") and audit.get("force_within_threshold") and audit.get("one_negative_mode"))
    if d.get("scientific_success") != success:
        errors.append(f"scientific success flag mismatch in {path.name}")
    return errors


def audit(out: Path, protocol: Path, geometries: Path, checkpoint: Path, model: Path, v1_runner: Path, evaluator: Path, image_id: str):
    errors = []
    try:
        p = protocol_for_trial(protocol.read_bytes())
        env = json.loads((out / "envelope.json").read_text())
    except Exception as exc:
        return [f"protocol/envelope unreadable: {type(exc).__name__}: {exc}"]
    if env.get("trusted_output_root") != str(OUTPUT_ROOT):
        errors.append("trusted output root mismatch")
    if env.get("schema") != SCHEMA or env.get("protocol_sha256") != sha256(protocol):
        errors.append("schema/protocol hash mismatch")
    if not (readonly(protocol) and readonly(geometries) and readonly(checkpoint) and readonly(model) and readonly(v1_runner) and readonly(evaluator) and readonly(Path(__file__).resolve())):
        errors.append("a protected input is not mounted read-only")
    expected = {"geometry": EXPECTED_GEOMETRY_SHA256, "checkpoint": EXPECTED_CHECKPOINT_SHA256,
                "model_spec": EXPECTED_MODEL_SPEC_SHA256, "v1_runner": EXPECTED_V1_RUNNER_SHA256,
                "evaluator": EXPECTED_EVALUATOR_SHA256}
    actual = {"geometry": sha256(geometries), "checkpoint": sha256(checkpoint), "model_spec": sha256(model),
              "v1_runner": sha256(v1_runner), "evaluator": sha256(evaluator),
              "compact_runner": sha256(Path(__file__).resolve())}
    if any(actual.get(k) != v for k, v in expected.items()) or env.get("input_hashes") != actual:
        errors.append("protected source hashes do not match the frozen inventory")
    if env.get("selected_reaction_ids") != EXPECTED_IDS or env.get("expected_trials") != 4 or env.get("observed_trials") != 4:
        errors.append("fixed four-trial denominator is incomplete")
    snap = out / "protocol.snapshot.json"
    if not snap.is_file() or sha256(snap) != sha256(protocol):
        errors.append("protocol snapshot mismatch")
    if env.get("deliverable_hashes") != hash_tree(out):
        errors.append("deliverable hash tree mismatch")
    expected_trials = {(rid, arm) for rid in EXPECTED_IDS for arm in ("full_hessian", "quasi_newton")}
    observed = set()
    observed_total = {"energy_evaluations": 0, "force_evaluations": 0, "hessian_evaluations": 0}
    for record in env.get("trials", []):
        rid, arm = record.get("reaction_id"), record.get("arm")
        observed.add((rid, arm))
        tp = out / record.get("directory", "") / "trial.json"
        try:
            data = json.loads(tp.read_text())
            errors.extend(validate_trial(data, tp, rid, arm))
            for key in observed_total:
                observed_total[key] += data.get("counts", {}).get("total", {}).get(key, 0)
            if not data.get("event_stream"):
                errors.append(f"trial has no model events: {record.get('directory')}")
            else:
                first = next((e for e in data["event_stream"] if e.get("stage") == "optimization"), None)
                try:
                    import numpy as np
                    from ase.io import read
                    initial = next(x for x in read(str(geometries), index=":")
                                   if f"{int(x.info['reaction_id']):03d}" == rid)
                    expected_positions = hashlib.sha256(np.asarray(initial.get_positions(), dtype="<f8").tobytes()).hexdigest()
                    if first is None or first.get("input_hashes", {}).get("positions_sha256") != expected_positions:
                        errors.append(f"first optimization event does not start at selected input geometry: {record.get('directory')}")
                except Exception as exc:
                    errors.append(f"could not join initial geometry to first event: {type(exc).__name__}: {exc}")
        except Exception as exc:
            errors.append(f"trial unreadable {record.get('directory')}: {type(exc).__name__}: {exc}")
    if observed != expected_trials or len(env.get("trials", [])) != 4:
        errors.append("trial identity/coverage mismatch")
    if observed_total["hessian_evaluations"] > 120 or observed_total["energy_evaluations"] > 500 or observed_total["force_evaluations"] > 500:
        errors.append("observed evaluations exceed frozen v2 budget")
    return errors


def main() -> int:
    ap = argparse.ArgumentParser()
    for name in ("protocol", "geometries", "checkpoint", "model_spec", "v1_runner", "evaluator", "output"):
        ap.add_argument("--" + name.replace("_", "-"), type=Path, required=True)
    ap.add_argument("--image-id", required=True)
    ap.add_argument("--audit", action="store_true")
    a = ap.parse_args()
    run_begin_ns = time.monotonic_ns()
    global V1
    V1 = load_v1(a.v1_runner.resolve())
    out = a.output.resolve()
    if a.audit:
        errors = audit(out, a.protocol.resolve(), a.geometries.resolve(), a.checkpoint.resolve(), a.model_spec.resolve(), a.v1_runner.resolve(), a.evaluator.resolve(), a.image_id)
        print(json.dumps({"audit": "PASS" if not errors else "REJECT", "errors": errors}, indent=2))
        return 0 if not errors else 2
    if out.exists() and any(out.iterdir()):
        raise SystemExit("output directory must be empty")
    hashes = {"geometry": sha256(a.geometries), "checkpoint": sha256(a.checkpoint), "model_spec": sha256(a.model_spec),
              "v1_runner": sha256(a.v1_runner), "evaluator": sha256(a.evaluator),
              "compact_runner": sha256(Path(__file__).resolve())}
    expected = {"geometry": EXPECTED_GEOMETRY_SHA256, "checkpoint": EXPECTED_CHECKPOINT_SHA256,
                "model_spec": EXPECTED_MODEL_SPEC_SHA256, "v1_runner": EXPECTED_V1_RUNNER_SHA256,
                "evaluator": EXPECTED_EVALUATOR_SHA256}
    if hashes["geometry"] != EXPECTED_GEOMETRY_SHA256 or hashes["checkpoint"] != EXPECTED_CHECKPOINT_SHA256 or hashes["model_spec"] != EXPECTED_MODEL_SPEC_SHA256:
        raise SystemExit("public asset SHA-256 mismatch")
    raw = a.protocol.read_bytes(); protocol_hash = hashlib.sha256(raw).hexdigest()
    p = protocol_for_trial(raw)
    geometries = load_geometries(a.geometries)
    out.mkdir(parents=True, exist_ok=True)
    (out / "protocol.snapshot.json").write_bytes(raw)
    from newtonnet_evaluator import NewtonNetEvaluator
    model_load_begin_ns = time.monotonic_ns()
    evaluator = NewtonNetEvaluator(a.checkpoint, a.model_spec)
    model_load_seconds = (time.monotonic_ns() - model_load_begin_ns) / 1e9
    trials = []
    trial_loop_begin_ns = time.monotonic_ns()
    for i, rid in enumerate(p["reaction_ids"]):
        arms = ["full_hessian", "quasi_newton"] if i % 2 == 0 else ["quasi_newton", "full_hessian"]
        for arm in arms:
            name = f"rxn-{rid}-rep-01-{arm}"
            td = out / name; td.mkdir()
            trials.append(V1.run_trial(rid, 1, arm, geometries[rid], evaluator, p, td))
    trial_loop_wall_seconds = (time.monotonic_ns() - trial_loop_begin_ns) / 1e9
    env = {"schema": SCHEMA, "protocol_sha256": protocol_hash, "protocol_bytes": len(raw),
           "selected_reaction_ids": p["reaction_ids"], "repeats": 1, "max_steps_per_trial": 24,
           "expected_trials": 4, "observed_trials": len(trials), "image_id": a.image_id,
           "python": platform.python_version(), "platform": platform.platform(), "trusted_output_root": str(out),
           "model_load_seconds": model_load_seconds,
           "summed_per_trial_wall_seconds": sum(x["trial_walltime_ns"] for x in trials) / 1e9,
           "trial_loop_wall_seconds_including_reporting": trial_loop_wall_seconds,
           "runner_elapsed_seconds_excluding_container_start": (time.monotonic_ns() - run_begin_ns) / 1e9,
           "wall_cap_enforcement": "External command supervisor owns the timeout; per-trial timers exclude model initialization and container startup.",
           "read_only_inputs": all(readonly(q.resolve()) for q in (a.protocol, a.geometries, a.checkpoint, a.model_spec, a.v1_runner, a.evaluator, Path(__file__).resolve())), "input_hashes": hashes,
           "trial_order": [{"reaction_id": x["reaction_id"], "arm": x["arm"], "status": x["status"],
                            "optimizer_converged": x["optimizer_converged"], "scientific_success": x["scientific_success"],
                            "optimizer_steps": x["optimizer_steps"], "native_trajectory_frames": x["native_trajectory_frames"]} for x in trials],
           "trials": [{"directory": f"rxn-{x['reaction_id']}-rep-01-{x['arm']}", "reaction_id": x["reaction_id"],
                       "repeat": 1, "arm": x["arm"], "status": x["status"], "scientific_success": x["scientific_success"]} for x in trials],
           "counter_semantics": "Only instrumented model evaluate/calculator events count as E/F/H. An H event also counts its E/F output. Native trajectory frames are coordinate snapshots, not accepted-step counts. Every started trial, including nonconverged/failed trials, remains in the four-trial denominator.",
           "coverage": {"trial_coverage": "complete" if len(trials) == 4 else "incomplete", "science_scope": "predeclared_two_id_bounded_protocol"}}
    env["deliverable_hashes"] = hash_tree(out)
    (out / "envelope.json").write_text(json.dumps(env, indent=2, sort_keys=True) + "\n")
    errors = []
    (out / "audit.json").write_text(json.dumps({"audit": "CANDIDATE_GENERATION_COMPLETE", "errors": []}, indent=2) + "\n")
    print(json.dumps({"schema": SCHEMA, "audit": "PASS" if not errors else "REJECT", "trials": len(trials),
                      "optimizer_convergences": sum(bool(x["optimizer_converged"]) for x in trials),
                      "scientific_successes": sum(bool(x["scientific_success"]) for x in trials),
                      "errors": errors}, indent=2))
    return 0 if not errors else 2


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SystemExit:
        raise
    except Exception as exc:
        print(json.dumps({"status": "ENVIRONMENT_ERROR", "reward": None,
                          "reason": f"runner setup failure: {type(exc).__name__}: {exc}"}, ensure_ascii=False))
        raise SystemExit(2)
CCW_141_run_case04_py_3c147ec16e83_END
test "$(sha256sum "$oracle_dir/run_case04.py" | cut -d ' ' -f 1)" = "3c147ec16e83c28653a9cea2cd31d6d66fc6371cdd0c6ee3b2e214df47336c07"

cat > "$oracle_dir/summarize.py" <<'CCW_141_summarize_py_36ef64b84769_END'
import csv,json
from pathlib import Path
import numpy as np
from ase.io import read
root=Path('/app/final'); rr=root/'runner_output'; env=json.loads((rr/'envelope.json').read_text()); ids=['001','079']; arms=['full_hessian','quasi_newton']
records={}
with (root/'per_trial.csv').open('w',newline='') as f:
 w=csv.DictWriter(f,fieldnames=['reaction_id','arm','status','optimizer_steps','energy_calls','force_calls','hessian_calls','walltime_s']);w.writeheader()
 for tr in env['trials']:
  d=json.loads((rr/tr['directory']/'trial.json').read_text()); records[(d['reaction_id'],d['arm'])]=d;c=d['counts']['total']
  w.writerow({'reaction_id':d['reaction_id'],'arm':d['arm'],'status':d['status'],'optimizer_steps':d['optimizer_steps'],'energy_calls':c['energy_evaluations'],'force_calls':c['force_evaluations'],'hessian_calls':c['hessian_evaluations'],'walltime_s':d['trial_walltime_ns']/1e9})
def kabsch(a,b):
 ac=a.mean(0);bc=b.mean(0);u,s,v=np.linalg.svd((a-ac).T@(b-bc));d=np.linalg.det(u@v);r=u@np.diag([1,1,d])@v;return float(np.sqrt(np.mean(np.sum(((a-ac)@r+bc-b)**2,axis=1))))
with (root/'endpoint_comparison.csv').open('w',newline='') as f:
 endpoint_rows=[]
 w=csv.DictWriter(f,fieldnames=['reaction_id','delta_energy_eV','proper_kabsch_rmsd_A','identity_status']);w.writeheader()
 for rid in ids:
  a=read(str(rr/f'rxn-{rid}-rep-01-full_hessian/native.traj'),index=-1);b=read(str(rr/f'rxn-{rid}-rep-01-quasi_newton/native.traj'),index=-1)
  ea=records[(rid,'full_hessian')]['final_audit']['energy_eV'];eb=records[(rid,'quasi_newton')]['final_audit']['energy_eV']
  row={'reaction_id':rid,'delta_energy_eV':ea-eb,'proper_kabsch_rmsd_A':kabsch(a.positions,b.positions),'identity_status':'unresolved'};endpoint_rows.append(row);w.writerow(row)
step_by={arm:sum(records[(rid,arm)]['optimizer_steps'] for rid in ids) for arm in arms}
keys=('energy_evaluations','force_evaluations','hessian_evaluations');calls_by={arm:{k:sum(records[(rid,arm)]['counts']['total'][k] for rid in ids) for k in keys} for arm in arms}
time_by={arm:sum(records[(rid,arm)]['trial_walltime_ns'] for rid in ids)/1e9 for arm in arms}
success=sum(bool(d['scientific_success']) for d in records.values())
fh_steps=step_by['full_hessian']; qn_steps=step_by['quasi_newton']
fh_calls=calls_by['full_hessian']; qn_calls=calls_by['quasi_newton']
fh_time=time_by['full_hessian']; qn_time=time_by['quasi_newton']
paired_text=' '.join(
 f"ID {r['reaction_id']}: full-Hessian status "
 f"{records[(r['reaction_id'],'full_hessian')]['status']} and quasi-Newton status "
 f"{records[(r['reaction_id'],'quasi_newton')]['status']}; full-Hessian used "
 f"{records[(r['reaction_id'],'full_hessian')]['optimizer_steps']} versus "
 f"{records[(r['reaction_id'],'quasi_newton')]['optimizer_steps']} quasi-Newton steps, "
 f"with full-Hessian-minus-quasi-Newton endpoint ΔE {r['delta_energy_eV']:.6f} eV "
 f"and proper Kabsch RMSD {r['proper_kabsch_rmsd_A']:.4f} Å."
 for r in endpoint_rows)
assessment=(f"Within these two paired IDs, {success} of {len(records)} trials succeeded. Full-Hessian used "
 f"{fh_steps} total optimizer steps versus {qn_steps} for quasi-Newton and "
 f"{fh_calls['energy_evaluations']} versus {qn_calls['energy_evaluations']} energy/force "
 f"evaluations, but used {fh_calls['hessian_evaluations']} versus "
 f"{qn_calls['hessian_evaluations']} Hessian evaluations and measured "
 f"{fh_time:.3f} versus {qn_time:.3f} summed trial wall seconds. These observed "
 f"small-sample counts and timings show a tradeoff; they do not establish overall "
 f"method superiority or general runtime. {paired_text} The endpoint energies and "
 f"aligned RMSDs are descriptive only: no predeclared identity cutoff determines "
 f"whether either endpoint pair is the same saddle.")
(root/'analysis.json').write_text(json.dumps({'scope_ids':ids,'denominator':4,'scientific_successes':success,'optimizer_steps_by_arm':step_by,'model_calls_by_arm':calls_by,'trial_walltime_s_by_arm':time_by,'semantic_review':{'paired_comparison':[{'reaction_id':r['reaction_id'],'full_hessian_success':records[(r['reaction_id'],'full_hessian')]['status']=='scientific_success','quasi_newton_success':records[(r['reaction_id'],'quasi_newton')]['status']=='scientific_success','delta_energy_eV':float(r['delta_energy_eV']),'proper_kabsch_rmsd_A':float(r['proper_kabsch_rmsd_A'])} for r in endpoint_rows],'within_sample_assessment':assessment,'identity_uncertainty':'No predeclared structural cutoff establishes whether paired endpoints represent the same saddle.','extrapolation_scope':'Evidence covers two IDs with one repeat per arm and does not establish population-level performance.','evidence_index':['per_trial.csv','endpoint_comparison.csv','runner_output/audit.json','runner_output/*/event_evaluations.jsonl']}},indent=2)+'\n')
(root/'report.md').write_text(f"# Paired bounded saddle-search results\n\nThe four predeclared trials completed with {success} scientifically successful outcomes. Across IDs 001 and 079, full-Hessian used {fh_steps} optimizer steps and {fh_calls['energy_evaluations']} energy/force evaluations, versus {qn_steps} steps and {qn_calls['energy_evaluations']} evaluations for quasi-Newton. Full-Hessian used {fh_calls['hessian_evaluations']} Hessian evaluations versus {qn_calls['hessian_evaluations']} and took {fh_time:.3f} summed trial wall seconds versus {qn_time:.3f}; these two-ID observations show a call-count/runtime tradeoff and do not establish general efficiency or superiority.\n\n{paired_text} ΔE is full-Hessian minus quasi-Newton final energy. Proper Kabsch RMSDs use fixed atom order. No predeclared threshold establishes whether either endpoint pair represents the same saddle, so endpoint identity remains unresolved. Each ID has one repeat per arm; sub-second individual timings are sensitive to local runtime conditions and are not population-level timing estimates. The retained event streams, native trajectories, and per-trial records support review of this bounded comparison.\n")
CCW_141_summarize_py_36ef64b84769_END
test "$(sha256sum "$oracle_dir/summarize.py" | cut -d ' ' -f 1)" = "36ef64b84769b84fb057003dacb84cefd397ef362bb99df0c85eed43636380c7"

chmod 0444 "$oracle_dir"/*.py
python "$oracle_dir/run_case04.py" --protocol /app/assets/protocol.json --geometries /app/assets/case04_initial_guesses_001_079.extxyz --checkpoint /app/assets/best_model_state.tar --model-spec /app/assets/newtonnet_model_spec.yml --v1-runner "$oracle_dir/case04_controlled_runner.py" --evaluator /opt/compchembench/newtonnet_evaluator.py --output /app/final/runner_output --image-id case-container
python "$oracle_dir/summarize.py"
cp /app/assets/protocol.json /app/final/protocol.json
