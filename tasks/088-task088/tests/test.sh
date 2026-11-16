#!/usr/bin/env bash
set -euo pipefail

exec python3 - "${APP:-/app}" "${TESTS:-/tests}" "${LOGS:-/logs/verifier}" <<'PY'
import json, math, os, stat, subprocess, sys
from pathlib import Path

app, tests, logs = (Path(v).absolute() for v in sys.argv[1:])
names=('reward.txt','verification.json','verifier-error.json')

def check_no_links(path):
    cursor=Path(path.anchor)
    for part in path.parts[1:]:
        cursor=cursor/part
        if cursor.is_symlink(): raise ValueError(f'path traverses symlink: {path}')

def write_error(message):
    try:
        check_no_links(logs)
        log_r=logs.resolve(strict=False)
        for path in (app,tests):
            path_r=path.resolve(strict=False)
            if log_r==path_r or log_r in path_r.parents or path_r in log_r.parents:
                raise ValueError('LOGS must not overlap APP or TESTS')
        logs.mkdir(parents=True,exist_ok=True)
        error=logs/'verifier-error.json'
        if error.is_symlink(): error.unlink()
        if error.exists() and not error.is_file(): return
        error.write_text(json.dumps({'status':'ERROR','message':message})+'\n',encoding='utf-8')
    except Exception:
        pass

try:
    check_no_links(logs)
    app_r,tests_r=app.resolve(strict=False),tests.resolve(strict=False)
    log_r=logs.resolve(strict=False)
    if app_r==tests_r or app_r in tests_r.parents or tests_r in app_r.parents:
        raise ValueError('APP and TESTS paths must not overlap')
    if any(log_r==p or log_r in p.parents or p in log_r.parents for p in (app_r,tests_r)):
        raise ValueError('LOGS must not overlap APP or TESTS')
    logs.mkdir(parents=True,exist_ok=True)
    invalid=[]
    for name in names:
        p=logs/name
        if p.is_symlink(): p.unlink()
        elif p.exists():
            if not p.is_file(): invalid.append(name)
            else: p.unlink()
    if invalid: raise ValueError('verdict output is not a regular file: '+', '.join(invalid))
    for path in (app,tests): check_no_links(path)
    app.resolve(strict=True); tests.resolve(strict=True)
    env=dict(os.environ); env['BENCH_LOGS']=str(logs)
    rc=subprocess.run([sys.executable,str(tests/'verify.py'),str(app)],env=env,check=False).returncode
    reward=logs/'reward.txt'; report_path=logs/'verification.json'; error=logs/'verifier-error.json'
    if rc==2:
        # Preserve a detailed error emitted by the trusted verifier while
        # discarding any stale or contradictory verdict. Unsafe nodes still
        # fail closed and are handled by the outer cleanup path.
        if error.is_symlink(): raise ValueError('verifier error output is a symlink')
        if error.exists():
            if not error.is_file(): raise ValueError('verifier error output is not a regular file')
            def unique_error_object(pairs):
                obj={}
                for key,value in pairs:
                    if key in obj: raise ValueError(f'duplicate verifier error key: {key}')
                    obj[key]=value
                return obj
            detail=json.loads(error.read_text(encoding='utf-8'),object_pairs_hook=unique_error_object,
                              parse_constant=lambda value: (_ for _ in ()).throw(ValueError(f'non-finite verifier error value: {value}')))
            if not isinstance(detail,dict) or detail.get('status')!='ERROR' or not isinstance(detail.get('message'),str):
                raise ValueError('verifier error output has an invalid schema')
            for path in (reward,report_path):
                if path.is_symlink() or path.is_file(): path.unlink()
                elif path.exists(): raise ValueError('verdict output is not a regular file')
            print('verifier ERROR: '+detail['message'],file=sys.stderr)
            raise SystemExit(2)
    if rc not in (0,1): raise ValueError(f'verifier exited with infrastructure code {rc}')
    if error.exists() or error.is_symlink(): raise ValueError('verifier emitted an infrastructure error')
    if not report_path.is_file() or report_path.is_symlink(): raise ValueError('verifier report is missing or unsafe')
    if not reward.is_file() or reward.is_symlink(): raise ValueError('verifier reward is missing or unsafe')
    def unique_object(pairs):
        obj={}
        for key,value in pairs:
            if key in obj: raise ValueError(f'duplicate JSON key: {key}')
            obj[key]=value
        return obj
    def bad_constant(value): raise ValueError(f'non-finite JSON constant: {value}')
    def finite_float(value):
        number=float(value)
        if not math.isfinite(number): raise ValueError(f'non-finite JSON number: {value}')
        return number
    report=json.loads(report_path.read_text(encoding='utf-8'),object_pairs_hook=unique_object,parse_constant=bad_constant,parse_float=finite_float)
    if not isinstance(report,dict) or report.get('status') not in ('PASS','FAIL') or type(report.get('reward')) is not int:
        raise ValueError('verifier report has invalid status or reward')
    reward_value=reward.read_text(encoding='utf-8')
    expected_status='PASS' if rc==0 else 'FAIL'
    expected_reward=1 if rc==0 else 0
    if report['status']!=expected_status or report['reward']!=expected_reward or reward_value!=f'{expected_reward}\n':
        raise ValueError('verifier exit code, report and reward disagree')
    raise SystemExit(rc)
except SystemExit:
    raise
except Exception as exc:
    # Clear all safely removable outputs so a prior PASS can never survive.
    try:
        check_no_links(logs)
        log_r=logs.resolve(strict=False)
        for path in (app,tests):
            path_r=path.resolve(strict=False)
            if log_r==path_r or log_r in path_r.parents or path_r in log_r.parents:
                raise ValueError('LOGS must not overlap APP or TESTS')
        for name in names:
            p=logs/name
            if p.is_symlink(): p.unlink()
            elif p.is_file(): p.unlink()
    except Exception:
        pass
    write_error(f'{type(exc).__name__}: {exc}')
    print(f'verifier ERROR: {type(exc).__name__}: {exc}',file=sys.stderr)
    raise SystemExit(2)
PY
