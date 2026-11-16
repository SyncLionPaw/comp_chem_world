#!/usr/bin/env python3
# L1 Deliverables: Check required deliverables for completeness and parseability.
# L2 Execution: Check native records, run evidence and their linkage where required by this task.
# L3 Science: Pressure-dependent Γ-point phonons in MoS₂.
"""Offline, fail-closed scientific verifier for Bench15 pressure phonons."""
from __future__ import annotations
import csv, hashlib, json, math, os, re, stat, sys, xml.etree.ElementTree as ET
from pathlib import Path, PurePosixPath
import execution_contract

ROOT=Path(__file__).resolve().parent
REF=ROOT/'reference-hpc-v1'
_REFS_DOC=json.loads((ROOT/'refs.json').read_text(encoding='utf-8'))
if _REFS_DOC.get('reference_files_b64'):
    import base64 as _b64, atexit as _atexit, shutil as _shutil, tempfile as _tempfile
    _tmp=_tempfile.mkdtemp(prefix='b15ref-')
    _atexit.register(_shutil.rmtree,_tmp,True)
    for _rel,_val in _REFS_DOC['reference_files_b64'].items():
        _p=Path(_tmp)/'reference-hpc-v1'/_rel
        _p.parent.mkdir(parents=True,exist_ok=True)
        _p.write_bytes(_b64.b64decode(_val))
    REF=Path(_tmp)/'reference-hpc-v1'
REF_SHA='32c4ff82c9eba41720181c63358522ec867fc1758ca7044d85806953b6a0f397'
PRESSURES=(0.0,3.0,6.0,9.0)
PUBLIC_SHA={
 'INCAR_0GPa':'8eae2f056f15eb87b2e0e76700660da90caf94aa1fd1fcd9f35e30d18b9b5cf2',
 'INCAR_3GPa':'caa293836e84933f3689c3a71e9d51bbb6308a78be4fa1dd3b03d60d45291683',
 'INCAR_6GPa':'128e208ec98db9af4a1d7e5878128e70abfa40834166954a80b7545305560446',
 'INCAR_9GPa':'0a0899406684ed20a1a64161e419cf36db4017d96dc72e5b8980a53e8e2480b8',
 'KPOINTS_0GPa':'2d061821c6ad99a8d0b2fc7aee050969c1ee1e68cce9905f5180ab563789b4c4',
 'KPOINTS_3GPa':'2d061821c6ad99a8d0b2fc7aee050969c1ee1e68cce9905f5180ab563789b4c4',
 'KPOINTS_6GPa':'2d061821c6ad99a8d0b2fc7aee050969c1ee1e68cce9905f5180ab563789b4c4',
 'KPOINTS_9GPa':'2d061821c6ad99a8d0b2fc7aee050969c1ee1e68cce9905f5180ab563789b4c4',
 'POSCAR_0GPa':'5c53633a94f89a4abb57ccf651847b07c2bf139ee193a81a66c049b2fb3071dd',
 'POSCAR_3GPa':'a15d48aaf5b22224e1bf87921e56357f623cc2526050332c7742b881b5a948c8',
 'POSCAR_6GPa':'5be2b35ecf0eaf10ff29ad6c5ea985050eaa554dc56fa035ca233b2654908625',
 'POSCAR_9GPa':'3a3760e9d62372417d29cbdfb67697b0d1f4bb0b510893c3e1f5864058f70129',
 'pressure_deck_map.md':'a9166298d98e79804da1f8d7e9d39b5ca36cf8e55ba75fe32be94cc37b6b0517',
}
RUN_SCHEMA='bench15-pressure-dft-run-manifest/v1'
class ScienceFail(Exception): pass
class InfraError(Exception): pass

_REFS=json.loads((ROOT/'refs.json').read_text(encoding='utf-8'))
_TOL=_REFS.get('tolerances') or {}

def _tol(name):
    if name not in _TOL:
        raise InfraError(f'refs.json missing tolerance: {name}')
    return _TOL[name]

TAG_TOL={k: float(v) for k, v in _tol('TAG_TOL').items()}

def require(ok,msg):
    if not ok: raise ScienceFail(msg)
def sha(b): return hashlib.sha256(b).hexdigest()
def json_load(path, *, infra=False):
    try:
        raw=path.read_bytes()
        if len(raw)>64*1024*1024: raise ValueError('JSON exceeds 64 MiB')
        def pairs(items):
            out={}
            for k,v in items:
                if k in out: raise ValueError('duplicate JSON key')
                out[k]=v
            return out
        val=json.loads(raw.decode('utf-8'),object_pairs_hook=pairs,parse_constant=lambda x: (_ for _ in ()).throw(ValueError('nonfinite JSON constant')))
        finite(val)
        return val
    except Exception as e:
        exc=InfraError if infra else ScienceFail
        raise exc(f'cannot read valid JSON {path.name}: {type(e).__name__}') from e

def finite(v):
    if isinstance(v,float) and not math.isfinite(v): raise ValueError('nonfinite number')
    if isinstance(v,dict):
        for x in v.values(): finite(x)
    elif isinstance(v,list):
        for x in v: finite(x)

def number(v, label):
    """Accept JSON numbers, never bools or numeric-looking strings."""
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
        raise ScienceFail(f'{label} must be a finite JSON number')
    return float(v)

def strict_bool(v, label):
    if type(v) is not bool: raise ScienceFail(f'{label} must be a JSON boolean')
    return v

def require_object(v, label):
    if not isinstance(v, dict): raise ScienceFail(f'{label} must be an object')
    return v

def require_list(v, label, n=None):
    if not isinstance(v, list) or (n is not None and len(v) != n):
        raise ScienceFail(f'{label} must be a list' + (f' of length {n}' if n is not None else ''))
    return v

def safe_inventory(root, *, max_files=4096,max_total=2*1024**3,max_file=512*1024**2):
    if root.is_symlink() or not root.is_dir(): raise ScienceFail('final/ is missing or redirected')
    rows=[]; total=0
    for base,dirs,files in os.walk(root,topdown=True,followlinks=False):
        b=Path(base)
        for n in list(dirs):
            p=b/n; st=p.lstat()
            if stat.S_ISLNK(st.st_mode) or not stat.S_ISDIR(st.st_mode): raise ScienceFail('symlink or special directory in final/')
        for n in files:
            p=b/n; st=p.lstat()
            if stat.S_ISLNK(st.st_mode) or not stat.S_ISREG(st.st_mode) or st.st_nlink<1: raise ScienceFail('symlink or special file in final/')
            rel=p.relative_to(root).as_posix()
            if PurePosixPath(rel).is_absolute() or '..' in PurePosixPath(rel).parts: raise ScienceFail('unsafe output path')
            if n.upper()=='POTCAR': raise ScienceFail('POTCAR bytes must not be submitted')
            if st.st_size>max_file: raise ScienceFail('output file exceeds 512 MiB')
            total+=st.st_size
            if total>max_total: raise ScienceFail('final output exceeds 2 GiB')
            rows.append((rel,p,st.st_size))
            if len(rows)>max_files: raise ScienceFail('final output contains more than 4096 files')
    return rows

