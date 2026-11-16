#!/usr/bin/env python3
# L1 Deliverables: Check required deliverables for completeness and parseability.
# L2 Execution: Check execution evidence through bounded replay or independent recomputation where implemented.
# L3 Science: Generate an isolated water molecule.
"""Portable verifier for the isolated H2O structure-generation case."""
from __future__ import annotations

import argparse
import ctypes
import json
import hashlib
import math
import os
import resource
import signal
import subprocess
import sys
import tempfile
import shutil
from pathlib import Path

# Resource bounds for the isolated candidate-generator replay.
MAX_STREAM_CHARS = 12_000
TIMEOUT_SECONDS = 10
MAX_GENERATOR_FILE_BYTES = 1024 * 1024
MAX_GENERATOR_ADDRESS_SPACE = 512 * 1024 * 1024
MAX_GENERATOR_PROCESSES = 16
MAX_CANDIDATE_TMPFS_BYTES = 128 * 1024 * 1024


class EvaluationError(Exception):
    pass


class ScientificFailure(Exception):
    pass


EXPECTED_REFS_SHA256 = "a29559ec00dd055b137893ffc4a57fb0650de04d2f0de5ea1ecb022bf70c3a96"


def load_reference(tests_dir: Path) -> dict:
    path = tests_dir / "refs.json"
    if not path.is_file() or path.is_symlink():
        raise EvaluationError("hidden scientific reference is missing or unsafe")
    try:
        raw = path.read_bytes()
        if hashlib.sha256(raw).hexdigest() != EXPECTED_REFS_SHA256:
            raise EvaluationError("trusted scientific reference integrity check failed")
        ref = json.loads(raw.decode("utf-8"))
    except EvaluationError:
        raise
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise EvaluationError(f"hidden scientific reference is unreadable: {exc}") from exc
    try:
        species = ref["species"]
        geometry = ref["geometry_anchor"]
        if (ref.get("schema_version") != "1.0" or species["formula"] != "H2O"
                or species["atom_count"] != 3 or species["elements"] != {"H": 2, "O": 1}
                or species["net_charge"] != 0 or not isinstance(geometry["source_sha256"], str)
                or len(geometry["source_sha256"]) != 64):
            raise EvaluationError("trusted reference is incomplete or inconsistent")
        for field in (geometry["rOH_A"], geometry["aHOH_deg"]):
            for key in ("value", "tolerance"):
                value = field[key]
                if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
                    raise EvaluationError("trusted geometric references must be finite and nonnegative")
        repeat_tolerance = ref["geometry_repeat_tolerance"]
        if type(repeat_tolerance) not in (int, float) or not math.isfinite(repeat_tolerance) or repeat_tolerance <= 0:
            raise EvaluationError("trusted repeatability tolerance is invalid")
    except (KeyError, TypeError) as exc:
        raise EvaluationError(f"hidden scientific reference is incomplete: {exc}") from exc
    return ref

def parse_xyz(path: Path) -> list[tuple[str, tuple[float, float, float]]]:
    if not path.is_file() or path.is_symlink():
        raise ScientificFailure(f"required XYZ is missing or unsafe: {path.name}")
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError) as exc:
        raise ScientificFailure(f"cannot read XYZ: {exc}") from exc
    if len(lines) < 5:
        raise ScientificFailure("XYZ must contain an atom-count line, comment, and three atom rows")
    try:
        count = int(lines[0].strip())
    except ValueError as exc:
        raise ScientificFailure("XYZ first line must be the integer atom count") from exc
    if count != 3:
        raise ScientificFailure(f"XYZ atom count must be 3, found {count}")
    body = [line for line in lines[2:] if line.strip()]
    if len(body) != count:
        raise ScientificFailure(f"XYZ must contain exactly {count} non-empty atom rows")
    atoms = []
    for idx, line in enumerate(body, 1):
        fields = line.split()
        if len(fields) < 4:
            raise ScientificFailure(f"XYZ atom row {idx} needs an element and three coordinates")
        element = fields[0]
        if element not in {"H", "O"}:
            raise ScientificFailure(f"unsupported element in water geometry: {element!r}")
        try:
            xyz = tuple(float(x) for x in fields[1:4])
        except ValueError as exc:
            raise ScientificFailure(f"XYZ atom row {idx} has a non-numeric coordinate") from exc
        if not all(math.isfinite(x) for x in xyz):
            raise ScientificFailure(f"XYZ atom row {idx} has a non-finite coordinate")
        atoms.append((element, xyz))
    if sorted(a[0] for a in atoms) != ["H", "H", "O"]:
        raise ScientificFailure("XYZ composition must be exactly one O and two H")
    return atoms


