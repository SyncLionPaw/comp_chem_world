#!/usr/bin/env python3
# L1 Deliverables: Check required deliverables for completeness and parseability.
# L2 Execution: Check execution evidence through bounded replay or independent recomputation where implemented.
# L3 Science: Solve the coupled Poisson–Fermi double layer.
"""Private full-profile and off-grid replay verifier for case 005."""
from __future__ import annotations

import csv
import ctypes
import hashlib
import itertools
import json
import math
import os
import pwd
import re
import resource
import shutil
import signal
import subprocess
import stat
import sys
import tempfile
import time
from pathlib import Path

# The private physics-checker snapshot is hash-bound; don't create untracked
# bytecode in the protected Gold directory when importing it.
sys.dont_write_bytecode = True
import numpy as np

HERE = Path(__file__).resolve().parent
CASE = HERE.parent
GOLD = HERE / "_data" / "gold"
APP = Path(os.environ.get("BENCH_APP", "/app"))
RUNTIME_REQUEST = APP / "request" / "edl_request.json"
AUTHOR_REQUEST = CASE / "environment" / "assets" / "edl_request.json"
PUBLIC_REQUEST = RUNTIME_REQUEST if RUNTIME_REQUEST.is_file() else AUTHOR_REQUEST
PUBLIC_SPEC = json.loads(PUBLIC_REQUEST.read_text(encoding="utf-8"))
sys.path.insert(0, str(GOLD))
import physics_verifier

EXPECTED_COLUMNS = [
    "run_id", "concentration_mM", "Pbar_C_m2", "sigma0_C_m2",
    "temperature_K", "alpha", "cell_length_nm", "z_A", "phi_V",
    "P1_C_m2", "P1_prime_C_m3", "P1_second_C_m4", "P2_C_m2",
    "P2_prime_C_m3", "n_plus_m3", "n_minus_m3", "site_occupancy",
    "liquid_fraction", "rho1_wall_C_m3", "rho_total_wall_C_m3",
]
NUMERICAL = PUBLIC_SPEC["output_contract"]["numeric_tolerances"]
SHARP_TOL = {name: (value["absolute"], value["relative"])
             for name, value in NUMERICAL["sharp"].items()}
SMEARED_TOL = {name: (value["absolute"], value["relative"])
               for name, value in NUMERICAL["smeared"].items()}
METADATA_TOL = {name: (NUMERICAL["metadata"]["absolute"],
                        NUMERICAL["metadata"]["relative"])
                for name in EXPECTED_COLUMNS[1:7]}
METADATA_TOL.update({name: (NUMERICAL["metadata"][name]["absolute"],
                            NUMERICAL["metadata"][name]["relative"])
                     for name in ("rho1_wall_C_m3", "rho_total_wall_C_m3")})


def _finish(code: int, message: str, detail: dict | None = None) -> int:
    logs = os.environ.get("BENCH_LOGS")
    if logs:
        output = Path(logs)
        output.mkdir(parents=True, exist_ok=True)
        if code == 2:
            (output / "reward.txt").unlink(missing_ok=True)
            (output / "verification.json").unlink(missing_ok=True)
        else:
            reward = int(code == 0)
            (output / "reward.txt").write_text(f"{reward}\n", encoding="utf-8")
            report = {"status": "PASS" if reward else "FAIL", "reward": reward,
                      "message": message, "details": detail or {}}
            (output / "verification.json").write_text(
                json.dumps(report, indent=2, default=_json_value) + "\n", encoding="utf-8")
    return code


def _json_value(value):
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, np.ndarray):
        return value.tolist()
    raise TypeError(f"cannot encode {type(value).__name__}")


def _fail(message: str, detail: dict | None = None) -> int:
    print("FAIL L3: " + message, file=sys.stderr)
    return _finish(1, message, detail)


def _infra(message: str) -> int:
    print("ERROR L0: " + message, file=sys.stderr)
    return _finish(2, message)