def path_beneath(root,rel):
    if not isinstance(rel,str) or not rel or '\\' in rel or '\x00' in rel: raise ScienceFail('run manifest contains invalid relative path')
    p=PurePosixPath(rel)
    if p.is_absolute() or p.as_posix()!=rel or any(x in {'','.','..'} for x in p.parts): raise ScienceFail('run manifest path escapes engine_io')
    out=root.joinpath(*p.parts)
    cur=root
    for part in p.parts:
        cur=cur/part
        if cur.is_symlink(): raise ScienceFail('symlink in run path')
    if not out.is_dir(): raise ScienceFail('run directory is missing')
    return out

def verify_reference():
    if _REFS_DOC.get('schema')!='bench15.tests.refs/v1': raise InfraError('refs.json schema mismatch')
    code_rows=_REFS_DOC.get('files')
    if not isinstance(code_rows,list) or not code_rows: raise InfraError('refs.json code pin inventory is missing')
    seen_code=set()
    for row in code_rows:
        if not isinstance(row,dict) or set(row)!={'path','sha256','bytes'}: raise InfraError('refs.json code pin row is malformed')
        rel=row['path']; p=ROOT.parent/rel
        if rel in seen_code or not isinstance(rel,str) or PurePosixPath(rel).is_absolute() or '..' in PurePosixPath(rel).parts or p.is_symlink() or not p.is_file(): raise InfraError('pinned verifier source is missing or redirected')
        raw=p.read_bytes()
        if type(row['bytes']) is not int or len(raw)!=row['bytes'] or sha(raw)!=row['sha256']: raise InfraError('pinned verifier source hash mismatch')
        seen_code.add(rel)
    if not {'tests/verify.py','tests/execution_contract.py'}.issubset(seen_code): raise InfraError('refs.json omits active verifier source pins')
    mf=REF/'reference-manifest.json'
    if mf.is_symlink() or not mf.is_file() or sha(mf.read_bytes())!=REF_SHA: raise InfraError('pinned compact Gold reference manifest is missing or changed')
    doc=json_load(mf,infra=True)
    if doc.get('schema')!='bench15-pressure-dft-reference/v1': raise InfraError('reference schema mismatch')
    rows=doc.get('files')
    if not isinstance(rows,list) or len(rows)!=doc.get('file_count') or len(rows)>32: raise InfraError('reference inventory is malformed')
    seen=set(); size=0
    for r in rows:
        if not isinstance(r,dict) or set(r)!={'path','bytes','sha256'}: raise InfraError('reference inventory row malformed')
        rel=r['path']; p=REF/rel
        if rel in seen or PurePosixPath(rel).name!=rel or p.is_symlink() or not p.is_file(): raise InfraError('reference path inventory mismatch')
        b=p.read_bytes(); size+=len(b)
        if len(b)!=r['bytes'] or sha(b)!=r['sha256']: raise InfraError('compact reference asset hash mismatch')
        seen.add(rel)
    if size!=doc.get('total_bytes'): raise InfraError('reference size total mismatch')
    need={'phonons.json','raman_modes.json','provenance.json','convergence.md','pressure_state.md','resource_summary.tsv','job_ids.txt'}
    if seen!=need: raise InfraError('reference has missing or unexpected files')
    ph=json_load(REF/'phonons.json',infra=True); rm=json_load(REF/'raman_modes.json',infra=True)
    if ph.get('pressures_GPa')!=list(PRESSURES) or rm.get('pressures_GPa')!=list(PRESSURES): raise InfraError('reference pressure grid is invalid')
    if not isinstance(ph.get('points'),list) or len(ph['points'])!=4: raise InfraError('reference does not contain four points')
    return ph,rm

def verify_public_assets():
    root=Path(os.environ.get('CCB_PUBLIC_ASSETS','/app/assets'))
    if root.is_symlink() or not root.is_dir(): raise InfraError('mounted public case assets are missing or redirected')
    for name,want in PUBLIC_SHA.items():
        p=root/name
        if p.is_symlink() or not p.is_file(): raise InfraError(f'mounted public input is missing or redirected: {name}')
        try: data=p.read_bytes()
        except Exception as e: raise InfraError(f'mounted public input is unreadable: {name}') from e
        if sha(data)!=want: raise InfraError(f'mounted public input hash mismatch: {name}')
    return root

def parse_incar(path):
    tags={}; counts={}
    try: lines=path.read_text(encoding='ascii').splitlines()
    except Exception as e: raise ScienceFail('INCAR is unreadable') from e
    for line in lines:
        line=re.split(r'[!#]',line,1)[0].strip()
        if not line: continue
        if '=' not in line: raise ScienceFail('malformed INCAR tag')
        k,v=(x.strip() for x in line.split('=',1)); k=k.upper()
        if not re.fullmatch(r'[A-Z][A-Z0-9_]*',k) or not v: raise ScienceFail('invalid INCAR tag')
        counts[k]=counts.get(k,0)+1; tags[k]=v.split()[0]
    for key in ('PSTRESS','ENCUT','EDIFF','POTIM','NFREE','IBRION','ISIF','ISYM','IVDW','KPAR','NSW'):
        if counts.get(key)!=1: raise ScienceFail(f'INCAR must contain exactly one {key}')
    out={}
    for k,v in tags.items():
        try:
            out[k]=float(v.replace('D','E').replace('d','e'))
            if not math.isfinite(out[k]): raise ValueError('nonfinite INCAR value')
        except ValueError:
            out[k]=v
    return out

def parse_grid(path):
    try:
        lines=path.read_text(encoding='ascii').splitlines()
        if len(lines)<4: raise ValueError('incomplete KPOINTS')
        if lines[1].strip() not in {'0','0.0'}: raise ValueError('not automatic grid')
        grid=[int(x) for x in lines[3].split()]
    except Exception as e: raise ScienceFail('KPOINTS grid is malformed') from e
    if len(grid)!=3 or any(x<=0 for x in grid): raise ScienceFail('KPOINTS grid is invalid')
    if len(lines)<4 or lines[2].strip().lower() not in {'g','gamma'}: raise ScienceFail('KPOINTS must use Gamma-centered mesh')
    return grid

def parse_oszicar(path, ediff, outcar_text):
    try: text=path.read_text(encoding='ascii')
    except Exception as e: raise ScienceFail('OSZICAR is unreadable') from e
    rows=[]; final_d=[]; final_deps=[]; last_d=None; last_deps=None; iteration_counts=[]; count=0
    try: ediff=number(ediff,'effective EDIFF')
    except ScienceFail: raise
    rx=re.compile(r'^\s*(\d+)\s+F=\s*([-+0-9.Ee]+)\s+E0=\s*([-+0-9.Ee]+)\s+d E\s*=\s*([-+0-9.Ee]+)',re.M)
    for line in text.splitlines():
        if re.match(r'^\s*(DAV|RMM|CG):',line):
            fields=line.split(':',1)[1].split()
            if len(fields)>=4:
                try:
                    last_d=float(fields[2]); last_deps=float(fields[3]); count+=1
                except ValueError: pass
        m=rx.match(line)
        if m:
            vals=[float(x) for x in m.groups()[1:]]
            if any(not math.isfinite(x) for x in vals): raise ScienceFail('OSZICAR contains nonfinite energy')
            rows.append((int(m.group(1)),*vals))
            if last_d is None or last_deps is None: raise ScienceFail('OSZICAR energy step has no preceding electronic convergence record')
            final_d.append(last_d); final_deps.append(last_deps); iteration_counts.append(count)
            last_d=last_deps=None; count=0
    if len(rows)!=21 or [r[0] for r in rows]!=list(range(1,22)):
        raise ScienceFail('OSZICAR must contain exactly 21 ordered finite-displacement energy records')
    if (len(final_d)!=21 or any(abs(x)>ediff*(1+1e-5) for x in final_d)
        or any(abs(x)>ediff*(1+1e-5) for x in final_deps)):
        raise ScienceFail('one or more OSZICAR electronic steps do not satisfy EDIFF')
    if len(re.findall(r'aborting loop because EDIFF is reached',outcar_text,re.I))!=21 or re.search(r'reached\s+NELM|NELM\s+reached',outcar_text,re.I):
        raise ScienceFail('OUTCAR does not record an EDIFF stop for all 21 steps without NELM exhaustion')
    nelm=exact_tag(outcar_text,'NELM')[-1]
    if not nelm.is_integer() or nelm<=0 or any(x>nelm for x in iteration_counts):
        raise ScienceFail('SCF iteration count exceeds effective NELM')
    return rows

