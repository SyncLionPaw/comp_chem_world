#!/usr/bin/env python3
# L1 Deliverables: Check required deliverables for completeness and parseability.
# L2 Execution: No separate execution attestation is implied by checks of submitted results.
# L3 Science: Recover a hydration solver that loses oscillations.
"""Full-curve recovery verifier with unprivileged candidate replay."""
from __future__ import annotations
import ctypes, io, json, os, pwd, shutil, signal, stat, subprocess, sys, tempfile, time, resource, re, unicodedata
from pathlib import Path
import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE / "_support"))
import force_model_gold as gold
SHIFTS = ((0.08, 0.50), (0.12, 0.50), (0.10, 0.35), (0.10, 0.65))
LGRID = np.arange(2.0, 20.0001, 0.10)

def finish(code: int, message: str = "") -> int:
    logs = os.environ.get("BENCH_LOGS")
    if logs:
        out = Path(logs); out.mkdir(parents=True, exist_ok=True)
        if code == 2:
            (out / "reward.txt").unlink(missing_ok=True)
            (out / "verification.json").unlink(missing_ok=True)
        else:
            reward = int(code == 0)
            (out / "reward.txt").write_text(f"{reward}\n", encoding="utf-8")
            (out / "verification.json").write_text(json.dumps({"status": "PASS" if reward else "FAIL", "reward": reward, "message": message}) + "\n", encoding="utf-8")
    return code

def fail(message: str) -> int:
    print("FAIL L3: " + message)
    return finish(1, message)

def reference(P0: float, alpha: float) -> np.ndarray:
    old = gold.P0, gold.ALPHA
    gold.P0, gold.ALPHA = P0, alpha
    try:
        return np.asarray([gold.pressure(float(L)) for L in LGRID], dtype=float)
    finally:
        gold.P0, gold.ALPHA = old