def _sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _integrity_manifest() -> dict:
    manifest_path = GOLD / "manifest.json"
    if not manifest_path.is_file():
        raise RuntimeError("private Gold manifest is missing")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("schema") != "bench14.case005.gold-manifest/v1":
        raise RuntimeError("unsupported private Gold manifest")
    if manifest.get("public_request_sha256") != _sha(PUBLIC_REQUEST):
        raise RuntimeError("public request hash differs from the frozen Gold input")
    outputs = manifest.get("reference_outputs")
    if not isinstance(outputs, dict) or not outputs:
        raise RuntimeError("private Gold output hash list is empty")
    for relative, info in outputs.items():
        path = GOLD / relative
        if not path.is_file() or path.is_symlink():
            raise RuntimeError(f"private Gold asset missing or unsafe: {relative}")
        if path.stat().st_size != info.get("bytes") or _sha(path) != info.get("sha256"):
            raise RuntimeError(f"private Gold asset hash mismatch: {relative}")
    if len(manifest.get("private_probes", [])) != 4:
        raise RuntimeError("private probe manifest is incomplete")
    for probe in manifest["private_probes"]:
        request_path = GOLD / probe["request_file"]
        if not request_path.is_file() or request_path.is_symlink() or _sha(request_path) != probe.get("request_sha256"):
            raise RuntimeError(f"private request corrupt: {probe.get('request_file')}")
        expected = probe["parameters"]
        request = json.loads(request_path.read_text(encoding="utf-8"))
        if request["conditions"][0]["concentration_mM"] != expected["concentration_mM"]:
            raise RuntimeError("private probe parameter provenance mismatch")
    return manifest


def _demote() -> None:
    nobody = pwd.getpwnam("nobody")
    os.setgroups([])
    os.setgid(nobody.pw_gid)
    os.setuid(nobody.pw_uid)
    if ctypes.CDLL(None).prctl(38, 1, 0, 0, 0) != 0:
        raise OSError("PR_SET_NO_NEW_PRIVS failed")
    resource.setrlimit(resource.RLIMIT_CPU, (240, 240))
    resource.setrlimit(resource.RLIMIT_FSIZE, (256 * 1024 * 1024, 256 * 1024 * 1024))
    resource.setrlimit(resource.RLIMIT_NPROC, (1, 1))


def _process(argv: list[str], cwd: Path, env: dict[str, str], timeout: int):
    proc = subprocess.Popen(argv, cwd=cwd, env=env, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, text=True,
                            start_new_session=True, preexec_fn=_demote)
    try:
        stdout, stderr = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        os.killpg(proc.pid, signal.SIGKILL)
        stdout, stderr = proc.communicate()
        raise subprocess.TimeoutExpired(argv, timeout, output=stdout, stderr=stderr)
    finally:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    return subprocess.CompletedProcess(argv, proc.returncode, stdout, stderr)


