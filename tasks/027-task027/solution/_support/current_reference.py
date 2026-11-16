#!/usr/bin/env python3
"""Offline Case07 reference preparation, native parsing, and final assembly.

This program never submits jobs or contacts a remote service. `--prepare`
creates only public-input ORCA pilot/screen inputs and an owned Slurm script.
`--ingest` reparses a hash-bound fresh pilot + six-screen native bundle.
`--finalize` reparses a complete later-stage bundle and assembles candidate
artifacts only when the fresh-native audit passes; neither command authenticates
execution provenance or assigns reward.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import sys
from datetime import datetime, timezone
import uuid
from typing import Any

import public_geometry as geom
import fresh_audit
import native_parser

CASE_ID = "case-07-independent-saddle-point-recomputation"
REVISION = "2.1"
RESOURCE_PROFILE = "case07-8h-v1"
PUBLIC_ASSET_HASHES = {
    "bpr_skeleton_geometries.csv": geom.EXPECTED_SHA256,
    "ipso_energy_reference.csv": "a9224bde49cfc8fee17944238392af351fbc645dc98ed077b498b23dcb3d209b",
    "ipso_energy_reference_provenance.json": "8d7ae2cde6a0b1685159961fbc66ddb3ce00b663269377943e093ca7e4312ceb",
    "41467_2023_40675_MOESM1_ESM.docx": "52c8854e125cac6ea714c61a4e711fea66565cef62d0f176511e819e59fd568a",
    "Figure4/Toluene/Toluene-iBPR-DFT.log": "d2d7720643c371c07c3e34ea673ac6e70f7e4d610577241e7a7a87e368d168f1",
}
MAX_ACTIVE_SECONDS = 8 * 60 * 60
MAX_CORES = 8
MAX_MEMORY_GIB = 16
MAX_SCRATCH_GIB = 20
PILOT_CAP_SECONDS = 600
SCREEN_CAP_SECONDS = 450
HARTREE_TO_KCAL = 627.5094740631
STAGE_CAPS = {"screen_refinement": 900, "optts": 4800, "ts_frequency": 2400,
              "endpoint_opt": 5400, "endpoint_frequency": 2100}
FINAL_LEVEL_PROFILES = {
    "r2scan-3c": {"level": "UKS r2SCAN-3c DefGrid3",
                   "method": "UKS r2SCAN-3c DefGrid3"},
    "pbe-d3bj-def2-svp": {"level": "UKS PBE D3BJ def2-SVP def2/J RI DefGrid3",
                            "method": "UKS PBE D3BJ def2-SVP def2/J RI DefGrid3"},
}
PILOT_PROFILES = {
    "legacy-pbe-screen": "UKS PBE D3BJ def2-SVP DefGrid3 TightSCF",
    "pbe-d3bj-def2-svp": "UKS PBE D3BJ def2-SVP def2/J RI DefGrid3 VeryTightSCF",
}
CHANNEL_BONDS = {"C1": ((0, 5), (10, 11), (13, 14), (11, 14)),
                 "C2": ((1, 5), (10, 11), (13, 14), (10, 14))}
MODE_DISPLACEMENT_ANGSTROM = 0.12
MAX_PLANNED_STAGE_SECONDS = (3600 + STAGE_CAPS["screen_refinement"] + STAGE_CAPS["optts"]
                             + STAGE_CAPS["ts_frequency"]
                             + 2 * STAGE_CAPS["endpoint_opt"]
                             + 2 * STAGE_CAPS["endpoint_frequency"])
HEX64 = re.compile(r"^[0-9a-f]{64}$")


class ReferenceError(ValueError):
    pass


def sha256(path: Path) -> str:
    if path.is_symlink() or not path.is_file():
        raise ReferenceError(f"missing, non-regular, or symlink file: {path}")
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _safe_root(path: Path, *, allow_create: bool = False) -> Path:
    if path.is_symlink():
        raise ReferenceError(f"symlink root is not allowed: {path}")
    if allow_create:
        path.mkdir(parents=True, exist_ok=False)
    if not path.is_dir():
        raise ReferenceError(f"directory is missing: {path}")
    return path.resolve(strict=True)


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() or path.is_symlink():
        raise ReferenceError(f"refusing to overwrite prepared output: {path}")
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(content)


def _xyz(coords: list[list[float]], comment: str) -> str:
    # The typed P04 service rejects shell metacharacters in text inputs. An
    # XYZ comment is inert, so serialize its existing semicolon separators as
    # commas without changing any scientific coordinates or atom ordering.
    rows = [f"{len(geom.ATOM_ORDER)}", comment.replace(";", ",")]
    rows.extend(f"{e} {x:.10f} {y:.10f} {z:.10f}"
                for e, (x, y, z) in zip(geom.ATOM_ORDER, coords))
    return "\n".join(rows) + "\n"


def _orca_input(stage: str, *, constraints: list[dict[str, Any]] | None = None,
                ts_mode_bond: list[int] | None = None,
                ts_active_atoms: list[int] | None = None,
                final_profile: str = "r2scan-3c",
                pilot_profile: str = "legacy-pbe-screen",
                pilot_action: str = "SP") -> str:
    profile = FINAL_LEVEL_PROFILES.get(final_profile)
    if profile is None:
        raise ReferenceError("final method profile is not in the frozen Case07 profile registry")
    final_method = profile["method"]
    if stage == "pilot_sp":
        if pilot_profile not in PILOT_PROFILES or pilot_action not in {"SP", "EnGrad"}:
            raise ReferenceError("pilot method/action is outside the frozen Case07 pilot profiles")
        method = f"! {PILOT_PROFILES[pilot_profile]} {pilot_action}"
    elif stage == "screen_energy_gradient":
        method = "! UKS PBE D3BJ def2-SVP DefGrid3 TightSCF EnGrad"
    elif stage == "screen_refinement":
        if not isinstance(constraints, list) or len(constraints) != 4:
            raise ReferenceError("screen refinement requires four explicit decision constraints")
        method = "! UKS r2SCAN-3c DefGrid3 TightSCF Opt TightOpt"
        lines = []
        for row in constraints:
            pair, distance = row.get("atoms"), row.get("distance_angstrom")
            if (not isinstance(pair, list) or len(pair) != 2 or any(type(i) is not int or not 0 <= i < 21 for i in pair)
                    or pair[0] == pair[1] or isinstance(distance, bool)
                    or not isinstance(distance, (int, float)) or not math.isfinite(distance)
                    or not 0.5 <= distance <= 5.0):
                raise ReferenceError("screen refinement constraint is malformed or outside public bounds")
            lines.append(f"  {{ B {pair[0]} {pair[1]} {float(distance):.6f} C }}\n")
        extra = ("%scf\n  MaxIter 400\nend\n%geom\n  MaxIter 60\n  Constraints\n"
                 + "".join(lines) + "  end\nend\n")
        return f"{method}\n%pal nprocs 8 end\n%maxcore 1400\n{extra}* xyzfile 0 2 start.xyz\n"
    elif stage == "optts":
        if (not isinstance(ts_mode_bond, list) or len(ts_mode_bond) != 2
                or any(type(i) is not int or not 0 <= i < 21 for i in ts_mode_bond)
                or ts_mode_bond[0] == ts_mode_bond[1]
                or not isinstance(ts_active_atoms, list) or not 2 <= len(ts_active_atoms) <= 21
                or any(type(i) is not int or not 0 <= i < 21 for i in ts_active_atoms)
                or len(set(ts_active_atoms)) != len(ts_active_atoms)):
            raise ReferenceError("OptTS requires explicit valid mode bond and active atom decision")
        method = f"! {final_method} VeryTightSCF OptTS TightOpt"
        extra = ("%scf\n  MaxIter 400\nend\n%geom\n  Calc_Hess true\n  MaxIter 60\n  Recalc_Hess 10\n"
                 f"  TS_Mode {{ B {ts_mode_bond[0]} {ts_mode_bond[1]} }} end\n"
                 f"  TS_Active_Atoms {{ {' '.join(str(i) for i in ts_active_atoms)} }} end\nend\n")
        return f"{method}\n%pal nprocs 8 end\n%maxcore 1400\n{extra}* xyzfile 0 2 start.xyz\n"
    elif stage in {"ts_frequency", "endpoint_frequency"}:
        method = f"! {final_method} VeryTightSCF AnFreq"
        extra = ("%scf\n  MaxIter 400\n  ConvCheckMode 0\n  ConvForced 1\nend\n"
                 "%method\n  Z_Tol 1e-6\n  Z_MaxIter 128\nend\n")
        return f"{method}\n%pal nprocs 8 end\n%maxcore 1400\n{extra}* xyzfile 0 2 start.xyz\n"
    elif stage == "endpoint_opt":
        method = f"! {final_method} VeryTightSCF Opt TightOpt"
        extra = "%scf\n  MaxIter 400\nend\n%geom\n  MaxIter 100\nend\n"
        return f"{method}\n%pal nprocs 8 end\n%maxcore 1400\n{extra}* xyzfile 0 2 start.xyz\n"
    else:
        raise ReferenceError(f"no offline input template for stage {stage}")
    return (f"{method}\n%pal nprocs 8 end\n%maxcore 1400\n"
            "%scf\n  MaxIter 400\nend\n* xyzfile 0 2 start.xyz\n")


def _slurm_script(stage_ids: list[str], attempt_id: str) -> str:
    # Every invocation is locally prepared and network-free. A nonzero stage
    # stops immediately; the remaining campaign must be reconciled explicitly.
    lines = [
        "#!/usr/bin/env bash",
        "#SBATCH --job-name=case07-screen",
        "#SBATCH --nodes=1",
        f"#SBATCH --ntasks={MAX_CORES}",
        f"#SBATCH --cpus-per-task=1",
        f"#SBATCH --mem={MAX_MEMORY_GIB}G",
        "#SBATCH --no-requeue",
        "#SBATCH --time=01:00:00",
        "#SBATCH --export=ALL",
        "set -euo pipefail",
        "ROOT=$(cd -- \"$(dirname -- \"$0\")\" && pwd -P)",
        "START_EPOCH=$(date +%s)",
        "DEADLINE=$((START_EPOCH + 3600))",
        f"ATTEMPT_ID={attempt_id}",
        "ORCA_BIN=${ORCA_BIN:-orca}",
        "command -v \"$ORCA_BIN\" >/dev/null || { echo 'ORCA executable unavailable' >&2; exit 2; }",
        "SCRATCH_BASE=${CASE07_SCRATCH_ROOT:?operator must set an owned scratch directory}",
        "if [[ -L \"$SCRATCH_BASE\" ]]; then echo 'scratch root must not be a symlink' >&2; exit 2; fi",
        "mkdir -p \"$SCRATCH_BASE\"",
        "SCRATCH_BASE=$(cd -- \"$SCRATCH_BASE\" && pwd -P)",
        "SCRATCH_ROOT=\"$SCRATCH_BASE/case07-${ATTEMPT_ID}\"",
        "mkdir \"$SCRATCH_ROOT\" || { echo 'attempt scratch already exists' >&2; exit 2; }",
        "mkdir \"$SCRATCH_ROOT/.active-stage-lock\" || { echo 'another stage may be active; refusing overlap' >&2; exit 2; }",
        "trap 'rmdir \"$SCRATCH_ROOT/.active-stage-lock\" 2>/dev/null || true' EXIT",
        "export TMPDIR=\"$SCRATCH_ROOT\"",
        "mkdir -p \"$ROOT/raw\"",
        "run_stage() {",
        "  local id=$1 cap=$2 dir=\"$ROOT/stages/$1\" work now remaining rc",
        "  now=$(date +%s); remaining=$((DEADLINE-now))",
        "  if (( remaining <= 0 )); then echo \"HARD_STOP|$id|campaign_walltime_exhausted\" >&2; return 124; fi",
        "  if (( cap > remaining )); then cap=$remaining; fi",
        "  local stage_start=$(date +%s)",
        f"  local scratch_limit_kib=$(({MAX_SCRATCH_GIB} * 1024 * 1024))",
        "  local scratch_used_kib=$(du -sk \"$SCRATCH_ROOT\" | awk '{print $1}')",
        "  if (( scratch_used_kib > scratch_limit_kib )); then echo \"SCRATCH_USAGE_GUARD|$id|$scratch_used_kib\" >&2; return 125; fi",
        "  work=\"$SCRATCH_ROOT/$id\"; mkdir -p \"$work\"",
        "  cp \"$dir/start.xyz\" \"$work/start.xyz\"",
        "  cp \"$dir/job.inp\" \"$work/job.inp\"",
        "  (cd \"$work\" && timeout --signal=TERM --kill-after=30s \"${cap}s\" \"$ORCA_BIN\" job.inp >job.out 2>job.stderr) || rc=$?",
        "  rc=${rc:-0}",
        "  local stage_elapsed=$(( $(date +%s) - stage_start ))",
        "  mkdir -p \"$ROOT/raw/$id\"; cp -R \"$work/.\" \"$ROOT/raw/$id/\"",
        "  printf '%s\\n' \"$rc\" > \"$ROOT/raw/$id/exit-code.txt\"",
        "  printf '%s\\n' \"$stage_elapsed\" > \"$ROOT/raw/$id/elapsed-seconds.txt\"",
        "  scratch_used_kib=$(du -sk \"$SCRATCH_ROOT\" | awk '{print $1}')",
        "  if (( scratch_used_kib > scratch_limit_kib )); then echo \"SCRATCH_USAGE_GUARD|$id|$scratch_used_kib\" >&2; return 125; fi",
        "  printf '%s\\n' \"$ATTEMPT_ID|${SLURM_JOB_ID:-unknown}|$id|$rc|$stage_elapsed|$(date -u +%Y-%m-%dT%H:%M:%SZ)\" >> \"$ROOT/raw/stage-ledger.txt\"",
        "  if (( rc != 0 )); then echo \"STOP|$id|exit=$rc\" >&2; return \"$rc\"; fi",
        "  if (( $(date +%s) >= DEADLINE )); then echo 'HARD_STOP|campaign_walltime_exhausted' >&2; return 124; fi",
        "}",
    ]
    for stage_id in stage_ids:
        cap = PILOT_CAP_SECONDS if stage_id == "pilot_bpr" else SCREEN_CAP_SECONDS
        lines.append(f"run_stage {stage_id} {cap}")
    lines += [
        "echo 'SCREENING_STAGES_FINISHED; TS-stage progression is not implemented by this script'",
        "# No automatic retries, scheduler polling, remote RPC, or result fabrication.",
    ]
    return "\n".join(lines) + "\n"


def _stage_time(cap: int) -> str:
    return f"{cap // 3600:02d}:{(cap % 3600) // 60:02d}:{cap % 60:02d}"


def _single_stage_script(stage: str, attempt_id: str, stage_id: str | None = None) -> str:
    cap = STAGE_CAPS[stage]
    stage_id = stage_id or stage
    if not re.fullmatch(r"[a-z][a-z0-9_-]{0,63}", stage_id):
        raise ReferenceError("unsafe generated stage id")
    return "\n".join([
        "#!/usr/bin/env bash", f"#SBATCH --job-name=case07-{stage}", "#SBATCH --nodes=1",
        f"#SBATCH --ntasks={MAX_CORES}", "#SBATCH --cpus-per-task=1",
        f"#SBATCH --mem={MAX_MEMORY_GIB}G", f"#SBATCH --time={_stage_time(cap)}",
        "#SBATCH --no-requeue",
        "#SBATCH --export=ALL", "set -euo pipefail",
        "ROOT=$(cd -- \"$(dirname -- \"$0\")\" && pwd -P)",
        f"ATTEMPT_ID={attempt_id}", f"STAGE_ID={stage_id}", f"STAGE_CAP={cap}",
        "START_EPOCH=$(date +%s)", "DEADLINE=$((START_EPOCH + STAGE_CAP))",
        "ORCA_BIN=${ORCA_BIN:-orca}",
        "command -v \"$ORCA_BIN\" >/dev/null || { echo 'ORCA executable unavailable' >&2; exit 2; }",
        "SCRATCH_BASE=${CASE07_SCRATCH_ROOT:?operator must set an owned scratch directory}",
        "if [[ -L \"$SCRATCH_BASE\" ]]; then echo 'scratch root must not be a symlink' >&2; exit 2; fi",
        "mkdir -p \"$SCRATCH_BASE\"",
        "SCRATCH_BASE=$(cd -- \"$SCRATCH_BASE\" && pwd -P)",
        "SCRATCH_ROOT=\"$SCRATCH_BASE/case07-$ATTEMPT_ID\"",
        "mkdir -p \"$SCRATCH_ROOT\"",
        "mkdir \"$SCRATCH_ROOT/.active-stage-lock\" || { echo 'another stage may be active; refusing overlap' >&2; exit 2; }",
        "trap 'rmdir \"$SCRATCH_ROOT/.active-stage-lock\" 2>/dev/null || true' EXIT",
        f"WORK=\"$SCRATCH_ROOT/{stage}\"",
        "mkdir \"$WORK\" || { echo 'stage scratch already exists; retries are disabled' >&2; exit 2; }",
        "cp \"$ROOT/start.xyz\" \"$WORK/start.xyz\"; cp \"$ROOT/job.inp\" \"$WORK/job.inp\"",
        "mkdir -p \"$ROOT/raw\"",
        "du -sk \"$SCRATCH_ROOT\" > \"$ROOT/raw/scratch-before-kib.txt\"",
        "stage_start=$(date +%s); rc=0",
        "(cd \"$WORK\" && export TMPDIR=\"$WORK\" && timeout --signal=TERM --kill-after=30s \"${STAGE_CAP}s\" \"$ORCA_BIN\" job.inp >job.out 2>job.stderr) || rc=$?",
        "stage_elapsed=$(( $(date +%s) - stage_start ))",
        "mkdir -p \"$ROOT/raw/$STAGE_ID\"; cp -R \"$WORK/.\" \"$ROOT/raw/$STAGE_ID/\"",
        "printf '%s\\n' \"$rc\" > \"$ROOT/raw/$STAGE_ID/exit-code.txt\"",
        "printf '%s\\n' \"$stage_elapsed\" > \"$ROOT/raw/$STAGE_ID/elapsed-seconds.txt\"",
        "printf '%s\\n' \"$ATTEMPT_ID|${SLURM_JOB_ID:-unknown}|$STAGE_ID|$rc|$stage_elapsed|$(date -u +%Y-%m-%dT%H:%M:%SZ)\" >> \"$ROOT/raw/stage-ledger.txt\"",
        "du -sk \"$SCRATCH_ROOT\" > \"$ROOT/raw/scratch-after-kib.txt\"",
        f"scratch_kib=$(awk '{{print $1}}' \"$ROOT/raw/scratch-after-kib.txt\"); if (( scratch_kib > {MAX_SCRATCH_GIB}*1024*1024 )); then echo 'SCRATCH_USAGE_GUARD: observed usage exceeded 20GiB; this is not a filesystem quota' >&2; exit 125; fi",
        "if (( rc != 0 )); then echo \"STOP|$STAGE_ID|exit=$rc\" >&2; exit \"$rc\"; fi",
        "if (( $(date +%s) > DEADLINE )); then echo 'HARD_STOP|stage cap exceeded' >&2; exit 124; fi",
        "echo \"STAGE_FINISHED|$STAGE_ID|$stage_elapsed\"",
        "# Exactly one execution per generated stage; no automatic retries or network calls.",
    ]) + "\n"


def _load_json(path: Path) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise ReferenceError(f"JSON source is missing or unsafe: {path}")
    value = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=_unique_pairs,
                       parse_constant=lambda _: (_ for _ in ()).throw(ReferenceError("non-finite JSON")))
    if not isinstance(value, dict):
        raise ReferenceError("JSON root must be an object")
    return value


def _validate_geometry(value: Any) -> list[list[float]]:
    if not isinstance(value, list) or len(value) != 21:
        raise ReferenceError("source native fact must contain exactly 21 atom coordinates")
    result = []
    for row in value:
        if not isinstance(row, list) or len(row) != 3:
            raise ReferenceError("source native coordinate row must contain xyz")
        coords = [float(v) for v in row]
        if any(not math.isfinite(v) or abs(v) > 100 for v in coords):
            raise ReferenceError("source native coordinates must be finite and bounded")
        result.append(coords)
    return result


def _native_stage_record(value: dict[str, Any], expected_stage: str) -> tuple[str, list[list[float]], dict[str, Any]]:
    if (value.get("schema") != "case07-native-stage-reparse/v1"
            or value.get("status") != "REPARSED_ORCA_NATIVE_STAGE_FRESHNESS_NOT_AUTHENTICATED"
            or value.get("stage") != expected_stage
            or not isinstance(value.get("attempt_id"), str)
            or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{7,63}", value["attempt_id"])
            or not isinstance(value.get("output_sha256"), str)
            or not HEX64.fullmatch(value["output_sha256"])):
        raise ReferenceError(f"previous stage must be a reparsed {expected_stage} native-stage record")
    return value["attempt_id"], _validate_geometry(value.get("geometry_angstrom")), value


def advance(source_result: Path, output: Path, stage: str,
            decision_path: Path | None = None,
            final_profile: str = "r2scan-3c") -> dict[str, Any]:
    if final_profile not in FINAL_LEVEL_PROFILES:
        raise ReferenceError("final method profile is not in the frozen Case07 profile registry")
    if output.exists() or output.is_symlink():
        raise ReferenceError("advance output must be a new directory")
    source = _load_json(source_result)
    attempt_id: str
    channel: str | None = None
    geometry: list[list[float]]
    decision: dict[str, Any] = {}
    upstream_hash = sha256(source_result)
    if stage == "screen_refinement":
        if source.get("schema") != "case07-screening-reparse/v1":
            raise ReferenceError("screen refinement must consume reparsed pilot/screen evidence")
        channel = source.get("selected_channel_by_frozen_rule")
        if channel not in {"C1", "C2"}:
            raise ReferenceError("screen result has no derived selected channel")
        if decision_path is None:
            raise ReferenceError("screen refinement requires an explicit scientific decision JSON")
        decision = _load_json(decision_path)
        if (decision.get("schema") != "case07-screen-refinement-decision/v1"
                or decision.get("selected_channel") != channel
                or not isinstance(decision.get("rationale"), str) or not decision["rationale"].strip()):
            raise ReferenceError("screen-refinement decision schema/channel/rationale is invalid")
        constraints = decision.get("constraints")
        if not isinstance(constraints, list) or len(constraints) != 4:
            raise ReferenceError("screen-refinement decision needs four typed constraints")
        pairs = []
        for row in constraints:
            if not isinstance(row, dict) or set(row) != {"atoms", "distance_angstrom"}:
                raise ReferenceError("screen-refinement constraint has unsupported fields")
            pair, distance = row["atoms"], row["distance_angstrom"]
            if (not isinstance(pair, list) or len(pair) != 2 or any(type(i) is not int or not 0 <= i < 21 for i in pair)
                    or pair[0] == pair[1] or isinstance(distance, bool)
                    or not isinstance(distance, (int, float)) or not math.isfinite(distance)
                    or not 0.5 <= distance <= 5.0):
                raise ReferenceError("screen-refinement constraint is invalid")
            pairs.append(tuple(sorted(pair)))
        if len(set(pairs)) != 4 or set(pairs) != {tuple(sorted(pair)) for pair in CHANNEL_BONDS[channel]}:
            raise ReferenceError("screen-refinement constraints do not match the selected channel's fixed bonds")
        rows = [row for row in source.get("stage_facts", []) if row.get("channel") == channel]
        if len(rows) != 3 or any(not isinstance(row.get("energy_au"), (int, float)) for row in rows):
            raise ReferenceError("screening result lacks three parsed energies for selected channel")
        selected_point = max(rows, key=lambda row: float(row["energy_au"]))
        geometry = _validate_geometry(selected_point.get("geometry_angstrom"))
        attempt_id = source.get("attempt_id")
        if not isinstance(attempt_id, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{7,63}", attempt_id):
            raise ReferenceError("screening result does not preserve a valid original attempt id")
        stage_input = _orca_input(stage, constraints=constraints)
    else:
        if stage == "endpoint_opt" and source.get("schema") == "case07-mode-displacements/v1":
            attempt_id = source.get("attempt_id")
            channel = source.get("selected_channel")
            if (not isinstance(attempt_id, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{7,63}", attempt_id)
                    or channel not in {"C1", "C2"}):
                raise ReferenceError("mode-displacement result lacks attempt/channel binding")
            signs = source.get("signs")
            if not isinstance(signs, list) or {row.get("sign") for row in signs if isinstance(row, dict)} != {-1, 1}:
                raise ReferenceError("both signed mode-displacement seeds are required")
            if decision_path is not None:
                raise ReferenceError("endpoint optimization takes its geometry from signed mode evidence")
            output.mkdir(parents=True, exist_ok=False)
            stage_rows = []
            for row in sorted(signs, key=lambda item: item["sign"]):
                sign = row["sign"]
                side = "minus" if sign == -1 else "plus"
                coords = _validate_geometry(row.get("geometry_angstrom"))
                side_root = output / side
                side_root.mkdir()
                _write(side_root / "start.xyz", _xyz(coords, f"{attempt_id}; endpoint seed {side}; prepared, not run"))
                _write(side_root / "job.inp", _orca_input("endpoint_opt", final_profile=final_profile))
                _write(side_root / "submit-stage.sbatch", _single_stage_script(
                    "endpoint_opt", attempt_id, f"endpoint_opt_{side}"))
                os.chmod(side_root / "submit-stage.sbatch", 0o755)
                stage_rows.append({"stage_id": f"endpoint_opt_{side}", "sign": sign,
                                   "input_sha256": sha256(side_root / "job.inp"),
                                   "geometry_sha256": sha256(side_root / "start.xyz"),
                                   "slurm_script_sha256": sha256(side_root / "submit-stage.sbatch")})
            result = {"schema": "case07-advance-preparation/v1", "case_id": CASE_ID,
                      "definition_revision": REVISION, "attempt_id": attempt_id,
                      "stage": "endpoint_opt", "channel": channel,
                      "status": "PREPARED_ONLY_NOT_RUN", "source_result_sha256": upstream_hash,
                      "target_final_profile": final_profile,
                      "target_final_level": FINAL_LEVEL_PROFILES[final_profile]["level"],
                      "stages": stage_rows,
                      "attempt_planned_stage_cap_seconds": MAX_PLANNED_STAGE_SECONDS,
                      "attempt_wall_cap_seconds": MAX_ACTIVE_SECONDS,
                      "scope": "Both signed-mode endpoint optimizations prepared; neither was run."}
            _write(output / "advance-preparation.json", json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n")
            return result
        previous_stage = {"optts": "screen_refinement", "ts_frequency": "optts",
                          "mode_displacement": "ts_frequency", "endpoint_opt": "mode_displacement",
                          "endpoint_frequency": "endpoint_opt"}.get(stage)
        if previous_stage is None:
            raise ReferenceError(f"unsupported advance stage: {stage}")
        attempt_id, geometry, source = _native_stage_record(source, previous_stage)
        channel = source.get("selected_channel")
        if channel not in {"C1", "C2"}:
            raise ReferenceError("native-stage result lacks the selected channel")
        if stage == "optts":
            if decision_path is None:
                raise ReferenceError("OptTS requires an explicit mode-bond/active-atom decision JSON")
            decision = _load_json(decision_path)
            if (decision.get("schema") != "case07-optts-decision/v1"
                    or decision.get("selected_channel") != channel
                    or not isinstance(decision.get("rationale"), str) or not decision["rationale"].strip()):
                raise ReferenceError("OptTS decision schema/channel/rationale is invalid")
            selected_bond = decision.get("ts_mode_bond")
            if (not isinstance(selected_bond, list) or len(selected_bond) != 2
                    or any(type(i) is not int for i in selected_bond)
                    or tuple(sorted(selected_bond)) not in {tuple(sorted(pair)) for pair in CHANNEL_BONDS[channel]}):
                raise ReferenceError("OptTS mode bond is outside the selected channel's explicit bond set")
            stage_input = _orca_input(stage, ts_mode_bond=selected_bond,
                                      ts_active_atoms=decision.get("ts_active_atoms"),
                                      final_profile=final_profile)
        elif stage == "mode_displacement":
            hessian = source.get("hessian")
            if not isinstance(hessian, dict) or hessian.get("schema") != "case07-native-hessian-facts/v1":
                raise ReferenceError("mode displacement requires parsed native Hessian facts")
            hess_sha = hessian.get("sha256")
            physical = hessian.get("physical_imaginary_indices")
            frequencies = hessian.get("frequencies_cm-1")
            modes = hessian.get("modes")
            hcoords = _validate_geometry(hessian.get("coordinates_angstrom"))
            if (not isinstance(hess_sha, str) or not HEX64.fullmatch(hess_sha)
                    or not isinstance(physical, list) or len(physical) != 1
                    or type(physical[0]) is not int or not 6 <= physical[0] < 63
                    or not isinstance(frequencies, list) or len(frequencies) != 63
                    or not isinstance(modes, list) or len(modes) != 63
                    or any(not isinstance(row, list) or len(row) != 63 for row in modes)
                    or any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) for v in frequencies)
                    or any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v)
                           for row in modes if isinstance(row, list) for v in row)):
                raise ReferenceError("native Hessian facts fail the frozen 63-mode/one-imaginary schema")
            mode_index = physical[0]
            if ([i for i in range(6, 63) if frequencies[i] < 0] != physical
                    or frequencies[mode_index] >= 0):
                raise ReferenceError("physical imaginary mode index does not refer to a negative frequency")
            mode = [float(modes[3*i+k][mode_index]) for i in range(21) for k in range(3)]
            if any(not math.isfinite(v) for v in mode):
                raise ReferenceError("native imaginary mode contains non-finite coordinates")
            maxnorm = max(math.sqrt(sum(mode[3*i+k]**2 for k in range(3))) for i in range(21))
            if not math.isfinite(maxnorm) or maxnorm <= 0:
                raise ReferenceError("native imaginary mode has zero Cartesian amplitude")
            output.mkdir(parents=True, exist_ok=False)
            displacements = []
            for sign, label in ((-1, "minus"), (1, "plus")):
                coords = [[hcoords[i][k] + sign*MODE_DISPLACEMENT_ANGSTROM*mode[3*i+k]/maxnorm
                           for k in range(3)] for i in range(21)]
                rel = f"seed_{label}.xyz"
                _write(output / rel, _xyz(coords, f"{attempt_id}; mode {mode_index}; sign {sign}; prepared, not run"))
                displacements.append({"sign": sign, "geometry_path": rel,
                                      "geometry_sha256": sha256(output / rel),
                                      "geometry_angstrom": coords})
            result = {"schema": "case07-mode-displacements/v1", "attempt_id": attempt_id,
                      "selected_channel": channel,
                      "stage": "mode_displacement",
                      "status": "PREPARED_ONLY_NOT_RUN", "source_ts_frequency_result_sha256": upstream_hash,
                      "source_hessian_sha256": hess_sha, "mode_index": mode_index,
                      "frequency_cm-1": frequencies[mode_index],
                      "amplitude_angstrom": MODE_DISPLACEMENT_ANGSTROM,
                      "normalization": "max_atom_cartesian", "signs": displacements,
                      "scope": "Deterministic signed displacement of the parsed imaginary vector; no chemistry job was run."}
            _write(output / "mode-displacements.json", json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n")
            return result
        else:
            stage_input = _orca_input(stage, final_profile=final_profile)
    if decision_path is not None and stage != "screen_refinement" and stage != "optts":
        raise ReferenceError("this stage does not accept a decision file")
    output.mkdir(parents=True, exist_ok=False)
    _write(output / "start.xyz", _xyz(geometry, f"{attempt_id}; source-bound {stage} geometry; charge 0 multiplicity 2"))
    _write(output / "job.inp", stage_input)
    script_path = output / "submit-stage.sbatch"
    _write(script_path, _single_stage_script(stage, attempt_id))
    os.chmod(script_path, 0o755)
    record = {"schema": "case07-advance-preparation/v1", "case_id": CASE_ID,
              "definition_revision": REVISION, "resource_profile": RESOURCE_PROFILE,
              "status": "PREPARED_ONLY_NOT_RUN", "attempt_id": attempt_id,
              "stage": stage, "channel": channel, "stage_time_cap_seconds": STAGE_CAPS[stage],
              "attempt_planned_stage_cap_seconds": MAX_PLANNED_STAGE_SECONDS,
              "attempt_wall_cap_seconds": MAX_ACTIVE_SECONDS,
              "source_result_sha256": upstream_hash,
              "target_final_profile": final_profile,
              "target_final_level": FINAL_LEVEL_PROFILES[final_profile]["level"],
              "decision_sha256": sha256(decision_path) if decision_path else None,
              "endpoint_side": source.get("endpoint_side"),
              "job_input_sha256": sha256(output / "job.inp"),
              "start_geometry_sha256": sha256(output / "start.xyz"),
              "slurm_script_sha256": sha256(script_path),
              "decision": decision,
              "engine_status": "ORCA 6.0.1 historical/planned; runtime not verified",
              "scratch_enforcement": "20 GiB observed usage guard only; target quota unverified",
              "scope": "Input/stage prepared only; no ORCA, sbatch, SSH, network, or scientific execution."}
    _write(output / "advance-preparation.json", json.dumps(record, indent=2, sort_keys=True, allow_nan=False) + "\n")
    return record


def prepare(assets: Path, output: Path, attempt_id: str | None = None, *,
            pilot_profile: str = "legacy-pbe-screen", pilot_action: str = "SP") -> dict[str, Any]:
    assets = _safe_root(assets)
    if pilot_profile not in PILOT_PROFILES or pilot_action not in {"SP", "EnGrad"}:
        raise ReferenceError("pilot method/action is outside the frozen Case07 pilot profiles")
    if output.exists() or output.is_symlink():
        raise ReferenceError(f"output must be a new non-symlink directory: {output}")
    try:
        geometries = geom.load_public_geometries(assets)
    except ValueError as exc:
        raise ReferenceError(str(exc)) from exc
    attempt_id = attempt_id or uuid.uuid4().hex
    if not isinstance(attempt_id, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{7,63}", attempt_id):
        raise ReferenceError("attempt id must be a unique safe 8-64 character token")
    stage_specs: list[tuple[str, str, str | None, float | None, list[list[float]], int]] = []
    stage_specs.append(("pilot_bpr", "pilot_sp", None, None,
                        geometries["bpr"]["coordinates"], PILOT_CAP_SECONDS))
    for channel in ("C1", "C2"):
        for index, lam in enumerate(geom.SCREEN_LAMBDAS, start=1):
            coords = geom.screen_geometry(geometries["bpr"]["coordinates"],
                                          geometries[channel]["coordinates"], lam)
            stage_specs.append((f"screen_{channel.lower()}_p{index}",
                                "screen_energy_gradient", channel, lam, coords,
                                SCREEN_CAP_SECONDS))
    output.mkdir(parents=True, exist_ok=False)
    files: dict[str, str] = {}
    stages = []
    for stage_id, stage, channel, lam, coords, cap in stage_specs:
        rel = Path("stages") / stage_id
        xyz_path, inp_path = output / rel / "start.xyz", output / rel / "job.inp"
        _write(xyz_path, _xyz(coords, f"{stage_id}; public geometry; charge 0 multiplicity 2"))
        _write(inp_path, _orca_input(stage, pilot_profile=pilot_profile, pilot_action=pilot_action))
        rel_xyz, rel_inp = xyz_path.relative_to(output).as_posix(), inp_path.relative_to(output).as_posix()
        files[rel_xyz] = sha256(xyz_path)
        files[rel_inp] = sha256(inp_path)
        stages.append({"stage_id": stage_id, "stage": stage, "channel": channel,
                       "lambda": lam, "max_seconds": cap,
                       "geometry_path": rel_xyz, "input_path": rel_inp,
                       "expected_elements": list(geom.ATOM_ORDER)})
    script_path = output / "submit-case07-screening.sbatch"
    stage_ids = [item[0] for item in stage_specs]
    _write(script_path, _slurm_script(stage_ids, attempt_id))
    os.chmod(script_path, 0o755)
    files[script_path.relative_to(output).as_posix()] = sha256(script_path)
    record = {
        "schema": "case07-reference-preparation/v1", "case_id": CASE_ID,
        "definition_revision": REVISION, "resource_profile": RESOURCE_PROFILE,
        "attempt_id": attempt_id,
        "status": "PREPARED_ONLY_NOT_RUN",
        "created_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "engine": "ORCA 6.0.1 (planned; not locally verified)",
        "method": "UKS PBE D3BJ def2-SVP DefGrid3 for pilot and six EnGrad screens",
        "pilot_profile": pilot_profile, "pilot_action": pilot_action,
        "charge": 0, "multiplicity": 2, "atom_count": 21,
        "caps": {"active_wall_seconds": MAX_ACTIVE_SECONDS, "cores": MAX_CORES,
                 "memory_gib": MAX_MEMORY_GIB, "scratch_gib_observed_usage_guard": MAX_SCRATCH_GIB,
                 "scratch_guard_enforcement": "observed du usage check after each stage; not a hard filesystem quota",
                 "automatic_retries": False},
        "source_bindings": {
            "public_geometry_sha256": geom.EXPECTED_SHA256,
            "reference_campaign_source_sha256": "5ce15f16265bb2cd4e5add04d9b52d3823f9982befe86c9b3a21c67d6334aef2",
            "source_functions": ["SOURCE_INDEX", "SCREEN_LAMBDAS", "RETAINED_BONDS",
                                 "_align_quaternion", "_load_public_geometries",
                                 "_screen_geometry", "_typed_geometry"],
            "orca_renderer_source_sha256": "429a570934eb0c570900070dccd411cea54b1c85043b9cad8c65442138d5b1c9",
            "renderer_function": "typed_request.render_orca_input",
        "native_parser_source_sha256": sha256(Path(__file__).with_name("native_parser.py")),
            "parser_functions": ["parse_xyz", "parse_engrad", "stage_facts", "_output_energy"]
        },
        "public_assets": dict(PUBLIC_ASSET_HASHES),
        "stages": stages,
        "command_boundary": {"prepare": "python3 current_reference.py --prepare --assets assets --output <new-directory>",
                             "submit_after_review": "cd <prepared-directory> && sbatch submit-case07-screening.sbatch",
                             "required_operator_env": "CASE07_SCRATCH_ROOT=<owned non-symlink writable scratch directory>",
                             "submit_is_not_called_by_prepare": True,
                             "network_calls": False, "scheduler_calls": False},
        "explicit_limits": ["This prepares only pilot and six screen jobs.",
                            "20 GiB scratch is only an observed usage guard, not a hard quota; target-site scratch path/quota support is unverified.",
                            "No TS, frequency, signed-mode, IRC, endpoint, barrier, or final-contract generator is implemented here.",
                            "Screen results must be reparsed from fresh native files before any decision.",
                            "Historical files cannot be used to populate current screening output."],
        "prepared_file_sha256": dict(sorted(files.items())),
    }
    manifest = output / "preparation.json"
    _write(manifest, json.dumps(record, indent=2, sort_keys=True, allow_nan=False) + "\n")
    return record


def _relative_file(root: Path, raw: Any) -> Path:
    if not isinstance(raw, str) or not raw or "\\" in raw:
        raise ReferenceError("bundle file path is not canonical relative POSIX text")
    pure = PurePosixPath(raw)
    if pure.is_absolute() or pure.as_posix() != raw or any(p in {"", ".", ".."} for p in pure.parts):
        raise ReferenceError("bundle file path is absolute or traverses its root")
    if any(part.lower() in {"archive", "historical", "prepared_jobs", "prior_recovery_package"}
           for part in pure.parts):
        raise ReferenceError("archive-marked paths cannot be current native evidence")
    path = root.joinpath(*pure.parts)
    current = root
    for part in pure.parts:
        current = current / part
        if current.is_symlink():
            raise ReferenceError("symlink components are not allowed in native bundle")
    if not path.is_file():
        raise ReferenceError("bundle entry is not a regular file")
    return path


def _parse_engrad(path: Path) -> dict[str, Any]:
    """Small source-bound ORCA EnGrad parser copied from native_parser.parse_engrad."""
    lines = path.read_text(encoding="utf-8", errors="strict").splitlines()
    def section(marker: str) -> list[str]:
        hits = [i for i, line in enumerate(lines) if line.strip() == marker]
        if len(hits) != 1:
            raise ReferenceError(f"EnGrad must contain exactly one {marker} section")
        values: list[str] = []
        for line in lines[hits[0]+1:]:
            stripped = line.strip()
            if stripped.startswith("#"):
                if values:
                    break
                continue
            if stripped:
                values.extend(stripped.split())
        return values
    if section("# Number of atoms") != ["21"]:
        raise ReferenceError("EnGrad must describe 21 atoms")
    energy_fields = section("# The current total energy in Eh")
    gradient_fields = section("# The current gradient in Eh/bohr")
    atom_fields = section("# The atomic numbers and current coordinates in Bohr")
    if len(energy_fields) != 1 or len(gradient_fields) != 63 or len(atom_fields) != 84:
        raise ReferenceError("EnGrad energy, gradient, or coordinate block is malformed")
    energy = float(energy_fields[0])
    gradient = [float(value) for value in gradient_fields]
    atomic_numbers = [6]*6 + [1]*4 + [8]*4 + [1, 8, 6] + [1]*4
    coords_bohr: list[float] = []
    for index in range(21):
        if int(atom_fields[4*index]) != atomic_numbers[index]:
            raise ReferenceError("EnGrad atomic ordering differs from frozen atom map")
        coords_bohr.extend(float(value) for value in atom_fields[4*index+1:4*index+4])
    values = [energy, *gradient, *coords_bohr]
    if any(not math.isfinite(value) for value in values):
        raise ReferenceError("EnGrad contains non-finite values")
    coords = [[coords_bohr[3*i+k]*0.529177210903 for k in range(3)] for i in range(21)]
    return {"energy_au": energy, "gradient_eh_per_bohr": gradient, "geometry_angstrom": coords}


def _parse_orca_energy(path: Path) -> tuple[float, str]:
    text = path.read_text(encoding="utf-8", errors="strict")
    if "ORCA TERMINATED NORMALLY" not in text:
        raise ReferenceError("native ORCA output lacks normal termination")
    if not re.search(r"SCF CONVERGED AFTER\s+\d+\s+CYCLES", text):
        raise ReferenceError("native ORCA output lacks successful SCF marker")
    matches = re.findall(r"FINAL SINGLE POINT ENERGY\s+([-+0-9.Ee]+)", text)
    if not matches:
        raise ReferenceError("native ORCA output has no final energy")
    energy = float(matches[-1])
    if not math.isfinite(energy):
        raise ReferenceError("native ORCA energy is non-finite")
    return energy, text


def _unique_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ReferenceError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def ingest(bundle: Path, output: Path, assets: Path) -> dict[str, Any]:
    root = _safe_root(bundle)
    assets = _safe_root(assets)
    for relative, expected_hash in PUBLIC_ASSET_HASHES.items():
        if sha256(assets / relative) != expected_hash:
            raise ReferenceError(f"current public input hash mismatch: {relative}")
    public_geometries = geom.load_public_geometries(assets)
    if output.exists() or output.is_symlink():
        raise ReferenceError("ingest output must be a new directory")
    manifest_path = _relative_file(root, "manifest.json")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"),
                          object_pairs_hook=_unique_pairs,
                          parse_constant=lambda x: (_ for _ in ()).throw(ReferenceError("non-finite JSON")))
    required = {"schema", "case_id", "definition_revision", "resource_profile", "attempt_id",
                "authorization_ref", "started_at_utc", "reported_at_utc", "public_input_sha256",
                "preparation_manifest_sha256", "files_sha256", "decision_records_path", "stages"}
    if not isinstance(manifest, dict) or set(manifest) != required:
        raise ReferenceError("fresh bundle manifest fields do not match schema")
    if (manifest["schema"] != "case07-fresh-reference-bundle/v1" or manifest["case_id"] != CASE_ID
            or manifest["definition_revision"] != REVISION or manifest["resource_profile"] != RESOURCE_PROFILE):
        raise ReferenceError("bundle identity or revision is stale/unsupported")
    if (not isinstance(manifest["attempt_id"], str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{7,63}", manifest["attempt_id"])
            or not isinstance(manifest["authorization_ref"], str) or not manifest["authorization_ref"].strip()):
        raise ReferenceError("attempt id or authorization reference is malformed")
    preparation_path = _relative_file(root, "preparation.json")
    preparation_hash = sha256(preparation_path)
    if manifest["preparation_manifest_sha256"] != preparation_hash:
        raise ReferenceError("bundle does not bind the exact local preparation manifest")
    preparation = json.loads(preparation_path.read_text(encoding="utf-8"),
                             object_pairs_hook=_unique_pairs,
                             parse_constant=lambda _: (_ for _ in ()).throw(ReferenceError("non-finite preparation JSON")))
    if (preparation.get("schema") != "case07-reference-preparation/v1"
            or preparation.get("case_id") != CASE_ID
            or preparation.get("definition_revision") != REVISION
            or preparation.get("attempt_id") != manifest["attempt_id"]):
        raise ReferenceError("bundle attempt does not match the bound preparation manifest")
    if not isinstance(manifest["public_input_sha256"], dict) or manifest["public_input_sha256"] != PUBLIC_ASSET_HASHES:
        raise ReferenceError("bundle public input pins differ from current case inputs")
    parsed_times = []
    for timestamp in (manifest["started_at_utc"], manifest["reported_at_utc"]):
        if not isinstance(timestamp, str) or not timestamp.endswith("Z"):
            raise ReferenceError("bundle timestamps must be explicit UTC ISO-8601")
        parsed_times.append(datetime.fromisoformat(timestamp[:-1] + "+00:00"))
    if parsed_times[1] < parsed_times[0] or (parsed_times[1] - parsed_times[0]).total_seconds() > MAX_ACTIVE_SECONDS:
        raise ReferenceError("bundle report time violates the original eight-hour attempt window")
    if not isinstance(manifest["files_sha256"], dict) or not manifest["files_sha256"]:
        raise ReferenceError("bundle raw-file hash map is missing")
    actual_files: dict[str, str] = {}
    for rel, expected in manifest["files_sha256"].items():
        if not isinstance(expected, str) or not HEX64.fullmatch(expected):
            raise ReferenceError("bundle contains malformed file digest")
        path = _relative_file(root, rel)
        actual_files[rel] = sha256(path)
        if actual_files[rel] != expected:
            raise ReferenceError(f"bundle digest mismatch: {rel}")
    listed = set(actual_files)
    decision_path = manifest["decision_records_path"]
    if decision_path not in listed:
        raise ReferenceError("decision record is not hash-bound by bundle manifest")
    all_paths = list(root.rglob("*"))
    if any(path.is_symlink() for path in all_paths):
        raise ReferenceError("bundle contains a symlink, including an unlisted path")
    actual_bundle_files = {p.relative_to(root).as_posix() for p in all_paths
                           if p.is_file() and p.relative_to(root).as_posix() != "manifest.json"}
    if listed != actual_bundle_files:
        raise ReferenceError("bundle has unlisted files or omitted raw files")
    prep_hashes = preparation.get("prepared_file_sha256")
    if not isinstance(prep_hashes, dict):
        raise ReferenceError("preparation manifest lacks its generated-file digest map")
    for rel, expected_hash in prep_hashes.items():
        if rel not in listed or actual_files.get(rel) != expected_hash:
            raise ReferenceError(f"prepared input/script hash differs from its preparation record: {rel}")
    decisions = json.loads(_relative_file(root, decision_path).read_text(encoding="utf-8"),
                           object_pairs_hook=_unique_pairs,
                           parse_constant=lambda _: (_ for _ in ()).throw(ReferenceError("non-finite decision JSON")))
    expected_ids = ["pilot_bpr", "screen_c1_p1", "screen_c1_p2", "screen_c1_p3",
                    "screen_c2_p1", "screen_c2_p2", "screen_c2_p3"]
    if (not isinstance(decisions, dict)
            or decisions.get("schema") != "case07-screening-observation-plan/v1"
            or decisions.get("planned_stage_ids") != expected_ids):
        raise ReferenceError("decision record schema or planned stage identities are invalid")
    forbidden = {"ts_search_report.json", "barriers.csv", "reward.json", "reward.txt", "solution.json"}
    if any(PurePosixPath(rel).name.lower() in forbidden for rel in listed):
        raise ReferenceError("bundle contains a generated final contract/reward instead of native evidence")
    stages = manifest["stages"]
    if not isinstance(stages, list) or len(stages) != 7:
        raise ReferenceError("bundle must contain one pilot and six fresh screens")
    expected = {"pilot_bpr": ("pilot_sp", None, None)}
    for channel in ("C1", "C2"):
        for index, lam in enumerate(geom.SCREEN_LAMBDAS, 1):
            expected[f"screen_{channel.lower()}_p{index}"] = ("screen_energy_gradient", channel, lam)
    seen: set[str] = set()
    facts = []
    for stage in stages:
        if not isinstance(stage, dict) or set(stage) != {"stage_id", "stage", "channel", "lambda", "status", "exit_code", "elapsed_seconds", "files"}:
            raise ReferenceError("native stage record has unsupported fields")
        stage_id = stage["stage_id"]
        if stage_id not in expected or stage_id in seen or (stage["stage"], stage["channel"], stage["lambda"]) != expected[stage_id]:
            raise ReferenceError("native stage identity/geometry point is unexpected or duplicate")
        seen.add(stage_id)
        if stage["status"] != "COMPLETED" or type(stage["exit_code"]) is not int or stage["exit_code"] != 0:
            raise ReferenceError(f"native stage did not complete successfully: {stage_id}")
        cap = PILOT_CAP_SECONDS if stage["stage"] == "pilot_sp" else SCREEN_CAP_SECONDS
        elapsed = stage["elapsed_seconds"]
        if isinstance(elapsed, bool) or not isinstance(elapsed, (int, float)) or not math.isfinite(elapsed) or not 0 < elapsed <= cap:
            raise ReferenceError(f"native stage elapsed time is invalid or exceeds cap: {stage_id}")
        required_files = {"input", "geometry", "output", "stderr", "exit_code", "elapsed_seconds"}
        if stage["stage"] == "screen_energy_gradient":
            required_files.add("engrad")
        pilot_profile = preparation.get("pilot_profile", "legacy-pbe-screen")
        pilot_action = preparation.get("pilot_action", "SP")
        if stage_id == "pilot_bpr" and pilot_action == "EnGrad":
            required_files.add("engrad")
        if not isinstance(stage["files"], dict) or set(stage["files"]) != required_files:
            raise ReferenceError(f"native file set is incomplete for {stage_id}")
        paths = {key: _relative_file(root, value) for key, value in stage["files"].items()}
        prep_stage = next((item for item in preparation.get("stages", [])
                           if isinstance(item, dict) and item.get("stage_id") == stage_id), None)
        if prep_stage is None:
            raise ReferenceError("stage is absent from bound preparation manifest")
        if (sha256(paths["input"]) != prep_hashes.get(prep_stage.get("input_path"))
                or sha256(paths["geometry"]) != prep_hashes.get(prep_stage.get("geometry_path"))):
            raise ReferenceError("native stage input/geometry does not match the prepared attempt")
        if any(value not in listed for value in stage["files"].values()):
            raise ReferenceError("stage file is not hash-bound in manifest")
        if paths["exit_code"].read_text(encoding="ascii").strip() != "0":
            raise ReferenceError("raw exit-code file disagrees with successful stage record")
        try:
            raw_elapsed = float(paths["elapsed_seconds"].read_text(encoding="ascii").strip())
        except ValueError as exc:
            raise ReferenceError("raw elapsed-seconds file is malformed") from exc
        if not math.isfinite(raw_elapsed) or abs(raw_elapsed - elapsed) > 1e-6:
            raise ReferenceError("raw elapsed-seconds file disagrees with stage record")
        input_text = paths["input"].read_text(encoding="utf-8")
        expected_input = (_orca_input("pilot_sp", pilot_profile=pilot_profile, pilot_action=pilot_action)
                          if stage_id == "pilot_bpr" else _orca_input("screen_energy_gradient"))
        if input_text != expected_input:
            raise ReferenceError("native input differs from frozen preparation template")
        elements, coordinates = parse_xyz(paths["geometry"])
        if elements != list(geom.ATOM_ORDER):
            raise ReferenceError("native start geometry breaks atom mapping")
        if stage_id == "pilot_bpr":
            expected_coordinates = public_geometries["bpr"]["coordinates"]
        else:
            expected_coordinates = geom.screen_geometry(public_geometries["bpr"]["coordinates"],
                                                         public_geometries[stage["channel"]]["coordinates"],
                                                         stage["lambda"])
        if max(math.dist(a, b) for a, b in zip(coordinates, expected_coordinates)) > 5.1e-10:
            raise ReferenceError("native geometry differs from pinned public mapping/interpolation")
        energy, out_text = _parse_orca_energy(paths["output"])
        if stage["stage"] == "pilot_sp":
            pilot_fact = {"stage_id": stage_id, "stage": stage["stage"], "energy_au": energy,
                          "elapsed_seconds": elapsed, "scf_converged": True,
                          "geometry_angstrom": coordinates,
                          "geometry_sha256": sha256(paths["geometry"]),
                          "input_sha256": sha256(paths["input"]), "output_sha256": sha256(paths["output"]),
                          "action": pilot_action,
                          "method_profile": pilot_profile,
                          "status": "PARSED_ORCA_NATIVE_FORMAT_FRESHNESS_NOT_AUTHENTICATED"}
            if pilot_action == "EnGrad":
                parsed = _parse_engrad(paths["engrad"])
                if abs(parsed["energy_au"] - energy) > 1e-7:
                    raise ReferenceError("pilot EnGrad energy differs from output energy")
                if max(math.dist(a, b) for a, b in zip(parsed["geometry_angstrom"], coordinates)) > 1e-5:
                    raise ReferenceError("pilot EnGrad coordinates differ from bound start geometry")
                pilot_fact["gradient_component_count"] = len(parsed["gradient_eh_per_bohr"])
                pilot_fact["gradient_eh_per_bohr"] = parsed["gradient_eh_per_bohr"]
                pilot_fact["engrad_sha256"] = sha256(paths["engrad"])
            facts.append(pilot_fact)
            continue
        parsed = _parse_engrad(paths["engrad"])
        if abs(parsed["energy_au"] - energy) > 1e-7:
            raise ReferenceError("native EnGrad energy differs from output energy")
        if max(math.dist(a, b) for a, b in zip(parsed["geometry_angstrom"], coordinates)) > 1e-5:
            raise ReferenceError("native EnGrad coordinates differ from bound start geometry")
        facts.append({"stage_id": stage_id, "stage": stage["stage"], "channel": stage["channel"],
                      "lambda": stage["lambda"], "energy_au": energy,
                      "elapsed_seconds": elapsed, "scf_converged": True,
                      "geometry_angstrom": parsed["geometry_angstrom"],
                      "gradient_component_count": len(parsed["gradient_eh_per_bohr"]),
                      "gradient_eh_per_bohr": parsed["gradient_eh_per_bohr"],
                      "gradient_norm_eh_per_bohr": math.sqrt(sum(x*x for x in parsed["gradient_eh_per_bohr"])),
                      "geometry_sha256": sha256(paths["geometry"]),
                      "input_sha256": sha256(paths["input"]), "output_sha256": sha256(paths["output"]),
                      "engrad_sha256": sha256(paths["engrad"]),
                      "status": "PARSED_ORCA_NATIVE_FORMAT_FRESHNESS_NOT_AUTHENTICATED"})
    if seen != set(expected):
        raise ReferenceError("bundle omits one or more required fresh pilot/screen stages")
    maxima = {ch: max(row["energy_au"] for row in facts if row.get("channel") == ch)
              for ch in ("C1", "C2")}
    chosen = min(("C1", "C2"), key=lambda ch: (maxima[ch], ch))
    result = {"schema": "case07-screening-reparse/v1", "case_id": CASE_ID,
              "definition_revision": REVISION, "attempt_id": manifest["attempt_id"],
              "bundle_manifest_sha256": sha256(manifest_path),
              "status": "SCREENING_FILES_PARSED__FRESHNESS_NOT_AUTHENTICATED__LATER_STAGES_PENDING",
              "scope": "Pilot and six screening records parsed as ORCA-native-format files; this program does not authenticate their execution time/provenance. No TS, frequency, mode/IRC, endpoint, barrier or full output contract is generated.",
              "stage_facts": facts, "sampled_max_energies_au": maxima,
              "selected_channel_by_frozen_rule": chosen,
              "selection_rule": "lower maximum of three fresh PBE EnGrad energies",
              "all_current_values_derived_from_native": True,
              "not_claimed": ["authenticated fresh execution", "fresh TS", "frequency", "connected endpoints",
                              "barrier", "full candidate contract", "Oracle PASS"]}
    output.mkdir(parents=True, exist_ok=False)
    (output / "screening-reparse.json").write_text(json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    return result


FINALIZE_STAGE_FILES = {
    "screen_refinement": {"input", "geometry", "output", "stderr", "exit_code", "elapsed_seconds"},
    "optts": {"input", "geometry", "output", "stderr", "exit_code", "elapsed_seconds"},
    "ts_frequency": {"input", "geometry", "output", "stderr", "exit_code", "elapsed_seconds", "hessian"},
    "endpoint_opt_minus": {"input", "geometry", "output", "stderr", "exit_code", "elapsed_seconds"},
    "endpoint_opt_plus": {"input", "geometry", "output", "stderr", "exit_code", "elapsed_seconds"},
    "endpoint_freq_minus": {"input", "geometry", "output", "stderr", "exit_code", "elapsed_seconds", "hessian"},
    "endpoint_freq_plus": {"input", "geometry", "output", "stderr", "exit_code", "elapsed_seconds", "hessian"},
}
FINALIZE_REQUIRED_FILES = {
    "decision_records.json",
}


def _execution_stage_specs(report: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Mirror the public report-to-stage bindings required by candidate_execution."""
    result: dict[str, dict[str, Any]] = {}
    for i, item in enumerate(report["short_pilots"], 1):
        pilot_files = {k: item[k] for k in
                       ("native_input", "native_output", "geometry_path", "receipt_path")}
        if item.get("native_engrad") is not None:
            pilot_files["native_engrad"] = item["native_engrad"]
        result[f"pilot:{i}"] = {"kind": "pilot", "stage_path": str(PurePosixPath(item["native_output"]).parent),
            "files": pilot_files}
    for channel in ("C1", "C2"):
        for i, item in enumerate(report["channels"][channel]["screening"], 1):
            result[f"screen:{channel}:{i}"] = {"kind": "screen", "channel": channel,
                "stage_path": str(PurePosixPath(item["native_output"]).parent),
                "geometry_sha256": item["geometry_sha256"], "files": {k: item[k] for k in
                ("native_input", "native_output", "geometry_path", "receipt_path", "native_engrad")}}
    selected = report["selected_channel"]
    validation = report["channels"][selected]["validation"]
    paths = {"ts_opt": validation["ts_opt"], "ts_freq": validation["ts_freq"]}
    for side in ("minus", "plus"):
        paths[f"endpoint_{side}_opt"] = validation[f"endpoint_{side}"]["opt"]
        paths[f"endpoint_{side}_freq"] = validation[f"endpoint_{side}"]["freq"]
    for role, path in paths.items():
        result[f"production:{role}"] = {"kind": "production", "channel": selected,
            "validation_stage": role, "stage_path": path}
    refinement = report["channels"][selected].get("refinement")
    if isinstance(refinement, dict):
        result["production:screen_refinement"] = {"kind": "production", "channel": selected,
            "validation_stage": "screen_refinement", "stage_path": refinement["stage_path"]}
    for extra in report.get("native_extra_stages", []):
        if extra["stage_id"] in result:
            raise ReferenceError("native extra stage ID collides with a required report stage")
        result[extra["stage_id"]] = {"kind": "extension", "channel": selected,
            "route": extra["route"], "reason": extra["reason"],
            "stage_path": extra["stage_path"], "outcome": extra["outcome"]}
    return result


