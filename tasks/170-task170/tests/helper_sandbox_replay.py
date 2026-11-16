#!/usr/bin/env python3
"""Bounded behavior replay for the mounted, read-only RT04 helper.

This module is deliberately importable on a host without NumPy/spglib. Every
candidate subprocess is protected by an independently inspected container
guard in ``invoke``; the guard is also checked by ``main`` before fixtures are
created. Host tests may call ``invoke`` with subprocess mocked, but never run a
candidate helper.
"""
from __future__ import annotations
import math, os, pathlib, subprocess, sys, tempfile

HELPER=pathlib.Path(os.environ.get("CASE04_HELPER","/app/final/make-lambda-input.py"))
POSCAR=pathlib.Path(os.environ.get("CASE04_POSCAR","/app/assets/W2N3-monolayer.poscar"))
PYTHON=sys.executable

def _mount_table():
    table={}
    for line in pathlib.Path("/proc/self/mountinfo").read_text().splitlines():
        left,right=line.split(" - ",1); a=left.split(); b=right.split()
        point=a[4].replace("\\040"," ")
        table[point]={"options":set(a[5].split(",")),"fstype":b[0],"super":set(b[2].split(",")) if len(b)>2 else set()}
    return table

def _cgroup_limit(name):
    path=pathlib.Path("/sys/fs/cgroup")/name
    value=path.read_text().strip()
    if value=="max": return None
    return int(value)

def assert_isolated_grader():
    """Fail closed unless this is the expected bounded grader container."""
    if not sys.platform.startswith("linux"):
        raise RuntimeError("candidate execution is allowed only inside the Linux grader container")
    if not pathlib.Path("/.dockerenv").is_file() and not pathlib.Path("/run/.containerenv").is_file():
        raise RuntimeError("container marker missing; candidate execution blocked")
    if os.environ.get("SSH_AUTH_SOCK", ""):
        raise RuntimeError("SSH agent socket is exposed; candidate execution blocked")
    mounts=_mount_table()
    expected={"/":"ro","/app/tests":"ro","/app/final":"ro","/app/assets":"ro"}
    for point,flag in expected.items():
        m=mounts.get(point)
        if not m or flag not in m["options"]:
            raise RuntimeError(f"required read-only mount missing: {point}")
    tmp=mounts.get("/tmp")
    if not tmp or tmp["fstype"]!="tmpfs" or "rw" not in tmp["options"]:
        raise RuntimeError("/tmp must be a writable tmpfs")
    ssh=mounts.get("/root/.ssh")
    if not ssh or ssh["fstype"]!="tmpfs":
        raise RuntimeError("/root/.ssh must be masked by tmpfs")
    if pathlib.Path("/root/.ssh").stat().st_mode & 0o777:
        raise RuntimeError("/root/.ssh mask must have mode 000")
    try:
        mem=_cgroup_limit("memory.max")
        pids=_cgroup_limit("pids.max")
        cpu_quota,cpu_period=pathlib.Path("/sys/fs/cgroup/cpu.max").read_text().split()[:2]
        cpus=int(cpu_quota)/int(cpu_period) if cpu_quota!="max" else math.inf
    except Exception as exc:
        raise RuntimeError(f"cannot verify grader cgroup limits: {exc}") from exc
    if mem is None or mem>2*1024**3 or pids is None or pids>128 or cpus>2.0:
        raise RuntimeError(f"grader limits exceed policy (memory={mem}, pids={pids}, cpus={cpus})")
    if HELPER.resolve().parent!=pathlib.Path("/app/final").resolve() or POSCAR.resolve().parent!=pathlib.Path("/app/assets").resolve():
        raise RuntimeError("candidate/helper inputs must come from the declared read-only mounts")

def _science_modules():
    import numpy as np
    import spglib
    return np,spglib

def load_poscar(path):
    np,_=_science_modules()
    lines=path.read_text().splitlines(); scale=float(lines[1].split()[0])
    cell=np.array([[float(x) for x in lines[i].split()[:3]] for i in range(2,5)])*scale
    species=lines[5].split(); counts=[int(x) for x in lines[6].split()]
    coords=np.array([[float(x) for x in lines[8+i].split()[:3]] for i in range(sum(counts))])
    labels=[sp for sp,n in zip(species,counts) for _ in range(n)]
    numbers=np.array([74 if x.lower()=="w" else 7 if x.lower()=="n" else 0 for x in labels])
    return cell,coords,numbers