def _isolation_probe() -> dict:
    if os.geteuid() != 0:
        raise RuntimeError("private source isolation requires a root verifier")
    with tempfile.TemporaryDirectory(prefix="case005-iso-") as temp:
        root = Path(temp)
        os.chmod(root, 0o755)
        private = root / "private"
        private.mkdir(mode=0o700)
        reference = private / "gold.json"
        reference.write_text("private", encoding="utf-8")
        reference.chmod(0o600)
        reward_dir = root / "reward"
        reward_dir.mkdir(mode=0o700)
        reward_file = reward_dir / "reward.txt"
        gold_manifest = GOLD / "manifest.json"
        work = root / "work"
        work.mkdir(mode=0o777)
        marker = work / "probe.json"
        probe = work / "probe.py"
        probe.write_text(
            "import json,os,pathlib\n"
            f"private=pathlib.Path({str(reference)!r}); gold=pathlib.Path({str(gold_manifest)!r}); reward=pathlib.Path({str(reward_file)!r})\n"
            "out={}\n"
            "for key,path in [('read_private',private),('write_private',private),('write_reward',reward)]:\n"
            " try:\n"
            "  if key.startswith('write'): path.write_text('1')\n"
            "  else: path.read_text()\n"
            "  out[key]='allowed'\n"
            " except PermissionError: out[key]='denied'\n"
            " except Exception as e: out[key]=type(e).__name__\n"
            "try: gold.read_text(); out['read_gold']='allowed'\n"
            "except PermissionError: out['read_gold']='denied'\n"
            "except Exception as e: out['read_gold']=type(e).__name__\n"
            "try:\n pid=os.fork()\n if pid==0: os._exit(0)\n out['fork']='allowed'\n"
            "except OSError: out['fork']='denied'\n"
            f"pathlib.Path({str(marker)!r}).write_text(json.dumps(out))\n",
            encoding="utf-8")
        os.chmod(work, 0o777)
        env = {"PATH": "/usr/local/bin:/usr/bin:/bin", "HOME": str(root),
               "PYTHONNOUSERSITE": "1", "PYTHONDONTWRITEBYTECODE": "1"}
        child = _process([sys.executable, str(probe)], work, env, 10)
        if child.returncode != 0 or not marker.is_file():
            raise RuntimeError(f"isolation probe failed rc={child.returncode}; {child.stderr[-500:]}")
        result = json.loads(marker.read_text())
        expected = {"read_private": "denied", "write_private": "denied",
                    "write_reward": "denied", "read_gold": "denied", "fork": "denied"}
        if result != expected:
            raise RuntimeError(f"candidate uid can access protected state: {result}")
        return result


def _stage_candidate(final: Path, workspace: Path) -> str | None:
    for component in (final, *final.parents):
        try:
            if stat.S_ISLNK(component.lstat().st_mode):
                return f"candidate path contains a symlink: {component}"
        except OSError as exc:
            return f"cannot inspect candidate path component {component}: {exc}"
    if final.is_symlink() or not final.is_dir():
        return "candidate final path must be a real directory"
    copied: list[str] = []
    dir_flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        final_fd = os.open(final, dir_flags)
    except OSError as exc:
        return f"cannot safely open candidate final directory: {exc}"
    try:
        for name in sorted(os.listdir(final_fd)):
            try:
                st = os.stat(name, dir_fd=final_fd, follow_symlinks=False)
            except OSError as exc:
                return f"cannot inspect candidate helper {name}: {exc}"
            if stat.S_ISLNK(st.st_mode):
                return f"candidate helper may not be a symlink: {name}"
            if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*\.py", name):
                continue
            if not stat.S_ISREG(st.st_mode):
                return f"candidate helper must be a regular file within final/: {name}"
            if st.st_nlink != 1:
                return f"candidate helper must not be hard-linked: {name}"
            if st.st_size > 2 * 1024 * 1024:
                return f"candidate helper is too large: {name}"
            try:
                src_fd = os.open(name, os.O_RDONLY | os.O_NONBLOCK |
                                 getattr(os, "O_NOFOLLOW", 0), dir_fd=final_fd)
                opened = os.fstat(src_fd)
                if not stat.S_ISREG(opened.st_mode) or not os.path.samestat(st, opened):
                    os.close(src_fd)
                    return f"candidate helper changed while staging: {name}"
                dst_fd = os.open(workspace / name,
                    os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o644)
                with os.fdopen(src_fd, "rb") as source, os.fdopen(dst_fd, "wb") as destination:
                    shutil.copyfileobj(source, destination)
            except OSError as exc:
                return f"cannot safely stage candidate helper {name}: {exc}"
            copied.append(name)
    finally:
        os.close(final_fd)
    if "solver.py" not in copied:
        return "candidate must submit final/solver.py"
    return None


