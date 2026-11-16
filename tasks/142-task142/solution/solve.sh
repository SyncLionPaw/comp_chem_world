#!/bin/bash
set -euo pipefail
oracle_dir=$(mktemp -d)
cleanup() { rm -rf -- "$oracle_dir"; }
trap cleanup EXIT
trap 'exit 129' HUP
trap 'exit 130' INT
trap 'exit 143' TERM
cat > "$oracle_dir/capture_native_events.py" <<'CCW_142_capture_native_events_py_cbef400db7b2_END'
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
CCW_142_capture_native_events_py_cbef400db7b2_END
test "$(sha256sum "$oracle_dir/capture_native_events.py" | cut -d ' ' -f 1)" = "cbef400db7b2bbf412d33e3c7e086bc7537f5bb7f19b32897b8fbb87b3132eb4"

cat > "$oracle_dir/case04_controlled_runner.py" <<'CCW_142_case04_controlled_runner_py_331507873e73_END'
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


CCW_142_case04_controlled_runner_py_331507873e73_END
test "$(sha256sum "$oracle_dir/case04_controlled_runner.py" | cut -d ' ' -f 1)" = "331507873e739472f25410d963117ffc5b7fe229f4521c0100e16fc450ab098d"

cat > "$oracle_dir/run_case05.py" <<'CCW_142_run_case05_py_d009badd6846_END'
#!/usr/bin/env python3
"""Protected, deterministic case-11 small-sample initial-geometry search.

The runner creates one baseline plus frozen low-dimensional perturbations from
source NN1 TS geometries, removes rigid translation/rotation components, and
uses immutable v1 Sella/event instrumentation for every trial. It never accepts
or executes candidate code. Failed and capped trials remain in the declared
trial denominator.
"""
from __future__ import annotations
import argparse
import hashlib
import importlib.util
import json
import math
import platform
import time
from pathlib import Path

SCHEMA = "case11-perturbation-run/v1"
PROTOCOL_SCHEMA = "case11-perturbation-protocol/v1"
IMAGE_ID = "case-container"
EXPECTED_IDS = ["001", "162"]
EXPECTED_ATOMS = {"001": 10, "162": 10}
EXPECTED_GEOMETRY_SHA256 = "31bde820e66b0f34a1838b1d1056d52cd4e856e146a875844324f2215f944ace"
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


