#!/usr/bin/env python3
# L1 Deliverables: Check required deliverables for completeness and parseability.
# L2 Execution: Check execution evidence through bounded replay or independent recomputation where implemented.
# L3 Science: Infer the two-mode dielectric kernel from five response targets.
"""Score case 002 from a workspace that contains final/."""
from __future__ import annotations

import json
import hashlib
import io
import math
import os
import pwd
import resource
import re
import select
import selectors
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
import ctypes
from pathlib import Path

import numpy as np
from _support.fs_sandbox import apply_landlock, landlock_abi_version

HERE = Path(__file__).resolve().parent

TARGETS = {
    "eps_w": 70.997939,
    "k_min": 0.400044,
    "chi_min": 0.924774,
    "k_max": 2.998992,
    "delta_k": 1.216510,
}
TOL = {
    "eps_w": 0.02,
    "k_min": 0.002,
    "chi_min": 0.001,
    "k_max": 0.005,
    "delta_k": 0.01,
}
PUBLISHED = {
    "K11": 0.140125,
    "K12": -0.207118,
    "K13": 0.011290,
    "K21": 0.015908,
    "K22": 2.003940,
}
KERNEL_NAMES = tuple(PUBLISHED)
SCALES = np.array([1.0, 0.02, 0.01, 0.02, 0.02])
MAX_SOLVER_BYTES = 2_000_000
MAX_FEATURE_HELPER_BYTES = 100_000
MAX_OUTPUT_BYTES = 5_000_000
MAX_OBJECTIVE_REQUESTS = 10_000


def _normalized_metric_name(value):
    value = re.sub(r"[_-]+", " ", str(value).casefold())
    value = " ".join(value.split())
    for prefix in ("accepted ", "total ", "number of "):
        if value.startswith(prefix):
            value = value[len(prefix):]
            break
    for suffix in (" count", " number"):
        if value.endswith(suffix):
            value = value[:-len(suffix)]
            break
    return value