def _read_submitted_artifacts(final: Path):
    """Read the user's actual deliverables using no-follow directory FDs."""
    for component in (final, *final.parents):
        try:
            if stat.S_ISLNK(component.lstat().st_mode):
                return None, f"submitted artifact path contains a symlink: {component}"
        except OSError as exc:
            return None, f"cannot inspect submitted artifact path {component}: {exc}"
    if not final.is_dir():
        return None, "submitted final directory is missing or is not a directory"
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        directory_fd = os.open(final, flags)
    except OSError as exc:
        return None, f"cannot safely open submitted final directory: {exc}"
    artifacts = {}
    try:
        for name in ("dl_profiles_sharp.csv", "dl_profiles_smeared.csv",
                     "analysis.json", "solver.log"):
            try:
                before = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
                if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
                    return None, f"submitted artifact must be a regular single-link file: {name}"
                if before.st_size > 128 * 1024 * 1024:
                    return None, f"submitted artifact is oversized: {name}"
                fd = os.open(name, os.O_RDONLY | os.O_NONBLOCK |
                             getattr(os, "O_NOFOLLOW", 0), dir_fd=directory_fd)
                with os.fdopen(fd, "rb") as stream:
                    after = os.fstat(stream.fileno())
                    if (not stat.S_ISREG(after.st_mode) or after.st_nlink != 1
                            or not os.path.samestat(before, after)):
                        return None, f"submitted artifact changed during safe open: {name}"
                    payload = stream.read()
                    if len(payload) != after.st_size:
                        return None, f"submitted artifact changed while reading: {name}"
                    artifacts[name] = payload
            except OSError as exc:
                return None, f"submitted artifact missing or unsafe: {name}: {exc}"
    finally:
        os.close(directory_fd)
    return artifacts, None


def _run_candidate(final: Path, request_file: Path, timeout: int = 300):
    with tempfile.TemporaryDirectory(prefix="case005-candidate-") as temp:
        root = Path(temp)
        os.chmod(root, 0o755)
        workspace = root / "workspace"
        workspace.mkdir(mode=0o777)
        err = _stage_candidate(final, workspace)
        if err:
            return None, err
        readonly = workspace / "request"
        readonly.mkdir(mode=0o555)
        copied_request = readonly / "input.json"
        shutil.copyfile(request_file, copied_request)
        os.chmod(copied_request, 0o444)
        output = workspace / "final"
        output.mkdir(mode=0o777)
        os.chmod(output, 0o777)
        env = {"PATH": "/usr/local/bin:/usr/bin:/bin", "HOME": str(root),
               "PYTHONNOUSERSITE": "1", "PYTHONDONTWRITEBYTECODE": "1",
               "OPENBLAS_NUM_THREADS": "1", "OMP_NUM_THREADS": "1",
               "MKL_NUM_THREADS": "1"}
        argv = [sys.executable, str(workspace / "solver.py"), "--input",
                str(copied_request), "--output-dir", str(output)]
        started = time.perf_counter()
        try:
            result = _process(argv, workspace, env, timeout)
        except subprocess.TimeoutExpired as exc:
            return None, f"candidate timed out: {exc.timeout}s"
        duration = time.perf_counter() - started
        if result.returncode:
            return None, f"candidate exited {result.returncode}: {result.stderr[-2000:]}"
        produced = {}
        try:
            workspace_fd = os.open(workspace, os.O_RDONLY |
                getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0))
            output_fd = os.open("final", os.O_RDONLY |
                getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0),
                dir_fd=workspace_fd)
            try:
                for name in ("dl_profiles_sharp.csv", "dl_profiles_smeared.csv",
                             "analysis.json", "solver.log"):
                    fd = os.open(name, os.O_RDONLY | os.O_NONBLOCK |
                                 getattr(os, "O_NOFOLLOW", 0), dir_fd=output_fd)
                    with os.fdopen(fd, "rb") as stream:
                        st = os.fstat(stream.fileno())
                        if not stat.S_ISREG(st.st_mode) or st.st_nlink != 1:
                            return None, f"candidate output is not a private regular file: {name}"
                        if st.st_size > 128 * 1024 * 1024:
                            return None, f"candidate output is oversized: {name}"
                        produced[name] = stream.read()
            finally:
                os.close(output_fd)
                os.close(workspace_fd)
        except OSError as exc:
            return None, f"candidate output missing/unsafe: {exc}"
        return {"files": produced, "runtime_seconds": duration,
                "stdout": result.stdout[-2000:], "stderr": result.stderr[-2000:],
                "submitted_helpers": sorted(p.name for p in workspace.glob("*.py"))}, None