def verify_vasprun(path,pressure,incar,grid,outcar_text):
    try:
        root=ET.parse(path).getroot()
        if root.tag!='modeling': raise ValueError('wrong root')
        incars=root.find('./incar')
        params=root.find('./parameters')
        if incars is None or params is None: raise ValueError('missing input/runtime parameter sections')
        def named(section,name):
            vals=[(e.text or '').strip() for e in section.findall(f'.//*[@name="{name}"]')]
            if not vals: raise ValueError(f'missing {name}')
            try: parsed=[float(x) for x in vals]
            except ValueError as e: raise ValueError(f'malformed {name}') from e
            if any(not math.isfinite(x) for x in parsed): raise ValueError(f'nonfinite {name}')
            return parsed
        expected={'ENCUT':incar['ENCUT'],'EDIFF':incar['EDIFF'],'IBRION':6,'ISIF':3,'ISYM':2,
                  'IVDW':11,'NFREE':2,'POTIM':.015,'PSTRESS':pressure*10}
        for key,want in expected.items():
            input_values=named(incars,key)
            if not math.isclose(input_values[0],want,rel_tol=1e-7,abs_tol=1e-8): raise ValueError(f'input {key} mismatch')
            runtime_values=[(e.text or '').strip() for e in params.findall(f'.//*[@name="{key}"]')]
            if runtime_values:
                parsed=[float(x) for x in runtime_values]
                if any(not math.isfinite(x) for x in parsed): raise ValueError(f'nonfinite runtime {key}')
                if key=='EDIFF':
                    if any(x>1e-8 for x in parsed): raise ValueError('runtime EDIFF is outside stored precision/range')
                elif any(not math.isclose(x,want,rel_tol=1e-7,abs_tol=1e-8) for x in parsed):
                    raise ValueError(f'runtime {key} mismatch')
            else:
                # VASP omits ENCUT/IVDW (and in this build KPAR) from the
                # <parameters> block. Their requested values are present in
                # <incar>; the actual effective values are independently
                # parsed from OUTCAR by verify_effective_tags.
                actual=exact_tag(outcar_text,key)
                if any(not math.isclose(x,want,rel_tol=1e-7,abs_tol=1e-8) for x in actual): raise ValueError(f'OUTCAR fallback {key} mismatch')
        input_nsw=named(incars,'NSW'); runtime_nsw=named(params,'NSW')
        if input_nsw[0]!=1 or runtime_nsw[-1]!=109: raise ValueError('requested/effective NSW mismatch')
        gen=root.find('./kpoints/generation')
        if gen is None or (gen.get('param') or '').lower()!='gamma': raise ValueError('kpoint generation is not Gamma centered')
        div=gen.find('./v[@name="divisions"]')
        if div is None or [int(x) for x in (div.text or '').split()]!=grid: raise ValueError('vasprun kpoint dimensions mismatch')
        xmltext=path.read_text(encoding='iso-8859-1',errors='strict')
        if not xmltext.rstrip().endswith('</modeling>'): raise ValueError('incomplete document')
    except Exception as e:
        if isinstance(e,ScienceFail): raise
        raise ScienceFail(f'vasprun.xml runtime/input evidence is malformed or inconsistent: {type(e).__name__}') from e

def exact_tag(text, name):
    vals=re.findall(r'^\s*'+re.escape(name)+r'\s*=\s*([-+0-9.Ee]+)',text,re.M|re.I)
    if not vals: raise ScienceFail(f'OUTCAR lacks effective {name}')
    try: nums=[float(x.replace('D','E').replace('d','e')) for x in vals]
    except Exception as e: raise ScienceFail(f'OUTCAR effective {name} is malformed') from e
    if any(not math.isfinite(x) for x in nums): raise ScienceFail(f'OUTCAR effective {name} is nonfinite')
    return nums

def verify_engine_and_paw(run, text, pressure):
    engine=(run/'ENGINE.txt').read_text(encoding='ascii').strip()
    if not engine or len(engine)>4096 or 'vasp.6.4.1' not in engine or 'vasp.6.4.1' not in text:
        raise ScienceFail('engine provenance must identify VASP 6.4.1 in raw engine and OUTCAR evidence')
    if 'PAW_PBE Mo 08Apr2002' not in text or 'PAW_PBE S 06Sep2000' not in text:
        raise ScienceFail('OUTCAR PAW TITEL records do not match Mo/S reference potentials')
    digestfile=run/'POTCAR.identity.sha256'
    vals={}
    for line in digestfile.read_text(encoding='ascii').splitlines():
        fields=line.split()
        if len(fields)==2:
            if re.fullmatch(r'[0-9a-f]{64}',fields[0]): vals[fields[1]]=fields[0]
            elif re.fullmatch(r'[0-9a-f]{64}',fields[1]): vals[fields[0]]=fields[1]
    expected={'Mo_PAW_PBE_Mo_08Apr2002_sha256':'e91eef5e768b52c866a1a7e0829a38a041f11142f3595800aaf3206086d6c164',
              'S_PAW_PBE_S_06Sep2000_sha256':'0fc7481fb0695f01bdc6462160264c5c84044ae9ec85a907d398b887a2bc3132',
              'combined_POTCAR_sha256':'b8f5bccb188e7a8b1082445abe307e62f27d3cd9f9f7b128325dacee3e9192a0'}
    if any(vals.get(k)!=v for k,v in expected.items()):
        raise ScienceFail('PAW identity digest does not match the pinned Mo/S potentials')
    binary=re.search(r'^vasp_sha256=([0-9a-f]{64})$',engine,re.M)
    if not binary:
        binary=re.search(r'^vasp_binary\s+([0-9a-f]{64})\s*$',engine,re.M)
    if not binary or binary.group(1)!='14e2ac8e6b0de427ef2bff2b09a2cce7ae89010cddff59d933c45b88a5d7eae8':
        raise ScienceFail('VASP binary digest does not match the pinned engine build')
    if not re.search(r'PBE',text,re.I) or not re.search(r'DFTD3\s+V3\.0',text):
        raise ScienceFail('OUTCAR lacks PBE or D3 runtime evidence')

