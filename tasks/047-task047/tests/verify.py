#!/usr/bin/env python3
# L1 Deliverables: Check required deliverables for completeness and parseability (including results.csv, analysis.json, calculations.py).
# L2 Execution: Check the use of supplied data or archived evidence where required.
# L3 Science: Compare transport observables and finite-size-corrected diffusion across six temperatures.
"""Single-source case verifier and trusted runner adapter."""
from __future__ import annotations

# The terminal adapter is installed only in the separate CompChemBench verifier image.
if __name__ == "__main__" and __import__("sys").argv[1:] == ["--terminal"]:
    import runpy as _runpy
    from pathlib import Path as _Path
    import sys as _sys
    _entry = _Path(__file__).resolve().parent / "harbor_runtime" / "entry.py"
    if not _entry.is_file():
        raise SystemExit("The pinned CompChemBench verifier image is required for terminal grading.")
    _sys.argv = [str(_entry)]
    _runpy.run_path(str(_entry), run_name="__main__")
    raise SystemExit(0)


from types import SimpleNamespace
import json
import os
from pathlib import Path
import sys

def _make_case47_science():
    #!/usr/bin/env python3
    """Private evaluator for NE audit. Execute submissions only in a bound isolated runtime."""
    import argparse
    import csv
    import hashlib
    import json
    import math
    import os
    from pathlib import Path
    import subprocess
    import sys
    import tempfile
    import signal
    import shutil


    NUMERIC_REFS=json.loads((Path(__file__).resolve().parent/'refs.json').read_text(encoding='utf-8'))
    E=NUMERIC_REFS['constants']['e_C']
    KB=NUMERIC_REFS['constants']['kB_J_K']
    ZETA=NUMERIC_REFS['constants']['zeta_cubic']
    FIELDS = ['T_K','sigma_NE_S_m','gamma','delta_D_m2_s']

    class InfrastructureError(RuntimeError):
        pass

    def unprivileged_preflight():
        setpriv=shutil.which('setpriv')
        if not setpriv:
            raise InfrastructureError('setpriv is required for isolated submission replay')
        run=subprocess.run([setpriv,'--reuid=65534','--regid=65534','--clear-groups',
                            '--no-new-privs','--bounding-set=-all','/usr/bin/id','-u'],
                           capture_output=True,text=True,timeout=5,
                           env={'PATH':'/usr/bin:/bin','HOME':'/tmp'})
        if run.returncode or run.stdout.strip()!='65534':
            raise InfrastructureError(f'unprivileged setpriv probe failed: {run.returncode} {run.stderr.strip()}')

    def rows(path):
        with path.open(newline='', encoding='utf-8') as f:
            return [{k:float(v) for k,v in row.items()} for row in csv.DictReader(f)]

    def reference(inputs, refs=NUMERIC_REFS):
        result=[]
        for r in inputs:
            t,l,eta = r['T_K'],r['L_A']*1e-10,r['eta_mPa_s']*1e-3
            d=(r['D_cation_1e-11_m2_s']+r['D_anion_1e-11_m2_s'])*1e-11
            ne=64*E**2*d/(l**3*KB*t)
            result.append({'T_K':t,'sigma_NE_S_m':ne,'gamma':r['sigma_GK_S_m']/ne,
                           'delta_D_m2_s':ZETA*KB*t/(6*math.pi*eta*l)})
        return result

    def check_output(directory, expected, refs=NUMERIC_REFS):
        checks=[]
        def record(label, passed, detail=''):
            checks.append({'check':label,'passed':bool(passed),'detail':detail})
        for name in ['results.csv','analysis.json','calculations.py']:
            p=directory/name
            record('L1.'+name,p.is_file() and p.stat().st_size>0)
        try:
            actual=rows(directory/'results.csv')
            temps=[r['T_K'] for r in actual]
            record('L1.temperature_rows',temps==[r['T_K'] for r in expected])
            record('L1.csv_columns',all(set(r)==set(FIELDS) for r in actual))
            numeric_ok=len(actual)==len(expected)
            errors=[]
            if numeric_ok:
                for r,ref in zip(actual,expected):
                    for field in FIELDS:
                        good=math.isfinite(r.get(field,float('nan'))) and math.isclose(r[field],ref[field],rel_tol=refs['numeric_acceptance']['rtol'],abs_tol=refs['numeric_acceptance']['atol'])
                        numeric_ok=numeric_ok and good
                        if not good:errors.append({'T_K':ref['T_K'],'field':field,'actual':r.get(field),'expected':ref[field]})
            record('L3.ne_gamma_and_finite_size',numeric_ok,json.dumps(errors,ensure_ascii=False))
        except (OSError,ValueError,KeyError,TypeError) as exc:
            record('L1.csv_parse',False,str(exc))
        try:
            a=json.loads((directory/'analysis.json').read_text())
            if not isinstance(a,dict):raise ValueError('analysis must be a JSON object')
            record('L3.already_corrected',a.get('diffusion_input_status')=='already_corrected' and a.get('apply_correction_again') is False)
            record('L3.gamma_above_one',a.get('gamma_gt_one_T_K')==[int(r['T_K']) for r in expected if r['gamma']>1])
            record('L3.gamma_below_one',a.get('gamma_lt_one_T_K')==[int(r['T_K']) for r in expected if r['gamma']<1])
            record('L3.units',a.get('units')=={'L':'m','eta':'Pa*s','D':'m^2/s','sigma':'S/m'})
            explanation=a.get('interpretation')
            record('L1.interpretation',isinstance(explanation,dict) and isinstance(explanation.get('text'),str) and bool(explanation['text'].strip()))
            # Scientific meaning is adjudicated from the explanation and computed
            # evidence, not from candidate-supplied declarations of the right answer.
        except (OSError,ValueError,TypeError) as exc:
            record('L1.json_parse',False,str(exc))
        return checks

    def replay(source,input_rows,package_dir,refs=NUMERIC_REFS):
        """Native evidence here is reproducible analysis, not unverifiable claimed logs."""
        with tempfile.TemporaryDirectory(prefix='ne-audit-eval-') as temp:
            work=Path(temp); inp=work/'input.csv'; out=work/'outputs';out.mkdir()
            shutil_source=out/'calculations.py'
            # The source itself remains unchanged; staged only to satisfy the output contract.
            shutil_source.write_bytes(source.read_bytes())
            with inp.open('w',newline='') as f:
                writer=csv.DictWriter(f,fieldnames=list(input_rows[0]));writer.writeheader();writer.writerows(input_rows)
            os.chmod(work,0o755)
            os.chmod(out,0o777)
            try:
                env={'PATH':'/opt/deepmd/bin:/usr/local/bin:/usr/bin:/bin',
                     'HOME':str(work),'TMPDIR':str(work),'PYTHONNOUSERSITE':'1',
                     'PYTHONDONTWRITEBYTECODE':'1'}
                command=['/usr/bin/setpriv','--reuid=65534','--regid=65534','--clear-groups',
                         '--no-new-privs','--bounding-set=-all',
                         sys.executable,str(source.resolve()),'--input',str(inp),'--output',str(out)]
                proc=subprocess.Popen(command,cwd=work,env=env,stdout=subprocess.PIPE,
                                       stderr=subprocess.PIPE,text=True,start_new_session=True)
                try:
                    stdout,stderr=proc.communicate(timeout=20)
                except subprocess.TimeoutExpired:
                    os.killpg(proc.pid,signal.SIGKILL)
                    stdout,stderr=proc.communicate()
                    return [{'check':'L2.replay_timeout','passed':False,'detail':(stderr or '')[-1000:]}]
                if proc.returncode:
                    return [{'check':'L2.replay_exit','passed':False,
                             'detail':'exit={}; {}'.format(proc.returncode,(stderr or '')[-1000:])}]
            except OSError as exc:
                raise InfrastructureError(f'cannot start restricted submission replay: {exc}') from exc
            return [{'check':'L2.replay_exit','passed':True,'detail':'actual Python execution'}]+check_output(out,reference(input_rows,refs),refs)

    def main():
        ap=argparse.ArgumentParser(description=__doc__)
        ap.add_argument('--submission',type=Path,required=True)
        ap.add_argument('--input',type=Path)
        ap.add_argument('--skip-replay',action='store_true',help='diagnostics only; never returns an overall score')
        args=ap.parse_args();package=Path(os.environ.get('APP','/app')).resolve()
        tests=Path(os.environ.get('TESTS','/tests')).resolve()
        inp=args.input or package/'inputs/conductivity-audit.csv'
        refs=json.loads((tests/'refs.json').read_text())
        preflight=[]
        for rel,digest in refs['input_hashes'].items():
            path=package/rel
            actual=hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() and not path.is_symlink() else None
            preflight.append({'path':rel,'valid':actual==digest})
        # An explicit alternative input is only an evaluator diagnostic, not the frozen task.
        if not all(x['valid'] for x in preflight) or not inp.is_file():
            print(json.dumps({'status':'PREFLIGHT_ERROR','agent_graded':False,'preflight':preflight},ensure_ascii=False,indent=2));return 2
        try:
            if not args.skip_replay:
                unprivileged_preflight()
            data=rows(inp)
            if len(data)!=6 or any(not math.isfinite(v) for r in data for v in r.values()):raise ValueError('invalid evaluation input')
            checks=check_output(args.submission,reference(data,refs),refs)
            source=args.submission/'calculations.py'
            if not args.skip_replay and source.is_file():
                checks+=replay(source,data,package,refs)
                changed=[]
                for i,r in enumerate(data):
                    r=dict(r)
                    r['L_A']*=1+.007*(i+1)
                    r['eta_mPa_s']*=1.12+.03*i
                    r['D_cation_1e-11_m2_s']*=1.17
                    r['D_anion_1e-11_m2_s']*=.83
                    r['sigma_GK_S_m']*=.44 if i%2==0 else 1.91
                    changed.append(r)
                for c in replay(source,changed,package,refs):
                    c['check']='perturbed.'+c['check'];checks.append(c)
            ok=all(c['passed'] for c in checks)
            status='SCIENTIFIC_REVIEW_REQUIRED' if ok else 'FAIL'
            print(json.dumps({'status':status,'agent_graded':False,'preflight':preflight,'checks':checks,
                              'required_manual_criteria':['interpretation'],
                              'scientific_runtime_executed':False,'qualification_granted':False},ensure_ascii=False,indent=2))
            return 0 if status=='SCIENTIFIC_REVIEW_REQUIRED' else 1
        except (OSError,ValueError,KeyError,TypeError,ZeroDivisionError) as exc:
            print(json.dumps({'status':'FAIL','error':str(exc),'qualification_granted':False}));return 1
        except InfrastructureError as exc:
            print(json.dumps({'status':'INFRASTRUCTURE_ERROR','agent_graded':False,'reward':None,'error':str(exc)}));return 2
    return SimpleNamespace(main=main)