def load_v1(path: Path):
    spec = importlib.util.spec_from_file_location("case04_controlled_runner_v1", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load the pinned v1 instrumentation")
    module = importlib.util.module_from_spec(spec)
    import sys
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    from capture_native_events import attach
    return attach(module)


def readonly(path: Path) -> bool:
    return V1.read_only_mount(path)


def make_trials(protocol: dict) -> list[dict]:
    result = []
    seeds = protocol["perturbation_generation"]["seeds"]
    amps = protocol["perturbation_generation"]["amplitudes_rms_A"]
    for rid in protocol["reaction_ids"]:
        result.append({"reaction_id": rid, "condition": "baseline", "amplitude_rms_A": 0.0, "seed": None})
        for amp in amps:
            for seed in seeds:
                result.append({"reaction_id": rid, "condition": "perturbed", "amplitude_rms_A": amp, "seed": seed})
    return result


def validate_protocol(raw: bytes) -> dict:
    p = json.loads(raw)
    if not isinstance(p, dict) or p.get("schema") != PROTOCOL_SCHEMA:
        raise ValueError("protocol schema mismatch")
    if p.get("scope") not in {"calibration", "formal"}:
        raise ValueError("protocol scope must be calibration or formal")
    expected_ids = ["001"] if p["scope"] == "calibration" else EXPECTED_IDS
    expected_seeds = [17] if p["scope"] == "calibration" else [17, 31]
    expected_steps = 4 if p["scope"] == "calibration" else 16
    expected_trials = 3 if p["scope"] == "calibration" else 10
    if p.get("reaction_ids") != expected_ids:
        raise ValueError("protocol reaction IDs differ from frozen calibration/formal scope")
    g = p.get("perturbation_generation", {})
    if g.get("baseline_per_id") is not True or g.get("amplitudes_rms_A") != [0.05, 0.12] or g.get("seeds") != expected_seeds:
        raise ValueError("noise levels/seeds differ from frozen protocol")
    if g.get("generator") != "numpy.random.Generator(PCG64(seed)).normal(size=(N,3))":
        raise ValueError("random generator definition differs")
    if g.get("projection") != "Cartesian Euclidean orthogonal projection off the six rigid translation/rotation tangent vectors; rotation vectors use positions centered at the arithmetic centroid; rank-deficient rigid bases use numerical SVD rank":
        raise ValueError("rigid-mode projection definition differs")
    if g.get("scaling") != "after projection, scale each displacement so sqrt(mean_i(sum_xyz(delta_i^2))) equals its declared RMS amplitude in Angstrom":
        raise ValueError("noise scaling definition differs")
    if g.get("geometry_precision") != "standard extxyz with binary64 round-trip .17g Cartesian coordinates; generated coordinates are SHA-256 bound before optimization":
        raise ValueError("starting-geometry serialization precision differs")
    opt = p.get("optimizer", {})
    if opt != {"name": "Sella", "version": "2.5.0", "order": 1, "internal": False,
               "fmax_eV_A": 0.04, "delta0_A": 0.12, "max_steps": expected_steps,
               "restart": False, "refine_initial_hessian": 0, "hessian_strategy": "exact_callback", "diag_every_n": 0}:
        raise ValueError("optimizer differs from frozen protocol")
    if p.get("scientific_criteria") != {"maximum_force_eV_A": 0.04,
            "negative_mode_threshold_eV_A2": NEGATIVE_MODE_THRESHOLD,
            "required_projected_negative_modes": 1}:
        raise ValueError("scientific criteria differ from frozen protocol")
    expected_budget = ({"maximum_trials": 3, "maximum_total_hessian_evaluations": 15,
                        "maximum_total_energy_evaluations": 120, "maximum_total_force_evaluations": 120,
                        "wall_cap_seconds": 600} if p["scope"] == "calibration" else
                       {"maximum_trials": 10, "maximum_total_hessian_evaluations": 180,
                        "maximum_total_energy_evaluations": 640, "maximum_total_force_evaluations": 640,
                        "wall_cap_seconds": 2700})
    if p.get("budget") != expected_budget:
        raise ValueError("resource budget differs from frozen protocol")
    trials = make_trials(p)
    if len(trials) != expected_trials:
        raise ValueError("frozen trial denominator mismatch")
    return p


def load_base_geometries(path: Path):
    from ase.io import read
    frames = read(str(path), index=":")
    by_id = {}
    for atoms in frames:
        raw = atoms.info.get("reaction_id", "")
        rid = f"{int(raw):03d}" if isinstance(raw, (int, float)) and float(raw).is_integer() else str(raw).zfill(3)
        if rid in by_id:
            raise ValueError(f"duplicate reaction ID {rid}")
        by_id[rid] = atoms
    if {k: len(v) for k, v in by_id.items()} != EXPECTED_ATOMS:
        raise ValueError("source NN1 TS geometry IDs/atom counts differ from frozen case11 selection")
    return by_id


def perturb(atoms, amplitude: float, seed: int):
    import numpy as np
    result = atoms.copy()
    n = len(result)
    pos = np.asarray(result.get_positions(), dtype=float)
    centered = pos - pos.mean(axis=0)
    basis = np.zeros((3 * n, 6), dtype=float)
    for i, r in enumerate(centered):
        for axis in range(3):
            basis[3 * i + axis, axis] = 1.0
        x, y, z = r
        basis[3 * i:3 * i + 3, 3:] = np.array([[0.0, z, -y], [-z, 0.0, x], [y, -x, 0.0]])
    u, singular, _ = np.linalg.svd(basis, full_matrices=False)
    tol = max(basis.shape) * np.finfo(float).eps * (singular[0] if len(singular) else 1.0)
    q = u[:, singular > tol]
    rng = np.random.Generator(np.random.PCG64(seed))
    noise = rng.normal(size=(n, 3)).reshape(-1)
    noise -= q @ (q.T @ noise)
    noise = noise.reshape(n, 3)
    rms = float(np.sqrt(np.mean(np.sum(noise * noise, axis=1))))
    if not math.isfinite(rms) or rms <= 0:
        raise ValueError("degenerate projected perturbation")
    noise *= amplitude / rms
    result.set_positions(pos + noise)
    result.info["reaction_id"] = atoms.info.get("reaction_id")
    result.info["condition"] = "perturbed"
    result.info["perturbation_rms_A"] = amplitude
    result.info["seed"] = int(seed)
    return result, noise


def positions_hash(atoms) -> str:
    import numpy as np
    return hashlib.sha256(np.asarray(atoms.get_positions(), dtype="<f8").tobytes()).hexdigest()


def write_start(path: Path, atoms) -> None:
    """Write standards-compliant extxyz with binary64 round-trip positions."""
    path.parent.mkdir(parents=True, exist_ok=True)
    info = atoms.info
    header = ["Properties=species:S:1:pos:R:3",
              f"reaction_id={int(info['reaction_id']):03d}",
              f"condition={info.get('condition', 'baseline')}",
              "source=case11_compact_search"]
    if "perturbation_rms_A" in info:
        header.append(f"perturbation_rms_A={float(info['perturbation_rms_A']):.17g}")
    if "seed" in info:
        header.append(f"seed={int(info['seed'])}")
    lines = [str(len(atoms)), " ".join(header)]
    for symbol, position in zip(atoms.get_chemical_symbols(), atoms.get_positions()):
        lines.append(f"{symbol} {position[0]:.17g} {position[1]:.17g} {position[2]:.17g}")
    path.write_text("\n".join(lines) + "\n")


def generate_starts(protocol: dict, geometries: dict):
    import numpy as np
    prepared = []
    for trial in make_trials(protocol):
        rid = trial["reaction_id"]
        if trial["condition"] == "baseline":
            start = geometries[rid].copy()
            start.info.update({"reaction_id": rid, "condition": "baseline"})
            noise = np.zeros((len(start), 3))
        else:
            start, noise = perturb(geometries[rid], trial["amplitude_rms_A"], trial["seed"])
        amplitude_label = f"{trial['amplitude_rms_A']:.2f}".replace(".", "p")
        key = f"{rid}-baseline" if trial["condition"] == "baseline" else f"{rid}-rms{amplitude_label}-seed{trial['seed']}"
        entry = {**trial, "trial_id": key, "start_path": f"starts/{key}.extxyz",
                 "positions_sha256": positions_hash(start),
                 "atomic_numbers_sha256": hashlib.sha256(np.asarray(start.get_atomic_numbers(), dtype="<i4").tobytes()).hexdigest(),
                 "observed_rms_displacement_A": float(np.sqrt(np.mean(np.sum(noise * noise, axis=1)))),
                 "translation_projection_residual_A": float(np.linalg.norm(noise.sum(axis=0))),
                 "rotation_projection_residual_A2": float(np.linalg.norm(np.cross(geometries[rid].get_positions() - geometries[rid].get_positions().mean(axis=0), noise).sum(axis=0)))}
        prepared.append((trial, key, start, entry))
    return prepared


def prepare_starts(protocol: dict, geometries: dict, out: Path):
    prepared = generate_starts(protocol, geometries)
    manifest = []
    for _, _, start, entry in prepared:
        start_path = out / entry["start_path"]
        write_start(start_path, start)
        manifest.append({**entry, "start_file_sha256": sha256(start_path)})
    return manifest, prepared


def trial_audit(data: dict, path: Path, rid: str):
    errors = []
    events = data.get("event_stream", [])
    counts = data.get("counts", {})
    if data.get("reaction_id") != rid or data.get("arm") != "full_hessian" or data.get("repeat") != 1:
        errors.append(f"trial identity mismatch {path.parent.name}")
    if len(events) != counts.get("model_evaluate_calls"):
        errors.append(f"event counter mismatch {path.parent.name}")
    keys = ("energy_evaluations", "force_evaluations", "hessian_evaluations")
    stages = {s: {k: sum(e.get(k, 0) for e in events if e.get("stage") == s) for k in keys}
              for s in ("optimization", "independent_final_audit")}
    if counts.get("optimization") != stages["optimization"] or counts.get("independent_final_audit") != stages["independent_final_audit"]:
        errors.append(f"stage counter mismatch {path.parent.name}")
    if counts.get("total") != {k: sum(stages[s][k] for s in stages) for k in keys}:
        errors.append(f"total counter mismatch {path.parent.name}")
    if not data.get("failure"):
        if stages["optimization"]["hessian_evaluations"] != data.get("optimizer_steps"):
            errors.append(f"full-H events do not match recorded optimizer steps {path.parent.name}")
        if stages["independent_final_audit"]["hessian_evaluations"] != 1:
            errors.append(f"independent final Hessian missing {path.parent.name}")
        if data.get("native_trajectory_frames", 0) < 1:
            errors.append(f"native trajectory missing {path.parent.name}")
    traj = path.parent / "native.traj"
    ntraj = data.get("native_trajectory")
    if ntraj and (not traj.is_file() or sha256(traj) != ntraj.get("sha256")):
        errors.append(f"native trajectory hash mismatch {path.parent.name}")
    for e in events:
        if not e.get("input_hashes", {}).get("positions_sha256") or e.get("monotonic_end_ns", 0) <= e.get("monotonic_start_ns", 0):
            errors.append(f"bad event evidence {path.parent.name}")
        if e.get("call_status") == "completed" and (not e.get("output_hashes", {}).get("energy_sha256") or not e.get("output_hashes", {}).get("forces_sha256")):
            errors.append(f"completed E/F event lacks hashes {path.parent.name}")
    audit = data.get("final_audit") or {}
    success = bool(data.get("optimizer_converged") and audit.get("force_within_threshold") and audit.get("one_negative_mode"))
    if data.get("scientific_success") != success:
        errors.append(f"science flag mismatch {path.parent.name}")
    return errors


def audit(out: Path, protocol_path: Path, geometries_path: Path, checkpoint: Path, model: Path, v1_runner: Path, evaluator: Path, image_id: str):
    errors = []
    try:
        protocol = validate_protocol(protocol_path.read_bytes())
        env = json.loads((out / "envelope.json").read_text())
        manifest_doc = json.loads((out / "perturbation_manifest.json").read_text())
        bases = load_base_geometries(geometries_path)
    except Exception as exc:
        return [f"audit input unreadable: {type(exc).__name__}: {exc}"]
    if env.get("schema") != SCHEMA or env.get("scope") != protocol["scope"] or image_id != IMAGE_ID or env.get("image_id") != IMAGE_ID:
        errors.append("schema/scope/image mismatch")
    if env.get("trusted_output_root") != str(OUTPUT_ROOT):
        errors.append("trusted output root mismatch")
    if env.get("protocol_sha256") != sha256(protocol_path) or env.get("input_hashes", {}).get("geometry") != sha256(geometries_path):
        errors.append("protocol or source geometry hash mismatch")
    if (manifest_doc.get("schema") != "case11-perturbation-manifest/v1"
            or manifest_doc.get("source_geometry_sha256") != sha256(geometries_path)
            or manifest_doc.get("generator") != protocol["perturbation_generation"]["generator"]
            or manifest_doc.get("projection") != protocol["perturbation_generation"]["projection"]
            or manifest_doc.get("scaling") != protocol["perturbation_generation"]["scaling"]):
        errors.append("perturbation manifest metadata mismatch")
    manifest = manifest_doc.get("starts", [])
    hashes = {"geometry": sha256(geometries_path), "checkpoint": sha256(checkpoint), "model_spec": sha256(model),
              "v1_runner": sha256(v1_runner), "evaluator": sha256(evaluator), "perturbation_runner": sha256(Path(__file__).resolve())}
    fixed = {"geometry": EXPECTED_GEOMETRY_SHA256, "checkpoint": EXPECTED_CHECKPOINT_SHA256,
             "model_spec": EXPECTED_MODEL_SPEC_SHA256}
    if any(hashes.get(k) != v for k, v in fixed.items()) or env.get("input_hashes") != hashes:
        errors.append("protected input hashes mismatch")
    for q in (protocol_path, geometries_path, checkpoint, model, v1_runner, evaluator, Path(__file__).resolve()):
        if not readonly(q.resolve()):
            errors.append(f"input not mounted read-only: {q}")
    expected_prepared = generate_starts(protocol, bases)
    expected_manifest = [entry for _, _, _, entry in expected_prepared]
    # Recompute expected perturbations without writing or blessing the recorded starts.
    compared = ("reaction_id", "condition", "amplitude_rms_A", "seed", "trial_id", "start_path",
                "positions_sha256", "atomic_numbers_sha256", "observed_rms_displacement_A",
                "translation_projection_residual_A", "rotation_projection_residual_A2")
    if [{k:item.get(k) for k in compared} for item in manifest] != [{k:item.get(k) for k in compared} for item in expected_manifest]:
        errors.append("perturbation descriptors differ from frozen seed/algorithm")
    by_trial = {x.get("trial_id"): x for x in manifest}
    if len(by_trial) != len(expected_prepared):
        errors.append("perturbation manifest denominator/uniqueness mismatch")
    from ase.io import read
    import numpy as np
    for trial, key, expected_start, entry in expected_prepared:
        m = by_trial.get(key)
        start_path = out / "starts" / f"{key}.extxyz"
        if not m or not start_path.is_file():
            errors.append(f"missing start {key}"); continue
        saved = read(str(start_path))
        if sha256(start_path) != m.get("start_file_sha256") or positions_hash(saved) != m.get("positions_sha256"):
            errors.append(f"start hash mismatch {key}")
        if positions_hash(saved) != positions_hash(expected_start):
            errors.append(f"recomputed start coordinates mismatch {key}")
        if m.get("atomic_numbers_sha256") != hashlib.sha256(np.asarray(saved.get_atomic_numbers(), dtype="<i4").tobytes()).hexdigest():
            errors.append(f"start atom-order hash mismatch {key}")
    expected_n = protocol["budget"]["maximum_trials"]
    trials = env.get("trials", [])
    if len(trials) != expected_n or env.get("expected_trials") != expected_n or env.get("observed_trials") != expected_n:
        errors.append("trial denominator incomplete")
    total = {"energy_evaluations": 0, "force_evaluations": 0, "hessian_evaluations": 0}
    observed = set()
    for tr in trials:
        key, rid = tr.get("trial_id"), tr.get("reaction_id")
        observed.add(key)
        path = out / tr.get("directory", "") / "trial.json"
        try:
            data = json.loads(path.read_text())
            errors.extend(trial_audit(data, path, rid))
            for k in total: total[k] += data.get("counts", {}).get("total", {}).get(k, 0)
            descriptor = by_trial.get(key, {})
            first = next((e for e in data.get("event_stream", []) if e.get("stage") == "optimization"), None)
            if first is None or first.get("input_hashes", {}).get("positions_sha256") != descriptor.get("positions_sha256"):
                errors.append(f"first optimization event does not match frozen start {key}")
            if data.get("optimizer_steps", 0) > protocol["optimizer"]["max_steps"]:
                errors.append(f"optimizer step cap exceeded {key}")
            trajectory = out / tr.get("directory", "") / "native.traj"
            if trajectory.is_file():
                try:
                    import numpy as np
                    from ase.io import read
                    frame_hashes = {hashlib.sha256(np.asarray(frame.get_positions(), dtype="<f8").tobytes()).hexdigest()
                                    for frame in read(str(trajectory), index=":")}
                    callback_hashes = [e.get("input_hashes", {}).get("positions_sha256") for e in data.get("event_stream", [])
                                       if e.get("stage") == "optimization" and e.get("hessian_evaluations", 0) == 1]
                    if any(h not in frame_hashes for h in callback_hashes):
                        errors.append(f"Hessian callback coordinates are absent from native trajectory {key}")
                except Exception as exc:
                    errors.append(f"native trajectory replay failed {key}: {type(exc).__name__}: {exc}")
        except Exception as exc:
            errors.append(f"trial unreadable {key}: {type(exc).__name__}: {exc}")
    if observed != set(by_trial):
        errors.append("observed trial IDs differ from perturbation starts")
    caps = protocol["budget"]
    if total["hessian_evaluations"] > caps["maximum_total_hessian_evaluations"] or total["energy_evaluations"] > caps["maximum_total_energy_evaluations"] or total["force_evaluations"] > caps["maximum_total_force_evaluations"]:
        errors.append("observed model evaluations exceed the frozen protocol budget")
    if env.get("observed_total_counts") != total:
        errors.append("aggregate model counters mismatch")
    if env.get("deliverable_hashes") != hash_tree(out):
        errors.append("deliverable hash tree mismatch")
    snap = out / "protocol.snapshot.json"
    if not snap.is_file() or sha256(snap) != sha256(protocol_path):
        errors.append("protocol snapshot mismatch")
    return errors


def main() -> int:
    ap = argparse.ArgumentParser()
    for name in ("protocol", "geometries", "checkpoint", "model_spec", "v1_runner", "evaluator", "output"):
        ap.add_argument("--" + name.replace("_", "-"), type=Path, required=True)
    ap.add_argument("--image-id", required=True)
    ap.add_argument("--audit", action="store_true")
    a = ap.parse_args()
    global V1
    V1 = load_v1(a.v1_runner.resolve())
    out = a.output.resolve()
    if a.audit:
        errors = audit(out, a.protocol.resolve(), a.geometries.resolve(), a.checkpoint.resolve(), a.model_spec.resolve(), a.v1_runner.resolve(), a.evaluator.resolve(), a.image_id)
        print(json.dumps({"audit": "PASS" if not errors else "REJECT", "errors": errors}, indent=2))
        return 0 if not errors else 2
    if out.exists() and any(out.iterdir()):
        raise SystemExit("output directory must be empty")
    raw = a.protocol.read_bytes(); protocol = validate_protocol(raw)
    fixed = {"geometry": EXPECTED_GEOMETRY_SHA256, "checkpoint": EXPECTED_CHECKPOINT_SHA256,
             "model_spec": EXPECTED_MODEL_SPEC_SHA256}
    hashes = {"geometry": sha256(a.geometries), "checkpoint": sha256(a.checkpoint), "model_spec": sha256(a.model_spec),
              "v1_runner": sha256(a.v1_runner), "evaluator": sha256(a.evaluator),
              "perturbation_runner": sha256(Path(__file__).resolve())}
    if any(hashes.get(k) != v for k, v in fixed.items()):
        raise SystemExit("environment error: fixed input source hash mismatch")
    geometries = load_base_geometries(a.geometries)
    out.mkdir(parents=True, exist_ok=True)
    (out / "protocol.snapshot.json").write_bytes(raw)
    manifest, prepared = prepare_starts(protocol, geometries, out)
    (out / "perturbation_manifest.json").write_text(json.dumps({"schema": "case11-perturbation-manifest/v1",
        "generator": protocol["perturbation_generation"]["generator"], "projection": protocol["perturbation_generation"]["projection"],
        "scaling": protocol["perturbation_generation"]["scaling"], "source_geometry_sha256": hashes["geometry"],
        "starts": manifest}, indent=2, sort_keys=True)+"\n")
    from newtonnet_evaluator import NewtonNetEvaluator
    load_begin = time.monotonic_ns(); evaluator = NewtonNetEvaluator(a.checkpoint, a.model_spec); model_load_seconds=(time.monotonic_ns()-load_begin)/1e9
    trials=[]; begun=time.monotonic_ns()
    for descriptor,key,start,entry in prepared:
        name=f"rxn-{descriptor['reaction_id']}-{key.split('-',1)[1]}"
        td=out/name; td.mkdir()
        record=V1.run_trial(descriptor["reaction_id"],1,"full_hessian",start,evaluator,{
            "optimizer":{"order":1,"internal":False,"fmax_eV_A":0.04,"delta0_A":0.12,"max_steps":protocol["optimizer"]["max_steps"],"restart":False,"refine_initial_hessian":0},
            "scientific_criteria":protocol["scientific_criteria"],"arms":{"full_hessian":{"hessian_strategy":"exact_callback","diag_every_n":0}}},td)
        record["trial_id"]=key
        (td/"trial.json").write_text(json.dumps(record,indent=2,sort_keys=True)+"\n")
        trials.append({"trial_id":key,"directory":name,"reaction_id":descriptor["reaction_id"],"condition":descriptor["condition"],
                       "amplitude_rms_A":descriptor["amplitude_rms_A"],"seed":descriptor["seed"],"status":record["status"],
                       "optimizer_converged":record["optimizer_converged"],"scientific_success":record["scientific_success"],
                       "optimizer_steps":record["optimizer_steps"],"native_trajectory_frames":record["native_trajectory_frames"]})
    elapsed=(time.monotonic_ns()-begun)/1e9
    totals={"energy_evaluations":0,"force_evaluations":0,"hessian_evaluations":0}
    for tr in trials:
        d=json.loads((out/tr["directory"]/"trial.json").read_text())
        for k in totals:totals[k]+=d["counts"]["total"][k]
    env={"schema":SCHEMA,"scope":protocol["scope"],"protocol_sha256":hashlib.sha256(raw).hexdigest(),"protocol_bytes":len(raw),
         "image_id":a.image_id,"python":platform.python_version(),"platform":platform.platform(),"trusted_output_root":str(out),
         "input_hashes":hashes,"selected_reaction_ids":protocol["reaction_ids"],"expected_trials":protocol["budget"]["maximum_trials"],
         "observed_trials":len(trials),"trial_order":trials,"trials":trials,"model_load_seconds":model_load_seconds,
         "optimizer_trials_wall_seconds":elapsed,"observed_total_counts":totals,
         "coverage":{"trial_coverage":"complete" if len(trials)==protocol["budget"]["maximum_trials"] else "incomplete",
                     "science_scope":"case11_small_sample_perturbation" if protocol["scope"]=="formal" else "calibration_only"},
         "failure_semantics":"Every expected trial appears in the denominator even if Sella fails or reaches max_steps. A capped or failed trial is not scientific success.",
         "trajectory_semantics":"Native Sella frames are coordinate snapshots, not accepted-step counts."}
    env["deliverable_hashes"]=hash_tree(out)
    (out/"envelope.json").write_text(json.dumps(env,indent=2,sort_keys=True)+"\n")
    errors=[]
    (out/"audit.json").write_text(json.dumps({"audit":"CANDIDATE_GENERATION_COMPLETE","errors":[]},indent=2)+"\n")
    print(json.dumps({"schema":SCHEMA,"scope":protocol["scope"],"audit":"PASS" if not errors else "REJECT","trials":len(trials),
        "model_load_seconds":model_load_seconds,"optimizer_trials_wall_seconds":elapsed,"observed_total_counts":totals,
        "optimizer_convergences":sum(bool(t["optimizer_converged"]) for t in trials),"scientific_successes":sum(bool(t["scientific_success"]) for t in trials),"errors":errors},indent=2))
    return 0 if not errors else 2


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SystemExit:
        raise
    except Exception as exc:
        print(json.dumps({"status":"ENVIRONMENT_ERROR","reward":None,"reason":f"runner setup failure: {type(exc).__name__}: {exc}"},ensure_ascii=False))
        raise SystemExit(2)
CCW_142_run_case05_py_d009badd6846_END
test "$(sha256sum "$oracle_dir/run_case05.py" | cut -d ' ' -f 1)" = "d009badd68464b99fae6e5e41ffe25e73dc13dc542cc03d13c399d50e0cc9f66"

cat > "$oracle_dir/summarize.py" <<'CCW_142_summarize_py_1b0dd505df80_END'
import csv,json
from pathlib import Path
import numpy as np
from ase.io import read
root=Path('/app/final');rr=root/'runner_output';env=json.loads((rr/'envelope.json').read_text());manifest=json.loads((rr/'perturbation_manifest.json').read_text());starts={x['trial_id']:x for x in manifest['starts']};records={}
for tr in env['trials']:
 d=json.loads((rr/tr['directory']/'trial.json').read_text());records[d['trial_id']]=d
base_frames=read('/app/assets/case05_ts_geometries_001_162.extxyz',index=':');base={f'{int(a.info["reaction_id"]):03d}':a for a in base_frames}
def kabsch(a,b,mask):
 a=a[mask];b=b[mask];ac=a.mean(0);bc=b.mean(0);u,s,v=np.linalg.svd((a-ac).T@(b-bc));d=np.linalg.det(u@v);r=u@np.diag([1,1,d])@v;return float(np.sqrt(np.mean(np.sum(((a-ac)@r+bc-b)**2,axis=1))))
final={};
for tid,d in records.items():
 path=rr/d['native_trajectory']['path'] if False else rr/next(t['directory'] for t in env['trials'] if t['trial_id']==tid)/'native.traj'
 atoms=read(str(path),index=-1);final[tid]=(atoms,d['final_audit']['energy_eV'],d)
with (root/'trial_table.csv').open('w',newline='') as f:
 fields=['trial_id','reaction_id','condition','status','optimizer_steps','energy_calls','force_calls','hessian_calls','start_sha256','walltime_s'];w=csv.DictWriter(f,fieldnames=fields);w.writeheader()
 for tid,d in records.items():
  m=starts[tid];c=d['counts']['total'];w.writerow({'trial_id':tid,'reaction_id':d['reaction_id'],'condition':m['condition'],'status':d['status'],'optimizer_steps':d['optimizer_steps'],'energy_calls':c['energy_evaluations'],'force_calls':c['force_evaluations'],'hessian_calls':c['hessian_evaluations'],'start_sha256':m['positions_sha256'],'walltime_s':d['trial_walltime_ns']/1e9})
endpoint_rows=[]
with (root/'endpoint_comparison.csv').open('w',newline='') as f:
 fields=['reaction_id','trial_id','delta_energy_eV','heavy_atom_proper_kabsch_rmsd_A','identity_status'];w=csv.DictWriter(f,fieldnames=fields);w.writeheader()
 for tid,(atoms,energy,d) in final.items():
  rid=d['reaction_id'];baseline=final[f'{rid}-baseline'];mask=base[rid].get_atomic_numbers()!=1
  row={'reaction_id':rid,'trial_id':tid,'delta_energy_eV':energy-baseline[1],'heavy_atom_proper_kabsch_rmsd_A':kabsch(atoms.positions,baseline[0].positions,mask),'identity_status':'baseline_anchor' if tid==f'{rid}-baseline' else 'unresolved'}
  endpoint_rows.append(row);w.writerow(row)
success=sum(bool(d['scientific_success']) for d in records.values());lower=[]
for tid,(atoms,energy,d) in final.items():
 if starts[tid]['condition']!='baseline' and final[f"{d['reaction_id']}-baseline"][1]-energy>1e-6:lower.append(tid)
groups={}
for tid,d in records.items():
 m=starts[tid];key=('baseline',0.0) if m['condition']=='baseline' else ('perturbed',float(m['amplitude_rms_A']))
 g=groups.setdefault(key,{'n':0,'success':0,'steps':0,'energy':0,'force':0,'hessian':0,'wall':0.0})
 c=d['counts']['total'];g['n']+=1;g['success']+=int(bool(d['scientific_success']));g['steps']+=int(d['optimizer_steps'])
 g['energy']+=int(c['energy_evaluations']);g['force']+=int(c['force_evaluations']);g['hessian']+=int(c['hessian_evaluations']);g['wall']+=d['trial_walltime_ns']/1e9
group_text=' '.join(
 f"{('baseline' if amplitude==0 else f'{amplitude:.2f} Å RMS perturbation')}: "
 f"{g['success']}/{g['n']} successes, {g['steps']} optimizer steps, "
 f"{g['energy']} energy calls, {g['force']} force calls, {g['hessian']} Hessian calls, "
 f"{g['wall']:.3f} summed trial wall seconds."
 for (condition,amplitude),g in sorted(groups.items(),key=lambda item:item[0][1]))
lower_rows=[r for r in endpoint_rows if r['trial_id'] in lower]
lower_text=(
 'Lower perturbed endpoint energy than the same-ID baseline was observed for '+
 '; '.join(f"{r['trial_id']} (ΔE {float(r['delta_energy_eV']):.6f} eV, heavy-atom proper Kabsch RMSD {float(r['heavy_atom_proper_kabsch_rmsd_A']):.4f} Å)" for r in lower_rows)+'.'
 if lower_rows else 'No perturbed endpoint was lower in energy than its same-ID baseline by more than the reporting tolerance.')
assessment=(f"Within these {len(records)} fixed trials, {success} met the scientific success criteria. "
 f"Observed counts and summed per-trial wall time grouped by perturbation condition: {group_text} "
 f"{lower_text} This is an endpoint energy/RMSD observation only; it does not establish saddle identity, a mechanism, or a robustness rate beyond these sampled starts. Endpoint RMSD and energy differences have no validated identity cutoff here. The results cover only the structures and seeds present in this frozen manifest.")
(root/'analysis.json').write_text(json.dumps({'scope_ids':sorted({d['reaction_id'] for d in records.values()}),'denominator':len(records),'scientific_successes':success,'lower_energy_trials':sorted(lower),'semantic_review':{'trial_observations':[{'trial_id':tid,'status':d['status'],'scientific_success':bool(d['scientific_success'])} for tid,d in records.items()],'within_sample_assessment':assessment,'identity_uncertainty':'Endpoint RMSD and energy differences do not define a validated saddle-identity cutoff; identity remains unresolved for perturbations.','extrapolation_scope':'Two proxy structures, two amplitudes and two seeds do not establish population-level robustness or transfer to unavailable original guesses.','evidence_index':['trial_table.csv','endpoint_comparison.csv','runner_output/perturbation_manifest.json','runner_output/audit.json','runner_output/*/event_evaluations.jsonl']}},indent=2)+'\n')
(root/'failure_analysis.md').write_text(f"# Finite perturbation outcomes\n\nThe {len(records)} frozen trials produced {success} outcomes meeting the optimizer, final-force, and projected-mode criteria. {group_text}\n\n{lower_text} The lower endpoint is not assigned a saddle identity or mechanism; no validated identity cutoff is available. These observations are limited to the structures, amplitudes, and seeds in the frozen perturbation manifest and do not establish population-level robustness or transfer to unavailable original guesses. The full model event stream, native trajectories, generated starts, and perturbation manifest are preserved under `runner_output/` for independent review.\n")
CCW_142_summarize_py_1b0dd505df80_END
test "$(sha256sum "$oracle_dir/summarize.py" | cut -d ' ' -f 1)" = "1b0dd505df80ef85a54941678f0ba137d839e5462908f5bad2f49d0deb8aabc8"

chmod 0444 "$oracle_dir"/*.py
python "$oracle_dir/run_case05.py" --protocol /app/assets/protocol.json --geometries /app/assets/case05_ts_geometries_001_162.extxyz --checkpoint /app/assets/best_model_state.tar --model-spec /app/assets/newtonnet_model_spec.yml --v1-runner "$oracle_dir/case04_controlled_runner.py" --evaluator /opt/compchembench/newtonnet_evaluator.py --output /app/final/runner_output --image-id case-container
python "$oracle_dir/summarize.py"
cp /app/assets/protocol.json /app/final/protocol.json