def _queue_only_seconds(pending: list[tuple[datetime, datetime]],
                        running: list[tuple[datetime, datetime]]) -> float:
    """Union scheduler pending windows after subtracting every running allocation."""
    pieces = []
    for lower, upper in pending:
        if upper <= lower:
            continue
        remaining = [(lower, upper)]
        for run_start, run_end in running:
            next_pieces = []
            for left, right in remaining:
                if run_end <= left or run_start >= right:
                    next_pieces.append((left, right))
                else:
                    if left < run_start:
                        next_pieces.append((left, run_start))
                    if run_end < right:
                        next_pieces.append((run_end, right))
            remaining = next_pieces
        pieces.extend(remaining)
    merged: list[tuple[datetime, datetime]] = []
    for lower, upper in sorted(pieces):
        if merged and lower <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], upper))
        else:
            merged.append((lower, upper))
    return sum((upper-lower).total_seconds() for lower, upper in merged)


def _p04_provider_binding(host: dict, logical_stage_id: str, receipt_path: Path,
                          allocation_start: datetime, allocation_end: datetime) -> dict[str, str]:
    """Return exact provider-role metadata when a P04 stage ID differs from its report role."""
    provider_id = host.get("stage_id")
    if not isinstance(provider_id, str) or not provider_id:
        raise ReferenceError("raw P04 allocation has no provider stage identifier")
    if provider_id == logical_stage_id:
        return {}
    provider = native_parser.safe_json(receipt_path)
    if (provider.get("schema") != "compchemworld.p04-native-stage-receipt/v1"
            or str(provider.get("job_id")) != str(host.get("job_id"))
            or provider.get("stage_id") != provider_id):
        raise ReferenceError("provider stage receipt does not bind the mapped raw P04 allocation")
    def parse_time(value: Any, label: str) -> datetime:
        if not isinstance(value, str):
            raise ReferenceError(f"{label} must be an ISO-8601 timestamp")
        try:
            parsed = datetime.fromisoformat(value[:-1] + "+00:00" if value.endswith("Z") else value)
        except ValueError as exc:
            raise ReferenceError(f"{label} is malformed") from exc
        if parsed.tzinfo is None:
            raise ReferenceError(f"{label} must include a UTC offset")
        return parsed.astimezone(timezone.utc)
    start = parse_time(provider.get("started_at_utc"), "provider stage start")
    end = parse_time(provider.get("ended_at_utc"), "provider stage end")
    if end <= start or start < allocation_start or end > allocation_end:
        raise ReferenceError("provider stage interval lies outside its scheduler allocation")
    return {"provider_stage_id": provider_id,
            "started_at_utc": start.isoformat().replace("+00:00", "Z"),
            "ended_at_utc": end.isoformat().replace("+00:00", "Z")}