def _numeric_equal(name: str, got: float, ref: float, tolerances: dict,
                   scale: float | None = None) -> tuple[bool, float]:
    atol, rtol = tolerances[name]
    norm = max(abs(ref), scale or 0.0)
    error = abs(got - ref)
    return error <= atol + rtol * norm, error / max(norm, atol, 1e-300)


def _check_profiles(candidate_bytes: bytes, reference_path: Path, table: str,
                    params_by_id: dict, report_detail: dict) -> tuple[str | None, dict[str, dict]]:
    tolerances = SHARP_TOL if table == "dl_profiles_sharp.csv" else SMEARED_TOL
    try:
        candidate_stream = candidate_bytes.decode("utf-8").splitlines()
    except UnicodeError as exc:
        return f"{table} is not UTF-8 CSV: {exc}", {}
    reference_stream = reference_path.open("r", newline="", encoding="utf-8")
    reader_ref = csv.DictReader(reference_stream)
    reader_got = csv.DictReader(candidate_stream)
    if reader_got.fieldnames != EXPECTED_COLUMNS or reader_ref.fieldnames != EXPECTED_COLUMNS:
        reference_stream.close()
        return f"{table} headers do not match the frozen schema", {}
    max_norm: dict[str, float] = {}
    physics: dict[str, dict] = {}
    active_id = None
    profile_arrays: dict[str, list[float]] = {}
    profile_params = None
    row_count = 0
    rough_field = table == "dl_profiles_smeared.csv"

    def finalize_profile() -> str | None:
        if active_id is None or rough_field:
            return None
        try:
            fields = {key: np.asarray(profile_arrays[key], dtype=float)
                      for key in physics_verifier.REQUIRED}
            checked = physics_verifier.verify_profile(fields, profile_params)
        except Exception as exc:
            return f"independent physical verifier failed for {active_id}: {exc}"
        physics[active_id] = checked
        if checked["status"] != "PASS":
            return f"independent physical checks failed for {active_id}: {checked['passed']}"
        return None

    try:
        sentinel = object()
        for index, (got, ref) in enumerate(itertools.zip_longest(
                reader_got, reader_ref, fillvalue=sentinel)):
            if got is sentinel or ref is sentinel:
                return f"{table} row count differs from private reference at row {index}", physics
            row_count += 1
            run_id = got.get("run_id")
            if run_id != ref.get("run_id"):
                return f"{table} row {index} run_id/order differs", physics
            if run_id != active_id:
                issue = finalize_profile()
                if issue:
                    return issue, physics
                active_id = run_id
                profile_params = params_by_id.get(run_id)
                profile_arrays = {key: [] for key in physics_verifier.REQUIRED}
                if profile_params is None:
                    return f"unexpected run_id {run_id} in {table}", physics
            names = list(METADATA_TOL)
            names.extend(["z_A"])
            for name in names:
                gv, rv = float(got[name]), float(ref[name])
                if not math.isfinite(gv) or not math.isfinite(rv):
                    return f"non-finite {name} at row {index}", physics
                if name == "z_A":
                    ok = abs(gv - rv) <= 1e-9
                    err = abs(gv - rv)
                else:
                    ok, err = _numeric_equal(name, gv, rv, METADATA_TOL)
                if not ok:
                    return f"{table} metadata {name} mismatch at row {index}: {gv} vs {rv}", physics
            c = float(got["concentration_mM"])
            sigma = float(got["sigma0_C_m2"])
            liq = float(got["liquid_fraction"])
            nb = c * 6.02214076e23
            eps_bulk = 1.0 + 1.0 / 0.140125 + 1.0 / 0.015908
            lambda_gc_A = math.sqrt(
                8.8541878128e-12 * eps_bulk * 1.380649e-23
                * float(got["temperature_K"])
                / (2.0 * 1.602176634e-19**2 * nb)) * 1e10
            for name, (atol, rtol) in tolerances.items():
                gv, rv = float(got[name]), float(ref[name])
                if not math.isfinite(gv) or not math.isfinite(rv):
                    return f"non-finite {name} at {run_id} row {index}", physics
                scale = None
                if name in ("n_plus_m3", "n_minus_m3"):
                    scale = (max(nb * liq, nb * 1e-12) if rough_field else nb)
                ok, err = _numeric_equal(name, gv, rv, tolerances, scale)
                max_norm[name] = max(max_norm.get(name, 0.0), err)
                if not ok:
                    return (f"{table} {name} differs from private full-profile reference "
                            f"at {run_id} z={got['z_A']} (scaled error={err:.4g})"), physics
            for name in physics_verifier.REQUIRED:
                profile_arrays[name].append(float(got[name]))
            if rough_field:
                nplus, nminus = float(got["n_plus_m3"]), float(got["n_minus_m3"])
                occupancy = float(got["site_occupancy"])
                a3 = float(got["cell_length_nm"])**3 * 1e-27
                rough_limits = NUMERICAL["rough_constraints"]
                density_floor = rough_limits["ion_density_negative_tolerance_relative_to_n_b"] * nb
                if nplus < -density_floor or nminus < -density_floor:
                    return f"rough ion density is materially negative at {run_id} z={got['z_A']}", physics
                if occupancy < -rough_limits["site_occupancy_negative_tolerance_absolute"]:
                    return f"rough site occupancy is negative at {run_id} z={got['z_A']}", physics
                if occupancy > liq + rough_limits["site_occupancy_le_liquid_fraction_absolute"]:
                    return f"rough occupancy exceeds liquid fraction at {run_id} z={got['z_A']}", physics
                if abs(occupancy - a3 * (nplus + nminus)) > rough_limits["occupancy_consistency_relative"] * max(liq, 1e-6):
                    return f"rough occupancy is inconsistent with averaged ion densities at {run_id}", physics
                if (float(got["z_A"]) >= rough_limits["far_tail_start_in_GC_lengths"] * lambda_gc_A
                        and liq > 1.0 - 1e-8):
                    for name, density in (("n_plus_m3", nplus), ("n_minus_m3", nminus)):
                        if abs(density - nb * liq) > rough_limits["far_tail_ion_density_relative_to_n_b"] * nb:
                            return f"rough {name} far tail does not approach nb*liquid_fraction at {run_id}", physics
        issue = finalize_profile()
        if issue:
            return issue, physics
    except (ValueError, TypeError, KeyError, csv.Error, UnicodeError) as exc:
        return f"{table} has malformed candidate rows: {exc}", physics
    finally:
        reference_stream.close()
    report_detail[table] = {"rows": row_count, "max_scaled_error": max_norm,
                            "sharp_physics": physics}
    return None, physics


