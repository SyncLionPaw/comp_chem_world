#!/usr/bin/env python3
# L1 Deliverables: Check required deliverables for completeness and parseability.
# L2 Execution: Check execution evidence through bounded replay or independent recomputation where implemented.
# L3 Science: Extract solvent clusters while preserving molecules and periodic-boundary geometry.
"""Terminal-state science verification with private references and isolated replay."""
from __future__ import annotations
import hashlib,json,importlib,sys,traceback
from pathlib import Path
_REFS_BYTES=Path(__file__).with_name('refs.json').read_bytes()
if hashlib.sha256(_REFS_BYTES).hexdigest()!='89739253c06cf0d16e9889ca35ce20b5aba64d3cb3a9bd182489d326324a2d8a':
    raise RuntimeError('Private reference integrity mismatch')
REFS=json.loads(_REFS_BYTES)
"""Linux replay isolation: public inputs/source only, immutable runtime, private scratch.

Landlock is enforced even against root; replay also drops to nobody so it cannot
inspect/control the root verifier. No /proc process paths, scorer, final artifacts,
SSH material, inherited descriptors or application environment are exposed.
"""
import ctypes
import errno
import os
from pathlib import Path
import selectors
import signal
import shutil
import stat
import subprocess
import sys
import tempfile
import time

READ = (1 << 0) | (1 << 2) | (1 << 3)  # execute, read file, read directory
WRITE = (1 << 1) | sum(1 << i for i in range(4, 15))
MAX_CAPTURE_BYTES = 64 * 1024


class ReplayInfrastructureError(RuntimeError):
    """The evaluator could not provision or launch an isolated replay."""


def run_bounded(command, timeout, env, pass_fds=()):
    """Run one submitted program with bounded diagnostics and process cleanup."""
    try:
        process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                   close_fds=True, pass_fds=pass_fds, start_new_session=True, env=env)
    except OSError as error:
        raise ReplayInfrastructureError('Cannot launch isolated replay: ' + str(error)) from error
    output = bytearray()
    selector = selectors.DefaultSelector()
    selector.register(process.stdout, selectors.EVENT_READ)
    deadline = time.monotonic() + timeout
    timed_out = False
    while selector.get_map() or process.poll() is None:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            timed_out = True
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.wait()
            # Drain only the bounded tail after killing the whole replay group.
            remaining = 1.0
        events = selector.select(min(max(remaining, 0), 0.1))
        for key, _ in events:
            try:
                chunk = os.read(key.fileobj.fileno(), 16384)
            except OSError as error:
                raise ReplayInfrastructureError('Cannot capture isolated replay output: ' + str(error)) from error
            if not chunk:
                selector.unregister(key.fileobj)
                continue
            output.extend(chunk)
            if len(output) > MAX_CAPTURE_BYTES:
                del output[:-MAX_CAPTURE_BYTES]
        if timed_out:
            # Children that inherited stdout are in the same session and have
            # been killed; do not wait forever on a leaked pipe descriptor.
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            break
    selector.close()
    if process.poll() is None:
        process.wait()
    text = output.decode('utf-8', errors='replace')
    if timed_out:
        raise subprocess.TimeoutExpired(command, timeout, output=text, stderr=None)
    # Existing scientific verifiers include ``stderr`` in failed replay
    # diagnostics; keep that field as a bounded combined stream.
    return subprocess.CompletedProcess(command, process.returncode, '', text)


def copy_python_sources(source_root, destination_root):
    """Stage submitted Python helpers only; never stage precomputed outputs."""
    source_root = Path(source_root).resolve()
    for source in sorted(source_root.rglob('*.py')):
        if '__pycache__' in source.parts:
            continue
        mode = source.lstat().st_mode
        if not stat.S_ISREG(mode):
            raise ValueError('Submitted Python helper must be a regular file: ' + str(source.relative_to(source_root)))
        relative = source.relative_to(source_root)
        target = Path(destination_root) / relative
        try:
            data = source.read_bytes()
        except OSError as error:
            raise ValueError('Submitted Python helper cannot be read: ' + str(relative)) from error
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
            target.chmod(0o444)
        except OSError as error:
            raise ReplayInfrastructureError('Cannot stage submitted Python helper: ' + str(error)) from error