def norm(v: tuple[float, float, float]) -> float:
    return math.sqrt(sum(x * x for x in v))


def geometry(atoms: list[tuple[str, tuple[float, float, float]]]) -> dict:
    oxygens = [xyz for el, xyz in atoms if el == "O"]
    hydrogens = [xyz for el, xyz in atoms if el == "H"]
    if len(oxygens) != 1 or len(hydrogens) != 2:
        raise ScientificFailure("water geometry must contain one O and two H")
    o = oxygens[0]
    vecs = [tuple(h[i] - o[i] for i in range(3)) for h in hydrogens]
    distances = [norm(v) for v in vecs]
    hh = norm(tuple(hydrogens[0][i] - hydrogens[1][i] for i in range(3)))
    if min(distances + [hh]) < 0.5:
        raise ScientificFailure("geometry contains an atomic overlap or near-zero bond")
    dot = sum(vecs[0][i] * vecs[1][i] for i in range(3))
    cosine = dot / (distances[0] * distances[1])
    angle = math.degrees(math.acos(max(-1.0, min(1.0, cosine))))
    if not (0.0 < angle < 180.0):
        raise ScientificFailure("H–O–H angle is degenerate")
    return {"rOH_A": sorted(distances), "rHH_A": hh, "aHOH_deg": angle}


def assess_geometry(g: dict, ref: dict, label: str) -> None:
    geom_ref = ref["geometry_anchor"]
    r = geom_ref["rOH_A"]
    lo, hi = r["value"] - r["tolerance"], r["value"] + r["tolerance"]
    for i, distance in enumerate(g["rOH_A"], 1):
        if not lo <= distance <= hi:
            raise ScientificFailure(f"{label}: O–H distance {i} is {distance:.6f} Å; accepted interval is {lo:.3f}–{hi:.3f} Å")
    a = geom_ref["aHOH_deg"]
    lo, hi = a["value"] - a["tolerance"], a["value"] + a["tolerance"]
    if not lo <= g["aHOH_deg"] <= hi:
        raise ScientificFailure(f"{label}: H–O–H angle is {g['aHOH_deg']:.6f}°; accepted interval is {lo:.4f}–{hi:.4f}°")


def _candidate_preexec(rootfs: Path) -> None:
    """Enter a private Python-only chroot, then drop every candidate privilege."""
    os.chroot(rootfs)
    os.chdir("/work")
    resource.setrlimit(resource.RLIMIT_CPU, (TIMEOUT_SECONDS, TIMEOUT_SECONDS + 1))
    resource.setrlimit(resource.RLIMIT_FSIZE, (MAX_GENERATOR_FILE_BYTES, MAX_GENERATOR_FILE_BYTES))
    resource.setrlimit(resource.RLIMIT_NPROC, (MAX_GENERATOR_PROCESSES, MAX_GENERATOR_PROCESSES))
    resource.setrlimit(resource.RLIMIT_NOFILE, (32, 32))
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    resource.setrlimit(resource.RLIMIT_AS, (MAX_GENERATOR_ADDRESS_SPACE, MAX_GENERATOR_ADDRESS_SPACE))
    os.umask(0o077)
    os.setgroups([])
    os.setgid(65534)
    os.setuid(65534)
    libc = ctypes.CDLL(None, use_errno=True)
    if libc.prctl(38, 1, 0, 0, 0) != 0:  # PR_SET_NO_NEW_PRIVS
        err = ctypes.get_errno()
        raise OSError(err, os.strerror(err), "prctl(PR_SET_NO_NEW_PRIVS)")