def verify_effective_tags(text, incar, pressure, grid):
    required={'ENCUT':incar.get('ENCUT'),'EDIFF':incar.get('EDIFF'),'POTIM':.015,'NFREE':2.0,'IBRION':6.0,
              'ISIF':3.0,'ISYM':2.0,'IVDW':11.0,'PSTRESS':pressure*10.0,'KPAR':4.0,'NSW':109.0}
    for tag,want in required.items():
        nums=exact_tag(text,tag)
        observed=[nums[-1]] if tag=='NSW' else nums
        if not math.isfinite(want) or any(not math.isclose(x,want,rel_tol=1e-8,abs_tol=1e-12) for x in observed):
            raise ScienceFail(f'OUTCAR effective {tag} differs from the strict route')

def parse_poscar(path):
    try: lines=path.read_text(encoding='ascii').splitlines(); scale=float(lines[1]); names=lines[5].split(); counts=list(map(int,lines[6].split()))
    except Exception as e: raise ScienceFail('POSCAR header is malformed') from e
    if names!=['Mo','S'] or counts!=[2,4]: raise ScienceFail('POSCAR species or atom count differs from Mo2S4 reference')
    i=7
    if lines[i].strip().lower().startswith('s'): i+=1
    mode=lines[i].strip().lower(); i+=1
    if not mode.startswith('d'): raise ScienceFail('POSCAR must use Direct coordinates')
    coords=[]
    for line in lines[i:i+6]:
        vals=[float(x) for x in line.split()[:3]]
        if len(vals)!=3 or any(not math.isfinite(x) for x in vals): raise ScienceFail('POSCAR coordinate malformed')
        coords.append([x%1.0 for x in vals])
    if len(coords)!=6: raise ScienceFail('POSCAR must contain six positions')
    return coords,['Mo','Mo','S','S','S','S']

def mode_rows(text):
    start=text.find('Eigenvectors and eigenvalues of the dynamical matrix')
    if start<0: raise ScienceFail('OUTCAR lacks phonon eigenvectors')
    tail=text[start:]; lines=tail.splitlines()
    header=re.compile(r'^\s*(\d+)\s+(f/i|f)\s*=\s*([-+0-9.Ee]+)\s+THz.*?([-+0-9.Ee]+)\s+cm-1',re.M)
    modes=[]
    matches=list(header.finditer(tail))
    for mi,m in enumerate(matches):
        line_no=tail[:m.start()].count('\n'); vec=[]
        next_line=tail[:matches[mi+1].start()].count('\n') if mi+1<len(matches) else len(lines)
        for line in lines[line_no+1:next_line]:
            cols=line.split()
            if len(cols)>=6:
                try:
                    atom=[float(x.replace('D','E')) for x in cols[-3:]]
                    if any(not math.isfinite(x) for x in atom): raise ValueError('nonfinite vector')
                    vec.append(atom)
                except ValueError: pass
                if len(vec)==6: break
        if len(vec)!=6: raise ScienceFail('OUTCAR eigenvector block is malformed')
        freq=float(m.group(4)); imag=m.group(2)=='f/i'
        if not math.isfinite(freq): raise ScienceFail('nonfinite OUTCAR mode frequency')
        modes.append({'index':int(m.group(1)),'frequency_cm-1':-freq if imag else freq,'imaginary':imag,'vector':vec})
    if len(modes)!=18 or sorted(x['index'] for x in modes)!=list(range(1,19)): raise ScienceFail('OUTCAR must contain exactly 18 unique Gamma modes')
    return modes

def outcar_state(text):
    def one(rx,label):
        m=re.search(rx,text,re.M)
        if not m: raise ScienceFail(f'OUTCAR lacks {label}')
        return m
    m=one(r'^\s*PSTRESS\s*=\s*([-+0-9.Ee]+)','PSTRESS')
    stress=one(r'^\s*in kB\s+([-+0-9.Ee]+)\s+([-+0-9.Ee]+)\s+([-+0-9.Ee]+)','initial stress')
    ext=one(r'^\s*external pressure\s*=\s*([-+0-9.Ee]+)\s*kB','initial external pressure')
    force_start=one(r'^\s*POSITION\s+TOTAL-FORCE \(eV/Angst\)','force block').end()
    block=text[force_start:].splitlines()
    forces=[]
    for line in block:
        if set(line.strip()) <= {'-'} or not line.strip(): continue
        q=line.split()
        if len(q)>=6:
            try: forces.append([float(x.replace('D','E')) for x in q[-3:]])
            except ValueError: pass
            if len(forces)==6: break
    if len(forces)!=6: raise ScienceFail('OUTCAR initial force block is incomplete')
    maxf=max(math.sqrt(sum(x*x for x in row)) for row in forces)
    if not math.isfinite(maxf): raise ScienceFail('nonfinite force in OUTCAR')
    vals=[float(m.group(1)),*[float(x) for x in stress.groups()],float(ext.group(1)),maxf]
    if any(not math.isfinite(x) for x in vals): raise ScienceFail('nonfinite pressure/stress/force in OUTCAR')
    return vals[0],vals[1:4],vals[4],vals[5]

def inverter(coords,species):
    # Find a POSCAR-derived inversion center and species-preserving bijection.
    for i in range(6):
      for j in range(6):
        if species[i]!=species[j]: continue
        center=[((coords[i][k]+coords[j][k])*0.5)%1 for k in range(3)]
        mapping=[]; used=set(); ok=True
        for a,r in enumerate(coords):
            target=[(2*center[k]-r[k])%1 for k in range(3)]
            candidates=[]
            for b,q in enumerate(coords):
                if species[a]!=species[b] or b in used: continue
                d=[(target[k]-q[k]+0.5)%1-0.5 for k in range(3)]
                candidates.append((sum(x*x for x in d),b))
            if not candidates: ok=False; break
            d,b=min(candidates)
            if d>1e-8: ok=False; break
            mapping.append(b);used.add(b)
        if ok and all(mapping[mapping[i]]==i for i in range(6)): return mapping,center
    raise ScienceFail('POSCAR does not yield a consistent inversion mapping')

def parity(mode,mapping):
    v=mode['vector']; a=[x for row in v for x in row]; inv=[-v[mapping[i]][k] for i in range(6) for k in range(3)]
    den=sum(x*x for x in a)
    if den<=1e-18: raise ScienceFail('zero eigenvector norm')
    return sum(x*y for x,y in zip(a,inv))/den

def mode_features(mode,coords,species,mapping):
    v=mode['vector']; norm=sum(x*x for row in v for x in row)
    z=sum(row[2]**2 for row in v)/norm
    mo_total=math.sqrt(sum(x*x for row in v[:2] for x in row))/math.sqrt(norm)
    s_total=math.sqrt(sum(x*x for row in v[2:] for x in row))/math.sqrt(norm)
    mo=math.sqrt(sum(v[i][0]**2+v[i][1]**2 for i in (0,1)))
    sulfur=math.sqrt(sum(v[i][0]**2+v[i][1]**2 for i in (2,3,4,5)))
    cosines=[]; layer=[]
    for mi in (0,1):
        si=sorted((i for i in (2,3,4,5)),key=lambda i: abs((coords[i][2]-coords[mi][2]+0.5)%1-0.5))[:2]
        sx=sum(v[i][0] for i in si)/2; sy=sum(v[i][1] for i in si)/2
        mx,my=v[mi][0],v[mi][1]
        den=math.hypot(mx,my)*math.hypot(sx,sy)
        cosines.append((mx*sx+my*sy)/den if den>1e-15 else 0.0)
        layer.append((mx+sx,my+sy))
    den=math.hypot(*layer[0])*math.hypot(*layer[1])
    inter=(layer[0][0]*layer[1][0]+layer[0][1]*layer[1][1])/den if den>1e-15 else 0.0
    pol=parity(mode,mapping)
    return {'z_fraction':z,'mo_total':mo_total,'s_total':s_total,'mo_inplane':mo,'s_inplane':sulfur,'mo_s_cosines':cosines,'interlayer_cosine':inter,'parity':pol}