def copy_resp_config(source_root, destination_root):
    """Stage only case-01's explicitly contracted, independently validated config."""
    source = Path(source_root) / 'fit-input.json'
    try:
        mode = source.lstat().st_mode
    except FileNotFoundError:
        return
    except OSError as error:
        raise ValueError('Submitted fit-input.json cannot be inspected') from error
    if not stat.S_ISREG(mode):
        raise ValueError('Submitted fit-input.json must be a regular file')
    try:
        import json
        data = json.loads(source.read_text())
    except (OSError, ValueError) as error:
        raise ValueError('Submitted fit-input.json is not valid readable JSON') from error
    if (not isinstance(data, dict) or not {'method','a','b','restrained_atoms','charge_constraint','convergence_rule'}.issubset(data)
            or not isinstance(data.get('method'), str) or not isinstance(data.get('convergence_rule'), str)
            or type(data.get('a')) not in (int,float) or type(data.get('b')) not in (int,float)
            or type(data.get('charge_constraint')) not in (int, float)
            or not isinstance(data.get('restrained_atoms'),list)
            or any(type(value) is not int for value in data['restrained_atoms'])):
        raise ValueError('Submitted fit-input.json has invalid contracted types')
    target = Path(destination_root) / 'fit-input.json'
    try:
        allowed = ('method','a','b','restrained_atoms','charge_constraint','convergence_rule')
        target.write_text(json.dumps({key: data[key] for key in allowed}, separators=(',', ':')) + '\n')
        target.chmod(0o444)
    except OSError as error:
        raise ReplayInfrastructureError('Cannot stage declared RESP config: ' + str(error)) from error


def restrict(root):
    libc = ctypes.CDLL(None, use_errno=True)
    abi = libc.syscall(444, 0, 0, 1)
    if abi < 3:
        raise RuntimeError('Replay requires Linux Landlock ABI >= 3')
    handled = READ | WRITE
    if abi < 3:
        handled &= ~(1 << 14)
    attr = ctypes.c_uint64(handled)
    fd = libc.syscall(444, ctypes.byref(attr), ctypes.sizeof(attr), 0)
    if fd < 0:
        raise OSError(ctypes.get_errno(), 'landlock_create_ruleset')
    class Rule(ctypes.Structure):
        _pack_ = 1
        _fields_ = [('access', ctypes.c_uint64), ('parent', ctypes.c_int32)]
    def allow(path, rights):
        if not Path(path).exists():
            return
        parent = os.open(path, os.O_PATH | os.O_CLOEXEC)
        try:
            rule = Rule(rights, parent)
            if libc.syscall(445, fd, 1, ctypes.byref(rule), 0):
                raise OSError(ctypes.get_errno(), 'landlock_add_rule: ' + str(path))
        finally:
            os.close(parent)
    try:
        for path in ['/opt/autosolvate', '/usr', '/bin', '/lib', '/lib64']:
            allow(path, READ)
        for path in ['/etc/ld.so.cache', '/etc/localtime', '/proc/cpuinfo', '/proc/meminfo', '/dev/urandom', '/dev/random']:
            allow(path, 1 << 2)
        allow('/dev/null', (1 << 1) | (1 << 2))
        allow(root / 'inputs', READ)
        allow(root / 'sources', READ)
        allow(root / 'work', handled)
        if libc.prctl(38, 1, 0, 0, 0):  # PR_SET_NO_NEW_PRIVS
            raise OSError(ctypes.get_errno(), 'no_new_privs')
        if libc.syscall(446, fd, 0):
            raise OSError(ctypes.get_errno(), 'landlock_restrict_self')
    finally:
        os.close(fd)


def launch(root, probe=False, script_name="script.py", status_fd=None):
    root = Path(root).resolve()
    try:
        if os.getuid() == 0:
            os.setgroups([])
            os.setgid(65534)
            os.setuid(65534)
        restrict(root)
    except Exception as error:
        if status_fd is not None:
            try: os.write(status_fd, b'X')
            except OSError: pass
        raise SystemExit(125)
    if probe:
        # Probe in the same privilege/filesystem state used by actual replays.
        for forbidden in ['/app/final', '/tests', '/root/.ssh', '/proc/1/root']:
            try:
                os.listdir(forbidden)
            except (PermissionError, FileNotFoundError):
                continue
            raise RuntimeError('Replay isolation probe could read ' + forbidden)
        return
    source = root / 'sources' / script_name
    os.chdir(root / 'work')
    env = {'PATH': '/opt/autosolvate/bin:/usr/local/bin:/usr/bin:/bin',
           'AMBERHOME': '/opt/autosolvate', 'HOME': str(root / 'work'),
           'TMPDIR': str(root / 'work'), 'OPENMM_CPU_THREADS': '4',
           'OPENBLAS_NUM_THREADS': '1', 'OMP_NUM_THREADS': '4', 'LANG': 'C.UTF-8'}
    if status_fd is not None:
        os.set_inheritable(status_fd, False)
        os.write(status_fd, b'S')
    try:
        os.execve(sys.executable, [sys.executable, '-B', str(source),
                   '--input-dir', str(root / 'inputs'), '--output-dir', str(root / 'work/outputs')], env)
    except OSError:
        if status_fd is not None:
            try: os.write(status_fd, b'E')
            except OSError: pass
        raise SystemExit(125)


