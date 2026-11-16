#!/usr/bin/env python3
# L1 Deliverables: Check required deliverables for completeness and parseability.
# L2 Execution: Check execution evidence through bounded replay or independent recomputation where implemented.
# L3 Science: Validate chemical requests and charge-model choices within the workflow's supported scope.
"""Terminal-state science verification with private references and isolated replay."""
from __future__ import annotations
import hashlib,json,importlib,sys,traceback
from pathlib import Path
_REFS_BYTES=Path(__file__).with_name('refs.json').read_bytes()
if hashlib.sha256(_REFS_BYTES).hexdigest()!='7096b8408d52f0087124bd88c25ca7cb5bec4fa7b12ca680e09c5aaa39906789':
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
"""Published Web scope + electron-spin parity + safe charge-model routing."""
import argparse,json,hashlib,sys,subprocess,tempfile,copy,math
from pathlib import Path
PACKAGE=Path(__file__).resolve().parents[1]
Z={'H':1,'C':6,'N':7,'O':8,'P':15,'S':16,'F':9,'Cl':17,'Br':35,'I':53,'Fe':26,'Xe':54}
SUPPORTED=set(REFS['chemical_scope']['supported_elements'])
def integer_json_number(value):
    return (type(value) is int or
            (type(value) is float and math.isfinite(value) and value.is_integer()))
def expected(item):
 electrons=sum(Z[k]*v for k,v in item['element_counts'].items())-item['charge'];m=item['spin_multiplicity']
 reasons=[]
 if m<1 or m>electrons+1 or (electrons-(m-1))%2:verdict='invalid_state';reasons=['electron_spin_parity']
 elif not set(item['element_counts']).issubset(SUPPORTED):verdict='unsupported';reasons=['unsupported_element_in_published_web']
 elif item['connected_components']!=1:verdict='unsupported';reasons=['published_web_requires_single_solute_molecule']
 elif item['iodine_bond_degree'] is not None and item['iodine_bond_degree']>1:verdict='unsupported';reasons=['iodine_bond_pattern_outside_published_gaff_scope']
 else:verdict='supported';reasons=['closed_shell_bcc' if m==1 else 'open_shell_resp']
 return {'request_id':item['request_id'],'electrons':electrons,'verdict':verdict,'reason_codes':reasons,'charge_method':'am1-bcc' if verdict=='supported' and m==1 else ('resp' if verdict=='supported' else None),'launch_allowed':verdict=='supported','charge':item['charge'],'spin_multiplicity':m}
def check(output,requests,require_delivery=True):
 required=['decisions.json']
 if require_delivery:required += ['route.py','analysis.md']
 for name in required:assert (output/name).is_file() and (output/name).stat().st_size>0,'Missing '+name
 rows=json.loads((output/'decisions.json').read_text())['decisions']
 if isinstance(rows,dict):
  assert all(isinstance(key,str) and isinstance(value,dict) for key,value in rows.items()),'decisions mapping must map request_id strings to decision objects'
  assert all(key==value.get('request_id') for key,value in rows.items()),'decisions mapping keys must match each decision request_id'
  records=list(rows.values())
 elif isinstance(rows,list):records=rows
 else:raise AssertionError('decisions must be a list or request_id-keyed object')
 assert len(records)==len(requests)
 assert all(isinstance(r,dict) and isinstance(r.get('request_id'),str) for r in records),'Each decision must be an object with a string request_id'
 byid={r['request_id']:r for r in records};assert len(byid)==len(records)
 assert set(byid)=={x['request_id'] for x in requests},'Decision request_ids must match the supplied requests exactly'
 for x in requests:
  e=expected(x);r=byid[x['request_id']]
  for k in ['electrons','charge','spin_multiplicity']:
   assert integer_json_number(r[k]),'Chemical count/state fields must be finite integer-valued JSON numbers, not booleans'
  assert type(r['launch_allowed']) is bool and isinstance(r['verdict'],str),'Decision fields have invalid JSON types'
  for k in ['electrons','verdict','charge_method','launch_allowed','charge','spin_multiplicity']:assert r[k]==e[k],f'{x["request_id"]}: wrong {k}'
  assert isinstance(r['reason_codes'],list) and len(r['reason_codes'])==len(set(r['reason_codes'])) and set(e['reason_codes'])==set(r['reason_codes']),'Missing chemical rationale'
def verify(output,replay=True):
 requests=json.loads((PACKAGE/'inputs/requests.json').read_text())['requests'];check(output,requests)
 if replay:
  with tempfile.TemporaryDirectory(prefix='chemical-routing-replay-') as d:
   inp=Path(d)/'input';inp.mkdir();out=Path(d)/'output';out.mkdir()
   # Identity names/row order cannot substitute for electron counts and supplied scope.
   renamed=copy.deepcopy(requests[::-1])
   for i,x in enumerate(renamed):x['identity']='structure-'+str(i);x['request_id']='audit-'+str(i)
   (inp/'requests.json').write_text(json.dumps({'requests':renamed,'scope':'published_AutoSolvateWeb_2025'}))
   r=run_replay(output/'route.py',inp,out,timeout=30)
   assert r.returncode==0,'Routing replay failed: '+r.stderr[-1000:]
   check(out,renamed,require_delivery=False)
 return {'status':'PASS','layers':['L1','L2','L3'],'requests':len(requests),'renamed_replay':replay}
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