def _check_analysis(candidate_bytes: bytes, reference_path: Path,
                    requested_ids: list[str], request_sha256: str | None = None) -> str | None:
    try:
        got = json.loads(candidate_bytes)
        ref = json.loads(reference_path.read_text(encoding="utf-8"))
    except Exception as exc:
        return f"analysis.json is invalid: {exc}"
    try:
        schema = PUBLIC_SPEC["output_contract"]["analysis_json"]
        if got.get("schema") != schema["schema"]:
            return "analysis.json schema version is missing or unsupported"
        if any(key not in got for key in schema["required_top_level"]):
            return "analysis.json omits a required top-level field"
        author_reconstruction = got.get("author_reconstruction")
        if (author_reconstruction is None or author_reconstruction is False or
                (isinstance(author_reconstruction, str) and not author_reconstruction.strip()) or
                (isinstance(author_reconstruction, (dict, list)) and not author_reconstruction)):
            return "analysis.json author_reconstruction must not be null, false, or empty"
        if request_sha256 is not None and got.get("input_sha256") != request_sha256:
            return "analysis.json input_sha256 does not identify the request used for this run"
        rows = got.get("conditions")
        if not isinstance(rows, list) or [x.get("run_id") for x in rows] != requested_ids:
            return "analysis.json does not contain exactly the requested ordered conditions"
        by_reference = {x["run_id"]: x for x in ref["conditions"]}
        for row in rows:
            rid = row["run_id"]
            if any(key not in row for key in schema["required_condition"]):
                return f"analysis omits required condition metadata for {rid}"
            if not row.get("bvp", {}).get("success"):
                return f"analysis marks BVP failure for {rid}"
            if not isinstance(row.get("checks"), dict) or any(
                    key not in row["checks"] for key in schema["checks_required"]):
                return f"analysis omits physical checks for {rid}"
            if any(key not in row["bvp"] for key in schema["bvp_required"]):
                return f"analysis omits BVP convergence evidence for {rid}"
            omega = float(row.get("fixed_sigma_functional_energy_J_m2", float("nan")))
            target = float(by_reference[rid]["fixed_sigma_functional_energy_J_m2"])
            energy_tol = NUMERICAL["analysis"]["fixed_sigma_functional_energy_J_m2"]
            if not math.isfinite(omega) or abs(omega - target) > energy_tol["absolute"] + energy_tol["relative"] * abs(target):
                return f"fixed-sigma functional energy mismatch for {rid}"
            if row.get("parameters", {}).get("Pbar_C_m2") != by_reference[rid]["parameters"]["Pbar_C_m2"]:
                return f"analysis lost requested Pbar for {rid}"
    except (TypeError, KeyError, ValueError, AttributeError) as exc:
        return f"analysis.json has malformed candidate content: {exc}"
    return None