def prepare_case(parent, name):
    np,spglib=_science_modules()
    case=parent/name; case.mkdir()
    elph=case/"elph";elph.mkdir();out=case/"out"
    cell,coords,numbers=load_poscar(POSCAR); mesh=np.array([4,4,1])
    mapping,addresses=spglib.get_ir_reciprocal_mesh(tuple(mesh),(cell,coords,numbers),is_shift=(0,0,0),is_time_reversal=True,symprec=1e-5)
    reps=sorted(set(int(x) for x in mapping))
    alat=float(np.linalg.norm(cell[0])); expected={}
    for n,rep in enumerate(reps,1):
        q_frac=np.mod(addresses[rep]/mesh,1.0)
        q_tpiba=alat*np.linalg.solve(cell,q_frac)
        filename=elph/f"elph.inp_lambda.{n}"
        filename.write_text("%.12f %.12f %.12f 1 1 0.001\n"%tuple(q_tpiba))
        expected[str(filename.resolve())]={"q":q_frac.tolist(),"weight":int(np.count_nonzero(mapping==rep))}
    if sum(v["weight"] for v in expected.values())!=16:
        raise AssertionError("independent full-mesh orbit weights do not sum to 16")
    return case,elph,out,expected

def invoke(case,elph,out):
    assert_isolated_grader()
    cmd=[PYTHON,str(HELPER),"--structure",str(POSCAR),"--elph-dir",str(elph),"--nq1","4","--nq2","4","--nq3","1","--outdir",str(out)]
    return subprocess.run(cmd,cwd=case,capture_output=True,text=True,timeout=45)

def _parse_deck(path,expected_mu):
    lines=path.read_text().splitlines()
    if len(lines)<5: raise AssertionError(f"{path.name}: truncated lambda.x input")
    head=lines[0].split(); count_fields=lines[1].split()
    if len(head)<3 or len(count_fields)<1: raise AssertionError("missing standard lambda.x header")
    emax,degauss=float(head[0]),float(head[1]); ngauss=int(head[2]); n=int(count_fields[0])
    if not (math.isfinite(emax) and emax>0 and math.isfinite(degauss) and degauss>0 and ngauss in (0,1)):
        raise AssertionError("invalid lambda.x broadening header")
    if n<=0 or len(lines)!=2+2*n+1: raise AssertionError("lambda.x deck record count/shape is invalid")
    qrows=[]
    for line in lines[2:2+n]:
        fields=line.split()
        if len(fields)<4: raise AssertionError("malformed q/weight row")
        q=[float(v) for v in fields[:3]]; raw_weight=float(fields[3])
        if not all(math.isfinite(x) for x in q) or not raw_weight.is_integer(): raise AssertionError("non-finite q or non-integral orbit weight")
        qrows.append((q,int(raw_weight)))
    files=[str(pathlib.Path(s).resolve()) for s in lines[2+n:2+2*n]]
    mu=float(lines[-1].split()[0])
    if abs(mu-expected_mu)>1e-8: raise AssertionError(f"wrong mu*: {mu}")
    return qrows,files

def validate_outputs(out,expected):
    parsed=[]
    for path,mu in ((out/"lambda.in.mu0.16",0.16),(out/"lambda.in.mu0.10",0.10)):
        if not path.is_file(): raise AssertionError("both requested mu* decks must exist")
        qrows,files=_parse_deck(path,mu)
        if len(qrows)!=len(expected) or len(files)!=len(expected): raise AssertionError("irreducible q record count mismatch")
        if len(set(files))!=len(files) or set(files)!=set(expected): raise AssertionError("file-to-q mapping is missing, duplicated, or unexpected")
        seen=[]
        for (q,weight),filename in zip(qrows,files):
            ref=expected[filename]; delta=[q[i]-ref["q"][i] for i in range(3)]
            delta=[x-round(x) for x in delta]
            if max(abs(x) for x in delta)>1e-8: raise AssertionError(f"q/file pairing mismatch for {filename}")
            if weight!=ref["weight"]: raise AssertionError(f"wrong independent orbit weight for {filename}: {weight} != {ref['weight']}")
            seen.append(filename)
        if sum(w for _,w in qrows)!=16: raise AssertionError("orbit weights do not sum to the full 4x4x1 mesh")
        parsed.append((qrows,files))
    if parsed[0]!=parsed[1]: raise AssertionError("the two mu* decks do not preserve identical q/file mapping")
    return [{"file":pathlib.Path(filename).name,"q":q,"weight":weight} for (q,weight),filename in zip(parsed[0][0],parsed[0][1])]