def _assemble_execution_receipt(root: Path, output: Path, report: dict[str, Any],
                                manifest: dict[str, Any], decisions: dict[str, Any]) -> tuple[int, list[dict[str, Any]]]:
    """Build candidate receipt/resource rows only from hash-bound scheduler and raw-stage records."""
    execution = decisions.get("execution_index")
    if not isinstance(execution, dict) or set(execution) != {"jobs"}:
        raise ReferenceError("execution_index is absent or malformed")
    jobs_in = execution.get("jobs")
    if not isinstance(jobs_in, list) or not jobs_in:
        raise ReferenceError("execution_index.jobs must list actual scheduler allocations")
    specs = _execution_stage_specs(report)
    seen: set[str] = set()
    receipt_jobs: list[dict[str, Any]] = []
    stage_times: list[tuple[datetime, str]] = []
    resources: list[dict[str, Any]] = []
    allocation_windows: list[tuple[datetime, datetime, int, float, float]] = []
    pending_windows: list[tuple[datetime, datetime]] = []
    allocated_core_hours = 0.0
    resource_review_required = False
    def utc(raw: Any, label: str) -> datetime:
        if not isinstance(raw, str):
            raise ReferenceError(f"{label} must be an ISO-8601 UTC string")
        try:
            parsed = datetime.fromisoformat(raw[:-1] + "+00:00" if raw.endswith("Z") else raw)
        except ValueError as exc:
            raise ReferenceError(f"{label} is malformed") from exc
        if parsed.tzinfo is None or parsed.utcoffset() != timezone.utc.utcoffset(parsed):
            raise ReferenceError(f"{label} must carry a UTC offset")
        return parsed.astimezone(timezone.utc)
    attempt_start = utc(manifest.get("started_at_utc"), "attempt start")
    attempt_end = utc(manifest.get("reported_at_utc"), "report submission time")
    if attempt_end < attempt_start:
        raise ReferenceError("attempt report precedes attempt start")
    for source in jobs_in:
        required = {"scheduler_record", "batch_script", "stdout", "stderr", "stage_ids"}
        if not isinstance(source, dict) or set(source) != required:
            raise ReferenceError("execution allocation record has unsupported fields")
        if (not isinstance(source["scheduler_record"], str) or not isinstance(source["batch_script"], str)
                or not source["scheduler_record"].startswith("native_outputs/")
                or not source["batch_script"].startswith("native_outputs/")):
            raise ReferenceError("scheduler projection and batch script must be native_outputs-relative files")
        if any(source[key] is not None and (not isinstance(source[key], str)
               or not source[key].startswith("native_outputs/")) for key in ("stdout", "stderr")):
            raise ReferenceError("scheduler logs must be native_outputs-relative files or null when not created")
        raw_paths = [source[key] for key in ("scheduler_record", "batch_script", "stdout", "stderr")]
        raw = [_relative_file(root, source[key]) for key in ("scheduler_record", "batch_script")]
        scheduler = native_parser.safe_json(raw[0])
        allocation_only_failure = False
        host = None
        p04_markers = {"p04_source_schema", "p04_scheduler_record_path", "p04_scheduler_record_sha256"}
        has_p04 = any(key in scheduler for key in p04_markers)
        if not has_p04:
            no_start = (scheduler.get("state") in {"FAILED", "CANCELLED"}
                        and scheduler.get("started_at_utc") is None
                        and scheduler.get("wall_seconds") == 0 and scheduler.get("cpus") == 0
                        and scheduler.get("memory_gib") == 0)
        else:
            host_name = scheduler.get("p04_scheduler_record_path")
            if (not isinstance(host_name, str) or PurePosixPath(host_name).name != host_name
                    or scheduler.get("p04_source_schema") != "compchemworld.p04-scheduler-record/v1"):
                raise ReferenceError("candidate scheduler projection lacks a raw P04 source binding")
            host_rel = (PurePosixPath(source["scheduler_record"]).parent / host_name).as_posix()
            host_file = _relative_file(root, host_rel)
            host_digest = sha256(host_file)
            if (host_rel not in manifest["files_sha256"] or manifest["files_sha256"][host_rel] != host_digest
                    or scheduler.get("p04_scheduler_record_sha256") != host_digest):
                raise ReferenceError("raw P04 scheduler record is not hash-bound to the projection and bundle")
            host = native_parser.safe_json(host_file)
            allocated, measured, policy = host.get("allocated"), host.get("measured"), host.get("scheduler")
            if (host.get("schema") != "compchemworld.p04-scheduler-record/v1"
                    or host.get("case_id") != "case-07-independent-saddle-point-recomputation"
                    or not isinstance(allocated, dict) or not isinstance(measured, dict) or not isinstance(policy, dict)):
                raise ReferenceError("raw P04 scheduler record has an unsupported schema or case binding")
            try:
                p04_expected = {
                    "job_id": str(host["job_id"]), "scheduler": policy["name"],
                    "stage_id": host["stage_id"],
                    "candidate_stage_declaration": host["candidate_stage_declaration"],
                    "allocation_id": policy["allocation_id"], "cpus": allocated["cpus"],
                    "memory_gib": None if allocated["memory_mib"] is None else float(allocated["memory_mib"]) / 1024,
                    "scratch_gib": None if measured.get("scratch_observed_bytes_peak") is None else
                        float(measured["scratch_observed_bytes_peak"]) / 1024**3,
                    "peak_memory_gib": None if measured.get("peak_memory_mib") is None else
                        float(measured["peak_memory_mib"]) / 1024,
                    "wall_seconds": allocated["elapsed_seconds"], "state": host["state"],
                    "exit_code": host["exit_code_raw"], "submitted_at_utc": host["submitted_at_utc"],
                    "started_at_utc": host["started_at_utc"], "ended_at_utc": host["ended_at_utc"],
                    "array_job": policy["array_job"],
                }
            except (KeyError, TypeError, ValueError, OverflowError) as exc:
                raise ReferenceError("raw P04 scheduler fields cannot be mapped to the candidate projection") from exc
            if any(scheduler.get(key) != value for key, value in p04_expected.items()):
                raise ReferenceError("candidate scheduler projection disagrees with hash-bound raw P04 facts")
            no_start = (host.get("state") in {"FAILED", "CANCELLED"} and host.get("started_at_utc") is None
                        and allocated.get("elapsed_seconds") == 0 and allocated.get("cpus") == 0
                        and allocated.get("memory_mib") == 0
                        and host.get("raw_sacct", {}).get("Start") in (None, "", "Unknown"))
            outputs = host.get("expected_outputs")
            output_by_path = ({item.get("path"): item for item in outputs
                               if isinstance(item, dict) and isinstance(item.get("path"), str)}
                              if isinstance(outputs, list) else {})
            job_id = str(host.get("job_id", ""))
            missing_native = {"orca.stdout", "orca.stderr", "native.exitcode", "native-stage-receipt.json"}
            required_logs = {"job.sbatch", f"slurm-{job_id}.out", f"slurm-{job_id}.err"}
            allocation_only_failure = (
                host.get("state") in {"FAILED", "CANCELLED"}
                and type(host.get("exit_code")) is int and host["exit_code"] != 0
                and host.get("started_at_utc") is not None
                and host.get("ended_at_utc") == host.get("started_at_utc")
                and allocated.get("elapsed_seconds") == 0
                and isinstance(outputs, list) and len(output_by_path) == len(outputs)
                and required_logs <= output_by_path.keys()
                and all(output_by_path[name].get("present") is True for name in required_logs)
                and missing_native <= output_by_path.keys()
                and all(output_by_path[name].get("present") is False
                        and output_by_path[name].get("bytes") is None
                        and output_by_path[name].get("sha256") is None
                        and output_by_path[name].get("absence_reason") == "not_observed_in_terminal_job_directory"
                        for name in missing_native)
            )
            partial_cancelled_allocation = (
                host.get("state") in {"CANCELLED", "TIMEOUT"}
                and isinstance(allocated.get("elapsed_seconds"), int) and allocated["elapsed_seconds"] > 0
                and isinstance(allocated.get("cpus"), int) and allocated["cpus"] > 0
                and (allocated.get("memory_mib") is None
                     or (type(allocated.get("memory_mib")) is int and allocated["memory_mib"] > 0))
                and host.get("started_at_utc") is not None
                and host.get("ended_at_utc") is not None
                and host.get("raw_sacct", {}).get("Start") not in (None, "", "Unknown")
                and host.get("raw_sacct", {}).get("End") not in (None, "", "Unknown")
                and isinstance(outputs, list) and len(output_by_path) == len(outputs)
                and host.get("ended_at_utc") != host.get("started_at_utc")
                and {"job.sbatch", f"slurm-{job_id}.out", f"slurm-{job_id}.err", "orca.stdout", "orca.stderr"}
                    <= output_by_path.keys()
                and all(output_by_path[name].get("present") is True for name in
                    {"job.sbatch", f"slurm-{job_id}.out", f"slurm-{job_id}.err", "orca.stdout", "orca.stderr"})
                and {"native.exitcode", "native-stage-receipt.json"} <= output_by_path.keys()
                and all(output_by_path[name].get("present") is False
                    and output_by_path[name].get("bytes") is None
                    and output_by_path[name].get("sha256") is None
                    and output_by_path[name].get("absence_reason") == "not_observed_in_terminal_job_directory"
                    for name in {"native.exitcode", "native-stage-receipt.json"})
            )
            if (source["stdout"] is None or source["stderr"] is None) and not no_start:
                raise ReferenceError("scheduler logs may be absent only for a never-started cancellation")
            if (source["stdout"] is None) != (source["stderr"] is None):
                raise ReferenceError("scheduler stdout and stderr must both be present or both absent")
            if no_start and source["stage_ids"]:
                raise ReferenceError("never-started allocation cannot bind a native stage")
            if not isinstance(outputs, list):
                raise ReferenceError("raw P04 scheduler record omits expected output identities")
            stage_dir = Path(host_rel).parent
            for item in outputs:
                if not isinstance(item, dict) or set(item) != {"path", "present", "bytes", "sha256", "absence_reason"}:
                    raise ReferenceError("raw P04 expected-output descriptor is malformed")
                output_rel = (stage_dir / item["path"]).as_posix()
                output_pure = PurePosixPath(output_rel)
                if (output_pure.is_absolute() or output_pure.as_posix() != output_rel
                        or any(part in {"", ".", ".."} for part in output_pure.parts)):
                    raise ReferenceError("raw P04 output path is not a confined relative path")
                output_file = root.joinpath(*output_pure.parts)
                if item["present"] is True:
                    output_file = _relative_file(root, output_rel)
                    if (not output_file.is_file() or output_file.is_symlink()
                            or output_file.stat().st_size != item["bytes"] or sha256(output_file) != item["sha256"]
                            or manifest["files_sha256"].get(output_rel) != item["sha256"]):
                        raise ReferenceError(f"raw P04 output differs from bundle content: {item['path']}")
                elif item["present"] is False:
                    never_started_absence = no_start and item.get("absence_reason") == "not_created_before_start"
                    failed_bootstrap_absence = (allocation_only_failure and item["path"] in missing_native
                        and item.get("absence_reason") == "not_observed_in_terminal_job_directory")
                    partial_cancel_absence = (partial_cancelled_allocation
                        and item["path"] in {"native.exitcode", "native-stage-receipt.json"}
                        and item.get("absence_reason") == "not_observed_in_terminal_job_directory")
                    if (not (never_started_absence or failed_bootstrap_absence or partial_cancel_absence)
                            or item.get("bytes") is not None or item.get("sha256") is not None
                            or output_file.exists() or output_file.is_symlink()):
                        raise ReferenceError(f"raw P04 absent output is not valid for this allocation: {item['path']}")
                else:
                    raise ReferenceError("raw P04 output presence flag is not boolean")
        if any(p.relative_to(root).as_posix() not in manifest["files_sha256"] for p in raw):
            raise ReferenceError("execution evidence is not bound by the bundle manifest")
        if (source["stdout"] is None or source["stderr"] is None) and not no_start:
            raise ReferenceError("scheduler logs may be absent only for a hash-bound never-started allocation")
        if (source["stdout"] is None) != (source["stderr"] is None):
            raise ReferenceError("scheduler stdout and stderr must both be present or both absent")
        raw_by_key = {"stdout": None, "stderr": None}
        for key in ("stdout", "stderr"):
            if source[key] is not None:
                raw_by_key[key] = _relative_file(root, source[key])
                raw.append(raw_by_key[key])
        if any(p.relative_to(root).as_posix() not in manifest["files_sha256"] for p in raw):
            raise ReferenceError("execution evidence is not bound by the bundle manifest")
        scheduler_fields = ("job_id", "scheduler", "allocation_id", "cpus", "memory_gib", "scratch_gib",
                            "wall_seconds", "state", "exit_code", "submitted_at_utc", "started_at_utc",
                            "ended_at_utc", "batch_script_sha256", "array_job", "peak_memory_gib",
                            "process_cpu_hours")
        if (scheduler.get("schema") != "case07-scheduler-record/v2"
                or any(key not in scheduler for key in scheduler_fields)
                or scheduler["batch_script_sha256"] != sha256(raw[1])):
            raise ReferenceError("scheduler record is incomplete or does not bind its batch script")
        job_id = str(scheduler["job_id"])
        if (scheduler["array_job"] is not False or not job_id.isdigit()
                or type(scheduler["cpus"]) is not int):
            raise ReferenceError("scheduler allocation must be a non-array root job with integer allocated CPUs")
        if (no_start and (scheduler["cpus"] != 0 or scheduler.get("memory_gib") != 0)
                or not no_start and not 1 <= scheduler["cpus"] <= MAX_CORES):
            raise ReferenceError("allocated CPU or memory is inconsistent with start status or exceeds limits")
        try:
            memory = None if scheduler["memory_gib"] is None else float(scheduler["memory_gib"])
            scratch = None if scheduler["scratch_gib"] is None else float(scheduler["scratch_gib"])
            wall = float(scheduler["wall_seconds"])
            exit_code = int(str(scheduler["exit_code"]).split(":", 1)[0])
        except (TypeError, ValueError, OverflowError) as exc:
            raise ReferenceError("scheduler resource totals or exit code are malformed") from exc
        if ((memory is not None and (not math.isfinite(memory)
                or (not no_start and not 0 < memory <= MAX_MEMORY_GIB)))
                or (no_start and memory != 0)
                or (scratch is not None and (not math.isfinite(scratch) or not 0 <= scratch <= MAX_SCRATCH_GIB))
                or not math.isfinite(wall) or wall < 0 or wall > MAX_ACTIVE_SECONDS):
            raise ReferenceError("per-allocation memory, scratch or wall-time limit is exceeded")
        if memory is None or scratch is None or scheduler.get("peak_memory_gib") is None:
            resource_review_required = True
        state = str(scheduler["state"]).split()[0].upper().rstrip("+")
        if state not in {"COMPLETED", "FAILED", "CANCELLED", "TIMEOUT", "OUT_OF_MEMORY", "PREEMPTED"}:
            raise ReferenceError("scheduler final state is unsupported")
        if state == "COMPLETED" and exit_code != 0:
            raise ReferenceError("scheduler final state and exit code disagree")
        submitted = utc(scheduler["submitted_at_utc"], f"job {job_id} submission")
        job_end = utc(scheduler["ended_at_utc"], f"job {job_id} end")
        raw_start = scheduler["started_at_utc"]
        job_start = None if raw_start is None else utc(raw_start, f"job {job_id} start")
        if job_start is None:
            if state == "COMPLETED" or wall != 0 or job_end < submitted:
                raise ReferenceError("never-started allocation has inconsistent state, wall time or timestamps")
        else:
            elapsed = (job_end-job_start).total_seconds()
            if (job_start < submitted or job_end < job_start
                    or abs(elapsed-wall) > max(60, 0.02*max(elapsed, wall))):
                raise ReferenceError("scheduler duration and timestamp span disagree")
        if submitted < attempt_start or job_end > attempt_end:
            raise ReferenceError("scheduler allocation times disagree or lie outside the complete attempt")
        pending_end = job_start if job_start is not None else job_end
        pending_windows.append((submitted, pending_end))
        if scheduler["scheduler"] in (None, "") or scheduler["allocation_id"] in (None, ""):
            raise ReferenceError("scheduler allocation identity is incomplete")
        cpu_hours = scheduler["cpus"]*wall/3600
        allocated_core_hours += cpu_hours
        if job_start is not None:
            allocation_windows.append((job_start, job_end, scheduler["cpus"],
                                       0.0 if memory is None else memory,
                                       0.0 if scratch is None else scratch))
        process_cpu = scheduler.get("process_cpu_hours", "")
        if process_cpu not in (None, "") and (not math.isfinite(float(process_cpu)) or float(process_cpu) < 0):
            raise ReferenceError("process CPU hours must be a finite nonnegative measurement")
        stage_ids = source["stage_ids"]
        if (not job_id.isdigit() or job_id in {j.get("job_id") for j in receipt_jobs}
                or not isinstance(stage_ids, list)
                or (not stage_ids and job_start is not None
                    and not (allocation_only_failure or partial_cancelled_allocation))
                or (stage_ids and job_start is None)
                or any(not isinstance(x, str) or x not in specs or x in seen for x in stage_ids)):
            raise ReferenceError("scheduler allocation has duplicate/unknown stage bindings")
        bound_stages = []
        for stage_id in stage_ids:
            spec = specs[stage_id]
            stage_path = spec.get("stage_path")
            if not isinstance(stage_path, str) or not stage_path.startswith("native_outputs/"):
                raise ReferenceError(f"stage {stage_id} is outside native_outputs")
            stage_dir = output.joinpath(*PurePosixPath(stage_path).parts)
            if not stage_dir.is_dir() or stage_dir.is_symlink():
                raise ReferenceError(f"stage directory is missing or unsafe: {stage_id}")
            stage_receipt_path = stage_dir / "receipt.json"
            stage_receipt = native_parser.safe_json(stage_receipt_path)
            try:
                start = datetime.fromisoformat(stage_receipt["started_at_utc"].replace("Z", "+00:00"))
                end = datetime.fromisoformat(stage_receipt["ended_at_utc"].replace("Z", "+00:00"))
            except (KeyError, TypeError, ValueError) as exc:
                raise ReferenceError(f"stage receipt lacks actual UTC execution times: {stage_id}") from exc
            if end <= start:
                raise ReferenceError(f"stage execution interval is invalid: {stage_id}")
            if job_start is None or start < job_start or end > job_end:
                raise ReferenceError(f"stage interval lies outside its scheduler allocation: {stage_id}")
            all_files = sorted(p for p in stage_dir.rglob("*") if p.is_file())
            if not all_files or any(p.is_symlink() for p in all_files):
                raise ReferenceError(f"stage file manifest is empty or unsafe: {stage_id}")
            binding = dict(spec, stage_id=stage_id,
                started_at_utc=start.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
                ended_at_utc=end.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
                native_files=[{"path": p.relative_to(output).as_posix(), "sha256": sha256(p)} for p in all_files])
            if has_p04 and host.get("stage_id") != stage_id:
                if job_start is None:
                    raise ReferenceError("provider stage has no scheduler allocation start")
                binding.update(_p04_provider_binding(host, stage_id,
                    stage_dir / "native-stage-receipt.json", job_start, job_end))
            bound_stages.append(binding)
            binding_start = utc(binding["started_at_utc"], "bound stage start")
            stage_times.append((binding_start, stage_id)); seen.add(stage_id)
        job = {key: scheduler[key] for key in scheduler_fields}
        for key in ("stage_id", "candidate_stage_declaration"):
            if key in scheduler:
                job[key] = scheduler[key]
        job.update({"scheduler_record": raw_paths[0], "scheduler_record_sha256": sha256(raw[0]),
                    "batch_script": raw_paths[1],
                    "stdout": raw_paths[2], "stdout_sha256": sha256(raw_by_key["stdout"]) if raw_by_key["stdout"] else None,
                    "stdout_absence_reason": "not_created_before_start" if raw_by_key["stdout"] is None else None,
                    "stderr": raw_paths[3], "stderr_sha256": sha256(raw_by_key["stderr"]) if raw_by_key["stderr"] else None,
                    "stderr_absence_reason": "not_created_before_start" if raw_by_key["stderr"] is None else None,
                    "native_artifacts": bound_stages})
        if has_p04:
            job.update({"p04_scheduler_record": host_rel, "p04_scheduler_record_sha256": host_digest,
                        "p04_source_schema": host["schema"]})
        receipt_jobs.append(job)
        started = scheduler.get("started_at_utc") or ""
        ended = scheduler.get("ended_at_utc")
        resources.append({"job_id": job_id, "start_utc": started, "end_utc": ended,
            "allocated_cores": scheduler["cpus"],
            "allocated_core_hours": f"{cpu_hours:.6f}",
            "process_cpu_hours": scheduler.get("process_cpu_hours", ""),
            "peak_memory_gib": "" if scheduler["peak_memory_gib"] is None else scheduler["peak_memory_gib"],
            "scratch_gib": "" if scheduler["scratch_gib"] is None else scheduler["scratch_gib"],
            "status": scheduler["state"], "evidence_path": raw_paths[0]})
    if seen != set(specs):
        raise ReferenceError("execution_index must bind every report stage exactly once")
    ordered = [stage_id for _, stage_id in sorted(stage_times)]
    if len(ordered) != len(set(ordered)):
        raise ReferenceError("execution order is ambiguous")
    if allocated_core_hours > 64.0001:
        raise ReferenceError("submitted allocations exceed the 64 core-hour limit")
    points = sorted({point for start, end, *_ in allocation_windows for point in (start, end)})
    for left, right in zip(points, points[1:]):
        active = [row for row in allocation_windows if row[0] < right and row[1] > left]
        if (sum(row[2] for row in active) > MAX_CORES
                or sum(row[3] for row in active) > MAX_MEMORY_GIB
                or sum(row[4] for row in active) > MAX_SCRATCH_GIB):
            raise ReferenceError("concurrent allocations exceed CPU, memory or scratch limits")
    queue_seconds = _queue_only_seconds(pending_windows,
        [(start, end) for start, end, *_ in allocation_windows])
    active_seconds = (attempt_end-attempt_start).total_seconds() - queue_seconds
    if active_seconds > MAX_ACTIVE_SECONDS:
        raise ReferenceError("attempt active time exceeds eight hours after evidenced scheduler queue intervals")
    attempt_started = manifest.get("started_at_utc")
    report_submitted = manifest.get("reported_at_utc")
    receipt = {"schema": "case07-candidate-execution/v2", "attempt_id": manifest["attempt_id"],
               "attempt_started_at_utc": attempt_started, "report_submitted_at_utc": report_submitted,
               "jobs": receipt_jobs, "execution_order": ordered}
    (output / "execution-receipt.json").write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n")
    return len(receipt_jobs), resources