def _make_case47_runner():
    #!/usr/bin/env python3
    """Runner adapter: deterministic diagnostics plus a trusted, submission-bound review."""

    import argparse
    import errno
    import hashlib
    import json
    import os
    from pathlib import Path, PurePosixPath
    import shutil
    import subprocess
    import sys
    import uuid


    APP = Path(os.environ.get("APP", "/app")).resolve()
    TESTS = Path(os.environ.get("TESTS", "/tests")).resolve()
    LOGS = Path(os.environ.get("LOGS", "/logs/verifier")).resolve()
    REPORT = LOGS / "verification.json"
    REVIEW = TESTS / "scientific-review.json"
    PREFLIGHT = LOGS / "isolation-preflight.json"
    PREFLIGHT_STDOUT = LOGS / "isolation-preflight.stdout.log"
    PREFLIGHT_STDERR = LOGS / "isolation-preflight.stderr.log"
    PROTECTED = (
        TESTS / "verify.py",
        TESTS / "refs.json",
        TESTS / "assessment-protocol.json",
        TESTS / "reference-hashes.json",
        TESTS / "evidence" / "reference-values.json",
        TESTS / "review-rubric.md",
    )
    PREFLIGHT_SCRIPT = r'''import errno, json, os, sys
    paths = sys.argv[1:-2]
    sentinel, create_path = sys.argv[-2:]
    try:
        status = open("/proc/self/status", "r", encoding="ascii").read()
        capeff = next(line.split()[1] for line in status.splitlines() if line.startswith("CapEff:"))
    except Exception as exc:
        print(json.dumps({"status": "INFRA", "error": "capabilities unreadable: " + repr(exc)}))
        raise SystemExit(2)
    if os.getuid() != 65534 or os.geteuid() != 65534 or os.getgid() != 65534 or os.getegid() != 65534:
        print(json.dumps({"status": "INFRA", "uid": os.getuid(), "euid": os.geteuid(), "gid": os.getgid(), "egid": os.getegid(), "capeff": capeff}))
        raise SystemExit(2)
    if int(capeff, 16) != 0:
        print(json.dumps({"status": "INFRA", "capeff": capeff, "error": "capabilities are not empty"}))
        raise SystemExit(2)
    checks = []
    def probe(label, operation):
        try:
            operation()
        except OSError as exc:
            if isinstance(exc, PermissionError) and exc.errno in (errno.EACCES, errno.EPERM):
                checks.append({"name": label, "result": "DENIED", "errno": exc.errno})
            else:
                checks.append({"name": label, "result": "INFRA", "errno": exc.errno, "error": repr(exc)})
        except Exception as exc:
            checks.append({"name": label, "result": "INFRA", "error": repr(exc)})
        else:
            checks.append({"name": label, "result": "ACCESSIBLE"})
    for path in paths:
        probe("read:" + path, lambda path=path: open(path, "rb").read())
    def read_sentinel():
        with open(sentinel, "rb") as stream:
            stream.read()
    probe("read:root-sentinel", read_sentinel)
    def overwrite_sentinel():
        with open(sentinel, "r+b") as stream:
            stream.write(b"X")
            stream.flush()
    probe("overwrite:root-sentinel", overwrite_sentinel)
    def create_sentinel():
        fd = os.open(create_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        os.close(fd)
    probe("create:second-sentinel", create_sentinel)
    bad = any(item["result"] != "DENIED" for item in checks)
    print(json.dumps({"status": "INFRA" if bad else "PASS", "uid": os.getuid(), "gid": os.getgid(), "capeff": capeff, "checks": checks}, sort_keys=True))
    raise SystemExit(2 if bad else 0)
    '''
    PREFLIGHT_SCRIPT = PREFLIGHT_SCRIPT.replace("\n    ", "\n")


    def sha256(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for block in iter(lambda: stream.read(1 << 20), b""):
                digest.update(block)
        return digest.hexdigest()


    def _write_private(path: Path, data: bytes) -> None:
        flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, "O_NOFOLLOW", 0)
        fd = os.open(str(path), flags, 0o600)
        try:
            os.fchmod(fd, 0o600)
            with os.fdopen(fd, "wb") as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
        except BaseException:
            try:
                os.close(fd)
            except OSError:
                pass
            raise


    def isolation_preflight() -> dict:
        record: dict = {
            "schema": "case06-private-tests-preflight/1",
            "status": "INFRA",
            "uid": os.getuid(), "euid": os.geteuid(), "gid": os.getgid(), "egid": os.getegid(),
            "protected_paths": [str(path) for path in PROTECTED],
            "checks": [],
        }
        sentinel = LOGS / ("isolation-root-" + uuid.uuid4().hex)
        second = LOGS / ("isolation-replay-" + uuid.uuid4().hex)
        try:
            if os.geteuid() != 0:
                raise RuntimeError("grader preflight must run as root")
            for path in PROTECTED:
                with path.open("rb") as stream:
                    stream.read()
            flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
            fd = os.open(str(sentinel), flags, 0o600)
            os.fchmod(fd, 0o600)
            with os.fdopen(fd, "wb") as stream:
                stream.write(b"R")
                stream.flush()
                os.fsync(stream.fileno())
            with sentinel.open("rb") as stream:
                if stream.read() != b"R":
                    raise RuntimeError("root sentinel readback mismatch")
            with sentinel.open("r+b") as stream:
                stream.write(b"R")
                stream.flush()
            second_fd = os.open(str(second), flags, 0o600)
            os.close(second_fd)
            second.unlink()

            setpriv = shutil.which("setpriv")
            if not setpriv:
                raise RuntimeError("setpriv is unavailable")
            command = [
                setpriv, "--reuid=65534", "--regid=65534", "--clear-groups",
                "--no-new-privs", "--bounding-set=-all", "--", sys.executable, "-I", "-c",
                PREFLIGHT_SCRIPT, *[str(path) for path in PROTECTED], str(sentinel), str(second),
            ]
            record["command"] = command
            try:
                proc = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                      text=True, timeout=20,
                                      env={"PATH": os.environ.get("PATH", "/usr/bin:/bin")})
            except subprocess.TimeoutExpired as exc:
                record["error"] = "setpriv preflight timed out"
                record["stdout"] = (exc.stdout or b"").decode(errors="replace") if isinstance(exc.stdout, bytes) else (exc.stdout or "")
                record["stderr"] = (exc.stderr or b"").decode(errors="replace") if isinstance(exc.stderr, bytes) else (exc.stderr or "")
                return record
            record["exit_code"] = proc.returncode
            record["stdout"] = proc.stdout
            record["stderr"] = proc.stderr
            if proc.returncode not in (0, 2):
                record["error"] = "unexpected setpriv preflight exit code"
                return record
            try:
                result = json.loads(proc.stdout)
            except json.JSONDecodeError as exc:
                record["error"] = "setpriv preflight returned invalid JSON: " + str(exc)
                return record
            record["child_result"] = result
            checks = result.get("checks") if isinstance(result, dict) else None
            expected = {"read:" + str(path) for path in PROTECTED} | {
                "read:root-sentinel", "overwrite:root-sentinel", "create:second-sentinel",
            }
            valid_checks = (
                isinstance(checks, list)
                and len(checks) == len(expected)
                and all(isinstance(item, dict) for item in checks)
                and len({item.get("name") for item in checks}) == len(checks)
                and {item.get("name") for item in checks} == expected
                and all(item.get("result") == "DENIED"
                        and type(item.get("errno")) is int
                        and item.get("errno") in (errno.EACCES, errno.EPERM)
                        for item in checks)
            )
            if (proc.returncode == 0 and result.get("status") == "PASS"
                    and result.get("uid") == 65534 and result.get("gid") == 65534
                    and result.get("capeff") == "0000000000000000"
                    and valid_checks):
                record["status"] = "PASS"
            else:
                record["error"] = "protected-path denial or replay identity did not meet the exact preflight contract"
            return record
        except Exception as exc:
            record["error"] = repr(exc)
            return record
        finally:
            for path in (sentinel, second):
                try:
                    if path.exists() or path.is_symlink():
                        path.unlink()
                except OSError as exc:
                    record.setdefault("cleanup_errors", []).append({"path": str(path), "error": repr(exc)})
                    record["status"] = "INFRA"
            try:
                stdout_data = str(record.get("stdout", "")).encode()
                stderr_data = str(record.get("stderr", "")).encode()
                _write_private(PREFLIGHT_STDOUT, stdout_data)
                _write_private(PREFLIGHT_STDERR, stderr_data)
                record["stdout_path"] = str(PREFLIGHT_STDOUT)
                record["stderr_path"] = str(PREFLIGHT_STDERR)
                record["stdout_sha256"] = hashlib.sha256(stdout_data).hexdigest()
                record["stderr_sha256"] = hashlib.sha256(stderr_data).hexdigest()
                _write_private(PREFLIGHT, (json.dumps(record, indent=2, ensure_ascii=False, sort_keys=True) + "\n").encode())
            except Exception as exc:
                record["status"] = "INFRA"
                record["evidence_write_error"] = repr(exc)


    def json_hash(value: object) -> str:
        data = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
        return hashlib.sha256(data).hexdigest()


    def outputs_manifest(expected: list[str]) -> list[dict[str, str]]:
        rows: list[dict[str, str]] = []
        seen: set[str] = set()
        for raw in expected:
            directory = raw.endswith("/")
            rel = raw[:-1] if directory else raw
            if not rel or PurePosixPath(rel).is_absolute() or ".." in PurePosixPath(rel).parts:
                raise ValueError(f"invalid expected output path: {raw!r}")
            path = APP / rel
            current = APP
            for part in PurePosixPath(rel).parts:
                current = current / part
                if current.is_symlink():
                    raise ValueError(f"expected output path contains a symlink: {raw}")
            if directory:
                if not path.is_dir():
                    raise ValueError(f"required output directory missing: {raw}")
                for item in sorted(path.rglob("*")):
                    if item.is_symlink():
                        raise ValueError(f"expected output contains a symlink: {item.relative_to(APP)}")
                    if item.is_dir():
                        continue
                    if not item.is_file():
                        raise ValueError(f"expected output contains a non-regular file: {item.relative_to(APP)}")
                    item_rel = item.relative_to(APP).as_posix()
                    if item_rel in seen:
                        raise ValueError(f"duplicate output manifest path: {item_rel}")
                    seen.add(item_rel)
                    rows.append({"path": item_rel, "sha256": sha256(item)})
                if not any(row["path"].startswith(rel + "/") for row in rows):
                    raise ValueError(f"required output directory is empty: {raw}")
            else:
                if path.is_symlink() or not path.is_file():
                    raise ValueError(f"required output file missing or not regular: {raw}")
                if rel in seen:
                    raise ValueError(f"duplicate output manifest path: {rel}")
                seen.add(rel)
                rows.append({"path": rel, "sha256": sha256(path)})
        return sorted(rows, key=lambda row: row["path"])


    def protocol_data() -> dict:
        protocol_path = TESTS / "assessment-protocol.json"
        protocol = json.loads(protocol_path.read_text(encoding="utf-8"))
        if not isinstance(protocol, dict) or not isinstance(protocol.get("case_id"), str):
            raise ValueError("assessment protocol must identify its case")
        outputs = protocol.get("expected_outputs")
        criteria = protocol.get("criteria")
        if not isinstance(outputs, list) or not outputs or not all(isinstance(x, str) and x for x in outputs):
            raise ValueError("assessment protocol has no valid expected_outputs")
        if len(set(outputs)) != len(outputs):
            raise ValueError("assessment protocol contains duplicate expected_outputs")
        if not isinstance(criteria, list) or not criteria:
            raise ValueError("assessment protocol has no criteria")
        required = [c.get("criterion") for c in criteria if isinstance(c, dict) and c.get("necessary") is True]
        if not required or any(not isinstance(x, str) or not x for x in required) or len(set(required)) != len(required):
            raise ValueError("assessment protocol has empty, missing, or duplicate necessary criteria")
        return protocol


    def validate_review(protocol: dict, manifest: list[dict[str, str]]) -> tuple[str, dict]:
        if not isinstance(protocol, dict) or not isinstance(protocol.get("expected_outputs"), list) or not protocol["expected_outputs"]:
            raise ValueError("trusted protocol has no expected outputs")
        protocol_criteria = protocol.get("criteria")
        if not isinstance(protocol_criteria, list) or not protocol_criteria:
            raise ValueError("trusted protocol has no criteria")
        required_list = [item.get("criterion") for item in protocol_criteria
                         if isinstance(item, dict) and item.get("necessary") is True]
        if (not required_list or any(not isinstance(name, str) or not name for name in required_list)
                or len(set(required_list)) != len(required_list)):
            raise ValueError("trusted protocol has empty or duplicate necessary criteria")
        if REVIEW.is_symlink():
            raise ValueError("trusted scientific review is a symlink")
        if not REVIEW.exists():
            return "REVIEW_REQUIRED", {"reason": "No trusted submission-specific scientific review is recorded."}
        if not REVIEW.is_file():
            raise ValueError("trusted scientific review is not a regular file")
        review = json.loads(REVIEW.read_text(encoding="utf-8"))
        if not isinstance(review, dict) or review.get("schema") != "scientific-review/v1":
            raise ValueError("trusted scientific review schema mismatch")
        if review.get("case_id") != protocol.get("case_id"):
            raise ValueError("trusted scientific review case_id mismatch")
        if review.get("protocol_sha256") != sha256(TESTS / "assessment-protocol.json"):
            raise ValueError("trusted scientific review protocol hash mismatch")
        if review.get("submission_manifest_sha256") != json_hash(manifest):
            raise ValueError("trusted scientific review submission manifest mismatch")

        required = set(required_list)
        decisions = review.get("criteria")
        if not isinstance(decisions, list):
            raise ValueError("trusted scientific review criteria must be an array")
        seen: set[str] = set()
        for item in decisions:
            if not isinstance(item, dict):
                raise ValueError("trusted scientific review criterion must be an object")
            name = item.get("criterion")
            if not isinstance(name, str) or name not in required or name in seen:
                raise ValueError(f"unknown or repeated review criterion: {name!r}")
            seen.add(name)
            if item.get("verdict") not in {"PASS", "FAIL", "INFRA"}:
                raise ValueError(f"invalid review verdict for {name}")
            if not isinstance(item.get("reviewer"), str) or not item["reviewer"].strip():
                raise ValueError(f"missing reviewer identity for {name}")
            if not isinstance(item.get("reason"), str) or not item["reason"].strip():
                raise ValueError(f"review reason missing for {name}")
            evidence = item.get("evidence")
            if not isinstance(evidence, list) or not evidence:
                raise ValueError(f"missing evidence references for {name}")
            for record in evidence:
                if not isinstance(record, dict):
                    raise ValueError(f"malformed evidence reference for {name}")
                rel = record.get("path")
                if not isinstance(rel, str) or PurePosixPath(rel).is_absolute() or ".." in PurePosixPath(rel).parts:
                    raise ValueError(f"evidence path escapes APP for {name}")
                path = APP / rel
                current = APP
                for part in PurePosixPath(rel).parts:
                    current = current / part
                    if current.is_symlink():
                        raise ValueError(f"evidence path contains a symlink: {rel}")
                if not path.is_file() or path.is_symlink() or sha256(path) != record.get("sha256"):
                    raise ValueError(f"evidence hash mismatch: {rel}")
        if seen != required:
            raise ValueError(f"trusted review has missing criteria: {sorted(required - seen)}")
        verdicts = {item["verdict"] for item in decisions}
        if "INFRA" in verdicts:
            raise ValueError("review records infrastructure failure; it cannot issue a scientific score")
        return ("FAIL" if "FAIL" in verdicts else "PASS"), {
            "reviewer": review.get("reviewer", "criterion-level reviewers"),
            "protocol_sha256": review["protocol_sha256"],
            "submission_manifest_sha256": review["submission_manifest_sha256"],
            "criteria": decisions,
        }


    def main() -> int:
        parser = argparse.ArgumentParser()
        parser.add_argument("--verifier", default=str(TESTS / "verify.py"))
        args = parser.parse_args()
        LOGS.mkdir(parents=True, exist_ok=True)
        LOGS.chmod(0o700)
        for old in (LOGS / "reward.txt", REPORT, LOGS / "verdict.json",
                    PREFLIGHT, PREFLIGHT_STDOUT, PREFLIGHT_STDERR):
            if old.is_symlink():
                raise ValueError(f"unsafe verifier output path: {old.name}")
            old.unlink(missing_ok=True)
        preflight = isolation_preflight()
        if preflight.get("status") != "PASS":
            raise RuntimeError("private grader isolation preflight failed closed")
        protocol = protocol_data()

        # Check all evaluator assets against the frozen private reference list. Public
        # input bytes are checked by the case verifier against the mounted APP tree.
        ref_file = TESTS / "reference-hashes.json"
        refs = json.loads(ref_file.read_text(encoding="utf-8"))
        if not isinstance(refs, dict) or refs.get("tests/assessment-protocol.json") != sha256(TESTS / "assessment-protocol.json"):
            raise ValueError("assessment protocol is not pinned by reference-hashes.json")
        bad = []
        for declared, expected_hash in refs.items():
            if declared.startswith("tests/"):
                path = TESTS / declared[len("tests/"):]
                if path == ref_file:
                    continue
            elif declared.startswith("inputs/"):
                path = APP / declared
            else:
                raise ValueError(f"unsupported trusted reference path: {declared}")
            if path.is_symlink() or not path.is_file() or sha256(path) != expected_hash:
                bad.append(declared)
        if bad:
            raise RuntimeError(f"trusted scoring assets are invalid: {bad}")

        proc = subprocess.run(
            [sys.executable, args.verifier, "--submission", str(APP)],
            cwd=APP, capture_output=True, text=True, timeout=300,
            env={"PATH": os.environ.get("PATH", "/opt/deepmd/bin:/usr/bin:/bin"),
                 "HOME": "/tmp", "APP": str(APP), "TESTS": str(TESTS), "LOGS": str(LOGS),
                 "TF_CPP_MIN_LOG_LEVEL": "2", "OMP_NUM_THREADS": "1", "OPENBLAS_NUM_THREADS": "1"},
        )
        try:
            diagnostic = json.loads(proc.stdout)
        except (json.JSONDecodeError, TypeError) as exc:
            raise RuntimeError(f"diagnostic verifier returned no structured JSON (rc={proc.returncode}): {proc.stdout[-1000:]} {proc.stderr[-1000:]}") from exc
        if not isinstance(diagnostic, dict):
            raise RuntimeError("diagnostic verifier response must be an object")
        status = str(diagnostic.get("status", "")).upper()
        checks = diagnostic.get("checks")
        if (not isinstance(checks, list) or not checks
                or any(not isinstance(c, dict) or type(c.get("passed")) is not bool for c in checks)):
            if status not in {"PREFLIGHT_ERROR", "INFRASTRUCTURE_ERROR", "ENV_INVALID", "ERROR"}:
                raise RuntimeError("diagnostic verifier returned missing or malformed checks")
        if proc.returncode == 2 or status in {"PREFLIGHT_ERROR", "INFRASTRUCTURE_ERROR", "ENV_INVALID", "ERROR"}:
            result = {"status": "INFRA_ERROR", "agent_graded": False, "reward": None,
                      "diagnostics": diagnostic}
            REPORT.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n")
            print("INFRA_ERROR: scoring preflight or verifier failed", file=sys.stderr)
            return 2
        if proc.returncode != 0 and not (proc.returncode == 1 and status == "FAIL"):
            raise RuntimeError(f"diagnostic verifier returned unexpected exit/status: rc={proc.returncode} status={status!r}")
        if status not in {"FAIL", "SCIENTIFIC_REVIEW_REQUIRED", "REVIEW_REQUIRED", "DIAGNOSTIC_ONLY"}:
            raise RuntimeError(f"diagnostic verifier returned unsupported status {status!r}")
        if status == "FAIL" or any(not c.get("passed", False) for c in checks):
            if status != "FAIL":
                raise RuntimeError("failed diagnostic checks were not reported as FAIL")
            result = {"status": "FAIL", "reward": 0, "diagnostics": diagnostic}
            REPORT.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n")
            print("FAIL: deterministic diagnostic criterion failed", file=sys.stderr)
            (LOGS / "reward.txt").write_text("0\n", encoding="utf-8")
            return 1

        try:
            manifest = outputs_manifest(protocol["expected_outputs"])
        except ValueError as exc:
            result = {"status": "FAIL", "reward": 0, "diagnostics": diagnostic,
                      "delivery_failure": str(exc)}
            REPORT.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n")
            (LOGS / "reward.txt").write_text("0\n", encoding="utf-8")
            print(f"FAIL: {exc}", file=sys.stderr)
            return 1
        decision, review_details = validate_review(protocol, manifest)
        if decision == "REVIEW_REQUIRED":
            result = {"status": "REVIEW_REQUIRED", "implementation": "partial",
                      "diagnostics": diagnostic, "review": review_details,
                      "submission_manifest": manifest, "submission_manifest_sha256": json_hash(manifest)}
            REPORT.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n")
            print("REVIEW_REQUIRED: manual scientific adjudication is pending")
            return 0
        result = {"status": decision, "reward": 1 if decision == "PASS" else 0,
                  "diagnostics": diagnostic, "review": review_details,
                  "submission_manifest": manifest, "submission_manifest_sha256": json_hash(manifest)}
        REPORT.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n")
        (LOGS / "reward.txt").write_text(f"{result['reward']}\n", encoding="utf-8")
        print(f"{decision}: trusted scientific review applied")
        return 0 if decision == "PASS" else 1


    def _runner_entry():
        try:
            raise SystemExit(main())
        except Exception as exc:
            LOGS.mkdir(parents=True, exist_ok=True)
            if REPORT.exists():
                REPORT.unlink()
            (LOGS / "reward.txt").unlink(missing_ok=True)
            REPORT.write_text(json.dumps({"status": "INFRA_ERROR", "reward": None,
                                          "agent_graded": False, "error": str(exc)},
                                         indent=2, ensure_ascii=False) + "\n")
            print(f"INFRA_ERROR: {exc}", file=sys.stderr)
            raise SystemExit(2)
    return SimpleNamespace(main=main, entry=_runner_entry)