def prepare(root):
    root.chmod(0o755)
    (root / 'sources').mkdir(mode=0o755)
    (root / 'work').mkdir(mode=0o777)
    (root / 'work').chmod(0o777)
    (root / 'inputs').mkdir(mode=0o755)


def preflight():
    with tempfile.TemporaryDirectory(prefix='replay-probe-') as directory:
        root = Path(directory)
        prepare(root)
        result = subprocess.run([sys.executable, str(Path(__file__).resolve()), '--probe', str(root)],
                                capture_output=True, text=True, timeout=15, close_fds=True)
        if result.returncode:
            raise RuntimeError('Replay isolation unavailable: ' + result.stderr[-1000:])


def run_replay(script, input_dir, output_dir, timeout):
    try:
        temporary = tempfile.TemporaryDirectory(prefix='isolated-replay-')
    except OSError as error:
        raise ReplayInfrastructureError('Cannot create private replay directory: ' + str(error)) from error
    with temporary as directory:
        root = Path(directory)
        try:
            prepare(root)
        except OSError as error:
            raise ReplayInfrastructureError('Cannot provision isolated replay directories: ' + str(error)) from error
        script = Path(script).resolve()
        source_root = script.parent
        copy_python_sources(source_root, root / 'sources')
        if script.name == 'fit.py':
            copy_resp_config(source_root, root / 'sources')
        # Preserve __file__/argv basename for programs that copy their own source.
        script_name=Path(script).name
        try:
            shutil.copytree(input_dir, root / 'inputs', dirs_exist_ok=True)
            for path in (root / 'inputs').rglob('*'):
                if path.is_symlink():
                    raise ReplayInfrastructureError('Public replay input contains a symlink')
                path.chmod(0o555 if path.is_dir() else 0o444)
        except ReplayInfrastructureError:
            raise
        except OSError as error:
            raise ReplayInfrastructureError('Cannot stage public replay inputs: ' + str(error)) from error
        out = root / 'work/outputs'
        try:
            out.mkdir(mode=0o777)
            out.chmod(0o777)
        except OSError as error:
            raise ReplayInfrastructureError('Cannot provision private replay output: ' + str(error)) from error
        status_read, status_write = os.pipe()
        try:
            command = [sys.executable, str(Path(__file__).resolve()), '--launch', str(root),
                       script_name, '--status-fd', str(status_write)]
            try:
                result = run_bounded(command, timeout=timeout, env={'PATH': os.environ.get('PATH', '')},
                                     pass_fds=(status_write,))
            except subprocess.TimeoutExpired:
                os.close(status_read)
                raise
        finally:
            os.close(status_write)
        try:
            trusted_status = bytearray()
            while True:
                chunk = os.read(status_read, 64)
                if not chunk: break
                trusted_status.extend(chunk)
        finally:
            os.close(status_read)
        if trusted_status == b'X':
            raise ReplayInfrastructureError('Isolated replay could not establish sandbox restrictions')
        if trusted_status == b'E':
            raise ReplayInfrastructureError('Isolated replay could not exec submitted program')
        if trusted_status != b'S':
            raise ReplayInfrastructureError('Isolated replay launcher exited before its trusted start marker')
        if result.returncode == 125:
            # A candidate can choose both its stderr text and exit status; neither
            # changes the trusted launch marker or upgrades FAIL to ENV_INVALID.
            pass
        # Never follow submitted output symlinks into scoring/reference material.
        try:
            for path in out.rglob('*'):
                mode=path.lstat().st_mode
                if not (stat.S_ISREG(mode) or stat.S_ISDIR(mode)):
                    raise ValueError('Replay output must be regular file/directory: ' + str(path.relative_to(out)))
        except OSError as error:
            raise ReplayInfrastructureError('Cannot inspect isolated replay output: ' + str(error)) from error
        output_dir = Path(output_dir)
        if output_dir.is_symlink() or not output_dir.is_dir():
            raise ValueError('Replay destination must be a real directory')
        if any(output_dir.iterdir()):
            raise ValueError('Replay destination must be empty; refusing to merge stale files')
        try:
            output_dir.rmdir()
            shutil.copytree(out, output_dir)
        except OSError as error:
            raise ReplayInfrastructureError('Cannot collect isolated replay output: ' + str(error)) from error
        return result