def _bounded_candidate_temp_root() -> Path:
    """Require an executable bounded tmpfs for the replay chroot, not grader disk."""
    mount = None
    try:
        for line in Path("/proc/self/mountinfo").read_text(encoding="utf-8").splitlines():
            fields = line.split()
            if len(fields) < 10 or fields[4].replace("\\040", " ") != "/dev/shm":
                continue
            separator = fields.index("-")
            if fields[separator + 1] != "tmpfs":
                continue
            mount_options = fields[5].split(",")
            super_options = fields[separator + 3].split(",")
            size_option = next((option for option in super_options if option.startswith("size=")), None)
            if size_option is None:
                continue
            size_text = size_option[5:]
            multiplier = 1
            if size_text.endswith("k"):
                multiplier, size_text = 1024, size_text[:-1]
            elif size_text.endswith("m"):
                multiplier, size_text = 1024**2, size_text[:-1]
            elif size_text.endswith("g"):
                multiplier, size_text = 1024**3, size_text[:-1]
            mount = int(size_text) * multiplier
            if "noexec" in mount_options or not {"nosuid", "nodev"}.issubset(mount_options):
                raise EvaluationError("candidate replay /dev/shm tmpfs must be executable, nosuid, and nodev")
            break
    except (OSError, ValueError, IndexError) as exc:
        raise EvaluationError(f"cannot verify bounded /dev/shm for candidate replay: {exc}") from exc
    if mount is None or mount <= 0 or mount > MAX_CANDIDATE_TMPFS_BYTES:
        raise EvaluationError("candidate replay requires executable /dev/shm tmpfs capped at 128 MiB or less")
    if Path("/dev/shm").is_symlink() or not Path("/dev/shm").is_dir():
        raise EvaluationError("candidate replay /dev/shm path is missing or unsafe")
    return Path("/dev/shm")