def _parse_numeric_scalar(value):
    if type(value) in (int, float):
        return value
    if type(value) is not str:
        return None
    text = value.strip()
    if not re.fullmatch(r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?", text):
        return None
    try:
        return float(text)
    except (OverflowError, ValueError):
        return None


def _finite_numeric_scalar(value):
    parsed = _parse_numeric_scalar(value)
    if parsed is None:
        return False
    try:
        return math.isfinite(float(parsed))
    except (OverflowError, ValueError):
        return False


def _is_count_value(value):
    parsed = _parse_numeric_scalar(value)
    if parsed is None:
        return False
    try:
        number = float(parsed)
        return math.isfinite(number) and number >= 0 and number.is_integer()
    except (OverflowError, ValueError):
        return False

def _is_count_metric(value):
    return _normalized_metric_name(value) in {
        "iteration", "iterations", "iter", "nit", "nfev",
        "function evaluation", "function evaluations",
        "迭代次数", "函数评估次数",
    }


def _is_residual_metric(value):
    return _normalized_metric_name(value) in {
        "residual", "residual norm", "final residual", "final residual norm",
        "last residual", "last residual norm",
        "最终残差",
    }


def _valid_json_metrics(value):
    has_count = False
    has_residual = False

    def visit(item):
        nonlocal has_count, has_residual
        if isinstance(item, dict):
            for key, child in item.items():
                if _is_count_metric(key) and _is_count_value(child):
                    has_count = True
                if _is_residual_metric(key) and _finite_numeric_scalar(child):
                    has_residual = True
                visit(child)
        elif isinstance(item, list):
            for child in item:
                visit(child)

    visit(value)
    return has_count, has_residual


def solver_log_has_metrics(log):
    try:
        receipt = json.loads(log, object_pairs_hook=_unique_json_object)
        return (isinstance(receipt, dict)
                and receipt.get("schema") == "task90-host-objective-receipt/v1"
                and type(receipt.get("objective_requests")) is int
                and receipt["objective_requests"] > 0
                and _finite_numeric_scalar(receipt.get("final_residual"))
                and receipt.get("objective_scope") == "evaluator-observable objective requests; internal optimizer calls are not counted")
    except (json.JSONDecodeError, TypeError, ValueError):
        return False

    # Parse structured logs first so arrays, strings, booleans and other
    # non-scalar JSON values cannot masquerade as a number in text matching.
    try:
        payload = json.loads(log)
    except (json.JSONDecodeError, TypeError):
        payload = None
        valid_json = False
    else:
        valid_json = True
    if valid_json:
        has_count, has_residual = _valid_json_metrics(payload)
        return has_count and has_residual

    # Normalize label separators only; preserve a minus sign in numeric values.
    text = str(log).replace("：", ":")
    text = re.sub(r"(?<=[A-Za-z])[_-](?=[A-Za-z])", " ", text)
    count_label = re.compile(
        r"(?<!\w)(?:(?:accepted|total|number[\s_-]+of)[\s_-]+)?"
        r"(?:function[\s_-]+evaluations?|number[\s_-]+of[\s_-]+iterations?|"
        r"iterations?|iter|nit|nfev|迭代次数|函数评估次数)"
        r"(?:[\s_-]+(?:count|number))?(?!\w)", re.IGNORECASE)
    residual_label = re.compile(
        r"(?<!\w)(?:(?:final|last)[\s_-]+)?"
        r"(?:residual(?:[\s_-]+norm)?|最终残差)(?!\w)", re.IGNORECASE)
    number = re.compile(
        r"\s*['\"]?\s*(?:[:=]\s*['\"]?)?"
        r"([+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?)"
        r"['\"]?(?![\w.])")

    def scalar_terminator(tail):
        if not tail:
            return True
        first = tail[0]
        if first.isspace():
            rest = tail.lstrip()
            if not rest:
                return True
            return re.match(r"[+\-*/]\s*(?:\d|\.)|(?:\d|\.)", rest) is None
        if first in ",;":
            rest = tail[1:].lstrip()
            return not rest or re.match(r"[+\-*/]?\s*(?:\d|\.)", rest) is None
        return first in ")]}"

    has_count = False
    for label in count_label.finditer(text):
        match = number.match(text[label.end():])
        if not match or not scalar_terminator(text[label.end() + match.end():]):
            continue
        try:
            has_count = _is_count_value(float(match.group(1)))
        except (OverflowError, ValueError):
            has_count = False
        if has_count:
            break

    has_residual = False
    for label in residual_label.finditer(text):
        match = number.match(text[label.end():])
        if not match or not scalar_terminator(text[label.end() + match.end():]):
            continue
        try:
            if _finite_numeric_scalar(match.group(1)):
                has_residual = True
                break
        except (OverflowError, ValueError):
            pass
    return has_count and has_residual


def _parse_candidate_report(data):
    report = json.loads(data, object_pairs_hook=_unique_json_object)
    allowed = {"schema", "status", "objective_scope", "objective_requests", "final_residual"}
    if not isinstance(report, dict) or not set(report).issubset(allowed):
        raise ValueError("solver.log must be a JSON candidate report")
    report.setdefault("schema", "task90-candidate-objective-report/v1")
    report.setdefault("status", "PENDING")
    report.setdefault("objective_scope", "evaluator-observable objective requests; internal optimizer calls are not counted")
    if (report["schema"] != "task90-candidate-objective-report/v1"
            or report["status"] != "PENDING"
            or report["objective_scope"] != "evaluator-observable objective requests; internal optimizer calls are not counted"):
        raise ValueError("solver.log candidate report metadata is invalid")
    return report


def _check_candidate_claims(report, receipt):
    if ("objective_requests" in report
            and (type(report["objective_requests"]) is not int
                 or report["objective_requests"] != receipt["objective_requests"])):
        raise ValueError("candidate objective_requests claim does not match host-observed requests")
    if ("final_residual" in report
            and (not _finite_numeric_scalar(report["final_residual"])
                 or not math.isclose(float(report["final_residual"]), receipt["final_residual"],
                                     rel_tol=1e-12, abs_tol=1e-12))):
        raise ValueError("candidate final_residual claim does not match the host calculation")



def fail(layer, message):
    print(f"FAIL {layer}: {message}")
    return 1


def epsilon_k(k, K):
    k2 = np.asarray(k, dtype=float) ** 2
    A = K["K11"] + K["K12"] * k2 + K["K13"] * k2 ** 2
    B = K["K21"] + K["K22"] * k2
    return 1.0 + 1.0 / A + 1.0 / B


def chi_of(k, K):
    return 1.0 - 1.0 / epsilon_k(k, K)


def _refine_extremum(k, c, i1):
    if i1 <= 0 or i1 >= len(c) - 1:
        return float(k[i1]), float(c[i1])
    x0, x1, x2 = k[i1 - 1], k[i1], k[i1 + 1]
    y0, y1, y2 = c[i1 - 1], c[i1], c[i1 + 1]
    den = (x0 - x1) * (x0 - x2) * (x1 - x2)
    a = (x2 * (y1 - y0) + x1 * (y0 - y2) + x0 * (y2 - y1)) / den
    b = (x2 ** 2 * (y0 - y1) + x1 ** 2 * (y2 - y0) + x0 ** 2 * (y1 - y2)) / den
    xv = -b / (2.0 * a) if a else float(x1)
    return float(xv), float(np.interp(xv, k, c))


def observables(K, n=200001):
    k = np.linspace(0.0, 8.0, n)
    c = chi_of(k, K)
    dc = np.diff(c)
    turns = np.where(np.diff(np.sign(dc)))[0]
    feats = []
    for i in turns:
        i1 = min(i + 1, len(c) - 2)
        kind = "min" if dc[i] < 0 else "max"
        kk, cc = _refine_extremum(k, c, i1)
        feats.append((kind, kk, cc))
    mins = [f for f in feats if f[0] == "min"]
    maxs = [f for f in feats if f[0] == "max"]
    if not mins or not maxs:
        raise RuntimeError("chi(k) has no minimum/maximum on [0, 8]")
    kmin = min(mins, key=lambda f: f[1])
    kmax = max(maxs, key=lambda f: f[2])
    half = kmax[2] / 2.0
    window = (k > max(0.0, kmax[1] - 3.0)) & (k < kmax[1] + 3.0)
    kk, cc = k[window], c[window]
    cross = np.where(np.diff(np.sign(cc - half)))[0]
    if len(cross) < 2:
        raise RuntimeError("resonance half-maximum crossings were not found")

    def crossing(index):
        y0, y1 = cc[index], cc[index + 1]
        x0, x1 = kk[index], kk[index + 1]
        if y1 == y0:
            return float(x0)
        return float(x0 + (half - y0) * (x1 - x0) / (y1 - y0))

    k_minus = crossing(int(cross[0]))
    k_plus = crossing(int(cross[-1]))
    return {
        "eps_w": float(epsilon_k(0.0, K)),
        "k_min": kmin[1],
        "chi_min": kmin[2],
        "k_max": kmax[1],
        "delta_k": k_plus - k_minus,
    }


def dkm_band_occupied(K):
    """Analytically partition all real q>=0 around poles and eps=0/1 roots."""
    # Let x=q^2.  Between every real nonnegative root of these polynomials,
    # eps(x) is continuous and cannot enter [0,1) without crossing a boundary.
    A = np.array([K["K11"], K["K12"], K["K13"]], dtype=float)
    B = np.array([K["K21"], K["K22"]], dtype=float)
    one = np.array([1.0])
    polys = (A, B, np.polynomial.polynomial.polyadd(A, B),
             np.polynomial.polynomial.polyadd(
                 np.polynomial.polynomial.polymul(A, B),
                 np.polynomial.polynomial.polyadd(A, B)))
    roots = [0.0]
    for coeff in polys:
        trimmed = np.trim_zeros(np.asarray(coeff, dtype=float), "b")
        if len(trimmed) <= 1:
            continue
        for root in np.polynomial.polynomial.polyroots(trimmed):
            if abs(float(root.imag)) <= 1e-9 * max(1.0, abs(float(root.real))) and root.real >= 0:
                roots.append(max(0.0, float(root.real)))
    points = sorted(set(roots))
    probes = list(points)
    probes.extend(0.5 * (a + b) for a, b in zip(points, points[1:]) if b > a)
    last = points[-1]
    probes.append(last + max(1.0, last + 1.0))
    for x in probes:
        k = np.sqrt(x)
        try:
            e = float(epsilon_k(k, K))
        except (FloatingPointError, ZeroDivisionError):
            continue
        if np.isfinite(e) and 0.0 <= e < 1.0:
            return True
    return False


def load_kernel(payload):
    keys = ["K11", "K12", "K13", "K21", "K22"]
    if not isinstance(payload, dict) or not all(k in payload for k in keys):
        raise KeyError("kernel_params.json needs K11, K12, K13, K21, K22")
    out = {}
    for key in keys:
        value = payload[key]
        try:
            numeric_value = float(value)
        except (OverflowError, TypeError, ValueError):
            numeric_value = float("nan")
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not np.isfinite(numeric_value):
            raise ValueError(f"kernel coefficient {key} must be a finite number")
        out[key] = numeric_value
    return out


def _unique_json_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _read_regular(directory: Path, name: str, limit: int) -> bytes:
    dfd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=dfd)
        try:
            if not stat.S_ISREG(os.fstat(fd).st_mode):
                raise ValueError(f"{name} must be a regular file")
            chunks = []
            total = 0
            while True:
                part = os.read(fd, min(65536, limit + 1 - total))
                if not part:
                    return b"".join(chunks)
                total += len(part)
                if total > limit:
                    raise ValueError(f"{name} exceeds {limit} bytes")
                chunks.append(part)
        finally:
            os.close(fd)
    finally:
        os.close(dfd)