if __name__ == '__main__' and len(sys.argv)>1 and sys.argv[1] in ('--probe','--launch'):
    args=sys.argv[1:]
    launch(args[1], probe=args[0]=='--probe',
           script_name=args[2] if len(args)>2 and args[2]!='--status-fd' else 'script.py',
           status_fd=int(args[4]) if len(args)>4 and args[3]=='--status-fd' else None)
    raise SystemExit(0)

#!/usr/bin/env python3
"""Evaluator: independent periodic geometry reference and actual extraction replay."""
import argparse,hashlib,json,subprocess,sys,tempfile
from pathlib import Path
import numpy as np
PACKAGE=Path(__file__).resolve().parents[1]
GOLD=REFS['reference']

def verify(output,replay=True,require_analysis=True):
    # analysis.md is a required submitted deliverable, but L2 replays only the
    # declared frame map and extracted coordinates. It is a report, not a
    # trajectory-derived numeric artifact that the extraction script must
    # recreate in a clean output directory.
    required=['selection.json','extract.py']
    if require_analysis: required.append('analysis.md')
    for name in required:
        p=output/name;assert p.is_file() and p.stat().st_size>0,'Missing '+name
    selection=json.loads((output/'selection.json').read_text())
    actual=selection['frames'];assert len(actual)==10,'Expected ten clusters'
    for frame,ref in zip(actual,GOLD['frames']):
        assert type(frame['frame']) is int and isinstance(frame['atom_indices'],list) and all(type(i) is int for i in frame['atom_indices']),'Frame and atom indices must be JSON integers'
        assert type(frame['time_ps']) in (int,float),'Frame time must be a JSON number, not a boolean'
        assert frame['frame']==ref['frame'],'Wrong frame'
        assert abs(float(frame['time_ps'])-ref['time_ps'])<=REFS['tolerances']['frame_time_ps'],'Incorrect source time'
        assert frame['atom_indices']==ref['atom_indices'],'Whole-molecule shell membership or native atom order incorrect'
        path=Path(frame['file']);resolved=(output/path).resolve()
        assert not path.is_absolute() and resolved.is_relative_to(output.resolve()),'Unsafe cluster path'
        assert path.as_posix()==f"clusters/frame-{ref['frame']:03d}.xyz",'Cluster filename differs from contract'
        lines=resolved.read_text().splitlines();n=int(lines[0]);assert n==len(ref['elements']) and len(lines)==n+2,'Invalid XYZ'
        records=[line.split() for line in lines[2:]]
        assert all(len(row)==4 for row in records),'Invalid XYZ row'
        assert [row[0] for row in records]==ref['elements'],'Incorrect elements/order'
        xyz=np.array([list(map(float,row[1:])) for row in records]);assert np.isfinite(xyz).all()
        assert np.max(np.abs(xyz-np.array(ref['coordinates_angstrom'])))<=REFS['tolerances']['coordinates_angstrom'],'PBC reconstruction/cell/centering incorrect'
    sampling=selection['sampling']
    for key in ['selected_span_ps','source_span_ps']:
        assert type(sampling[key]) in (int,float),'Sampling spans must be JSON numbers, not booleans'
    selected_span=GOLD['frames'][-1]['time_ps']-GOLD['frames'][0]['time_ps']
    assert abs(sampling['selected_span_ps']-selected_span)<REFS['tolerances']['time_span_ps'] and abs(sampling['source_span_ps']-GOLD['trajectory_duration_ps'])<REFS['tolerances']['time_span_ps'],'Incorrect sampling time span'
    assert sampling['independent_equilibrium_samples'] is False,'Short geometric snapshots cannot establish independent equilibrium sampling'
    assert sampling['purpose']=='geometric_extraction_validation','Misrepresented trajectory purpose'
    if replay:
        with tempfile.TemporaryDirectory(prefix='cluster-replay-') as d:
            out=Path(d)/'outputs';out.mkdir()
            r=run_replay(output/'extract.py',PACKAGE/'inputs',out,timeout=120)
            assert r.returncode==0,'Extraction replay failed: '+r.stderr[-1000:]
            import shutil
            if not (out/'extract.py').exists():shutil.copyfile(output/'extract.py',out/'extract.py')
            verify(out,replay=False,require_analysis=False)
    return {'status':'PASS','checked':['L1','L2 actual extraction replay','L3 shell membership','L3 periodic coordinates','L3 sampling limitation','frame/time provenance'],'replayed':replay,'solvent_counts':[r['solvent_molecules'] for r in GOLD['frames']]}


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def emit(logs, status, reason=None, result=None):
    report = {"status": status}
    if reason is not None:
        report["reason"] = reason
    if result is not None:
        report["science"] = result
    if status in {"PASS", "FAIL"}:
        report["reward"] = int(status == "PASS")
        (logs / "reward.txt").write_text(str(report["reward"]) + "\n")
    else:
        (logs / "reward.txt").unlink(missing_ok=True)
    (logs / "verification.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report))
    return {"PASS": 0, "FAIL": 1, "ENV_INVALID": 2}[status]


def main():
    app = Path(os.environ.get("APP", "/app")).resolve()
    tests = Path(os.environ.get("TESTS", Path(__file__).parent)).resolve()
    logs = Path(os.environ.get("LOGS", "/logs/verifier")).resolve()
    logs.mkdir(parents=True, exist_ok=True)
    for name in ("reward.txt", "verification.json"):
        (logs / name).unlink(missing_ok=True)
    try:
        contract = REFS["runtime"]
        for item in contract["inputs"]:
            path = app / item["path"]
            if not path.is_file() or path.is_symlink() or digest(path) != item["sha256"]:
                raise RuntimeError("Public input integrity: " + item["path"])
        for module in contract["python_modules"]:
            importlib.import_module(module)
        verifier = sys.modules[__name__]
        if contract["case_id"] != "case-02":
            preflight()
    except Exception as error:
        (logs / "preflight-error.log").write_text(traceback.format_exc())
        return emit(logs, "ENV_INVALID", str(error))

    output = app / "final"
    # Preserve the original PACKAGE-relative input/reference interface without
    # exposing evaluator materials during the answer phase.
    with tempfile.TemporaryDirectory(prefix="case-verifier-") as directory:
        package = Path(directory)
        (package / "inputs").symlink_to(app / "inputs", target_is_directory=True)
        (package / "tests").symlink_to(tests, target_is_directory=True)
        verifier.PACKAGE = package
        try:
            # Reference-only calculations run before inspecting submissions.
            if contract["case_id"] == "case-03-audit":
                verifier.calculate(package / "inputs")
            if contract["case_id"] == "case-02":
                verifier.check_reference()
            if contract["case_id"] == "case-01":
                verifier.system(package / "inputs")
        except Exception as error:
            return emit(logs, "ENV_INVALID", "Reference preflight: " + str(error))
        try:
            if not output.is_dir():
                return emit(logs, "FAIL", "Missing final/ submission directory")
            if (output / ".invalid-submission-artifact").exists():
                raise ValueError("Submission tree contains symlink or special-file artifacts")
            for path in output.rglob("*"):
                mode = path.lstat().st_mode
                if not (stat.S_ISREG(mode) or stat.S_ISDIR(mode)):
                    raise ValueError("Submission tree contains a symlink or special file: " + str(path.relative_to(output)))
            for name in contract["output_paths"]:
                path = output / name
                if not path.resolve().is_relative_to(output.resolve()):
                    raise ValueError("Submission path escapes final/: " + name)
                if not path.exists():
                    raise AssertionError("Missing output: " + name)
                mode = path.lstat().st_mode
                kind = contract["output_types"][name]
                if ((kind == "file" and not stat.S_ISREG(mode))
                        or (kind == "directory" and not stat.S_ISDIR(mode))
                        or kind not in {"file", "directory"}):
                    raise ValueError("Required submission artifact has the wrong filesystem type: " + name)
            if contract["case_id"] == "case-01":
                result = verifier.verify(output, package / "inputs", replay=True)
            else:
                result = verifier.verify(output)
            if result.get("status") != "PASS":
                raise RuntimeError("Unexpected scientific verifier result")
        except ReplayInfrastructureError as error:
            return emit(logs, "ENV_INVALID", str(error))
        except (AssertionError, ValueError, KeyError, TypeError, IndexError,
                OSError, subprocess.TimeoutExpired) as error:
            return emit(logs, "FAIL", str(error) or type(error).__name__)
        except Exception as error:
            (logs / "verifier-error.log").write_text(traceback.format_exc())
            return emit(logs, "ENV_INVALID", str(error))
        return emit(logs, "PASS", result=result)


if __name__ == "__main__":
    sys.exit(main())
