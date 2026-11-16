#!/usr/bin/env python3
"""Rebuild case06 reports from five byte-pinned historical native VASP runs."""
from __future__ import annotations
import hashlib, importlib.util, json, os, re, shutil, sys
from pathlib import Path
TASK=Path(__file__).resolve().parents[1]
DEFAULT_SOURCE=TASK/'reference/native-v1'
OUT=Path(os.environ.get('APP','/app'))/'final'
PRESSURES=(0.0,3.0,6.0,9.0)
EXPECTED_IDS=('3899378','3899465','3899500','3899529','3899591')
def sha(raw): return hashlib.sha256(raw).hexdigest()
def dump(path,value): path.write_text(json.dumps(value,sort_keys=True,indent=2,allow_nan=False)+'\n',encoding='utf-8')
def fail(s): raise SystemExit('case06 reanalysis failed: '+s)
def verify_source(root):
    if not root.is_absolute() or root.is_symlink() or not root.is_dir(): fail('source root missing or unsafe')
    doc=json.loads((root/'manifest.json').read_text(encoding='utf-8'))
    if doc.get('schema')!='bench15-case06-historical-native/v1': fail('source schema mismatch')
    files=doc.get('files')
    if not isinstance(files,dict) or not files: fail('source inventory missing')
    actual=set()
    for base,dirs,names in os.walk(root,followlinks=False):
        if any((Path(base)/d).is_symlink() for d in dirs): fail('symlink in source')
        for name in names:
            p=Path(base)/name
            if p.is_symlink() or not p.is_file(): fail('special file in source')
            rel=p.relative_to(root).as_posix()
            if rel!='manifest.json': actual.add(rel)
    if actual!=set(files): fail('source inventory has missing or extra files')
    for rel,row in files.items():
        raw=(root/rel).read_bytes()
        if len(raw)!=row.get('bytes') or sha(raw)!=row.get('sha256'): fail('source hash mismatch: '+rel)
    runs=doc.get('runs')
    if not isinstance(runs,list) or [r.get('job_id') for r in runs]!=list(EXPECTED_IDS): fail('source is not the pinned four point route plus cutoff control')
    return doc
def sacct_rows(path):
    result={}
    for line in path.read_text(encoding='utf-8').splitlines():
        f=line.split('|')
        if len(f)!=15 or not re.fullmatch(r'\d{1,24}',f[0]) or f[0] in result: fail('malformed sacct evidence')
        result[f[0]]=f
    if set(result)!=set(EXPECTED_IDS): fail('sacct IDs differ from selected calculations')
    return result
def duration(text):
    m=re.fullmatch(r'(?:(\d+)-)?(\d{2}):(\d{2}):(\d{2})',text)
    if not m: fail('malformed Slurm time limit')
    d,h,mn,s=(int(x or 0) for x in m.groups())
    return d*86400+h*3600+mn*60+s