def identify(modes,coords,species,mapping):
    feats=[mode_features(m,coords,species,mapping) for m in modes]
    e2g2=[];e2g1=[];a1=[]
    for i,f in enumerate(feats):
        if f['parity']<0.8: continue
        if f['z_fraction']>0.92 and f['mo_total']<0.12 and f['s_total']>0.92:
            a1.append(i)
        elif f['z_fraction']<0.15 and all(x>0.75 for x in f['mo_s_cosines']) and f['interlayer_cosine']< -0.65:
            e2g2.append(i)
        elif f['z_fraction']<0.15 and all(x< -0.75 for x in f['mo_s_cosines']):
            e2g1.append(i)
    if len(e2g2)!=2 or len(e2g1)!=2 or len(a1)!=1:
        raise ScienceFail(f'layer/parity branch classification ambiguous (E2g2={len(e2g2)}, E2g1={len(e2g1)}, A1g={len(a1)})')
    return {'E2g2':e2g2,'E2g1':e2g1,'A1g':[a1[0]]},feats

def fit(xs,ys):
    xm=sum(xs)/len(xs); ym=sum(ys)/len(ys)
    slope=sum((x-xm)*(y-ym) for x,y in zip(xs,ys))/sum((x-xm)**2 for x in xs)
    intercept=ym-slope*xm; residual=[y-(intercept+slope*x) for x,y in zip(xs,ys)]
    return slope,intercept,residual

def _orthonormal_mode_subspace(modes,indices):
    basis=[]
    for index in indices:
        vec=[x for row in modes[index]['vector'] for x in row]
        for prior in basis:
            projection=sum(a*b for a,b in zip(vec,prior))
            vec=[a-projection*b for a,b in zip(vec,prior)]
        norm=math.sqrt(sum(x*x for x in vec))
        if not math.isfinite(norm) or norm<1e-12: raise ScienceFail('Raman mode subspace is linearly dependent')
        basis.append([x/norm for x in vec])
    return basis

def subspace_overlap(left_modes,left_indices,right_modes,right_indices):
    if len(left_indices)!=len(right_indices): raise ScienceFail('Raman branch dimension changed across pressure points')
    left=_orthonormal_mode_subspace(left_modes,left_indices); right=_orthonormal_mode_subspace(right_modes,right_indices)
    total=0.0
    for a in left:
        for b in right: total+=sum(x*y for x,y in zip(a,b))**2
    return total/len(left)

def raw_point_group(text):
    start=text.find('Eigenvectors and eigenvalues of the dynamical matrix')
    if start<0: raise ScienceFail('OUTCAR lacks Gamma point-group evidence')
    matches=list(re.finditer(r'point group associated with its full space group is\s+([A-Za-z0-9_]+)',text[start:],re.I))
    if not matches: raise ScienceFail('OUTCAR lacks point-group assignment before phonon modes')
    return matches[-1].group(1)