def _demote_candidate(workspace: Path):
    user = pwd.getpwnam("nobody")
    os.setgroups([])
    os.setgid(user.pw_gid)
    os.setuid(user.pw_uid)
    # No child process can inspect or alter the verifier's receipt/pipe owner.
    libc = ctypes.CDLL(None, use_errno=True)
    libc.prctl.restype = ctypes.c_int
    if libc.prctl(38, 1, 0, 0, 0) != 0:
        error = ctypes.get_errno()
        raise OSError(error, "PR_SET_NO_NEW_PRIVS failed")
    apply_landlock(workspace)
    resource.setrlimit(resource.RLIMIT_CPU, (170, 170))
    resource.setrlimit(resource.RLIMIT_FSIZE, (MAX_OUTPUT_BYTES, MAX_OUTPUT_BYTES))
    resource.setrlimit(resource.RLIMIT_NPROC, (1, 1))
    resource.setrlimit(resource.RLIMIT_AS, (3 * 1024**3, 3 * 1024**3))


def _protect_private_directory(path: Path, allow_standard_chmod=False, allow_landlock_mount=False):
    path = Path(os.path.abspath(path))
    if path.is_symlink():
        raise RuntimeError(f"private directory path must not be a symlink: {path}")
    if not path.is_dir():
        raise RuntimeError(f"private directory is missing: {path}")
    for ancestor in (path, *path.parents):
        info = ancestor.stat()
        if info.st_uid == 0 and (stat.S_IMODE(info.st_mode) & 0o077) == 0:
            return
    if allow_landlock_mount and path in (Path("/tests"), Path("/solution")):
        # These public paths may be read-only mounts or runtime-managed directories.
        # The same child Landlock policy below proves that they remain inaccessible.
        return
    raise RuntimeError(f"candidate-readable verifier/solution path cannot be made private safely: {path}")