def record_runs(engine,runs,rows):
    order=[];summary=[]
    for run in runs:
        jid=run['job_id']; f=rows[jid]
        _,name,account,partition,qos,work,state,exit_code=f[:8]
        cpus,nodes,elapsed=map(int,f[8:11]); mem,limit=f[11:13]
        if state!='COMPLETED' or exit_code!='0:0' or nodes!=1 or cpus<1: fail('historical job failed or used multiple allocations: '+jid)
        run_dir=engine/run['path']; script=run_dir/'run.slurm'; script_sha=sha(script.read_bytes())
        resources={'cpus':cpus,'gpus':0,'memory_bytes':int(mem.rstrip('GnG'))*1024**3,'wall_seconds':elapsed}
        dump(run_dir/'execution-receipt.json',{'schema':'bench15-execution-receipt/v1','execution_kind':'ARCHIVAL_NATIVE_REANALYSIS','job_id':jid,'scheduler':'Slurm','allocation_id':jid,'resources':resources,'exit_code':exit_code,'batch_script_sha256':script_sha})
        dump(run_dir/'scheduler_record.json',{'schema':'bench15-scheduler-record/v1','execution_kind':'ARCHIVAL_NATIVE_REANALYSIS','job_id':jid,'final_state':state,'exit_code':exit_code,'allocation_id':jid,'resources':resources,'walltime_limit_seconds':duration(limit),'nodes':nodes,'array_job':False,'timestamps':'NOT_AVAILABLE_IN_HISTORICAL_SOURCE','batch_script_sha256':script_sha,'raw_scheduler_record':'../resources/sacct.raw.psv','job_name':name,'account':account,'partition':partition,'qos':qos,'work_dir':work})
        run['directory']=run['path']
        run['resources']={'cpus':cpus,'memory_gib':resources['memory_bytes']//1024**3,'walltime_seconds':duration(limit)}
        if run['role']=='main': run.update({'ENCUT_eV':500.0,'kz':1,'EDIFF_eV':1e-10})
        else: run.update({'name':'encut600-0GPa','ENCUT_eV':600.0,'kz':1,'EDIFF_eV':1e-10})
        arm={'role':run['role'],'job_id':jid,'pressure_GPa':run['pressure_GPa'],'directory':run['directory']}
        if run['role']=='control': arm['name']=run['name']
        order.append(arm); summary.append((jid,name,cpus,elapsed,state,cpus*elapsed/3600))
    dump(engine/'execution-order.json',{'schema':'bench15-execution-order/v1','execution_kind':'ARCHIVAL_NATIVE_REANALYSIS','required_arms':order})
    res=engine/'resources'
    (res/'job_ids.txt').write_text(''.join(r[0]+'\n' for r in summary),encoding='ascii')
    (res/'allocation_cpu_hours_total.txt').write_text(f"{sum(r[2]*r[3] for r in summary)/3600:.6f}\n",encoding='ascii')
def sums(root):
    for directory in (root/'engine_io',root):
        rows=[]
        for p in sorted(directory.rglob('*')):
            if p.is_symlink(): fail('symlink in final output')
            if p.is_file() and p!=directory/'SHA256SUMS':
                rows.append(f'{sha(p.read_bytes())}  ./{p.relative_to(directory).as_posix()}\n')
        (directory/'SHA256SUMS').write_text(''.join(rows),encoding='ascii')
def main():
    source=Path(os.environ.get('BENCH15_CASE06_NATIVE_ROOT',str(DEFAULT_SOURCE)))
    doc=verify_source(source)
    if OUT.exists(): shutil.rmtree(OUT)
    OUT.mkdir(parents=True)
    engine=OUT/'engine_io'; native_engine=source/'engine_io'
    shutil.copytree(native_engine/'runs',engine/'runs'); shutil.copytree(native_engine/'resources',engine/'resources')
    rows=sacct_rows(engine/'resources/sacct.raw.psv'); runs=doc['runs']; record_runs(engine,runs,rows)
    dump(engine/'run_manifest.json',{'schema':'bench15-pressure-dft-run-manifest/v1','execution_kind':'ARCHIVAL_NATIVE_REANALYSIS','fresh_execution':'NOT_RUN','main':runs[:4],'controls':runs[4:]})
    source_sha=sha((source/'manifest.json').read_bytes())
    dump(engine/'historical-native-source.json',{'schema':'bench15-case06-reanalysis-source/v1','source_manifest_sha256':source_sha,'source':doc['provenance'],'fresh_execution':'NOT_RUN'})
    helper=Path(__file__).resolve().parent
    spec=importlib.util.spec_from_file_location('case06_builder',helper/'build_final.py')
    if spec is None or spec.loader is None: fail('native parser is unavailable')
    builder=importlib.util.module_from_spec(spec);sys.modules[spec.name]=builder;spec.loader.exec_module(builder)
    main_runs,control=runs[:4],runs[4]; zero=engine/main_runs[0]['path']
    raw=builder.parse_run(0.0,zero/'OUTCAR',zero/'OSZICAR')
    assigned=builder.identify_raman_modes_from_symmetry(raw['modes'],zero/'POSCAR')
    seed_modes={}
    for name,value in assigned.items():
        selected=value if isinstance(value,list) else [value]
        data=[{k:m[k] for k in ('index','imaginary','frequency_cm-1','eigenvector_mass_weighted')} for m in selected]
        seed_modes[name]=data if name.startswith('E') else data[0]
    work=OUT/'.reanalysis';work.mkdir();seed=work/'mode-seed-from-raw.json'
    dump(seed,{'classification':'computed from raw 0-GPa OUTCAR and POSCAR','modes':seed_modes})
    outcars={p:engine/r['path']/'OUTCAR' for p,r in zip(PRESSURES,main_runs)}
    oszicars={p:engine/r['path']/'OSZICAR' for p,r in zip(PRESSURES,main_runs)}
    builder.write_outputs(work,outcars,oszicars,{'encut600-0GPa':(0.0,engine/control['path']/'OUTCAR')},{},seed)
    for name in ('phonons.json','raman_modes.json','pressure_state.md','convergence.md','provenance.json'):
        shutil.copy2(work/'final'/name,OUT/name)
    ph=json.loads((OUT/'phonons.json').read_text(encoding='utf-8'))
    ph['source_classification']='matched byte-pinned historical native VASP output reanalysed from raw files'
    dump(OUT/'phonons.json',ph)
    provenance=json.loads((OUT/'provenance.json').read_text(encoding='utf-8'))
    provenance.update({'execution_kind':'ARCHIVAL_NATIVE_REANALYSIS','fresh_execution':'NOT_RUN','native_manifest_sha256':source_sha,'reanalysis':'phonon and Raman fields recomputed from raw OUTCAR/OSZICAR and POSCAR-derived symmetry; no precomputed phonons.json or raman_modes.json was read'})
    dump(OUT/'provenance.json',provenance)
    for name in ('pressure_state.md','convergence.md'):
        p=OUT/name;p.write_text(p.read_text(encoding='utf-8')+'\nHistorical reanalysis; fresh execution: NOT_RUN.\n',encoding='utf-8')
    shutil.rmtree(work);sums(OUT)
if __name__=='__main__': main()