def failcheck(candidate,ref_ph,ref_rm):
    rows=safe_inventory(candidate)
    expected_input=verify_public_assets()
    files={rel:p for rel,p,_ in rows}
    required={'phonons.json','raman_modes.json','pressure_state.md','convergence.md','engine_io/run_manifest.json'}
    missing=required-files.keys()
    if missing: raise ScienceFail(f'missing required outputs: {sorted(missing)}')
    ph=require_object(json_load(candidate/'phonons.json'),'phonons.json'); rm=require_object(json_load(candidate/'raman_modes.json'),'raman_modes.json')
    if (not isinstance(ph.get('pressures_GPa'),list) or not isinstance(rm.get('pressures_GPa'),list)
        or len(ph['pressures_GPa'])!=4 or len(rm['pressures_GPa'])!=4
        or any(type(x) not in (int,float) or not math.isfinite(x) for x in ph['pressures_GPa']+rm['pressures_GPa'])
        or ph['pressures_GPa']!=list(PRESSURES) or rm['pressures_GPa']!=list(PRESSURES)):
        raise ScienceFail('pressures must be exactly [0,3,6,9] GPa in order')
    if ph.get('frequency_unit')!='cm-1' or rm.get('frequency_unit')!='cm-1': raise ScienceFail('frequency unit must be cm-1')
    if rm.get('d_omega_dP_unit')!='cm-1/GPa': raise ScienceFail('slope unit must be cm-1/GPa')
    manifest=json_load(candidate/'engine_io/run_manifest.json')
    if manifest.get('schema')!=RUN_SCHEMA: raise ScienceFail('run manifest schema mismatch')
    main=manifest.get('main'); controls=manifest.get('controls')
    require_list(main,'run manifest main',4); require_list(controls,'run manifest controls')
    seen_jobs=set(); parsed=[]; branch_values={x:[] for x in ('E2g2','E2g1','A1g')}; branch_indices={x:[] for x in ('E2g2','E2g1','A1g')}
    point_by_p=ph.get('points'); tracks=rm.get('branches')
    require_list(point_by_p,'phonons.points',4); require_object(tracks,'raman_modes.branches')
    for n,(pressure,runrec,point) in enumerate(zip(PRESSURES,main,point_by_p)):
        require_object(runrec,'main run record'); require_object(point,'phonon pressure point')
        if number(runrec.get('pressure_GPa'),'main run pressure')!=pressure: raise ScienceFail('main run manifest points are mispaired')
        if (number(runrec.get('ENCUT_eV'),'main route ENCUT')!=500.0
            or type(runrec.get('kz')) is not int or runrec['kz']!=1
            or number(runrec.get('EDIFF_eV'),'main route EDIFF')>1e-10):
            raise ScienceFail('main run settings do not match strict route')
        job=runrec.get('job_id')
        if not isinstance(job,str): raise ScienceFail('main scheduler job IDs must be strings')
        if not re.fullmatch(r'\d{1,24}',job) or job in seen_jobs: raise ScienceFail('main scheduler job IDs must be unique numeric IDs')
        seen_jobs.add(job)
        run=path_beneath(candidate/'engine_io',runrec.get('directory'))
        for name in ('OUTCAR','OSZICAR','POSCAR','INCAR','KPOINTS','vasprun.xml','ENGINE.txt','POTCAR.identity.sha256'):
            p=run/name
            if p.is_symlink() or not p.is_file(): raise ScienceFail(f'main run lacks required raw {name}')
        try: out=run/'OUTCAR'; text=out.read_text(errors='strict')
        except Exception as e: raise ScienceFail('OUTCAR unreadable') from e
        incar=parse_incar(run/'INCAR'); grid=parse_grid(run/'KPOINTS'); coords,species=parse_poscar(run/'POSCAR')
        public={0.0:'POSCAR_0GPa',3.0:'POSCAR_3GPa',6.0:'POSCAR_6GPa',9.0:'POSCAR_9GPa'}
        pub=expected_input/public[pressure]
        if pub.is_symlink() or not pub.is_file(): raise InfraError('required public pressure structures are missing or redirected')
        if sha(pub.read_bytes())!=sha((run/'POSCAR').read_bytes()): raise ScienceFail('POSCAR is not the pressure-matched public structure')
        if grid!=[12,12,1] or incar.get('PSTRESS')!=pressure*10 or incar.get('ENCUT')!=500.0 or not isinstance(incar.get('EDIFF'),float) or incar.get('EDIFF')>1e-10 or [incar.get(k) for k in ('POTIM','NFREE','IBRION','ISIF','ISYM','IVDW','KPAR')]!=[.015,2.0,6.0,3.0,2.0,11.0,4.0]: raise ScienceFail('main route parameters differ from strict fixed route')
        if incar.get('NSW')!=1: raise ScienceFail('requested NSW must be the explicit single-step finite-displacement value')
        verify_effective_tags(text,incar,pressure,grid)
        if len(re.findall(r'aborting loop because EDIFF is reached',text,re.I))!=21 or re.search(r'reached NELM|NELM.*reached',text,re.I): raise ScienceFail('SCF did not EDIFF-converge all 21 finite-displacement calculations')
        parse_oszicar(run/'OSZICAR',incar['EDIFF'],text)
        verify_engine_and_paw(run,text,pressure)
        verify_vasprun(run/'vasprun.xml',pressure,incar,grid,text)
        modes=mode_rows(text); pstress,stress,ext,maxf=outcar_state(text)
        point_group=raw_point_group(text)
        if point_group!='D_6h': raise ScienceFail('raw OUTCAR Gamma phonons are not assigned to D_6h')
        if abs(pstress-pressure*10)>1e-8: raise ScienceFail('OUTCAR pressure target is mismatched')
        for key,want in [('point_group',point_group),('job_id',job),('target_pressure_GPa_from_PSTRESS',pstress/10.0)]:
            if key in point and point[key]!=want: raise ScienceFail(f'phonons point metadata {key} contradicts the raw run')
        reported=point.get('modes')
        if not isinstance(reported,list) or len(reported)!=18: raise ScienceFail('phonons.json must report 18 modes per point')
        raw_by_id={m['index']:m for m in modes}; rep_by_id={}
        for b in reported:
            require_object(b,'phonon mode')
            idx=b.get('index')
            if type(idx) is not int or idx not in raw_by_id or idx in rep_by_id: raise ScienceFail('phonon mode indices must be unique raw OUTCAR indices')
            f=number(b.get('frequency_cm-1'),'reported phonon frequency')
            imag=strict_bool(b.get('imaginary'),'reported phonon imaginary flag')
            raw=raw_by_id[idx]
            if abs(raw['frequency_cm-1']-f)>0.002 or raw['imaginary']!=imag: raise ScienceFail('phonons.json modes disagree with signed OUTCAR modes')
            if 'eigenvector_mass_weighted' in b:
                vec=require_list(b['eigenvector_mass_weighted'],'reported mass-weighted eigenvector',6)
                flat=[]
                for atomrow in vec:
                    require_list(atomrow,'reported eigenvector atom row',3)
                    flat.extend(number(x,'reported eigenvector component') for x in atomrow)
                norm=math.sqrt(sum(x*x for x in flat))
                if norm<1e-12: raise ScienceFail('reported eigenvector has zero norm')
                b['_parsed_vector']=[x/norm for x in flat]
            rep_by_id[idx]=b
        raw_sorted=sorted(modes,key=lambda m:m['frequency_cm-1'])
        # All 18 reported frequencies are bound to this run's raw OUTCAR above.
        # Only the independently calibrated Raman branches below receive a
        # numerical Gold comparison; there is no measured universal all-mode bound.
        mapping,center=inverter(coords,species); cls,features=identify(modes,coords,species,mapping)
        # Nondegenerate modes bind up to sign; degenerate doublets bind as
        # projectors so arbitrary orthogonal basis rotations remain equivalent.
        doublet_ids={modes[i]['index'] for branch in ('E2g2','E2g1') for i in cls[branch]}
        for idx,b in rep_by_id.items():
            vec=b.get('_parsed_vector')
            if vec is None or idx in doublet_ids: continue
            rawflat=[x for atomrow in modes[idx-1]['vector'] for x in atomrow]
            raw_norm=math.sqrt(sum(x*x for x in rawflat))
            cosine=sum(x*y/raw_norm for x,y in zip(vec,rawflat))
            if cosine*cosine<.998: raise ScienceFail('reported mass-weighted eigenvector differs from raw mode up to sign')
        for branch in ('E2g2','E2g1'):
            ids0=[modes[i]['index'] for i in cls[branch]]
            if all('_parsed_vector' in rep_by_id[i] for i in ids0):
                rep_modes=[{'vector':[rep_by_id[i]['_parsed_vector'][3*j:3*j+3] for j in range(6)]} for i in ids0]
                ov=subspace_overlap(modes,[i-1 for i in ids0],rep_modes,[0,1])
                if ov<.998: raise ScienceFail('reported degenerate eigenvectors do not span the raw Raman subspace')
        claimed=tracks
        found={}
        for name in ('E2g2','E2g1','A1g'):
            track=claimed.get(name)
            require_list(track,f'{name} branch',4)
            rec=track[n]
            require_object(rec,f'{name} branch record')
            if number(rec.get('pressure_GPa'),f'{name} pressure')!=pressure: raise ScienceFail(f'{name} branch pressure order mismatch')
            ids=rec.get('mode_indices_1_based') if name.startswith('E') else [rec.get('mode_index_1_based')]
            expected_ids=[modes[i]['index'] for i in cls[name]]
            if not isinstance(ids,list) or any(type(x) is not int for x in ids) or sorted(ids)!=sorted(expected_ids): raise ScienceFail(f'{name} labels disagree with raw POSCAR-derived mode character')
            rawfreq=[modes[i]['frequency_cm-1'] for i in cls[name]]
            raw_z=sum(features[i]['z_fraction'] for i in cls[name])/len(cls[name])
            if rec.get('z_polarization_fraction') is not None and abs(number(rec['z_polarization_fraction'],f'{name} z-polarization')-raw_z)>.02:
                raise ScienceFail(f'{name} reported polarization contradicts raw eigenvectors')
            layer_rows=rec.get('layer_symmetry_evidence_by_mode')
            if layer_rows is not None:
                require_list(layer_rows,f'{name} layer symmetry evidence',len(expected_ids))
                for idx,lrow in zip(ids,layer_rows):
                    require_object(lrow,f'{name} layer evidence row')
                    layer_map=lrow.get('layer_Mo_S_in_plane_phase')
                    if layer_map is not None:
                        require_object(layer_map,f'{name} layer phase map')
                        for layer_no,cosine in enumerate(features[idx-1]['mo_s_cosines']):
                            entry=require_object(layer_map.get(str(layer_no)),f'{name} layer {layer_no} phase')
                            if entry.get('Mo_S_in_plane_cosine') is not None and abs(number(entry['Mo_S_in_plane_cosine'],'reported Mo-S phase cosine')-cosine)>.03:
                                raise ScienceFail(f'{name} layer Mo-S phase metadata contradicts raw eigenvector')
                    if lrow.get('interlayer_net_in_plane_cosine') is not None and abs(number(lrow['interlayer_net_in_plane_cosine'],'reported interlayer cosine')-features[idx-1]['interlayer_cosine'])>.03:
                        raise ScienceFail(f'{name} interlayer phase metadata contradicts raw eigenvector')
            evidence=rec.get('inversion_evidence_by_mode') if name.startswith('E') else [rec.get('inversion_evidence')] if rec.get('inversion_evidence') is not None else None
            if evidence is not None:
                require_list(evidence,f'{name} inversion evidence',len(expected_ids))
                for idx,erow in zip(ids,evidence):
                    require_object(erow,f'{name} inversion evidence row')
                    raw_parity=features[idx-1]['parity']; eigenvalue=number(erow.get('polar_vector_inversion_eigenvalue'),'reported inversion eigenvalue')
                    if abs(eigenvalue-raw_parity)>.02: raise ScienceFail(f'{name} inversion metadata contradicts raw POSCAR/eigenvector parity')
                    expected_label='gerade' if raw_parity>0 else 'ungerade'
                    if erow.get('parity')!=expected_label: raise ScienceFail(f'{name} parity label contradicts raw eigenvector')
            value=sum(rawfreq)/len(rawfreq)
            reported_value=number(rec.get('mean_cm-1',rec.get('frequency_cm-1')),f'{name} reported frequency')
            if abs(reported_value-value)>.002: raise ScienceFail(f'{name} branch frequency does not equal raw mode/subspace mean')
            if rec.get('point_group') is not None and rec['point_group']!='D_6h': raise ScienceFail(f'{name} point-group metadata contradicts raw OUTCAR')
            if rec.get('job_id') is not None and rec['job_id']!=job: raise ScienceFail(f'{name} job metadata contradicts phonon point')
            listed_freqs=rec.get('frequencies_cm-1')
            if listed_freqs is not None:
                require_list(listed_freqs,f'{name} listed mode frequencies',len(expected_ids))
                raw_by_idx={m['index']:m['frequency_cm-1'] for m in modes}
                if any(abs(number(v,f'{name} listed frequency')-raw_by_idx[i])>.002 for i,v in zip(ids,listed_freqs)):
                    raise ScienceFail(f'{name} listed frequencies contradict raw mode IDs')
            if name.startswith('E') and rec.get('doublet_splitting_cm-1') is not None:
                split=max(rawfreq)-min(rawfreq)
                if abs(number(rec['doublet_splitting_cm-1'],f'{name} doublet splitting')-split)>.002: raise ScienceFail(f'{name} doublet splitting contradicts raw eigenvalues')
            if name.startswith('E') and rec.get('subspace_overlap_squared_to_0GPa') is not None:
                overlap0=subspace_overlap(parsed[0][2],branch_indices[name][0],modes,cls[name])*2.0 if n>0 else 2.0
                if abs(number(rec['subspace_overlap_squared_to_0GPa'],f'{name} overlap to 0 GPa')-overlap0)>.002: raise ScienceFail(f'{name} reported 2D subspace overlap contradicts raw eigenvectors')
            if name=='A1g' and rec.get('eigenvector_overlap_squared_to_0GPa') is not None:
                overlap0=subspace_overlap(parsed[0][2],branch_indices[name][0],modes,cls[name]) if n>0 else 1.0
                if abs(number(rec['eigenvector_overlap_squared_to_0GPa'],'A1g overlap to 0 GPa')-overlap0)>.002: raise ScienceFail('A1g overlap metadata contradicts raw eigenvector')
            if name=='A1g':
                for key,want in [('Mo_mass_weighted_amplitude',features[cls[name][0]]['mo_total']),('S_mass_weighted_amplitude',features[cls[name][0]]['s_total'])]:
                    if rec.get(key) is not None and abs(number(rec[key],f'A1g {key}')-want)>.02: raise ScienceFail(f'A1g {key} contradicts raw eigenvector')
            target=ref_rm['branches'][name][n]
            tol={'E2g2':.20,'E2g1':.25,'A1g':.25}[name]
            gold_value=number(target['mean_cm-1'] if name.startswith('E') else target['frequency_cm-1'],f'{name} frozen reference')
            if abs(value-gold_value)>tol: raise ScienceFail(f'{name} branch differs from strict reference tolerance')
            found[name]=value
            branch_values[name].append(value)
            branch_indices[name].append(cls[name])
        if abs(number(point.get('PSTRESS_kbar'),'reported PSTRESS')-pstress)>1e-7: raise ScienceFail('reported PSTRESS does not match raw OUTCAR')
        if abs(number(point.get('initial_pressure_residual_GPa_from_external_pressure'),'reported pressure')-ext/10)>0.002: raise ScienceFail('reported residual pressure does not match raw OUTCAR')
        pressure_from_stress=sum(stress)/30.0
        if abs(pressure_from_stress-pressure)>.03: raise ScienceFail('raw initial stress misses the requested fixed pressure state')
        if 'initial_hydrostatic_pressure_GPa_from_stress_trace' in point and abs(number(point['initial_hydrostatic_pressure_GPa_from_stress_trace'],'reported hydrostatic pressure')-pressure_from_stress)>.002:
            raise ScienceFail('phonons hydrostatic pressure metadata contradicts raw stress')
        if 'kpoint_grid' in point and point['kpoint_grid']!=grid: raise ScienceFail('phonons k-point metadata contradicts raw KPOINTS')
        if maxf>.01: raise ScienceFail('raw initial force exceeds the frozen-structure route ceiling')
        if abs(number(point.get('initial_max_force_eV_per_A'),'reported max force')-maxf)>.001: raise ScienceFail('reported initial force does not match raw OUTCAR')
        stress_rows=require_list(point.get('initial_stress_diagonal_kbar'),'reported initial stress',3)
        if any(abs(number(a,'reported stress')-b)>.02 for a,b in zip(stress_rows,stress)): raise ScienceFail('reported anisotropic stress differs from raw OUTCAR')
        parsed.append((runrec,run,modes,coords,species,mapping,stress,ext,maxf,incar))
    overlaps={name:[] for name in branch_values}
    for name,indices in branch_indices.items():
        for n in range(3):
            overlap=subspace_overlap(parsed[n][2],indices[n],parsed[n+1][2],indices[n+1])
            if overlap<.99: raise ScienceFail(f'{name} raw mode projector is discontinuous between adjacent pressure points')
            overlaps[name].append(overlap)
    # Recompute four-point OLS and compare both JSON surfaces and frozen fit/residuals.
    xs=list(PRESSURES); d=rm.get('d_omega_dP'); fits=rm.get('linear_fits')
    require_object(d,'d_omega_dP'); require_object(fits,'linear_fits')
    for name,ys in branch_values.items():
        slope,intercept,res=fit(xs,ys); rf=ref_rm['linear_fits'][name]
        fitrow=require_object(fits.get(name),f'{name} linear fit')
        if abs(number(d.get(name),f'{name} slope')-slope)>.002 or abs(number(fitrow.get('slope_cm-1_per_GPa'),f'{name} fitted slope')-slope)>.002 or abs(number(fitrow.get('intercept_cm-1'),f'{name} fitted intercept')-intercept)>.01: raise ScienceFail(f'{name} OLS slope/intercept was fabricated or miscomputed')
        expected_slope=number(ref_rm['d_omega_dP'][name],f'{name} reference slope')
        if abs(slope-expected_slope)>.10: raise ScienceFail(f'{name} four-point pressure coefficient outside protocol')
        rrows=fitrow.get('residuals')
        require_list(rrows,f'{name} fit residuals',4)
        for k,(got,expected) in enumerate(zip(res,rf['residuals'])):
            row=require_object(rrows[k],f'{name} residual row')
            if number(row.get('pressure_GPa'),f'{name} residual pressure')!=PRESSURES[k] or abs(number(row.get('residual_cm-1'),f'{name} residual')-got)>.01 or abs(got-number(expected['residual_cm-1'],f'{name} reference residual'))>.22: raise ScienceFail(f'{name} four-point residual mismatch')
    # At least one frozen-structure cutoff or kz control is required. A
    # tighter-EDIFF endpoint may be included, but it is optional calibration.
    names=set()
    for control in controls:
        require_object(control,'control record')
        name=control.get('name'); pressure=number(control.get('pressure_GPa'),'control pressure'); job=control.get('job_id')
        if name not in {'encut600-0GPa','kz2-0GPa','ediff1e-11-9GPa'} or name in names: raise ScienceFail('unknown or duplicate control record')
        names.add(name)
        if not isinstance(job,str) or job in seen_jobs or not re.fullmatch(r'\d{1,24}',job): raise ScienceFail('control job IDs must be unique')
        if (number(control.get('ENCUT_eV'),'control ENCUT')!=(600.0 if name=='encut600-0GPa' else 500.0)
            or type(control.get('kz')) is not int or control['kz']!=(2 if name=='kz2-0GPa' else 1)
            or number(control.get('EDIFF_eV'),'control EDIFF')>(1e-11 if name=='ediff1e-11-9GPa' else 1e-10)):
            raise ScienceFail('control typed settings do not match the registered single-variable route')
        seen_jobs.add(job); run=path_beneath(candidate/'engine_io',control.get('directory'))
        for fn in ('OUTCAR','OSZICAR','POSCAR','INCAR','KPOINTS','vasprun.xml','ENGINE.txt','POTCAR.identity.sha256'):
            if (run/fn).is_symlink() or not (run/fn).is_file(): raise ScienceFail(f'control lacks {fn}')
        tags=parse_incar(run/'INCAR'); out=(run/'OUTCAR').read_text(errors='strict')
        want_p=9.0 if name=='ediff1e-11-9GPa' else 0.0
        expected_grid=[12,12,2] if name=='kz2-0GPa' else [12,12,1]
        want_cut=600.0 if name=='encut600-0GPa' else 500.0
        want_ediff=1e-11 if name=='ediff1e-11-9GPa' else 1e-10
        main_ref=parsed[3 if want_p==9 else 0]
        if pressure!=want_p or tags.get('PSTRESS')!=want_p*10 or tags.get('ENCUT')!=want_cut or not isinstance(tags.get('EDIFF'),float) or tags.get('EDIFF')>want_ediff or tags.get('KPAR')!=4 or parse_grid(run/'KPOINTS')!=expected_grid: raise ScienceFail(f'control changed more than its registered single variable or has wrong pressure: {name} p={pressure} tags={tags} grid={parse_grid(run/"KPOINTS")}')
        _,main_dir,_,_,_,_,_,_,_,main_tags=main_ref
        if sha((run/'POSCAR').read_bytes())!=sha((main_dir/'POSCAR').read_bytes()): raise ScienceFail('control changed the frozen POSCAR')
        for key in ('POTIM','NFREE','IBRION','ISIF','ISYM','IVDW','KPAR','PSTRESS'):
            if tags.get(key)!=main_tags.get(key): raise ScienceFail(f'control changed unrelated INCAR parameter {key}')
        if name!='encut600-0GPa' and tags.get('ENCUT')!=main_tags.get('ENCUT'): raise ScienceFail('kz/EDIFF control changed ENCUT')
        if name!='ediff1e-11-9GPa' and tags.get('EDIFF')!=main_tags.get('EDIFF'): raise ScienceFail('cutoff/kz control changed EDIFF')
        if name!='kz2-0GPa' and expected_grid!=parse_grid(main_dir/'KPOINTS'): raise ScienceFail('cutoff/EDIFF control changed k grid')
        verify_effective_tags(out,tags,pressure,expected_grid)
        if len(re.findall(r'aborting loop because EDIFF is reached',out,re.I))!=21 or re.search(r'reached NELM|NELM.*reached',out,re.I): raise ScienceFail('control SCF failed to converge')
        parse_oszicar(run/'OSZICAR',tags['EDIFF'],out); verify_engine_and_paw(run,out,pressure)
        verify_vasprun(run/'vasprun.xml',pressure,tags,expected_grid,out)
    if not names.intersection({'encut600-0GPa','kz2-0GPa'}): raise ScienceFail('a single-variable ENCUT or kz control is required')
    # Candidate artifacts carry the execution provenance; no runner context is read.
    try: execution=execution_contract.verify(candidate,manifest,seen_jobs,_REFS)
    except execution_contract.EvidenceFail as e: raise ScienceFail(str(e)) from e
    # A narrative is checked for required provenance topics; physics is established from raw evidence above.
    text=(candidate/'convergence.md').read_text(errors='strict').lower()
    if not all(term in text for term in ('encut','ediff','control','global','pressure')):
        raise ScienceFail('convergence report omits a required scope/calibration statement')
    return {'status':'PASS','points':4,'modes_per_point':18,'branches':branch_values,'subspace_overlaps':overlaps,'d_omega_dP':d,'job_ids':sorted(seen_jobs),'execution_provenance':execution}