def _derive_final_profile(stages: dict[str, dict[str, Any]]) -> tuple[str, str]:
    """Describe the frozen final profile from the six reparsed production inputs."""
    if set(stages) != {"ts_opt", "ts_freq", "minus_opt", "minus_freq", "plus_opt", "plus_freq"}:
        raise ReferenceError("final profile derivation requires the six required production stages")
    levels = {item.get("method_fingerprint") for item in stages.values()}
    if len(levels) != 1:
        raise ReferenceError("six production stages do not share one supported final method profile")
    level = next(iter(levels))
    display = {"uks r2scan-3c defgrid3": "UKS r2SCAN-3c DefGrid3",
               "uks pbe d3bj def2-svp def2/j ri defgrid3":
                   "UKS PBE D3BJ def2-SVP def2/J RI DefGrid3"}.get(level)
    if display is None:
        raise ReferenceError("production outputs use a method outside the frozen Case07 final profiles")
    scf_settings = {item.get("scf_convergence", "unspecified") for item in stages.values()}
    scf_summary = str(next(iter(scf_settings))) if len(scf_settings) == 1 else "mixed"
    return display, scf_summary


def _write_failures(output: Path, report: dict[str, Any]) -> None:
    """Describe non-COMPLETED allocated jobs from the assembled receipt only."""
    receipt = native_parser.safe_json(output / "execution-receipt.json")
    jobs = receipt.get("jobs")
    if not isinstance(jobs, list):
        raise ReferenceError("execution receipt has no job list for failures.md")
    by_stage_path: dict[str, dict[str, Any]] = {}
    for job in jobs:
        for artifact in job.get("native_artifacts", []):
            stage_path = artifact.get("stage_path")
            if isinstance(stage_path, str):
                by_stage_path[stage_path] = {"job": job, "artifact": artifact}

    channel = report.get("channels", {}).get(report.get("selected_channel"), {})
    validation = channel.get("validation", {})
    chains: dict[str, tuple[str, dict[str, Any]]] = {}
    for side in ("minus", "plus"):
        chain = validation.get(f"endpoint_{side}", {}).get("opt_chain", {})
        for segment in chain.get("segments", []) if isinstance(chain, dict) else []:
            record_path = segment.get("scheduler_record_path")
            if isinstance(record_path, str):
                chains[record_path] = (side, segment)

    failed = sorted((job for job in jobs if job.get("state") != "COMPLETED"),
                    key=lambda job: str(job.get("submitted_at_utc", "")))
    lines = [
        "# Failed, cancelled, and timed-out allocations",
        "",
        "This account is derived from the hash-bound `execution-receipt.json`. It lists only submitted scheduler allocations whose recorded terminal state is not `COMPLETED`; it does not turn unallocated submission intent into a job row. Every listed allocation remains in `resource_usage.csv`; the failed allocation itself receives no successful scientific-stage or execution-order credit, while any separately completed stage is reported independently.",
        "",
    ]
    screen_event = next((event for event in report.get("decision_events", [])
                         if event.get("event") == "screen_path_review"), None)
    if screen_event is not None:
        lines.extend([
            "## Decision and method context",
            "",
            f"The hash-linked screen decision selected `{report.get('selected_channel')}` and did not advance the alternative channel because the matched screening points favored the selected channel in both energy and gradient components. These unrelaxed screening observations do not establish a barrier or prove global path competitiveness. The decision evidence is `{screen_event.get('evidence_path')}` (SHA-256 `{screen_event.get('evidence_sha256')}`).",
            f"The fresh calculation level is `{report.get('final_level', 'not reported')}`. The author reference levels in `barriers.csv` are reported separately; their difference is method dependence, not a calibrated uncertainty or same-level reproduction of the paper's higher-level result.",
            "",
        ])
    if not failed:
        lines.append("No non-`COMPLETED` scheduler allocations are recorded in this execution receipt.")
    for job in failed:
        declaration = job.get("candidate_stage_declaration", {})
        stage_id = declaration.get("stage_id", job.get("stage_id", "unknown"))
        lines.extend([
            f"## Job {job.get('job_id', 'unknown')} — {job.get('state', 'unknown')}",
            "",
            f"- Declared stage: `{stage_id}` ({declaration.get('kind', 'unspecified')}).",
            f"- Declared route/purpose: {declaration.get('route', 'not recorded')}; {declaration.get('reason', 'no further reason recorded')}.",
            f"- Scheduler exit status: `{job.get('exit_code', 'unknown')}`; allocation interval: `{job.get('started_at_utc') or 'unknown'}` to `{job.get('ended_at_utc') or 'unknown'}`; allocated CPUs: `{job.get('cpus', 'unknown')}`.",
            f"- Hash-bound scheduler record: `{job.get('p04_scheduler_record', job.get('scheduler_record', 'unknown'))}` (SHA-256 `{job.get('p04_scheduler_record_sha256', job.get('scheduler_record_sha256', 'unknown'))}`).",
            f"- Native completion credit from this allocation: `{len(job.get('native_artifacts', []))}` bound native artifacts. Scheduler exit status is not a substitute for a native exit file or completed-stage receipt.",
        ])
        chain_entry = chains.get(job.get("p04_scheduler_record"))
        if chain_entry is not None:
            side, segment = chain_entry
            endpoint_key = f"endpoint_{side}"
            successful_path = validation.get(endpoint_key, {}).get("opt")
            later = by_stage_path.get(successful_path) if isinstance(successful_path, str) else None
            lines.extend([
                f"- Resource-only continuation evidence: the validated `{side}` endpoint chain records last complete evaluated frame index `{segment.get('last_complete_frame_index')}` at `{segment.get('energy_au')}` Eh, from `{segment.get('trajectory_path')}` (SHA-256 `{segment.get('trajectory_sha256')}`) and frame `{segment.get('frame_xyz_path')}` (SHA-256 `{segment.get('frame_xyz_sha256')}`). This failed allocation itself is not a completed endpoint stage.",
            ])
            if later is not None:
                later_job, later_artifact = later["job"], later["artifact"]
                lines.append(
                    f"- A separate later successful endpoint Opt is bound as `{later_artifact.get('stage_id')}` in `{successful_path}` (job `{later_job.get('job_id')}`); it does not change this allocation's terminal status or resource charge."
                )
        elif stage_id == "extension:neb-ts:01":
            ts_path = validation.get("ts_opt")
            later = by_stage_path.get(ts_path) if isinstance(ts_path, str) else None
            if later is not None:
                later_job, later_artifact = later["job"], later["artifact"]
                lines.append(
                    f"- A distinct TS optimization is separately bound as `{later_artifact.get('stage_id')}` in `{ts_path}` (job `{later_job.get('job_id')}`); its own declaration describes a search from an exploratory NEB peak. The cancelled allocation itself is not represented as a validated TS."
                )
        lines.append("")
    lines.extend([
        "The receipt and resource ledger retain all actual allocations, including the rows above. A scheduler state or wrapper exit status alone does not establish native completion. No missing native output or receipt is synthesized here.",
        "",
    ])
    (output / "failures.md").write_text("\n".join(lines), encoding="utf-8")