def _require_secure_logs(path: Path):
    path = Path(os.path.abspath(path))
    if any(ancestor.is_symlink() for ancestor in (path, *path.parents)):
        raise RuntimeError("BENCH_LOGS path must not contain symlinks")
    info = path.stat()
    mode = stat.S_IMODE(info.st_mode)
    nobody_uid = pwd.getpwnam("nobody").pw_uid
    if not stat.S_ISDIR(info.st_mode) or info.st_uid == nobody_uid or mode & 0o022:
        raise RuntimeError("BENCH_LOGS must not be candidate-owned or group/other writable")
    for ancestor in path.parents:
        st = ancestor.stat()
        ancestor_mode = stat.S_IMODE(st.st_mode)
        if ancestor_mode & 0o022 and not (st.st_uid == 0 and ancestor_mode & stat.S_ISVTX):
            raise RuntimeError(f"unsafe writable ancestor for BENCH_LOGS: {ancestor}")


def _verify_private_boundary():
    if os.geteuid() != 0:
        raise RuntimeError("trusted evaluator must run as root")
    abi = landlock_abi_version()
    if abi < 3:
        raise RuntimeError(f"Landlock ABI {abi} lacks required filesystem truncate mediation")
    _protect_private_directory(HERE, allow_standard_chmod=True)
    public_tests_dir = Path(os.environ.get("BENCH_PUBLIC_TESTS", "/tests"))
    _protect_private_directory(public_tests_dir, allow_standard_chmod=True, allow_landlock_mount=True)
    tests = [HERE / "verify.py", HERE / "refs.json", public_tests_dir / "verify.py", public_tests_dir / "refs.json"]
    for helper in (HERE / "_support/fs_sandbox.py", public_tests_dir / "_support/fs_sandbox.py"):
        if helper.is_file():
            tests.append(helper)
    if not all(path.is_file() for path in tests):
        raise RuntimeError("private tests directory is missing verify.py or refs.json")
    solution_dirs = {HERE.parent / "solution", Path("/solution")}
    solution_value = os.environ.get("BENCH_SOLUTION_DIR")
    if solution_value:
        solution_dirs.add(Path(solution_value))
    solution_files = []
    for solution_dir in sorted(solution_dirs, key=str):
        if solution_dir.exists():
            _protect_private_directory(solution_dir, allow_standard_chmod=True, allow_landlock_mount=True)
            solution_files.extend(
                path for path in (
                    solution_dir / "solve.py",
                    solution_dir / "solve.sh",
                    solution_dir / "_impl/solve.py",
                ) if path.is_file()
            )
    solution_files = list(dict.fromkeys(solution_files))
    logs_value = os.environ.get("BENCH_LOGS")
    if not logs_value:
        raise RuntimeError("BENCH_LOGS must point to a private evaluator-owned directory")
    logs = Path(logs_value)
    logs.mkdir(parents=True, exist_ok=True)
    _require_secure_logs(logs)
    marker = logs / f".task90-boundary-probe-{os.getpid()}"
    fd = os.open(marker, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    os.close(fd)
    protected = [str(path) for path in (*tests, *solution_files, marker)]
    with tempfile.TemporaryDirectory(prefix="task90-private-probe-") as td:
        root = Path(td)
        os.chmod(root, 0o755)
        out = root / "out"
        out.mkdir()
        os.chmod(out, 0o777)
        result = out / "result.json"
        probe = root / "probe.py"
        probe.write_text(
            "import json,pathlib,sys\n"
            "paths=json.loads(sys.argv[1]); denied=[]; writable=[]\n"
            "for p in paths:\n"
            " try:pathlib.Path(p).read_bytes()\n"
            " except OSError:denied.append(p)\n"
            "try:pathlib.Path(paths[-1]).write_bytes(b'candidate')\n"
            "except OSError:writable.append(paths[-1])\n"
            "pathlib.Path(sys.argv[2]).write_text(json.dumps({'read_denied':denied,'write_denied':writable}))\n",
            encoding="utf-8",
        )
        probe.chmod(0o644)
        proc = subprocess.run(
            [sys.executable, str(probe), json.dumps(protected), str(result)],
            env={"PATH": "/usr/local/bin:/usr/bin:/bin", "HOME": str(root), "TMPDIR": str(root), "PYTHONNOUSERSITE": "1"},
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=10,
            preexec_fn=lambda: _demote_candidate(root),
        )
        checks = json.loads(result.read_text()) if result.is_file() else {}
        marker.unlink(missing_ok=True)
        if (proc.returncode or set(checks.get("read_denied", [])) != set(protected)
                or marker.as_posix() not in checks.get("write_denied", [])):
            readable = sorted(set(protected) - set(checks.get("read_denied", [])))
            raise RuntimeError(f"nobody can read private verifier/solution or write parent receipt; readable={readable}")
    return {"status": "PASS", "tests_protected": [str(path) for path in tests],
            "solution_protected": [str(path) for path in solution_files], "receipt_directory": str(logs)}


def _objective_residual(values):
    K = dict(zip(KERNEL_NAMES, (float(v) for v in values)))
    if (not all(np.isfinite(v) for v in K.values())
            or min(K["K11"], K["K13"], K["K21"], K["K22"]) <= 0
            or K["K12"] >= 0):
        return np.full(5, 10.0)
    try:
        with np.errstate(all="ignore"):
            got = observables(K)
    except Exception:
        return np.full(5, 10.0)
    target_values = np.array([TARGETS[key] for key in ("eps_w", "k_min", "chi_min", "k_max", "delta_k")])
    return (np.array([got[key] for key in ("eps_w", "k_min", "chi_min", "k_max", "delta_k")]) - target_values) / SCALES


def _run_candidate(source: bytes, candidate_report_bytes: bytes, target_bytes: bytes, feature_helper_bytes: bytes):
    if os.geteuid() != 0:
        raise RuntimeError("trusted evaluator must run as root to isolate the submitted solver")
    source_hash = hashlib.sha256(source).hexdigest()
    target_hash = hashlib.sha256(target_bytes).hexdigest()
    requests = []
    with tempfile.TemporaryDirectory(prefix="task90-objective-rpc-") as td:
        root = Path(td)
        os.chmod(root, 0o755)
        ws = root / "workspace"
        ws.mkdir(mode=0o755)
        os.chmod(ws, 0o755)
        (ws / "assets").mkdir(mode=0o755)
        (ws / "assets" / "response_targets.json").write_bytes(target_bytes)
        (ws / "assets" / "response_targets.json").chmod(0o444)
        (ws / "assets" / "objective_features.py").write_bytes(feature_helper_bytes)
        (ws / "assets" / "objective_features.py").chmod(0o444)
        (ws / "final").mkdir(mode=0o777)
        os.chmod(ws / "final", 0o777)
        script = ws / "solver.py"
        script.write_bytes(source)
        script.chmod(0o444)
        stderr_path = root / "candidate.stderr"
        env = {
            "PATH": "/usr/local/bin:/usr/bin:/bin",
            "HOME": str(ws),
            "TMPDIR": str(ws),
            "PYTHONNOUSERSITE": "1",
            "OPENBLAS_NUM_THREADS": "1",
            "OMP_NUM_THREADS": "1",
            "MKL_NUM_THREADS": "1",
        }
        with stderr_path.open("wb") as stderr:
            proc = subprocess.Popen(
                [sys.executable, str(script), str(ws), "--objective-rpc"], cwd=ws, env=env,
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=stderr,
                bufsize=0, start_new_session=True, preexec_fn=lambda: _demote_candidate(ws),
            )
            selector = selectors.DefaultSelector()
            selector.register(proc.stdout, selectors.EVENT_READ)
            os.set_blocking(proc.stdin.fileno(), False)
            pending = bytearray()
            deadline = __import__("time").monotonic() + 175
            try:
                while True:
                    remaining = deadline - __import__("time").monotonic()
                    if remaining <= 0:
                        raise ValueError("submitted solver timed out during objective RPC")
                    ready = selector.select(min(remaining, 1.0))
                    if not ready:
                        if proc.poll() is not None:
                            break
                        continue
                    chunk = os.read(proc.stdout.fileno(), 65536)
                    if not chunk:
                        break
                    pending.extend(chunk)
                    if len(pending) > 65_536 and b"\n" not in pending:
                        raise ValueError("objective RPC line exceeds 64 KiB")
                    while b"\n" in pending:
                        line, _, tail = pending.partition(b"\n")
                        pending = bytearray(tail)
                        if len(line) > 65_536:
                            raise ValueError("objective RPC line exceeds 64 KiB")
                        request = json.loads(line.decode("utf-8"), object_pairs_hook=_unique_json_object,
                                             parse_constant=lambda token: (_ for _ in ()).throw(ValueError(f"invalid JSON number {token}")))
                        if (not isinstance(request, dict) or set(request) != {"type", "seq", "K"}
                                or request["type"] != "objective_query"
                                or type(request["seq"]) is not int or request["seq"] != len(requests)
                                or not isinstance(request["K"], list) or len(request["K"]) != 5
                                or any(type(value) not in (int, float) or not math.isfinite(float(value)) for value in request["K"])):
                            raise ValueError("malformed or out-of-sequence objective RPC request")
                        if len(requests) >= MAX_OBJECTIVE_REQUESTS:
                            raise ValueError("submitted solver exceeded the objective request limit")
                        values = [float(value) for value in request["K"]]
                        residual = _objective_residual(values)
                        requests.append(values)
                        response = {"type": "objective_result", "seq": request["seq"],
                                    "residual": [float(value) for value in residual]}
                        payload = memoryview((json.dumps(response, allow_nan=False, separators=(",", ":")) + "\n").encode())
                        while payload:
                            try:
                                written = os.write(proc.stdin.fileno(), payload)
                                payload = payload[written:]
                            except BlockingIOError:
                                remaining = deadline - __import__("time").monotonic()
                                if remaining <= 0 or not select.select([], [proc.stdin], [], remaining)[1]:
                                    raise ValueError("submitted solver stopped reading objective RPC responses")
                if pending:
                    raise ValueError("objective RPC ended with an unterminated JSONL request")
                try:
                    status = proc.wait(timeout=max(0.1, deadline - __import__("time").monotonic()))
                except subprocess.TimeoutExpired:
                    raise ValueError("submitted solver timed out after its final objective request")
                if status != 0:
                    detail = stderr_path.read_bytes()[-2000:].decode("utf-8", "replace")
                    raise ValueError(f"submitted solver exited {status}: {detail}")
            except Exception:
                try:
                    os.killpg(proc.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                proc.wait()
                raise
            finally:
                selector.close()
                proc.stdin.close()
                proc.stdout.close()
        if not requests:
            raise ValueError("submitted solver made no evaluator-observable objective requests")
        params_bytes = _read_regular(ws / "final", "kernel_params.json", MAX_OUTPUT_BYTES)
        curve_bytes = _read_regular(ws / "final", "response_curves.csv", MAX_OUTPUT_BYTES)
        candidate_log = _parse_candidate_report(_read_regular(ws / "final", "solver.log", 100_000))
        try:
            params_payload = json.loads(params_bytes, object_pairs_hook=_unique_json_object)
            final_K = [float(params_payload[name]) for name in KERNEL_NAMES]
        except Exception as exc:
            raise ValueError(f"submitted solver produced invalid kernel_params.json: {exc}") from exc
        if not any(np.array_equal(np.asarray(query), np.asarray(final_K)) for query in requests):
            raise ValueError("final kernel was never evaluated by the host objective")
        final_residual = _objective_residual(final_K)
        if not np.isfinite(final_residual).all():
            raise ValueError("host objective returned a non-finite final residual")
        receipt = {
            "schema": "task90-host-objective-receipt/v1",
            "objective_scope": "evaluator-observable objective requests; internal optimizer calls are not counted",
            "objective_requests": len(requests),
            "final_residual": float(np.linalg.norm(final_residual)),
            "solver_sha256": source_hash,
            "target_sha256": target_hash,
            "objective_features_sha256": hashlib.sha256(feature_helper_bytes).hexdigest(),
            "candidate_report_sha256": hashlib.sha256(candidate_report_bytes).hexdigest(),
            "kernel_params_sha256": hashlib.sha256(params_bytes).hexdigest(),
            "response_curves_sha256": hashlib.sha256(curve_bytes).hexdigest(),
        }
        _check_candidate_claims(candidate_log, receipt)
        return receipt


def _save_host_receipt(receipt, candidate_report_bytes):
    logs_value = os.environ.get("BENCH_LOGS")
    if not logs_value:
        return
    logs = Path(logs_value)
    logs.mkdir(parents=True, exist_ok=True)
    for name, payload in (
        ("task90-objective-receipt.json", (json.dumps(receipt, sort_keys=True, indent=2) + "\n").encode("utf-8")),
        ("task90-candidate-report.json", candidate_report_bytes),
    ):
        temp = logs / f".{name}.{os.getpid()}.tmp"
        fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        try:
            view = memoryview(payload)
            while view:
                view = view[os.write(fd, view):]
            os.fsync(fd)
        finally:
            os.close(fd)
        os.replace(temp, logs / name)


def main(argv):
    workspace = Path(argv[1] if len(argv) > 1 else ".")
    final = workspace / "final"
    try:
        _verify_private_boundary()
    except (OSError, RuntimeError, subprocess.SubprocessError, json.JSONDecodeError) as exc:
        print(f"ERROR L0: candidate isolation is not established: {exc}", file=sys.stderr)
        return finish(2)
    try:
        source = _read_regular(final, "solver.py", MAX_SOLVER_BYTES)
        target_bytes = _read_regular(workspace / "assets", "response_targets.json", 100_000)
        feature_helper_bytes = _read_regular(workspace / "assets", "objective_features.py", MAX_FEATURE_HELPER_BYTES)
        original_params = _read_regular(final, "kernel_params.json", MAX_OUTPUT_BYTES)
        original_curve = _read_regular(final, "response_curves.csv", MAX_OUTPUT_BYTES)
        original_report_bytes = _read_regular(final, "solver.log", 100_000)
        original_report = _parse_candidate_report(original_report_bytes)
        receipt = _run_candidate(source, original_report_bytes, target_bytes, feature_helper_bytes)
        _check_candidate_claims(original_report, receipt)
        if receipt["kernel_params_sha256"] != hashlib.sha256(original_params).hexdigest():
            raise ValueError("submitted kernel_params.json differs from isolated solver replay")
        if receipt["response_curves_sha256"] != hashlib.sha256(original_curve).hexdigest():
            raise ValueError("submitted response_curves.csv differs from isolated solver replay")
        log_bytes = (json.dumps(receipt, sort_keys=True, indent=2) + "\n").encode("utf-8")
        dfd = os.open(final, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            temp_name = f".solver.log.{os.getpid()}.tmp"
            fd = os.open(temp_name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o644, dir_fd=dfd)
            try:
                os.write(fd, log_bytes)
                os.fsync(fd)
            finally:
                os.close(fd)
            os.rename(temp_name, "solver.log", src_dir_fd=dfd, dst_dir_fd=dfd)
        finally:
            os.close(dfd)
        params = json.loads(original_params, object_pairs_hook=_unique_json_object)
        K = load_kernel(params)
        curve = np.genfromtxt(io.StringIO(original_curve.decode("utf-8")), delimiter=",", names=True)
        log = log_bytes.decode("utf-8")
    except (OSError, json.JSONDecodeError, KeyError, ValueError, RuntimeError, subprocess.SubprocessError) as exc:
        return finish(fail("L1", str(exc)))
    if curve.ndim == 0:
        return finish(fail("L1", "response_curves.csv needs multiple data rows"))
    if not {"k_Ainv", "eps", "chi"}.issubset(set(curve.dtype.names or ())):
        return finish(fail("L1", "response_curves.csv needs columns k_Ainv, eps, chi"))
    if not all(np.isfinite(curve[name]).all() for name in ("k_Ainv", "eps", "chi")):
        return finish(fail("L2", "response curve contains a non-finite value"))
    k_curve = np.asarray(curve["k_Ainv"], dtype=float)
    if (len(k_curve) < 200 or k_curve[0] > 0.05 or k_curve[-1] < 6.0
            or np.any(np.diff(k_curve) <= 0.0)):
        return finish(fail("L2", "response curve must be strictly increasing and cover k from about 0 to at least 6 Angstrom^-1"))
    if not solver_log_has_metrics(log):
        return finish(fail("L2", "solver.log is missing a valid evaluator-generated objective request receipt"))
    if (receipt["solver_sha256"] != hashlib.sha256(source).hexdigest()
            or receipt["target_sha256"] != hashlib.sha256(target_bytes).hexdigest()
            or receipt["objective_features_sha256"] != hashlib.sha256(feature_helper_bytes).hexdigest()
            or receipt["kernel_params_sha256"] != hashlib.sha256(original_params).hexdigest()
            or receipt["response_curves_sha256"] != hashlib.sha256(original_curve).hexdigest()):
        return finish(fail("L2", "host objective receipt is not bound to the submitted source, target, and final outputs"))
    try:
        got = observables(K)
    except RuntimeError as exc:
        return finish(fail("L3", str(exc)))
    for key, tol in TOL.items():
        if abs(got[key] - TARGETS[key]) > tol:
            return finish(fail("L3", f"{key}={got[key]:.6g} is outside {TARGETS[key]} ± {tol}"))
    if dkm_band_occupied(K):
        return finish(fail("L3", "eps(k) enters 0 <= eps < 1 on real k"))
    # The curve is a required scientific deliverable, not decorative output:
    # every row must be generated by the submitted kernel coefficients.
    expected_eps = epsilon_k(k_curve, K)
    expected_chi = 1.0 - 1.0 / expected_eps
    if (not np.isfinite(expected_eps).all()
            or not np.allclose(curve["eps"], expected_eps, rtol=3e-6, atol=2e-8)
            or not np.allclose(curve["chi"], expected_chi, rtol=3e-6, atol=2e-8)):
        return finish(fail("L3", "response_curves.csv does not numerically match eps(k), chi(k) from kernel_params.json"))
    try:
        unchanged = (
            _read_regular(final, "solver.py", MAX_SOLVER_BYTES) == source
            and _read_regular(workspace / "assets", "response_targets.json", 100_000) == target_bytes
            and _read_regular(workspace / "assets", "objective_features.py", MAX_FEATURE_HELPER_BYTES) == feature_helper_bytes
            and _read_regular(final, "kernel_params.json", MAX_OUTPUT_BYTES) == original_params
            and _read_regular(final, "response_curves.csv", MAX_OUTPUT_BYTES) == original_curve
        )
    except (OSError, ValueError) as exc:
        return finish(fail("L2", f"could not recheck submitted file snapshots: {exc}"))
    if not unchanged:
        return finish(fail("L2", "submitted source, targets, or outputs changed during evaluation"))
    try:
        _save_host_receipt(receipt, original_report_bytes)
    except OSError as exc:
        print(f"ERROR L0: could not persist host objective receipt: {exc}", file=sys.stderr)
        return finish(2)
    # The published kernel is reported only as a distance, not as a second
    # pass/fail gate.
    distance = max(abs(K[name] - PUBLISHED[name]) / max(abs(PUBLISHED[name]), 1e-6) for name in PUBLISHED)
    print("PASS")
    print(json.dumps({"observables": got, "max_relative_distance_to_published_kernel": distance}, indent=2))
    return finish(0)


def finish(code):
    logs = os.environ.get("BENCH_LOGS")
    if logs:
        out = Path(logs)
        out.mkdir(parents=True, exist_ok=True)
        if code == 2:
            (out / "reward.txt").unlink(missing_ok=True)
            (out / "verification.json").unlink(missing_ok=True)
            return code
        reward = 1 if code == 0 else 0
        (out / "reward.txt").write_text(f"{reward}\n", encoding="utf-8")
        (out / "verification.json").write_text(json.dumps({
            "status": "PASS" if code == 0 else "FAIL", "reward": reward
        }) + "\n", encoding="utf-8")
    return code


if __name__ == "__main__":
    sys.exit(main(sys.argv))