def main():
    app=Path(os.environ.get('APP','/app')); logs=Path(os.environ.get('LOGS','/logs/verifier')); logs.mkdir(parents=True,exist_ok=True)
    try:
        ref_ph,ref_rm=verify_reference(); verify_public_assets(); result=failcheck(app/'final',ref_ph,ref_rm)
        result.update({'status':'PASS','reward':1})
        (logs/'verification.json').write_text(json.dumps(result,sort_keys=True,indent=2)+'\n')
        print('PASS: strict four-pressure DFT/Raman evidence verified')
        return 0
    except ScienceFail as e:
        (logs/'verification.json').write_text(json.dumps({'status':'FAIL','reward':0,'reason':str(e)},sort_keys=True)+'\n')
        print(f'FAIL: {e}')
        return 1
    except InfraError as e:
        (logs/'verification.json').write_text(json.dumps({'status':'ERROR','reason':str(e)},sort_keys=True)+'\n')
        print(f'ERROR: {e}')
        return 2
    except Exception as e:
        (logs/'verification.json').write_text(json.dumps({'status':'ERROR','reason':f'{type(e).__name__}: {e}'},sort_keys=True)+'\n')
        print(f'ERROR: verifier exception: {type(e).__name__}: {e}')
        return 2
if __name__=='__main__': sys.exit(main())