def _prepare_runner_logs(case_id):
    logs = Path(os.environ.get("LOGS", "/logs/verifier"))
    if logs.is_symlink():
        raise RuntimeError("LOGS path is a symlink")
    logs.mkdir(parents=True, exist_ok=True)
    report_name = "scoring-report.json" if case_id in {42, 43} else "verification.json"
    paths = [logs / "reward.txt", logs / report_name]
    if case_id in {42, 43}:
        paths.append(logs / "verdict.json")
    for path in paths:
        if path.is_symlink():
            raise RuntimeError(f"unsafe verifier output path: {path.name}")
    for path in paths:
        path.unlink(missing_ok=True)
    return logs, report_name


def _runner_initialization_error(case_id, logs, report_name, exc):
    payload = {"status": "INFRA_ERROR", "agent_graded": False, "reward": None,
               "error": f"{type(exc).__name__}: {exc}"}
    try:
        if logs is None:
            logs = Path(os.environ.get("LOGS", "/logs/verifier"))
        if not logs.is_symlink():
            logs.mkdir(parents=True, exist_ok=True)
            if report_name is None:
                report_name = "scoring-report.json" if case_id in {42, 43} else "verification.json"
            report = logs / report_name
            reward = logs / "reward.txt"
            if not report.is_symlink() and not reward.is_symlink():
                reward.unlink(missing_ok=True)
                report.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    except Exception:
        pass
    print(json.dumps(payload, ensure_ascii=False), file=sys.stderr)
    raise SystemExit(2)


def _diagnostic_initialization_error(exc):
    payload = {"status": "INFRASTRUCTURE_ERROR", "agent_graded": False, "reward": None,
               "error": f"{type(exc).__name__}: {exc}"}
    print(json.dumps(payload, ensure_ascii=False))
    return 2

def _main_dispatch():
    if sys.argv[1:] == ["--runner"]:
        logs = None
        report_name = None
        try:
            logs, report_name = _prepare_runner_logs(47)
            sys.argv = [sys.argv[0]]
            runner = _make_case47_runner()
            runner.entry()
        except SystemExit:
            raise
        except Exception as exc:
            _runner_initialization_error(47, logs, report_name, exc)
    try:
        science = _make_case47_science()
        return science.main()
    except SystemExit:
        raise
    except Exception as exc:
        return _diagnostic_initialization_error(exc)


if __name__ == "__main__":
    raise SystemExit(_main_dispatch())