def positive_check(case,elph,out,expected):
    p=invoke(case,elph,out)
    if p.returncode: raise AssertionError("valid synthetic full mesh rejected: "+p.stderr[-800:])
    validate_outputs(out,expected)

def _tamper_and_require_reject(out,expected,name,mutate):
    saved={p:p.read_text() for p in (out/"lambda.in.mu0.16",out/"lambda.in.mu0.10")}
    try:
        mutate(out/"lambda.in.mu0.16")
        try: validate_outputs(out,expected)
        except (AssertionError,ValueError) as exc: return str(exc)
        raise AssertionError(name+" output mutation escaped independent checker")
    finally:
        for p,text in saved.items(): p.write_text(text)

def negative_check(parent, name, mutate):
    case,elph,out,expected=prepare_case(parent,name)
    mutate(case,elph,out,expected)
    p=invoke(case,elph,out)
    if p.returncode==0: raise AssertionError(name+" attack was accepted")
    if (out/"lambda.in.mu0.16").exists() or (out/"lambda.in.mu0.10").exists(): raise AssertionError(name+" wrote lambda input despite invalid coverage")
    return {"case":name,"returncode":p.returncode,"outputs_written":False}

def main():
    assert_isolated_grader()
    if not HELPER.is_file() or not POSCAR.is_file(): raise SystemExit("sandbox fixture mount is incomplete")
    np,_=_science_modules()
    with tempfile.TemporaryDirectory(prefix="case04-helper-replay-") as td:
        root=pathlib.Path(td)
        case,elph,out,expected=prepare_case(root,"valid")
        positive_check(case,elph,out,expected)
        actual=validate_outputs(out,expected)
        def rotate_weights(path):
            lines=path.read_text().splitlines(); n=int(lines[1].split()[0]); rows=[2+i for i in range(n)]
            weights=[int(float(lines[i].split()[3])) for i in rows]
            pair=next(((i,j) for i in range(n) for j in range(i+1,n) if weights[i]!=weights[j]),None)
            if pair is None: raise AssertionError("fixture lacks distinct orbit weights")
            i,j=pair; a=lines[rows[i]].split(); b=lines[rows[j]].split(); a[3],b[3]=b[3],a[3]
            lines[rows[i]]=" ".join(a); lines[rows[j]]=" ".join(b); path.write_text("\n".join(lines)+"\n")
        rejected=[]
        rejected.append({"mutation":"same-sum swapped orbit weights","checker_rejection":_tamper_and_require_reject(out,expected,"same-sum swapped orbit weights",rotate_weights)})
        def swap_file_pair(path):
            lines=path.read_text().splitlines(); n=int(lines[1].split()[0]); start=2+n
            lines[start],lines[start+1]=lines[start+1],lines[start]; path.write_text("\n".join(lines)+"\n")
        rejected.append({"mutation":"wrong q/file pairing","checker_rejection":_tamper_and_require_reject(out,expected,"wrong q/file pairing",swap_file_pair)})
        def missing(c,e,o,r): sorted(e.iterdir())[-1].unlink()
        bad_inputs=[]
        bad_inputs.append(negative_check(root,"missing-orbit",missing))
        def duplicate(c,e,o,r):
            files=sorted(e.iterdir()); first=files[0].read_text().split(); last=files[-1]
            tail=last.read_text().split();tail[:3]=first[:3];last.write_text(" ".join(tail)+"\n")
        bad_inputs.append(negative_check(root,"duplicate-orbit",duplicate))
        def offgrid(c,e,o,r):
            q=sorted(e.iterdir())[-1];t=q.read_text().split();t[0]="0.1234567";t[1]="0.2345678";t[2]="0.3456789";q.write_text(" ".join(t)+"\n")
        bad_inputs.append(negative_check(root,"off-grid-q",offgrid))
    print("PASS: independent expected/actual mapping evidence: "+__import__("json").dumps({"mesh":[4,4,1],"expected_from_spglib_by_file":expected,"actual_mu016_and_mu010_mapping":actual,"checker_rejected_output_mutations":rejected,"invalid_input_controls":bad_inputs},sort_keys=True))

if __name__=="__main__": main()