def _copy_decision_evidence(root: Path, output: Path, manifest: dict[str, Any],
                            decisions: dict[str, Any]) -> None:
    """Copy the exact hash-bound decision records referenced by this submission."""
    required = {
        "decision-evidence/final-native-physical-review.json",
        "decision-evidence/minus-frequency-review.json",
        "decision-evidence/neb-to-optts-decision.json",
        "decision-evidence/plus-converged-review.json",
        "decision-evidence/plus-endpoint-continuation-decision.json",
        "decision-evidence/screen-review.json",
        "decision-evidence/ts-frequency-review.json",
    }
    events = decisions.get("decision_events")
    file_hashes = manifest.get("files_sha256")
    if not isinstance(events, list) or not isinstance(file_hashes, dict):
        raise ReferenceError("decision evidence index or source manifest is malformed")
    referenced: dict[str, str] = {}
    for event in events:
        if not isinstance(event, dict):
            raise ReferenceError("decision evidence event is malformed")
        rel, expected = event.get("evidence_path"), event.get("evidence_sha256")
        if (not isinstance(rel, str) or not rel.startswith("decision-evidence/")
                or not isinstance(expected, str) or not HEX64.fullmatch(expected)
                or file_hashes.get(rel) != expected):
            raise ReferenceError("decision evidence is not bound to the source manifest")
        source = _relative_file(root, rel)
        if sha256(source) != expected:
            raise ReferenceError(f"decision evidence digest mismatch: {rel}")
        if rel in referenced and referenced[rel] != expected:
            raise ReferenceError("decision evidence path has conflicting digests")
        referenced[rel] = expected
    if set(referenced) != required:
        raise ReferenceError("submission does not reference the seven required decision-evidence files")
    destination_root = output / "decision-evidence"
    destination_root.mkdir(exist_ok=False)
    for rel, expected in sorted(referenced.items()):
        source = _relative_file(root, rel)
        destination = output.joinpath(*PurePosixPath(rel).parts)
        shutil.copyfile(source, destination)
        if sha256(destination) != expected:
            raise ReferenceError(f"copied decision evidence digest mismatch: {rel}")


