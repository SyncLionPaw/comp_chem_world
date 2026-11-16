#!/usr/bin/env python3
# L1 Deliverables: Check required deliverables for completeness and parseability (including predictions.npz, metrics.json, report.md).
# L2 Execution: No separate execution attestation is implied by checks of submitted results.
# L3 Science: Audit model errors on a small public DFT training and holdout dataset.
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

def _make_case42_isolation():
    """Fail-closed check for the runner's root-owned private verifier mount."""

    import errno
    import json
    import os
    from pathlib import Path
    import shutil
    import subprocess
    import sys
    import uuid


    CORE_NAMES = {
        "read:assessment-protocol.json",
        "read:reference-hashes.json",
        "read:refs.json",
        "read:verify.py",
        "import:verify.py",
        "read:root-sentinel",
        "overwrite:root-sentinel",
        "create:second-sentinel",
        "create:private-tests",
        "overwrite:reference-hashes.json",
    }


    def isolation_preflight(tests: Path, logs: Path) -> dict:
        protected = [tests / name for name in (
            "assessment-protocol.json", "reference-hashes.json", "refs.json", "verify.py",
        )]
        review = tests / "scientific-review.json"
        record = {"schema": "reline01-private-tests-preflight/v1", "status": "INFRA",
                  "uid": os.getuid(), "euid": os.geteuid(), "checks": []}
        sentinel = logs / ("isolation-root-" + uuid.uuid4().hex)
        second = logs / ("isolation-replay-" + uuid.uuid4().hex)
        probe = tests / (".isolation-write-" + uuid.uuid4().hex)
        probe_created = False
        try:
            if os.geteuid() != 0 or tests.is_symlink() or not tests.is_dir():
                raise RuntimeError("private tests must be a mounted root-owned directory")
            root_info = tests.stat()
            if (root_info.st_uid, root_info.st_gid, root_info.st_mode & 0o777) != (0, 0, 0o700):
                raise RuntimeError("private tests root ownership or mode mismatch")
            actual_protected = protected + ([review] if review.exists() else [])
            for path in actual_protected:
                info = path.lstat()
                if path.is_symlink() or not path.is_file() or (info.st_uid, info.st_gid, info.st_mode & 0o777) != (0, 0, 0o600):
                    raise RuntimeError(f"unsafe private verifier file: {path.name}")
                path.read_bytes()

            try:
                fd = os.open(probe, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            except OSError as exc:
                if exc.errno not in (errno.EROFS, errno.EACCES, errno.EPERM):
                    raise RuntimeError(f"unexpected /tests write-probe error: {exc}") from exc
            else:
                probe_created = True
                os.close(fd)
                raise RuntimeError("private tests mount is writable")

            fd = os.open(sentinel, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "wb") as stream:
                stream.write(b"case02-root-only")
            child = r"""import errno,importlib.util,json,os,sys
    protected=sys.argv[1:5]; sentinel,second,create,review=sys.argv[5:9]; checks=[]
    def attempt(name,fn):
     try: fn()
     except OSError as exc: return {"name":name,"result":"DENIED" if exc.errno in (errno.EACCES,errno.EPERM) else "UNEXPECTED","errno":exc.errno}
     return {"name":name,"result":"ALLOWED"}
    for path in protected: checks.append(attempt("read:"+os.path.basename(path),lambda p=path:open(p,"rb").read(1)))
    def import_verify():
     spec=importlib.util.spec_from_file_location("case07_private_verify",protected[-1]); module=importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    checks.append(attempt("import:verify.py",import_verify))
    checks.append(attempt("read:root-sentinel",lambda:open(sentinel,"rb").read(1)))
    checks.append(attempt("overwrite:root-sentinel",lambda:open(sentinel,"wb").write(b"X")))
    checks.append(attempt("create:second-sentinel",lambda:os.open(second,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)))
    checks.append(attempt("create:private-tests",lambda:os.open(create,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)))
    checks.append(attempt("overwrite:reference-hashes.json",lambda:open(protected[1],"wb").write(b"X")))
    optional_review={"status":"ABSENT"} if review=="-" else attempt("read:scientific-review.json",lambda:open(review,"rb").read(1))
    print(json.dumps({"uid":os.getuid(),"gid":os.getgid(),"capeff":open("/proc/self/status").read().split("CapEff:")[1].splitlines()[0].strip(),"checks":checks,"optional_review":optional_review},sort_keys=True))
    """
            child = child.replace("\n    ", "\n")
            setpriv = shutil.which("setpriv")
            if not setpriv:
                raise RuntimeError("setpriv is unavailable for private-tests isolation check")
            proc = subprocess.run(
                [setpriv, "--reuid=65534", "--regid=65534", "--clear-groups", "--no-new-privs",
                 "--bounding-set=-all", "--", sys.executable, "-I", "-c", child,
                 *map(str, protected), str(sentinel), str(second), str(probe), str(review if review.exists() else "-")],
                capture_output=True, text=True, timeout=20,
                env={"PATH": os.environ.get("PATH", "/usr/bin:/bin")})
            record["child_stdout"] = proc.stdout
            record["child_stderr"] = proc.stderr
            if proc.returncode != 0:
                raise RuntimeError(f"UID65534 isolation probe failed: {proc.stderr[-1000:]}")
            result = json.loads(proc.stdout)
            checks = result.get("checks", [])
            names = {item.get("name") for item in checks if isinstance(item, dict)}
            if (result.get("uid") != 65534 or result.get("gid") != 65534
                    or result.get("capeff") != "0000000000000000"
                    or not isinstance(checks, list) or len(checks) != 10 or names != CORE_NAMES
                    or any(not isinstance(item, dict) or item.get("result") != "DENIED"
                           or type(item.get("errno")) is not int
                           or item["errno"] not in (errno.EACCES, errno.EPERM) for item in checks)):
                raise RuntimeError("UID65534 isolation checks did not meet the exact denial contract")
            optional = result.get("optional_review")
            expected_optional = "DENIED" if review.exists() else "ABSENT"
            if (not isinstance(optional, dict) or optional.get("status", optional.get("result")) != expected_optional
                    or (review.exists() and (type(optional.get("errno")) is not int
                                             or optional["errno"] not in (errno.EACCES, errno.EPERM)))):
                raise RuntimeError("optional historical review isolation check failed")
            record.update({"status": "PASS", "child_result": result,
                           "protected_files": [path.name for path in actual_protected],
                           "runner_tests_mount_read_only": True})
            return record
        except Exception as exc:
            record["error"] = repr(exc)
            raise
        finally:
            cleanup_errors = []
            for path in (sentinel, second):
                try:
                    path.unlink(missing_ok=True)
                except OSError as exc:
                    cleanup_errors.append({"path": str(path), "error": repr(exc)})
            if probe_created:
                try:
                    probe.unlink(missing_ok=True)
                except OSError as exc:
                    cleanup_errors.append({"path": str(probe), "error": repr(exc)})
            if cleanup_errors:
                record["cleanup_errors"] = cleanup_errors
                record["status"] = "INFRA"
            (logs / "private-isolation.json").write_text(
                json.dumps(record, indent=2, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
            if cleanup_errors:
                raise RuntimeError("private-isolation probe cleanup failed")
    return SimpleNamespace(isolation_preflight=isolation_preflight)

def _make_case42_science():
    #!/usr/bin/env python3
    """Deterministic partial diagnostics; full scientific review remains required."""
    import argparse
    import csv
    import hashlib
    import json
    import os
    from pathlib import Path
    import shutil
    import signal
    import subprocess
    import sys
    import tempfile
    try:
        import numpy as np
    except ImportError:
        np = None



    def file_hash(path):
        h=hashlib.sha256()
        with path.open('rb') as f:
            for b in iter(lambda:f.read(1024*1024),b''):h.update(b)
        return h.hexdigest()


    def metric_values(pred_e,pred_f,true_e,true_f,natoms):
        de=(np.asarray(pred_e,dtype=float)-np.asarray(true_e,dtype=float))/natoms
        df=np.asarray(pred_f,dtype=float).reshape(-1,natoms,3)-np.asarray(true_f,dtype=float).reshape(-1,natoms,3)
        return {'raw_energy_rmse_eV_atom':float(np.sqrt(np.mean(de**2))),
                'centered_energy_rmse_eV_atom':float(np.sqrt(np.mean((de-de.mean())**2))),
                'force_component_rmse_eV_A':float(np.sqrt(np.mean(df**2))),
                'energy_bias_eV_atom':float(np.mean(de))}


    def restricted_deepmd_replay(graph,holdout_dir,type_file,sample_ids):
        """Load a frozen graph only under a restricted UID, clean env and timeout."""
        setpriv=shutil.which('setpriv')
        python=Path('/opt/deepmd/bin/python')
        if not setpriv or not python.is_file():raise RuntimeError('INFRA: restricted DeepMD runtime is unavailable')
        env={'PATH':'/opt/deepmd/bin:/usr/local/bin:/usr/bin:/bin','HOME':'/tmp',
             'PYTHONNOUSERSITE':'1','TF_CPP_MIN_LOG_LEVEL':'2'}
        probe=subprocess.run([setpriv,'--reuid=65534','--regid=65534','--clear-groups','--no-new-privs',
                              '--bounding-set=-all',str(python),'-c','import deepmd, numpy'],
                             capture_output=True,text=True,timeout=30,env=env)
        if probe.returncode:raise RuntimeError('INFRA: isolated DeepMD import failed: '+probe.stderr[-1000:])
        with tempfile.TemporaryDirectory(prefix='short-training-replay-') as td:
            work=Path(td);work.chmod(0o755)
            copied_graph=work/'candidate.pb';shutil.copyfile(graph,copied_graph);copied_graph.chmod(0o444)
            inp=work/'inputs';inp.mkdir(mode=0o755)
            out=work/'output';out.mkdir(mode=0o777);out.chmod(0o777)
            for name in ('coord.npy','box.npy'):
                shutil.copyfile(holdout_dir/name,inp/name);(inp/name).chmod(0o444)
            shutil.copyfile(type_file,inp/'type.raw');(inp/'type.raw').chmod(0o444)
            ids=inp/'sample_ids.json';ids.write_text(json.dumps(sample_ids));ids.chmod(0o444)
            code='''import json,sys,numpy as np\nfrom deepmd.infer import DeepPot\nm=DeepPot(sys.argv[1]); c=np.load(sys.argv[2]); b=np.load(sys.argv[3]); t=np.loadtxt(sys.argv[4],dtype=int)\ne,f,v=m.eval(c,b,t)\nnp.savez_compressed(sys.argv[5],sample_id=np.asarray(json.load(open(sys.argv[6])),dtype="U16"),energy=np.asarray(e).reshape(-1),force=np.asarray(f).reshape(-1,len(t),3))\n'''
            script=work/'replay.py';script.write_text(code);script.chmod(0o444)
            command=[setpriv,'--reuid=65534','--regid=65534','--clear-groups','--no-new-privs','--bounding-set=-all',
                     str(python),str(script),str(copied_graph),str(inp/'coord.npy'),str(inp/'box.npy'),
                     str(inp/'type.raw'),str(out/'predictions.npz'),str(ids)]
            proc=subprocess.Popen(command,cwd=work,env={**env,'HOME':str(work),'TMPDIR':str(work),
                                  'OMP_NUM_THREADS':'1','OPENBLAS_NUM_THREADS':'1',
                                  'DP_INTRA_OP_PARALLELISM_THREADS':'1','DP_INTER_OP_PARALLELISM_THREADS':'1'},
                                  stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,start_new_session=True)
            try:stdout,stderr=proc.communicate(timeout=180)
            except subprocess.TimeoutExpired:
                os.killpg(proc.pid,signal.SIGKILL);stdout,stderr=proc.communicate()
                return None,'candidate replay timeout: '+stderr[-1000:]
            if proc.returncode:return None,'candidate graph replay failed: '+stderr[-1500:]
            with np.load(out/'predictions.npz',allow_pickle=False) as z:
                return {k:np.asarray(z[k]).copy() for k in z.files},''


    def _short_training_checks(package,submission,test_root,check,skip_model_replay):
        manifest=json.loads((package/'inputs/sample-manifest.json').read_text())
        train_dir=package/'inputs/short-training/train/set.000'
        holdout_dir=package/'inputs/short-training/holdout/set.000'
        natoms=int(manifest['natoms'])
        train_ids=[x['sample_id'] for x in manifest['train']]
        holdout_ids=[x['sample_id'] for x in manifest['holdout']]
        train_hashes={x['source_coordinate_row_sha256'] for x in manifest['train']}
        valid_hashes={x['source_coordinate_row_sha256'] for x in manifest['holdout']}
        good=(manifest.get('schema')=='reline-short-training-samples/v1' and natoms==304
              and len(train_ids)==64 and len(set(train_ids))==64 and len(holdout_ids)==16
              and len(set(holdout_ids))==16 and not train_hashes.intersection(valid_hashes))
        check('L1.sample_manifest',good,'64 train / 16 visible holdout; exact source coordinate overlap is rejected.')
        if not good:return
        label_e=np.load(holdout_dir/'energy.npy',allow_pickle=False)
        label_f=np.load(holdout_dir/'force.npy',allow_pickle=False).reshape(16,natoms,3)
        expected_ids=np.asarray(holdout_ids,dtype='U16')
        try:
            with np.load(submission/'predictions.npz',allow_pickle=False) as pred:
                pred_ids=np.asarray(pred['sample_id']);pred_e=np.asarray(pred['energy']);pred_f=np.asarray(pred['force'])
            schema=(pred_ids.shape==(16,) and pred_e.shape==(16,) and pred_f.shape==(16,natoms,3)
                    and np.array_equal(pred_ids,expected_ids) and np.isfinite(pred_e).all() and np.isfinite(pred_f).all())
        except (OSError,ValueError,KeyError) as exc:
            check('L1.prediction_schema',False,str(exc));return
        check('L1.prediction_schema',schema,'holdout IDs/order and eV/eV-A array shapes')
        if not schema:return
        observed={'candidate':metric_values(pred_e,pred_f,label_e,label_f,natoms)}
        for i in range(4):
            with np.load(package/f'inputs/author-predictions/model.{i:03d}.npz',allow_pickle=False) as z:
                ids=np.asarray(z['sample_id'])
                check(f'L1.author_observation_{i}_ids',ids.shape==(16,) and np.array_equal(ids,expected_ids))
                observed[f'author_{i:03d}']=metric_values(z['energy'],z['force'],label_e,label_f,natoms)
        train_e=np.load(train_dir/'energy.npy',allow_pickle=False)
        observed['baseline']=metric_values(np.full(16,float(np.mean(train_e))),np.zeros_like(label_f),label_e,label_f,natoms)
        try:
            metrics=json.loads((submission/'metrics.json').read_text())
            expected_units={'energy':'eV total','energy_metric':'eV/atom','force':'eV/Angstrom','force_metric':'component eV/Angstrom'}
            schema=(metrics.get('natoms')==natoms
                    and metrics.get('units')==expected_units
                    and isinstance(metrics.get('models'),dict))
            check('L1.metrics_schema',schema)
            correct=schema;errors={}
            if schema:
                for name,expected in observed.items():
                    actual=metrics['models'].get(name);okay=isinstance(actual,dict)
                    for key,value in expected.items():
                        okay=okay and key in actual and isinstance(actual[key],(int,float)) and np.isclose(actual[key],value,rtol=1e-6,atol=1e-12)
                    correct=correct and okay
                    if not okay:errors[name]={'expected':expected,'actual':actual}
            check('L3.independent_error_attribution',correct,json.dumps(errors,ensure_ascii=False))
            shifted=metric_values(pred_e+304.0,pred_f,label_e,label_f,natoms)
            check('L3.centered_offset_invariance',np.isclose(shifted['centered_energy_rmse_eV_atom'],
                  observed['candidate']['centered_energy_rmse_eV_atom'],rtol=1e-12,atol=1e-12))
            decision=metrics.get('decision')
            if not isinstance(decision,dict):raise ValueError('decision must be a JSON object')
            tol=float(json.loads((test_root/'refs.json').read_text())['author_model_tie_tolerance'])
            energy_values=[observed[f'author_{i:03d}']['centered_energy_rmse_eV_atom'] for i in range(4)]
            force_values=[observed[f'author_{i:03d}']['force_component_rmse_eV_A'] for i in range(4)]
            best_energy=next(i for i,value in enumerate(energy_values) if value<=min(energy_values)+tol)
            best_force=next(i for i,value in enumerate(force_values) if value<=min(force_values)+tol)
            facts=(decision.get('best_author_energy_centered')==f'author_{best_energy:03d}'
                   and decision.get('best_author_force_component')==f'author_{best_force:03d}'
                   and decision.get('chosen_route') in {'candidate','author_000','author_001','author_002','author_003','none'}
                   and isinstance(decision.get('reason'),str) and bool(decision['reason'].strip()))
            check('L3.decision_facts',facts,'Route rationale remains a human scientific decision.')
        except (OSError,ValueError,KeyError,TypeError) as exc:
            check('L1.metrics_or_decision_parse',False,str(exc));return
        graph=submission/'model/graph.pb'
        ordinary=graph.is_file() and not graph.is_symlink() and graph.stat().st_size>0
        check('L1.frozen_graph',ordinary)
        public=json.loads((package/'inputs/author-predictions/provenance.json').read_text())
        author_hashes=set(public.get('source_model_sha256',[]))|set(public.get('source_compressed_model_sha256',[]))
        check('L2.not_author_graph_copy',ordinary and file_hash(graph) not in author_hashes)
        try:
            cfg=json.loads((submission/'training-trace/train.json').read_text())
            training=cfg['training'];systems=training['training_data']['systems']
            stop_batch=training['stop_batch']
            config_ok=(type(stop_batch) is int and 1<=stop_batch<=20 and systems==['/app/inputs/short-training/train'])
            check('L2.bounded_train_config',config_ok,'1–20 optimizer steps; exact 64-frame public training system; no holdout path')
            curve=np.loadtxt(submission/'training-trace/lcurve.out',comments='#')
            steps=curve[:,0] if curve.ndim==2 else np.asarray([curve[0]])
            check('L2.training_curve',curve.size>0 and np.isfinite(curve).all() and 0<int(np.max(steps))<=20)
            checkpoint=any(p.is_file() and p.stat().st_size>0 for p in (submission/'training-trace').glob('model.ckpt*'))
            check('L2.checkpoint_present',checkpoint)
        except (OSError,ValueError,KeyError,TypeError) as exc:
            check('L2.training_trace_parse',False,str(exc))
        if skip_model_replay:
            check('L2.native_graph_replay',False,'diagnostic-only test mode; production scorer always replays')
            return
        if not ordinary:return
        actual,detail=restricted_deepmd_replay(graph,holdout_dir,package/'inputs/short-training/holdout/type.raw',holdout_ids)
        if actual is None:
            if detail.startswith('INFRA:'):raise RuntimeError(detail)
            check('L2.native_graph_replay',False,detail);return
        replay_ok=(np.array_equal(actual.get('sample_id'),expected_ids)
                   and actual.get('energy',np.array([])).shape==(16,)
                   and actual.get('force',np.array([])).shape==(16,natoms,3)
                   and np.allclose(actual['energy'],pred_e,rtol=1e-5,atol=1e-7)
                   and np.allclose(actual['force'],pred_f,rtol=1e-5,atol=1e-7))
        check('L2.native_graph_replay',replay_ok,'isolated evaluator replay of the submitted frozen graph')


    def diagnostics(package,submission,test_root,skip_model_replay=False):
        protocol=json.loads((test_root/'assessment-protocol.json').read_text())
        checks=[]
        def check(k,value,detail=''):checks.append({'check':k,'passed':bool(value),'detail':detail})
        for name in protocol['expected_outputs']:
            p=submission/name
            good=any(x.is_file() and x.stat().st_size>0 for x in p.rglob('*')) if name.endswith('/') and p.is_dir() else p.is_file() and p.stat().st_size>0
            check('L1.'+name,good)
        if not all(c['passed'] for c in checks):return checks
        if protocol['case_id']=='reline-01-train':
            _short_training_checks(package,submission,test_root,check,skip_model_replay)
        elif protocol['case_id']=='reline-02-density':
            with (submission/'density.csv').open(newline='') as f: rows=list(csv.DictReader(f))
            try:
                ts=[float(r['T_K']) for r in rows];check('L1.temperature_rows',ts==[323,333,343,353,363,373])
                ref=protocol['numeric_policy']['density'];means=np.array([float(r['mean_g_cm3']) for r in rows])
                sems=np.array([float(r['sem_g_cm3']) for r in rows]);blocks=np.array([int(r['n_blocks']) for r in rows])
                good=len(rows)==6 and np.isfinite(means).all() and np.isfinite(sems).all() and (sems>=0).all() and (blocks>=8).all()
                check('L3.precision_and_block_count',good and (sems<=ref['sem_max_g_cm3']).all(),'Block independence remains subject to native-series review.')
                if good:
                    check('L3.published_density_means',(np.abs(means-np.array(ref['reference']))<=ref['equivalence_margin_g_cm3']+ref['reference_rounding_g_cm3']).all())
                    check('L3.negative_mean_thermal_slope',np.polyfit(ts,means,1)[0]<0,'NPT execution and uncertainty require manual review.')
            except (KeyError,ValueError,TypeError) as exc:check('L1.density_schema',False,str(exc))
        else:
            for path in submission.glob('*.npz'):
                try:
                    with np.load(path,allow_pickle=False) as archive:
                        good=bool(archive.files) and all(x.size>0 and (not np.issubdtype(x.dtype,np.number) or np.isfinite(x).all()) for x in [archive[k] for k in archive.files])
                    check('L1.npz_finite.'+path.name,good)
                except (ValueError,OSError) as exc:check('L1.npz_parse.'+path.name,False,str(exc))
            for path in submission.glob('*.json'):
                try:
                    obj=json.loads(path.read_text());check('L1.json_parse.'+path.name,isinstance(obj,(dict,list)) and bool(obj))
                except (ValueError,OSError) as exc:check('L1.json_parse.'+path.name,False,str(exc))
        return checks


    def main():
        ap=argparse.ArgumentParser(description=__doc__)
        ap.add_argument('--submission',type=Path,required=True)
        ap.add_argument('--skip-model-replay',action='store_true',help='test-only diagnostics; production test.sh never supplies this')
        args=ap.parse_args()
        try:
            if np is None:raise ImportError('NumPy is required by the partial diagnostic checker')
            package=Path(os.environ.get('APP',str(Path(__file__).resolve().parents[1]))).resolve()
            test_root=Path(os.environ.get('TESTS',str(package/'tests'))).resolve()
            refs=json.loads((test_root/'reference-hashes.json').read_text());bad=[]
            for rel,digest in refs.items():
                path=(test_root/rel[len('tests/'):] if rel.startswith('tests/') else package/rel)
                if path.is_symlink() or not path.is_file() or file_hash(path)!=digest:bad.append(rel)
            if bad:
                print(json.dumps({'status':'PREFLIGHT_ERROR','agent_graded':False,'bad_inputs_or_references':bad,'reward':None}));return 2
            try:checks=diagnostics(package,args.submission,test_root,args.skip_model_replay)
            except (OSError,ValueError,KeyError,TypeError,OverflowError) as exc:
                checks=[{'check':'L1.submission_parse','passed':False,'detail':str(exc)}]
            failed=[c for c in checks if not c['passed']]
            status='FAIL' if failed else 'SCIENTIFIC_REVIEW_REQUIRED'
            result={'status':status,'checks':checks,'implementation':'partial','overall_scientific_pass':False,
                    'reward':0 if failed else None,'manual_protocol':'tests/review-rubric.md','qualification_granted':False}
            print(json.dumps(result,indent=2,ensure_ascii=False));return 1 if failed else 0
        except RuntimeError as exc:
            infra=str(exc).startswith('INFRA:')
            print(json.dumps({'status':'INFRASTRUCTURE_ERROR' if infra else 'FAIL','agent_graded':not infra,
                              'reward':None if infra else 0,'error':str(exc)}));return 2 if infra else 1
        except (ImportError,OSError,ValueError,KeyError,TypeError) as exc:
            print(json.dumps({'status':'INFRASTRUCTURE_ERROR','agent_graded':False,'reward':None,'error':str(exc)}));return 2
    return SimpleNamespace(main=main)

def _make_case42_runner(_isolation):
    #!/usr/bin/env python3
    """Runner adapter: deterministic diagnostics plus a trusted, submission-bound review."""

    import argparse
    import hashlib
    import json
    import os
    from pathlib import Path, PurePosixPath
    import subprocess
    import sys
    isolation_preflight = _isolation.isolation_preflight


    APP = Path(os.environ.get("APP", "/app")).resolve()
    TESTS = Path(os.environ.get("TESTS", "/tests")).resolve()
    LOGS = Path(os.environ.get("LOGS", "/logs/verifier")).resolve()
    REPORT = LOGS / "verification.json"
    REVIEW = TESTS / "scientific-review.json"


    def sha256(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for block in iter(lambda: stream.read(1 << 20), b""):
                digest.update(block)
        return digest.hexdigest()


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
        isolation_preflight(TESTS, LOGS)
        for old in (LOGS / "reward.txt", REPORT, LOGS / "verdict.json"):
            if old.is_symlink():
                raise ValueError(f"unsafe verifier output path: {old.name}")
            old.unlink(missing_ok=True)
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
            logs, report_name = _prepare_runner_logs(42)
            sys.argv = [sys.argv[0]]
            runner = _make_case42_runner(_make_case42_isolation())
            runner.entry()
        except SystemExit:
            raise
        except Exception as exc:
            _runner_initialization_error(42, logs, report_name, exc)
    try:
        science = _make_case42_science()
        return science.main()
    except SystemExit:
        raise
    except Exception as exc:
        return _diagnostic_initialization_error(exc)


if __name__ == "__main__":
    raise SystemExit(_main_dispatch())