def run(app_dir: Path, tests_dir: Path) -> tuple[str, str, dict]:
    ref = load_reference(tests_dir)
    final = app_dir / "final"
    xyz_path = final / "water.xyz"
    script = final / "generate_water.py"
    if not script.is_file() or script.is_symlink():
        raise ScientificFailure("required generator final/generate_water.py is missing or unsafe")
    submitted = geometry(parse_xyz(xyz_path))
    assess_geometry(submitted, ref, "submitted XYZ")

    rootfs_setting = os.environ.get("CCB_PYTHON_ROOTFS")
    if not rootfs_setting:
        raise EvaluationError("Python 3.12 candidate chroot is not configured")
    configured_rootfs = Path(rootfs_setting)
    if configured_rootfs.is_symlink() or not configured_rootfs.is_dir():
        raise EvaluationError("Python 3.12 candidate chroot is missing or unsafe")
    rootfs_source = configured_rootfs.resolve(strict=True)
    if not (rootfs_source / "usr/bin/python3").is_file():
        raise EvaluationError("Python 3.12 candidate chroot lacks its interpreter")
    if os.geteuid() != 0:
        raise EvaluationError("candidate chroot requires the verifier to run as root")

    temp_root = _bounded_candidate_temp_root()
    with tempfile.TemporaryDirectory(prefix="h2o-chroot-replay-", dir=temp_root) as temp_name:
        rootfs = Path(temp_name) / "rootfs"
        try:
            shutil.copytree(rootfs_source, rootfs, symlinks=True)
        except OSError as exc:
            raise EvaluationError(f"cannot stage the private candidate chroot: {exc}") from exc
        work = rootfs / "work"
        if work.is_symlink() or not work.is_dir():
            raise EvaluationError("candidate chroot work directory is missing or unsafe")
        os.chmod(work, 0o777)
        isolated_script = work / "generate_water.py"
        try:
            shutil.copyfile(script, isolated_script)
            os.chmod(isolated_script, 0o444)
        except OSError as exc:
            raise ScientificFailure(f"cannot stage generator for clean-directory execution: {exc}") from exc
        proc = None
        try:
            proc = subprocess.Popen(
                ["/usr/bin/python3", "-I", "/work/generate_water.py"],
                stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                text=True, encoding="utf-8", errors="replace", env={
                    "HOME": "/work", "LANG": "C.UTF-8", "PATH": "/usr/bin:/bin",
                }, close_fds=True, start_new_session=True,
                preexec_fn=lambda: _candidate_preexec(rootfs),
            )
            try:
                stdout, stderr = proc.communicate(timeout=TIMEOUT_SECONDS)
            except subprocess.TimeoutExpired as exc:
                try:
                    os.killpg(proc.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                stdout, stderr = proc.communicate()
                raise ScientificFailure(
                    f"generator exceeded {TIMEOUT_SECONDS}s timeout; stdout={stdout[-MAX_STREAM_CHARS:]!r}; stderr={stderr[-MAX_STREAM_CHARS:]!r}"
                ) from exc
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        except subprocess.TimeoutExpired as exc:
            raise ScientificFailure(f"generator exceeded {TIMEOUT_SECONDS}s timeout") from exc
        except (OSError, subprocess.SubprocessError) as exc:
            raise EvaluationError(f"could not start isolated Python 3.12 chroot: {exc}") from exc
        captured = {
            "returncode": proc.returncode,
            "stdout": stdout[-MAX_STREAM_CHARS:],
            "stderr": stderr[-MAX_STREAM_CHARS:],
            "isolation": "chroot+uid65534+no_new_privileges+rlimits+outer-network-none",
        }
        if proc.returncode != 0:
            raise ScientificFailure(f"generator exited {proc.returncode}; captured={captured!r}")
        regenerated = geometry(parse_xyz(work / "water.xyz"))
        assess_geometry(regenerated, ref, "regenerated XYZ")

    tol = ref["geometry_repeat_tolerance"]
    delta_oh = max(abs(a - b) for a, b in zip(submitted["rOH_A"], regenerated["rOH_A"]))
    delta_hh = abs(submitted["rHH_A"] - regenerated["rHH_A"])
    delta_angle = abs(submitted["aHOH_deg"] - regenerated["aHOH_deg"])
    if max(delta_oh, delta_hh, delta_angle) > tol:
        raise ScientificFailure(
            "generator output does not reproduce the submitted geometry within invariant tolerance "
            f"{tol:g}; max deltas: OH={delta_oh:.3g} Å, HH={delta_hh:.3g} Å, angle={delta_angle:.3g}°"
        )
    return "PASS", "scientific outputs and repeatability passed", {
        "reward": 1,
        "submitted_geometry": submitted,
        "regenerated_geometry": regenerated,
        "repeatability_max_delta": max(delta_oh, delta_hh, delta_angle),
        "generator_process": captured,
        "scientific_scope": "isolated-molecule geometry and reproducible generation only",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--app-dir", required=True, type=Path)
    parser.add_argument("--tests-dir", required=True, type=Path)
    args = parser.parse_args()
    try:
        status, message, details = run(args.app_dir.resolve(), args.tests_dir.resolve())
        payload = {"status": status, "message": message, **details}
        code = 0
    except EvaluationError as exc:
        payload = {"status": "ERROR", "message": str(exc), "reward": None}
        code = 2
    except ScientificFailure as exc:
        payload = {"status": "FAIL", "message": str(exc), "reward": 0}
        code = 1
    except Exception as exc:  # evaluator faults must never masquerade as scientific failure
        payload = {"status": "ERROR", "message": f"verifier internal error: {type(exc).__name__}: {exc}", "reward": None}
        code = 2
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