def _finalize_from_index(root: Path, output: Path, assets: Path, manifest: dict[str, Any],
                        decisions: dict[str, Any], index: dict[str, Any]) -> dict[str, Any]:
    selected = decisions["selected_channel"]
    assets = _safe_root(assets)
    for rel, expected in PUBLIC_ASSET_HASHES.items():
        if sha256(assets / rel) != expected:
            raise ReferenceError(f"pinned public asset mismatch: {rel}")
    validation = index["validation"]
    screening = index["screening"]
    output.mkdir(parents=True, exist_ok=False)
    shutil.copytree(root / "native_outputs", output / "native_outputs")
    _copy_decision_evidence(root, output, manifest, decisions)
    api = fresh_audit.verifier_api(native_parser)
    def stage_path(rel: str, *, opt: bool = False, imaginary: int | None = None) -> dict[str, Any]:
        return native_parser.stage_facts(output, rel, require_opt=opt,
                                         expected_imaginary=imaginary)
    pilot_dir = index["pilot"]
    refinement_dir = index.get("screen_refinement")
    pilot_input_text = (output / pilot_dir / "job.inp").read_text(encoding="utf-8", errors="strict")
    pilot_method = next((line.strip()[1:].strip() for line in pilot_input_text.splitlines()
                         if line.lstrip().startswith("!")), None)
    pilot_record = {"native_input": f"{pilot_dir}/job.inp", "native_output": f"{pilot_dir}/job.out",
                    "geometry_path": f"{pilot_dir}/start.xyz", "receipt_path": f"{pilot_dir}/receipt.json",
                    "method": pilot_method}
    if f"{pilot_dir}/job.engrad" in manifest.get("files_sha256", {}):
        pilot_record["native_engrad"] = f"{pilot_dir}/job.engrad"
    receipt = native_parser.safe_json(output / pilot_record["receipt_path"])
    pilot_record["elapsed_seconds"] = receipt.get("elapsed_seconds")
    channels = {name: {"channel": name, "status": "screened_unresolved", "screening": []}
                for name in ("C1", "C2")}
    for ch in ("C1", "C2"):
        for i, rel in enumerate(screening[ch], 1):
            item = {"native_input": f"{rel}/job.inp", "native_output": f"{rel}/job.out",
                    "native_engrad": f"{rel}/job.engrad", "geometry_path": f"{rel}/start.xyz",
                    "receipt_path": f"{rel}/receipt.json", "lambda": geom.SCREEN_LAMBDAS[i-1],
                    "screen_id": f"{ch}_p{i}"}
            egrad = fresh_audit._parse_engrad(output / item["native_engrad"])
            item["geometry_sha256"] = fresh_audit._xyz_digest(list(geom.ATOM_ORDER), egrad["coordinates"])
            channels[ch]["screening"].append(item)
    validation_report = {"ts_opt": validation["ts_opt"], "ts_freq": validation["ts_freq"],
                         "seed_minus": validation["seed_minus"], "seed_plus": validation["seed_plus"],
                         "displacement": validation["displacement"],
                         "endpoint_minus": validation["endpoint_minus"],
                         "endpoint_plus": validation["endpoint_plus"]}
    channels[selected]["status"] = "validated"
    if refinement_dir is not None:
        channels[selected]["refinement"] = {"stage_path": refinement_dir,
                                             "decision": decisions.get("screen_refinement_decision", {})}
    else:
        channels[selected]["optts_seed_binding"] = decisions["optts_seed_decision"]
    channels[selected]["validation"] = validation_report
    report = {"case_id": manifest["case_id"], "definition_revision": REVISION, "resource_profile": RESOURCE_PROFILE,
              "engine": "ORCA 6.0.1", "final_level": "UKS r2SCAN-3c DefGrid3",
              "scf_convergence": "VeryTightSCF", "atom_mapping": geom.SOURCE_INDEX,
              "short_pilots": [pilot_record], "decision_events": decisions.get("decision_events", []),
              "selected_channel": selected, "channels": channels,
              "native_route": decisions.get("native_route", "signed-mode-two-endpoint-opt"),
              "native_extra_stages": decisions.get("native_extra_stages", []),
              "attempt_id": manifest["attempt_id"], "campaign_status": "INCOMPLETE",
              "campaign_failures": ["scheduler accounting was not authenticated by the offline finalizer"],
              "scope": {"F12_migrated": False, "limitations": [
                  "Offline report assembly does not authenticate scheduler provenance.",
                  "Reference levels remain separate; no cross-method uncertainty is inferred."]}}
    # Reparse selected production outputs to derive barrier values from bytes.
    stages = {
        "ts_opt": stage_path(validation["ts_opt"], opt=True),
        "ts_freq": stage_path(validation["ts_freq"], imaginary=1),
        "minus_opt": stage_path(validation["endpoint_minus"]["opt"], opt=True),
        "minus_freq": stage_path(validation["endpoint_minus"]["freq"], imaginary=0),
        "plus_opt": stage_path(validation["endpoint_plus"]["opt"], opt=True),
        "plus_freq": stage_path(validation["endpoint_plus"]["freq"], imaginary=0),
    }
    report["final_level"], report["scf_convergence"] = _derive_final_profile(stages)
    report["scf_convergence_by_stage"] = {
        name: str(item.get("scf_convergence", "unspecified")) for name, item in stages.items()}
    stage_caps = [(pilot_dir, PILOT_CAP_SECONDS)]
    stage_caps.extend((rel, SCREEN_CAP_SECONDS) for ch in ("C1", "C2") for rel in screening[ch])
    if refinement_dir is not None:
        stage_caps.append((refinement_dir, STAGE_CAPS["screen_refinement"]))
    stage_caps.extend([(validation["ts_opt"], STAGE_CAPS["optts"]),
                       (validation["ts_freq"], STAGE_CAPS["ts_frequency"])])
    stage_caps.extend((validation[side][kind],
                       STAGE_CAPS["endpoint_opt"] if kind == "opt" else STAGE_CAPS["endpoint_frequency"])
                      for side in ("endpoint_minus", "endpoint_plus") for kind in ("opt", "freq"))
    elapsed_total = 0.0
    for rel, cap in stage_caps:
        receipt_obj = native_parser.safe_json(output / rel / "receipt.json")
        try:
            elapsed = float(receipt_obj["elapsed_seconds"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ReferenceError(f"stage receipt lacks elapsed seconds: {rel}") from exc
        if not math.isfinite(elapsed) or elapsed <= 0 or elapsed > cap:
            raise ReferenceError(f"stage exceeded its per-stage budget cap: {rel}")
        elapsed_total += elapsed
    if elapsed_total > MAX_PLANNED_STAGE_SECONDS:
        raise ReferenceError("sum of native stage elapsed times exceeds the attempt stage-cap budget")
    refs = geom.load_public_geometries(assets)
    role_by_side = {}
    for side, facts in (("minus", stages["minus_freq"]), ("plus", stages["plus_freq"])):
        graph = native_parser.bond_graph(list(geom.ATOM_ORDER), facts["hessian"]["coordinates"])
        if graph == native_parser.bond_graph(refs["bpr"]["elements"], refs["bpr"]["coordinates"]):
            role_by_side[side] = "bpr"
        elif graph == native_parser.bond_graph(refs[selected]["elements"], refs[selected]["coordinates"]):
            role_by_side[side] = "product"
    if set(role_by_side.values()) != {"bpr", "product"}:
        raise ReferenceError("native endpoint graphs do not identify one BPR and one selected product")
    bpr_side = next(side for side, role in role_by_side.items() if role == "bpr")
    bpr_facts = stages[f"{bpr_side}_freq"]
    ts_facts = stages["ts_freq"]
    version_match = re.search(r"(?im)Program Version\s+([0-9]+\.[0-9]+\.[0-9]+)", ts_facts["output"])
    if not version_match:
        raise ReferenceError("fresh TS frequency output lacks a native ORCA version marker")
    report["engine"] = "ORCA " + version_match.group(1)
    barrier = ((bpr_facts["energy_au"] * -1 + ts_facts["energy_au"] +
                bpr_facts["zpe_au"] * -1 + ts_facts["zpe_au"]) * HARTREE_TO_KCAL)
    # The preceding expression is E_TS+ZPE_TS minus E_BPR+ZPE_BPR.
    refs_path = assets / "ipso_energy_reference.csv"
    with refs_path.open(newline="", encoding="utf-8") as stream:
        energy_rows = {row["species"]: row for row in csv.DictReader(stream)}
    def finite_col(row: dict[str, str], key: str) -> float:
        value = float(row[key])
        if not math.isfinite(value):
            raise ReferenceError(f"non-finite public reference field: {key}")
        return value
    barrier_fields = ["channel", "status", "level", "reactant_output", "ts_output",
                      "e_reactant_au", "e_ts_au", "zpe_reactant_au", "zpe_ts_au",
                      "dft_zpe_barrier_kcal_per_mol", "author_dft_zpe_barrier_kcal_per_mol",
                      "author_composite_barrier_kcal_per_mol", "published_channel_barrier_kcal_per_mol",
                      "comparison_scope"]
    rows = []
    for ch in ("C1", "C2"):
        bpr, product = energy_rows["BPR"], energy_rows[ch]
        author_dft = ((finite_col(product, "e_dft_au") + finite_col(product, "zpe_au")) -
                      (finite_col(bpr, "e_dft_au") + finite_col(bpr, "zpe_au"))) * HARTREE_TO_KCAL
        author_composite = ((finite_col(product, "e_f12_au") + finite_col(product, "zpe_au")) -
                            (finite_col(bpr, "e_f12_au") + finite_col(bpr, "zpe_au"))) * HARTREE_TO_KCAL
        row = {"channel": ch, "status": channels[ch]["status"], "level": report["final_level"],
               "reactant_output": "", "ts_output": "", "e_reactant_au": "", "e_ts_au": "",
               "zpe_reactant_au": "", "zpe_ts_au": "", "dft_zpe_barrier_kcal_per_mol": "",
               "author_dft_zpe_barrier_kcal_per_mol": f"{author_dft:.6f}",
               "author_composite_barrier_kcal_per_mol": f"{author_composite:.6f}",
               "published_channel_barrier_kcal_per_mol": product["published_channel_barrier_kcal_per_mol"],
               "comparison_scope": "fresh native DFT+ZPE only; reference levels remain separate"}
        if ch == selected:
            row.update({"reactant_output": f"{validation['endpoint_'+bpr_side]['freq']}/job.out",
                        "ts_output": f"{validation['ts_freq']}/job.out",
                        "e_reactant_au": f"{bpr_facts['energy_au']:.12f}",
                        "e_ts_au": f"{ts_facts['energy_au']:.12f}",
                        "zpe_reactant_au": f"{bpr_facts['zpe_au']:.12f}",
                        "zpe_ts_au": f"{ts_facts['zpe_au']:.12f}",
                        "dft_zpe_barrier_kcal_per_mol": f"{barrier:.6f}"})
        rows.append(row)
    with (output / "barriers.csv").open("x", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=barrier_fields); writer.writeheader(); writer.writerows(rows)
    audit = fresh_audit.audit_fresh_native(output, report, api, refs)
    if audit.native_status != "PASS" or audit.connection_status != "PASS":
        raise ReferenceError("NATIVE_AUDIT_NOT_PASS: native=" + str(audit.native_status)
                             + "; connection=" + str(audit.connection_status))
    maxima = {ch: max(point["energy_au"] for point in audit.facts["screening"][ch]["points"])
              for ch in ("C1", "C2")}
    expected_channel = min(("C1", "C2"), key=lambda ch: (maxima[ch], ch))
    if selected != expected_channel:
        raise ReferenceError("selected channel decision differs from reparsed lower-sampled-maximum rule")
    report["native_audit"] = {"status": audit.native_status, "connection_status": audit.connection_status,
                              "reason": audit.reason}
    (output / "references_uncertainty.md").write_text(
        "Fresh native DFT+ZPE values are reported separately from author reference levels. Their differences are method dependence, not a calibrated uncertainty.\n",
        encoding="utf-8")
    execution_records = []
    for rel, _ in stage_caps:
        receipt_rel = f"{rel}/receipt.json"
        receipt_obj = native_parser.safe_json(output / receipt_rel)
        execution_records.append({"stage_path": rel, "status": receipt_obj.get("status"),
                                  "elapsed_seconds": receipt_obj.get("elapsed_seconds"),
                                  "receipt_path": receipt_rel})
    for extra in report.get("native_extra_stages", []):
        receipt_rel = f"{extra['stage_path']}/receipt.json"
        receipt_obj = native_parser.safe_json(output / receipt_rel)
        execution_records.append({"stage_id": extra["stage_id"], "stage_path": extra["stage_path"],
            "status": receipt_obj.get("status"), "outcome": extra["outcome"],
            "elapsed_seconds": receipt_obj.get("elapsed_seconds"), "receipt_path": receipt_rel})
    report["execution_stages"] = execution_records
    (output / "ts_search_report.json").write_text(json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n")
    receipt_generated = False
    receipt_error = "execution_index is absent or incomplete"
    resource_rows: list[dict[str, Any]] = []
    try:
        _, resource_rows = _assemble_execution_receipt(root, output, report, manifest, decisions)
        _write_failures(output, report)
        receipt_generated = True
        receipt_error = ""
    except (ReferenceError, KeyError, TypeError, OSError, json.JSONDecodeError) as exc:
        receipt_error = str(exc)
    resource_fields = ["job_id", "start_utc", "end_utc", "allocated_cores", "allocated_core_hours",
                       "process_cpu_hours", "peak_memory_gib", "scratch_gib", "status", "evidence_path"]
    with (output / "resource_usage.csv").open("x", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=resource_fields); writer.writeheader(); writer.writerows(resource_rows)
    result = {"schema": "case07-finalization-status/v1", "case_id": CASE_ID,
            "definition_revision": REVISION, "attempt_id": manifest["attempt_id"],
            "status": ("NATIVE_AUDIT_PASS_EXECUTION_RECEIPT_ASSEMBLED" if receipt_generated else
                       "NATIVE_AUDIT_PASS_EXECUTION_RECEIPT_NOT_ASSEMBLED"),
            "native_audit": audit.native_status, "connection_audit": audit.connection_status,
            "candidate_report_generated": True,
            "final_contract_generated": False,
            "final_artifacts_assembled": receipt_generated, "oracle_pass": False,
            "resource_rows": len(resource_rows),
            "execution_receipt_error": None if receipt_generated else receipt_error,
            "scheduler_accounting_authenticated": False,
            "execution_receipt_generated": receipt_generated,
            "execution_allocation_count": len(resource_rows),
            "scope": "Candidate report, execution receipt and resource files are assembled from hash-bound raw scheduler/job records. Assembly is not an independent verifier result, scheduler authentication, or Oracle reward."}
    _write(output / "finalization-status.json", json.dumps(result, indent=2, sort_keys=True) + "\n")
    return result


def finalize_preflight(bundle: Path, output: Path, assets: Path) -> dict[str, Any]:
    """Reparse a complete raw bundle or write an explicit NOT_RUN status."""
    root = _safe_root(bundle)
    if output.is_symlink() or (output.exists() and not output.is_dir()):
        raise ReferenceError("finalize output must be a non-symlink directory")
    if output.exists():
        if any(output.iterdir()):
            raise ReferenceError("finalize output directory must be empty")
        output.rmdir()
    manifest_path = _relative_file(root, "manifest.json")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"),
                          object_pairs_hook=_unique_pairs,
                          parse_constant=lambda _: (_ for _ in ()).throw(ReferenceError("non-finite JSON")))
    if not isinstance(manifest, dict) or manifest.get("schema") != "case07-fresh-reference-bundle/v2":
        raise ReferenceError("finalizer requires case07-fresh-reference-bundle/v2")
    if (manifest.get("case_id") != CASE_ID or manifest.get("definition_revision") != REVISION
            or manifest.get("resource_profile") != RESOURCE_PROFILE):
        raise ReferenceError("final bundle identity or definition revision is stale")
    attempt_id = manifest.get("attempt_id")
    if not isinstance(attempt_id, str) or not re.fullmatch(r"[0-9a-f]{32}", attempt_id):
        raise ReferenceError("final bundle attempt id must match the candidate execution receipt's lowercase 32-hex contract")
    listed = manifest.get("files_sha256")
    if not isinstance(listed, dict) or not listed:
        raise ReferenceError("final bundle raw-file hash map is missing")
    actual: set[str] = set()
    for rel, expected in listed.items():
        if not isinstance(rel, str) or not isinstance(expected, str) or not HEX64.fullmatch(expected):
            raise ReferenceError("final bundle file map contains malformed path or digest")
        path = _relative_file(root, rel)
        if sha256(path) != expected:
            raise ReferenceError(f"final bundle digest mismatch: {rel}")
        actual.add(rel)
    if any(path.is_symlink() for path in root.rglob("*")):
        raise ReferenceError("final bundle contains a symlink")
    on_disk = {p.relative_to(root).as_posix() for p in root.rglob("*")
               if p.is_file() and p.name != "manifest.json"}
    if actual != on_disk:
        raise ReferenceError("final bundle has unlisted files or omits hash-bound files")

    decision_rel = manifest.get("decision_records_path", "decision_records.json")
    missing = sorted(FINALIZE_REQUIRED_FILES - actual)
    missing = sorted(set(missing))
    status = {"schema": "case07-finalization-status/v1", "case_id": CASE_ID,
              "definition_revision": REVISION, "attempt_id": attempt_id,
              "status": "NOT_RUN", "bundle_manifest_sha256": sha256(manifest_path),
              "missing_evidence": missing,
              "reason": "required native stages are absent",
              "final_contract_generated": False,
              "native_reparse": "NOT_RUN",
              "scope": "This command parses hash-bound native inputs and outputs; it does not authenticate execution provenance or assign reward."}
    if not missing:
        try:
            decisions = json.loads(_relative_file(root, decision_rel).read_text(encoding="utf-8"),
                                  object_pairs_hook=_unique_pairs)
            index = decisions.get("path_index") if isinstance(decisions, dict) else None
            required_index = {"pilot", "screening", "validation"}
            if (not isinstance(decisions, dict) or decisions.get("schema") != "case07-finalization-decisions/v1"
                    or decisions.get("attempt_id") != attempt_id
                    or not isinstance(index, dict) or not required_index <= index.keys()
                    or ("screen_refinement" in index and index["screen_refinement"] is not None
                        and (not isinstance(index["screen_refinement"], str)
                             or not index["screen_refinement"].startswith("native_outputs/")))
                    or not isinstance(decisions.get("selected_channel"), str)
                    or not isinstance(decisions.get("decision_events"), list)
                    or not decisions["decision_events"]):
                raise ReferenceError("decision record lacks the typed finalization path index")
            selected = decisions["selected_channel"]
            if selected not in {"C1", "C2"}:
                raise ReferenceError("selected channel is invalid")
            extra_stages = decisions.get("native_extra_stages", [])
            if not isinstance(extra_stages, list):
                raise ReferenceError("native_extra_stages must be a list")
            extra_ids: set[str] = set()
            for extra in extra_stages:
                if (not isinstance(extra, dict)
                        or set(extra) != {"stage_id", "stage_path", "route", "reason", "outcome"}
                        or not isinstance(extra["stage_id"], str)
                        or not re.fullmatch(r"[a-z][a-z0-9:_-]{0,63}", extra["stage_id"])
                        or extra["stage_id"] in extra_ids
                        or not isinstance(extra["stage_path"], str)
                        or not extra["stage_path"].startswith("native_outputs/")
                        or not isinstance(extra["route"], str) or not extra["route"].strip()
                        or not isinstance(extra["reason"], str) or not extra["reason"].strip()
                        or extra["outcome"] not in {"COMPLETED", "FAILED", "CANCELLED", "RESTARTED"}):
                    raise ReferenceError("native extra stage declaration is malformed")
                extra_ids.add(extra["stage_id"])
                extra_dir = root.joinpath(*PurePosixPath(extra["stage_path"]).parts)
                if not extra_dir.is_dir() or extra_dir.is_symlink():
                    raise ReferenceError("native extra stage directory is missing or unsafe")
                extra_receipt = native_parser.safe_json(extra_dir / "receipt.json")
                if extra_receipt.get("execution_outcome") != extra["outcome"]:
                    raise ReferenceError("native extra stage outcome differs from its raw stage receipt")
            screens = index["screening"]
            validation = index["validation"]
            if (not isinstance(screens, dict) or set(screens) != {"C1", "C2"}
                    or any(not isinstance(screens[ch], list) or len(screens[ch]) != 3 for ch in ("C1", "C2"))):
                raise ReferenceError("path index must name exactly three screening stage directories per channel")
            validation_keys = {"ts_opt", "ts_freq", "seed_minus", "seed_plus", "displacement",
                               "endpoint_minus", "endpoint_plus"}
            if not isinstance(validation, dict) or set(validation) != validation_keys:
                raise ReferenceError("path index is missing selected-channel validation paths")
            chain_files: set[str] = set()
            for side in ("endpoint_minus", "endpoint_plus"):
                endpoint = validation[side]
                if (not isinstance(endpoint, dict)
                        or set(endpoint) not in ({"opt", "freq"}, {"opt", "freq", "opt_chain"})):
                    raise ReferenceError(f"{side} must name opt/freq and may include an opt_chain")
                chain = endpoint.get("opt_chain")
                if chain is None:
                    continue
                if (not isinstance(chain, dict) or chain.get("schema") != "case07-endpoint-opt-chain/v1"
                        or not isinstance(chain.get("segments"), list) or not chain["segments"]):
                    raise ReferenceError(f"{side}.opt_chain schema/segments are malformed")
                for segment in chain["segments"]:
                    if not isinstance(segment, dict):
                        raise ReferenceError(f"{side}.opt_chain segment is malformed")
                    stage_path = segment.get("stage_path")
                    if not isinstance(stage_path, str) or not stage_path.startswith("native_outputs/"):
                        raise ReferenceError("opt_chain stage paths must remain below native_outputs/")
                    stage_dir = _relative_file(root, stage_path + "/job.inp").parent
                    for key in ("scheduler_record_path", "inventory_path", "trajectory_path", "frame_xyz_path"):
                        rel = segment.get(key)
                        digest_key = key.removesuffix("_path") + "_sha256"
                        expected_sha = segment.get(digest_key)
                        if (not isinstance(rel, str) or not rel.startswith("native_outputs/")
                                or not isinstance(expected_sha, str) or not HEX64.fullmatch(expected_sha)):
                            raise ReferenceError(f"opt_chain {key} path/hash is malformed")
                        item = _relative_file(root, rel)
                        if rel not in actual or sha256(item) != expected_sha:
                            raise ReferenceError(f"opt_chain {key} is not bound to the final manifest")
                        if key != "frame_xyz_path":
                            try:
                                item.resolve().relative_to(stage_dir.resolve())
                            except ValueError as exc:
                                raise ReferenceError("opt_chain source evidence escapes its native allocation directory") from exc
                        chain_files.add(rel)
                    inventory = json.loads(_relative_file(root, segment["inventory_path"]).read_text(encoding="utf-8"))
                    downloaded = inventory.get("locally_downloaded_files") if isinstance(inventory, dict) else None
                    if not isinstance(downloaded, list):
                        raise ReferenceError("opt_chain inventory lacks downloaded-file descriptors")
                    for row in downloaded:
                        if not isinstance(row, dict) or not isinstance(row.get("path"), str):
                            raise ReferenceError("opt_chain inventory contains a malformed file descriptor")
                        rel = str(PurePosixPath(stage_path) / row["path"])
                        item = _relative_file(root, rel)
                        if (rel not in actual or item.stat().st_size != row.get("bytes")
                                or sha256(item) != row.get("sha256")):
                            raise ReferenceError(f"opt_chain inventory file is not hash-bound: {rel}")
                        chain_files.add(rel)
            dirs = [index["pilot"]]
            if index.get("screen_refinement") is not None:
                dirs.append(index["screen_refinement"])
            dirs += [p for ch in ("C1", "C2") for p in screens[ch]]
            dirs += [validation[k] for k in ("ts_opt", "ts_freq")]
            missing_endpoint_stages = []
            for side in ("endpoint_minus", "endpoint_plus"):
                for kind in ("opt", "freq"):
                    rel = validation[side].get(kind)
                    if isinstance(rel, str) and rel.startswith("native_outputs/"):
                        dirs.append(rel)
                    else:
                        missing_endpoint_stages.append(f"{side}.{kind}")
            raw_required = set()
            for rel in dirs:
                if not isinstance(rel, str) or not rel.startswith("native_outputs/"):
                    raise ReferenceError("native stage paths must remain below native_outputs/")
                for filename in ("job.inp", "job.out", "start.xyz", "receipt.json"):
                    file_rel = str(PurePosixPath(rel) / filename)
                    _relative_file(root, file_rel)
                    raw_required.add(file_rel)
            raw_required.update(chain_files)
            opt_geometry_dirs = [validation["ts_opt"]] + [validation[side]["opt"]
                for side in ("endpoint_minus", "endpoint_plus")
                if isinstance(validation[side].get("opt"), str)]
            if index.get("screen_refinement") is not None:
                opt_geometry_dirs.insert(0, index["screen_refinement"])
            for rel in opt_geometry_dirs:
                file_rel = str(PurePosixPath(rel) / "job.xyz")
                _relative_file(root, file_rel)
                raw_required.add(file_rel)
            for ch in ("C1", "C2"):
                for rel in screens[ch]:
                    file_rel = str(PurePosixPath(rel) / "job.engrad")
                    _relative_file(root, file_rel)
                    raw_required.add(file_rel)
            for rel in [validation["ts_freq"]] + [validation[side]["freq"]
                        for side in ("endpoint_minus", "endpoint_plus")
                        if isinstance(validation[side].get("freq"), str)]:
                file_rel = str(PurePosixPath(rel) / "job.hess")
                _relative_file(root, file_rel)
                raw_required.add(file_rel)
            for key in ("seed_minus", "seed_plus", "displacement"):
                if not isinstance(validation[key], str) or not validation[key].startswith("native_outputs/"):
                    raise ReferenceError(f"{key} must remain below native_outputs/")
                _relative_file(root, validation[key]); raw_required.add(validation[key])
            if index.get("screen_refinement") is None:
                seed = decisions.get("optts_seed_decision")
                if (not isinstance(seed, dict) or seed.get("schema") != "case07-optts-decision/v1"
                        or seed.get("selected_channel") != selected
                        or not isinstance(seed.get("rationale"), str) or not seed["rationale"].strip()):
                    raise ReferenceError("optional refinement requires a typed, selected-channel OptTS seed decision")
                source_rel, source_sha = seed.get("source_path"), seed.get("source_sha256")
                ts_start_rel = str(PurePosixPath(validation["ts_opt"]) / "start.xyz")
                ts_start_sha = seed.get("ts_opt_start_xyz_sha256")
                if (not isinstance(source_rel, str) or not source_rel.startswith("native_outputs/")
                        or not source_rel.endswith(".xyz") or source_rel == ts_start_rel
                        or not isinstance(source_sha, str) or not HEX64.fullmatch(source_sha)
                        or not isinstance(ts_start_sha, str) or not HEX64.fullmatch(ts_start_sha)):
                    raise ReferenceError("OptTS seed decision must bind a distinct native XYZ source and the TS start XYZ")
                source_path = _relative_file(root, source_rel)
                ts_start_path = _relative_file(root, ts_start_rel)
                if (source_sha != sha256(source_path) or ts_start_sha != sha256(ts_start_path)
                        or source_rel not in actual or ts_start_rel not in actual):
                    raise ReferenceError("OptTS seed decision does not match hash-bound source/start geometry")
                source_elements, source_coords = parse_xyz(source_path)
                start_elements, start_coords = parse_xyz(ts_start_path)
                if source_elements != start_elements or source_coords != start_coords:
                    raise ReferenceError("OptTS start geometry differs from its declared native XYZ seed source")
                raw_required.add(source_rel)
            if raw_required - actual:
                raise ReferenceError("raw stage files are not hash-bound: " + ", ".join(sorted(raw_required-actual)))
            if decision_rel not in actual:
                raise ReferenceError("decision record is not hash-bound in the final bundle")
            required_manifest = {"authorization_ref", "started_at_utc", "reported_at_utc",
                                 "public_input_sha256", "preparation_manifest_sha256"}
            if (not required_manifest <= manifest.keys()
                    or not isinstance(manifest.get("authorization_ref"), str)
                    or not manifest["authorization_ref"].strip()
                    or manifest["public_input_sha256"] != PUBLIC_ASSET_HASHES):
                raise ReferenceError("final manifest lacks authorization/timing/public-input bindings")
            prep_path = _relative_file(root, "preparation.json")
            if "preparation.json" not in actual or sha256(prep_path) != manifest["preparation_manifest_sha256"]:
                raise ReferenceError("final manifest does not bind the original preparation record")
            start_time, report_time = (manifest.get("started_at_utc"), manifest.get("reported_at_utc"))
            if not isinstance(start_time, str) or not isinstance(report_time, str):
                raise ReferenceError("final attempt timestamps are missing")
            start_dt = datetime.fromisoformat(start_time.removesuffix("Z") + ("+00:00" if start_time.endswith("Z") else ""))
            report_dt = datetime.fromisoformat(report_time.removesuffix("Z") + ("+00:00" if report_time.endswith("Z") else ""))
            if report_dt < start_dt:
                raise ReferenceError("final bundle report submission precedes attempt start")
            if missing_endpoint_stages:
                status["reason"] = "required endpoint stages are still pending"
                status["missing_evidence"] = sorted(missing_endpoint_stages)
                status["opt_chain_provenance"] = "hash-bound; no failed-stage scientific credit"
                output.mkdir(parents=True, exist_ok=False)
                _write(output / "finalization-status.json",
                       json.dumps(status, indent=2, sort_keys=True, allow_nan=False) + "\n")
                return status
            return _finalize_from_index(root, output, assets, manifest, decisions, index)
        except (ReferenceError, KeyError, TypeError, OSError, json.JSONDecodeError) as exc:
            if output.exists():
                shutil.rmtree(output)
            output.mkdir(parents=True, exist_ok=False)
            status["reason"] = f"final path index is incomplete or invalid: {exc}"
            status["missing_evidence"] = ["valid decision_records.path_index"]
            if str(exc).startswith("NATIVE_AUDIT_NOT_PASS:"):
                status["status"] = "NATIVE_AUDIT_NOT_PASS"
                status["native_reparse"] = "COMPLETED"
                status["candidate_report_generated"] = False
                status["final_contract_generated"] = False
                status["final_artifacts_assembled"] = False
    else:
        output.mkdir(parents=True, exist_ok=False)
    _write(output / "finalization-status.json", json.dumps(status, indent=2, sort_keys=True, allow_nan=False) + "\n")
    return status


def parse_xyz(path: Path) -> tuple[list[str], list[list[float]]]:
    if path.is_symlink() or not path.is_file():
        raise ReferenceError("XYZ is missing or unsafe")
    lines = path.read_text(encoding="utf-8", errors="strict").splitlines()
    if len(lines) != 23 or lines[0].strip() != "21":
        raise ReferenceError("XYZ must contain exactly 21 atoms")
    elements, coords = [], []
    for line in lines[2:]:
        row = line.split()
        if len(row) != 4:
            raise ReferenceError("malformed XYZ coordinate row")
        elements.append(row[0])
        values = [float(value) for value in row[1:]]
        if any(not math.isfinite(value) for value in values):
            raise ReferenceError("XYZ coordinates must be finite")
        coords.append(values)
    return elements, coords


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument("--prepare", action="store_true", help="prepare public pilot/screen inputs; no external calls")
    modes.add_argument("--ingest", action="store_true", help="validate and reparse fresh screening bundle raw files")
    modes.add_argument("--advance", action="store_true", help="prepare one later ORCA/mode stage from parsed evidence")
    modes.add_argument("--finalize", action="store_true", help="reparse complete later-stage raw bundle and assemble native-audited candidate artifacts")
    parser.add_argument("--assets", type=Path, help="public assets directory (required for preparation, ingestion, and finalization)")
    parser.add_argument("--bundle", type=Path, help="fresh bundle directory (required for --ingest)")
    parser.add_argument("--source-result", type=Path, help="hash-bound reparsed screening/native stage facts")
    parser.add_argument("--decision-json", type=Path, help="scientific decision record for refinement/OptTS")
    parser.add_argument("--stage", choices=sorted(set(STAGE_CAPS) | {"mode_displacement"}),
                        help="later stage to prepare for --advance")
    parser.add_argument("--final-profile", choices=sorted(FINAL_LEVEL_PROFILES),
                        help="frozen final-method profile for production-stage preparation")
    parser.add_argument("--pilot-profile", choices=sorted(PILOT_PROFILES),
                        help="frozen pilot method profile for --prepare")
    parser.add_argument("--pilot-action", choices=("SP", "EnGrad"),
                        help="native pilot action for --prepare")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.prepare:
            if (args.assets is None or args.bundle is not None or args.source_result is not None
                    or args.decision_json is not None or args.stage is not None or args.final_profile is not None):
                parser.error("--prepare requires only --assets, --output, and optional --attempt-id")
            result = prepare(args.assets, args.output,
                             pilot_profile=args.pilot_profile or "legacy-pbe-screen",
                             pilot_action=args.pilot_action or "SP")
            print(json.dumps({"status": result["status"], "attempt_id": result["attempt_id"], "output": str(args.output),
                              "stage_count": len(result["stages"]), "submit_file": "submit-case07-screening.sbatch"},
                             sort_keys=True))
        elif args.ingest:
            if (args.bundle is None or args.assets is None or args.source_result is not None
                    or args.decision_json is not None or args.stage is not None or args.final_profile is not None
                    or args.pilot_profile is not None or args.pilot_action is not None):
                parser.error("--ingest requires --bundle and --assets")
            result = ingest(args.bundle, args.output, args.assets)
            print(json.dumps({"status": result["status"], "output": str(args.output),
                              "stage_count": len(result["stage_facts"]),
                              "selected_channel_by_frozen_rule": result["selected_channel_by_frozen_rule"]},
                             sort_keys=True))
        elif args.finalize:
            if (args.bundle is None or args.assets is None or args.source_result is not None
                    or args.decision_json is not None or args.stage is not None or args.final_profile is not None
                    or args.pilot_profile is not None or args.pilot_action is not None):
                parser.error("--finalize requires --bundle, --assets, and --output")
            result = finalize_preflight(args.bundle, args.output, args.assets)
            print(json.dumps({"status": result["status"], "output": str(args.output),
                              "missing_evidence_count": len(result.get("missing_evidence", [])),
                              "final_contract_generated": result["final_contract_generated"]}, sort_keys=True))
        else:
            if args.source_result is None or args.stage is None or args.assets is not None or args.bundle is not None:
                parser.error("--advance requires --source-result and --stage; it does not accept --assets/--bundle")
            if args.pilot_profile is not None or args.pilot_action is not None:
                parser.error("--pilot-profile/--pilot-action are only valid with --prepare")
            result = advance(args.source_result, args.output, args.stage, args.decision_json,
                             args.final_profile or "r2scan-3c")
            print(json.dumps({"status": result["status"], "attempt_id": result["attempt_id"],
                              "stage": result["stage"], "output": str(args.output)}, sort_keys=True))
        return 0
    except (ReferenceError, OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