def read_regular_at(directory: Path, basename: str) -> bytes:
    """Read a single untrusted file through a no-follow directory/file FD."""
    if basename in ("", ".", "..") or "/" in basename or "\\" in basename:
        raise ValueError("unsafe submitted basename")
    dfd=os.open(directory,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
    try:
        fd=os.open(basename,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK,dir_fd=dfd)
        try:
            if not stat.S_ISREG(os.fstat(fd).st_mode):
                raise ValueError(f"{basename} is not a regular file")
            chunks=[]
            while True:
                chunk=os.read(fd,1<<20)
                if not chunk: break
                chunks.append(chunk)
            return b"".join(chunks)
        finally: os.close(fd)
    finally: os.close(dfd)

def write_private_copy(directory: Path, basename: str, content: bytes) -> None:
    if basename in ("", ".", "..") or "/" in basename or "\\" in basename:
        raise ValueError("unsafe staged basename")
    dfd=os.open(directory,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
    try:
        fd=os.open(basename,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600,dir_fd=dfd)
        try:
            with os.fdopen(fd,"wb",closefd=False) as stream: stream.write(content)
        finally: os.close(fd)
    finally: os.close(dfd)

def _demote():
    nobody = pwd.getpwnam("nobody")
    os.setgroups([])
    os.setgid(nobody.pw_gid)
    os.setuid(nobody.pw_uid)
    if ctypes.CDLL(None).prctl(38, 1, 0, 0, 0) != 0:  # PR_SET_NO_NEW_PRIVS
        raise OSError("PR_SET_NO_NEW_PRIVS failed")
    resource.setrlimit(resource.RLIMIT_CPU, (120, 120))
    resource.setrlimit(resource.RLIMIT_FSIZE, (100 * 1024 * 1024, 100 * 1024 * 1024))
    resource.setrlimit(resource.RLIMIT_NPROC, (1, 1))

def _isolated_process(argv, cwd: Path, env: dict[str, str], timeout: int):
    proc = subprocess.Popen(argv, cwd=cwd, env=env, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, text=True, start_new_session=True,
                            preexec_fn=_demote)
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

def isolation_probe() -> dict:
    """Adversarially prove the execution uid cannot access refs or reward."""
    if os.geteuid() != 0:
        raise RuntimeError("cannot establish private-reference isolation without root")
    with tempfile.TemporaryDirectory(prefix="case007-probe-") as td:
        root = Path(td); os.chmod(root, 0o755)
        scratch = root / "scratch"; scratch.mkdir(mode=0o777); os.chmod(scratch, 0o777)
        probe = scratch / "probe.py"
        marker = scratch / "probe-result.json"
        probe.write_text(
            "import json, pathlib\n"
            f"private=pathlib.Path({str(HERE / '_support' / 'force_model_gold.py')!r})\n"
            "out={}\n"
            "try: private.read_bytes(); out['read']='allowed'\n"
            "except PermissionError: out['read']='denied'\n"
            "except Exception as e: out['read']=type(e).__name__\n"
            "try: private.write_bytes(b'attack'); out['write']='allowed'\n"
            "except PermissionError: out['write']='denied'\n"
            "except Exception as e: out['write']=type(e).__name__\n"
            f"reward=pathlib.Path({str(Path(os.environ.get('BENCH_LOGS', '/logs/verifier')) / 'reward.txt')!r})\n"
            "try: reward.write_text('1\\n'); out['reward']='allowed'\n"
            "except PermissionError: out['reward']='denied'\n"
            "except Exception as e: out['reward']=type(e).__name__\n"
            "public_reward=pathlib.Path('/logs/verifier/reward.txt')\n"
            "try: public_reward.write_text('0\\n'); out['public_log_write']='allowed'\n"
            "except PermissionError: out['public_log_write']='denied'\n"
            "except Exception as e: out['public_log_write']=type(e).__name__\n"
            "try:\n"
            " pid=__import__('os').fork()\n"
            " if pid==0: __import__('os')._exit(0)\n"
            " out['fork']='allowed'\n"
            "except OSError: out['fork']='denied'\n"
            f"pathlib.Path({str(marker)!r}).write_text(json.dumps(out))\n",
            encoding="utf-8")
        env = {"PATH": "/usr/local/bin:/usr/bin:/bin", "HOME": str(root), "PYTHONNOUSERSITE": "1"}
        proc = _isolated_process([sys.executable, str(probe)], scratch, env, 10)
        if proc.returncode != 0 or not marker.is_file():
            raise RuntimeError(f"adversarial isolation probe failed: rc={proc.returncode}, marker={marker.is_file()}, stdout={proc.stdout!r}, stderr={proc.stderr!r}")
        result = json.loads(marker.read_text(encoding="utf-8"))
        if result.get("read") != "denied" or result.get("write") != "denied" or result.get("reward") != "denied" or result.get("fork") != "denied" or result.get("public_log_write") not in {"allowed", "denied"}:
            raise RuntimeError(f"candidate can access private evaluator state: {result}")
        return result

def candidate_run(submission: Path, P0: float, alpha: float, timeout: int = 120):
    """Run candidate code with only its own source and writable scratch visible."""
    if os.geteuid() != 0:
        raise RuntimeError("image must run verifier as root so candidate can be demoted to nobody")
    with tempfile.TemporaryDirectory(prefix="case007-isolated-") as td:
        root = Path(td); os.chmod(root, 0o755)
        ws = root / "workspace"; ws.mkdir(mode=0o777)
        try:
            solver_bytes=read_regular_at(submission,"fixed_solver.py")
            model_bytes=read_regular_at(submission,"force_model.py")
        except (OSError,ValueError) as exc:
            return subprocess.CompletedProcess([],0,"",""),None,f"unsafe candidate source (symlink/non-regular): {exc}"
        write_private_copy(ws,"fixed_solver.py",solver_bytes)
        write_private_copy(ws,"force_model.py",model_bytes)
        os.chmod(ws / "fixed_solver.py", 0o644); os.chmod(ws / "force_model.py", 0o644)
        os.chmod(ws, 0o777)
        env = {"PATH": "/usr/local/bin:/usr/bin:/bin", "HOME": str(root),
               "PYTHONNOUSERSITE": "1", "OPENBLAS_NUM_THREADS": "1", "OMP_NUM_THREADS": "1",
               "CASE007_P0": str(P0), "CASE007_ALPHA": str(alpha)}
        proc = _isolated_process([sys.executable, str(ws / "fixed_solver.py"), str(ws)], ws, env, timeout)
        try:
            curve_bytes=read_regular_at(ws / "final","force_fixed.csv")
            candidate_curve,error=parse_curve_bytes(curve_bytes)
        except (OSError,ValueError) as exc:
            candidate_curve,error=None,f"unsafe candidate output (symlink/non-regular): {exc}"
        return proc, candidate_curve, error

def parse_curve_bytes(data: bytes):
    try:
        data = np.genfromtxt(io.BytesIO(data), delimiter=",", names=True)
    except Exception as exc:
        return None, f"cannot parse force_fixed.csv: {exc}"
    names = data.dtype.names or ()
    if data.ndim != 1 or len(data) != len(LGRID) or not {"L_A", "Pi_Pa"}.issubset(names):
        return None, f"force_fixed.csv needs exactly {len(LGRID)} rows and L_A,Pi_Pa columns"
    x, y = np.asarray(data["L_A"], float), np.asarray(data["Pi_Pa"], float)
    if not np.isfinite(x).all() or not np.isfinite(y).all() or not np.allclose(x, LGRID, rtol=0, atol=1e-9):
        return None, "force_fixed.csv grid or pressure values are invalid"
    return y, ""

def parse_curve(path: Path):
    try: return parse_curve_bytes(read_regular_at(path.parent,path.name))
    except (OSError,ValueError) as exc: return None,f"unsafe/non-regular force_fixed.csv: {exc}"

def sign_changes(y: np.ndarray) -> int:
    mask = (LGRID >= 4.0) & (LGRID <= 20.0)
    signs = np.sign(y[mask]); signs = signs[signs != 0]
    return int(np.sum(signs[1:] * signs[:-1] < 0))

def defective_fixture_sign_changes() -> int:
    asset = Path("/app/assets/defective_force_model.py")
    if not asset.is_file():
        asset = Path(__file__).resolve().parents[1] / "environment/assets/defective_force_model.py"
    import importlib.util
    spec = importlib.util.spec_from_file_location("case007_public_defect", asset)
    if spec is None or spec.loader is None:
        raise RuntimeError("public injected-defect model cannot be loaded")
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    bad = np.asarray([module.pressure(float(L)) for L in LGRID], dtype=float)
    if not np.isfinite(bad).all():
        raise RuntimeError("public injected-defect model emitted non-finite pressures")
    return sign_changes(bad)


def _normalize_derivative_notation(text: str) -> str:
    # Normalize common Unicode/LaTeX prime and subscript spellings only.
    text = unicodedata.normalize("NFKC", text)
    text = text.replace("′", "'").replace("’", "'").replace("‘", "'")
    text = text.replace("″", "''").replace("‴", "'''")
    text = re.sub(r"\\prime\b", "'", text)
    text = re.sub(r"\\(?:left|right)\b", "", text)
    text = re.sub(r"P\s*_\s*\{?\s*1\s*\}?", "P1", text)
    text = text.replace("P₁", "P1")
    text = re.sub(r"\^\s*\{\s*('+?)\s*\}", r"\1", text)
    text = re.sub(r"\^\s*('+)", r"\1", text)
    return text

def has_zero_derivative_condition(text: str, order: int) -> bool:
    # Endpoint notation is optional; the full curve/replay gates assess both ends.
    if order not in (1, 2):
        return False
    normalized = _normalize_derivative_notation(text)
    prime = "'" * order
    atom = rf"(?<![A-Za-z0-9])P1\s*{re.escape(prime)}(?!')"
    endpoint = r"(?:\s*\(\s*(?:z\s*=\s*)?(?:0|L)\s*\))?"
    zero = r"\s*=\s*0(?:\.0+)?(?=$|[^0-9.]|\.(?!\d))"
    return re.search(atom + endpoint + zero, normalized) is not None

def main(argv: list[str]) -> int:
    final = Path(argv[1] if len(argv) > 1 else ".") / "final"
    required = [final / name for name in ("fixed_solver.py", "force_model.py", "diagnosis.md", "force_fixed.csv", "recovery.json")]
    try:
        submitted={name:read_regular_at(final,name) for name in
                   ("fixed_solver.py","force_model.py","diagnosis.md","force_fixed.csv","recovery.json")}
        recovery=json.loads(submitted["recovery.json"])
        diagnosis=submitted["diagnosis.md"].decode("utf-8")
    except (OSError, ValueError,UnicodeDecodeError) as exc:
        return fail(f"missing, unsafe, or invalid recovery submission: {exc}")
    if not isinstance(recovery, dict):
        return fail("recovery.json must contain a JSON object")
    if recovery.get("natural_boundary") != "P1''=0" or recovery.get("pressure_definition") != "-dU/dL_A/epsilon0":
        return fail("repair must retain natural P1''=0 and variational pressure definition")
    if not (has_zero_derivative_condition(diagnosis, 1) and has_zero_derivative_condition(diagnosis, 2)):
        return fail("diagnosis must identify the substituted first-derivative zero condition and the corrected second-derivative zero condition")
    # Keep private reference files inaccessible for the remainder of the
    # verifier lifetime; never reopen this directory to a candidate child.
    os.chmod(HERE, 0o700)
    try:
        isolation = isolation_probe()
        injected_defect_changes = defective_fixture_sign_changes()
    except Exception as exc:
        print(f"ERROR L0: adversarial candidate-isolation check failed: {exc}", file=sys.stderr)
        return finish(2)
    base, error = parse_curve_bytes(submitted["force_fixed.csv"])
    if error: return fail(error)
    expected_base = reference(0.10, 0.50)
    if not np.allclose(base, expected_base, rtol=2e-5, atol=1e-3):
        return fail(f"public-parameter full pressure curve differs from independent reference (max abs {np.max(np.abs(base-expected_base)):.6g} Pa)")
    if sign_changes(base) < 7:
        return fail("recovered public curve does not reproduce the oscillatory force pattern")
    if injected_defect_changes >= 2:
        return fail("public defective program no longer exhibits the injected loss of oscillations")
    # Private parameter shifts are grader-owned inputs. Requiring candidates to
    # predeclare their values in recovery.json would leak the hidden tuple.
    # Record execution evidence only in this trusted verifier's private logs.
    hidden_checks = []
    for p, a in SHIFTS:
        try:
            proc, got, error = candidate_run(final, p, a)
        except subprocess.TimeoutExpired:
            return fail(f"hidden solver timed out for P0={p}, alpha={a}")
        except Exception as exc:
            print(f"ERROR L0: candidate isolation unavailable: {exc}", file=sys.stderr)
            return finish(2)
        if proc.returncode != 0:
            return fail(f"hidden solver exited {proc.returncode} for P0={p}, alpha={a}")
        if error: return fail(f"hidden P0={p}, alpha={a}: {error}")
        expected = reference(p, a)
        if not np.allclose(got, expected, rtol=2e-5, atol=1e-3):
            return fail(f"hidden curve mismatch at P0={p}, alpha={a}; max abs {np.max(np.abs(got-expected)):.6g} Pa")
        if np.allclose(got, base, rtol=1e-6, atol=1e-6):
            return fail(f"hidden parameters were ignored at P0={p}, alpha={a}")
        hidden_checks.append({"P0": p, "alpha": a, "points": len(LGRID),
                              "full_curve_match": True, "parameters_responded": True})
    print("PASS")
    print(json.dumps({"full_curve_points": len(LGRID), "public_sign_changes_4_to_20_A": sign_changes(base),
                      "injected_defect_sign_changes_4_to_20_A": injected_defect_changes,
                      "hidden_numeric_reruns": len(hidden_checks), "hidden_run_checks": hidden_checks,
                      "candidate_uid": "nobody",
                      "private_ref_and_reward_write_probe": "denied",
                      "public_bind_write_probe": isolation["public_log_write"],
                      "public_bind_is_non_authoritative": "reward/report are private until all candidate processes are killed and absent"}, indent=2))
    return finish(0)

if __name__ == "__main__":
    try:
        code = main(sys.argv)
    except Exception as exc:
        print(f"ERROR L0: private reference/verifier failure: {exc}", file=sys.stderr)
        code = 2
    # Environment/verifier errors must clear any stale reward through the
    # shared wrapper; candidate failures remain ordinary reward-zero results.
    sys.exit(finish(2) if code == 2 else code)