def main(argv: list[str]) -> int:
    final = Path(argv[1] if len(argv) > 1 else "final")
    if not final.is_absolute():
        final = Path.cwd() / final
    started = time.perf_counter()
    log_dir = Path(os.environ["BENCH_LOGS"]) if os.environ.get("BENCH_LOGS") else None
    if log_dir:
        log_dir.mkdir(parents=True, exist_ok=True)
        (log_dir / "reward.txt").unlink(missing_ok=True)
        (log_dir / "verification.json").unlink(missing_ok=True)
    try:
        manifest = _integrity_manifest()
        isolation = _isolation_probe()
    except Exception as exc:
        return _infra(f"private evaluator preflight failed: {exc}")
    # Private Gold and test assets are protected before any untrusted candidate
    # process starts. They stay inaccessible for the rest of the run.
    public_request = json.loads(PUBLIC_REQUEST.read_text(encoding="utf-8"))
    public_ids = [row["run_id"] for row in public_request["conditions"]]
    params_by_id = {row["run_id"]: {**public_request["shared_parameters"], **row}
                    for row in public_request["conditions"]}
    # Validate and safely stage submitted source helpers before inspecting
    # reports, so a symlink-to-private helper is rejected even when reports
    # are also missing or malformed.
    with tempfile.TemporaryDirectory(prefix="case005-submitted-preflight-") as temp:
        preflight_workspace = Path(temp) / "workspace"
        preflight_workspace.mkdir(mode=0o777)
        err = _stage_candidate(final, preflight_workspace)
        if err:
            return _fail(err)
    submitted, err = _read_submitted_artifacts(final)
    if err:
        return _fail(err)
    submitted_detail: dict = {}
    for table in ("dl_profiles_sharp.csv", "dl_profiles_smeared.csv"):
        err, _ = _check_profiles(submitted[table], GOLD / "reference" / table,
                                 table, params_by_id, submitted_detail)
        if err:
            return _fail(f"submitted artifact {table}: {err}", {"submitted": submitted_detail})
    err = _check_analysis(submitted["analysis.json"], GOLD / "reference" / "analysis.json",
                          public_ids, _sha(PUBLIC_REQUEST))
    if err:
        return _fail(f"submitted artifact analysis.json: {err}", {"submitted": submitted_detail})
    try:
        log_text = submitted["solver.log"].decode("utf-8")
    except UnicodeError as exc:
        return _fail(f"submitted artifact solver.log is not UTF-8: {exc}")
    if not log_text.strip():
        return _fail("submitted artifact solver.log is empty")
    result, err = _run_candidate(final, PUBLIC_REQUEST)
    if err:
        return _fail(err)
    detail: dict = {"candidate_runtime_seconds_public": result["runtime_seconds"],
                    "candidate_helpers": result["submitted_helpers"],
                    "gold_manifest_sha256": _sha(GOLD / "manifest.json"),
                    "submitted_artifacts_checked": True,
                    "submitted_artifacts": submitted_detail,
                    "public": {}}
    for table in ("dl_profiles_sharp.csv", "dl_profiles_smeared.csv"):
        err, _ = _check_profiles(result["files"][table], GOLD / "reference" / table,
                                 table, params_by_id, detail["public"])
        if err:
            return _fail(err, detail)
    err = _check_analysis(result["files"]["analysis.json"],
                          GOLD / "reference" / "analysis.json", public_ids,
                          _sha(PUBLIC_REQUEST))
    if err:
        return _fail(err, detail)
    hidden_details = []
    for index, probe in enumerate(manifest["private_probes"]):
        request_path = GOLD / probe["request_file"]
        candidate_result, err = _run_candidate(final, request_path)
        if err:
            return _fail(f"hidden request {index}: {err}", detail)
        conditions = json.loads(request_path.read_text(encoding="utf-8"))["conditions"]
        shared = json.loads(request_path.read_text(encoding="utf-8"))["shared_parameters"]
        hidden_params = {conditions[0]["run_id"]: {**shared, **conditions[0]}}
        for table in ("dl_profiles_sharp.csv", "dl_profiles_smeared.csv"):
            err, _ = _check_profiles(candidate_result["files"][table],
                GOLD / probe["output_dir"] / table, table, hidden_params, {})
            if err:
                return _fail(f"hidden request {index}: {err}", detail)
        err = _check_analysis(candidate_result["files"]["analysis.json"],
            GOLD / probe["output_dir"] / "analysis.json", [conditions[0]["run_id"]],
            probe["request_sha256"])
        if err:
            return _fail(f"hidden request {index}: {err}", detail)
        hidden_details.append({"parameters": probe["parameters"],
                               "runtime_seconds": candidate_result["runtime_seconds"]})
    detail["hidden_probes"] = hidden_details
    detail["isolation"] = isolation
    detail["runtime_seconds_total"] = time.perf_counter() - started
    detail["reference_generation_image_id"] = manifest["runtime_image_id"]
    print("PASS")
    print(json.dumps(detail, indent=2, default=_json_value))
    return _finish(0, "all public profiles, physical checks, energies, and off-grid probes passed", detail)


if __name__ == "__main__":
    try:
        code = main(sys.argv)
    except Exception as exc:
        code = _infra(f"verifier exception: {type(exc).__name__}: {exc}")
    raise SystemExit(code)
