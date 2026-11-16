#!/usr/bin/env python3
"""Independent, read-only native artifact audit for Case01 submissions.

Candidate files are located through exact relative paths and SHA-256 hashes in
candidate provenance or evaluator-owned execution metadata. No reported
PASS/summary field is trusted.
"""
from __future__ import annotations
import argparse, hashlib, json, math, os, re, subprocess, tempfile
from pathlib import Path
import shlex

def sha256(path: Path) -> str:
    h=hashlib.sha256()
    with path.open('rb') as f:
        for b in iter(lambda:f.read(4*1024*1024), b''): h.update(b)
    return h.hexdigest()

def _artifact(root: Path, obj: dict, label: str) -> Path:
    if not isinstance(obj,dict) or not isinstance(obj.get('path'),str) or not re.fullmatch(r'[0-9a-fA-F]{64}',str(obj.get('sha256',''))):
        raise ValueError(f'{label}: missing exact relative path or SHA-256')
    rel=Path(obj['path'])
    if rel.is_absolute() or any(p in ('..','') for p in rel.parts): raise ValueError(f'{label}: unsafe relative path')
    p=root/rel
    # Reject symlink traversal and paths that resolve outside root.
    cur=root
    for part in rel.parts:
        cur=cur/part
        if cur.is_symlink(): raise ValueError(f'{label}: symlink paths are not accepted')
    if not p.is_file() or not p.resolve().is_relative_to(root.resolve()): raise ValueError(f'{label}: file missing or outside submission root')
    actual=sha256(p)
    if actual.lower()!=obj['sha256'].lower(): raise ValueError(f'{label}: SHA-256 mismatch')
    return p.resolve()

def _store_ancestor_artifact(resolved:dict, role:str, path:Path)->str:
    key='ancestor_'+role
    if key in resolved: raise ValueError(f'duplicate protected ancestor role: {role}')
    resolved[key]=path.resolve()
    return key

def _submission_metadata(root:Path, trusted_receipt:Path|None)->tuple[dict,str]:
    """Locate native files without adding a fourth mandatory public output.

    A candidate may provide final/provenance.json. Otherwise the evaluator's
    protected receipt must identify exact native files. This fallback does not
    establish protocol/science validity: the complete audit still runs.
    """
    p=root/'final/provenance.json'
    if (root/'final').is_symlink() or p.is_symlink(): raise ValueError('unsafe candidate provenance path')
    if p.exists():
        if not p.is_file(): raise ValueError('candidate provenance is not a regular file')
        return json.loads(p.read_text()),'candidate_provenance'
    if trusted_receipt is None: raise ValueError('native artifact metadata is missing from candidate and evaluator receipt')
    receipt=Path(trusted_receipt).absolute(); cur=Path(receipt.anchor)
    for part in receipt.parts[1:]:
        cur=cur/part
        if cur.is_symlink(): raise ValueError('trusted receipt path traverses a symlink')
    if not receipt.is_file() or receipt.resolve().is_relative_to(root.resolve()):
        raise ValueError('native metadata fallback requires an external evaluator-owned receipt')
    rec=json.loads(receipt.read_text())
    if rec.get('schema')!='case01-trusted-execution-receipt-v1': raise ValueError('unsupported evaluator receipt schema')
    src=rec.get('source_files',{}); native={}
    for alias in ('production.tpr','production.xtc','production.edr','production.log','npt.gro','nvt.log','npt.log'):
        item=src.get(alias)
        if not isinstance(item,dict): raise ValueError(f'evaluator receipt lacks native alias {alias}')
        raw=item.get('relative_path',item.get('path'))
        if not isinstance(raw,str): raise ValueError(f'evaluator receipt lacks native path for {alias}')
        path=Path(raw)
        if path.is_absolute():
            try: path=path.relative_to(root.resolve())
            except ValueError: raise ValueError(f'evaluator native path is outside submission: {alias}')
        native[alias]={'path':str(path),'sha256':item.get('sha256')}
    return {'native_source_files':native},'protected_evaluator_receipt'

def _run(args, stdin=None):
    p=subprocess.run(args,input=stdin,text=True,capture_output=True,timeout=1800)
    if p.returncode: raise RuntimeError(f"command failed ({p.returncode}): {' '.join(map(str,args))}: {(p.stderr or p.stdout)[-1200:]}")
    return p.stdout+'\n'+p.stderr

def _near(a,b,tol): return abs(float(a)-float(b))<=tol

def _mdp(path):
    vals={}
    for line in path.read_text(errors='replace').splitlines():
        line=line.split(';',1)[0].strip()
        if '=' in line:
            k,v=line.split('=',1); vals[k.strip().lower().replace('_','-')]=v.strip().lower()
    return vals

def _gro_box(path):
    lines=path.read_text(errors='replace').splitlines()
    if len(lines)<3: raise ValueError(f'invalid GRO file: {path.name}')
    n=int(lines[1].strip()); values=[float(x) for x in lines[-1].split()]
    if len(values)==3: dims=[x*10 for x in values]; angles=[90.,90.,90.]
    elif len(values)==9:
        # GRO triclinic vectors are (v1x,v2y,v3z,v1y,v1z,v2x,v2z,v3x,v3y).
        v1=(values[0],values[3],values[4]); v2=(values[5],values[1],values[6]); v3=(values[7],values[8],values[2])
        import math
        norm=lambda v: math.sqrt(sum(x*x for x in v))
        dims=[norm(v) * 10 for v in (v1,v2,v3)]
        dot=lambda a,b: sum(x*y for x,y in zip(a,b))
        angles=[math.degrees(math.acos(max(-1,min(1,dot(v2,v3)/(norm(v2)*norm(v3)))))),
                 math.degrees(math.acos(max(-1,min(1,dot(v1,v3)/(norm(v1)*norm(v3)))))),
                 math.degrees(math.acos(max(-1,min(1,dot(v1,v2)/(norm(v1)*norm(v2))))))]
    else: raise ValueError(f'unsupported GRO box record ({len(values)} values)')
    return {'atoms':n,'lengths_A':dims,'angles_deg':angles}

def _tpr_settings(text):
    patterns={
      'dt_ps':r'^\s*dt\s*=\s*([\d.eE+-]+)','nsteps':r'^\s*nsteps\s*=\s*(\d+)',
      'tcoupl':r'^\s*tcoupl\s*=\s*(\S+)','ref_t_K':r'^\s*ref-t\s*[:=]\s*([\d.eE+-]+)',
      'tau_t_ps':r'^\s*tau-t\s*[:=]\s*([\d.eE+-]+)','pcoupl':r'^\s*pcoupl\s*=\s*(\S+)',
      'coulombtype':r'^\s*coulombtype\s*=\s*(\S+)','rcoulomb_nm':r'^\s*rcoulomb\s*=\s*([\d.eE+-]+)',
      'rvdw_nm':r'^\s*rvdw\s*=\s*([\d.eE+-]+)','pbc':r'^\s*pbc\s*=\s*(\S+)',
      'vdwtype':r'^\s*vdw-type\s*=\s*(\S+)','vdw_modifier':r'^\s*vdw-modifier\s*=\s*(\S+)',
      'settle':r'functype\[\d+\]=SETTLE,\s*doh=\s*([\d.eE+-]+),\s*dhh=\s*([\d.eE+-]+)',
      'integrator':r'^\s*integrator\s*=\s*(\S+)',
      'ld_seed':r'^\s*ld-seed\s*=\s*(-?\d+)',
      'gen_seed':r'^\s*gen-seed\s*=\s*(-?\d+)',
      'gen_vel':r'^\s*gen-vel\s*=\s*(\S+)'}
    out={}
    for k,pat in patterns.items():
        m=re.search(pat,text,re.M|re.I)
        if m:
            vals=m.groups()
            out[k]=[float(x) for x in vals] if k=='settle' else (float(vals[0]) if k in {'dt_ps','ref_t_K','tau_t_ps','rcoulomb_nm','rvdw_nm'} else int(vals[0]) if k in {'nsteps','ld_seed','gen_seed'} else vals[0])
    return out

def _historical_ancestry_audit(root:Path, archive_info:dict, gmx:str)->dict:
    """Recheck exact 9806 replay sources and the pinned 9136 preparation chain."""
    archive=Path(archive_info['archive_root'])
    collected=archive/'collected'
    ancestry=archive/'ancestry9136'
    checks={}; facts={}; errors=[]
    try:
        # The output's primary native files must be the exact historical raw
        # inputs. This prevents a candidate from changing TPR/XTC/logs and
        # merely updating its own provenance hashes.
        source_map={
            'production.tpr':collected/'production.tpr',
            'production.xtc':archive/'production.xtc',
            'production.edr':collected/'production.edr',
            'production.log':collected/'production.log',
            'nvt.tpr':collected/'nvt.tpr','nvt.edr':collected/'nvt.edr',
            'nvt.gro':collected/'nvt.gro','nvt.cpt':collected/'nvt.cpt',
            'npt.gro':ancestry/'npt.gro','npt.log':ancestry/'npt.log',
            'nvt.log':collected/'nvt.log',
            'nvt.mdp':collected/'nvt.mdp','production.mdp':collected/'production.mdp',
            'npt.mdp':ancestry/'npt.mdp','em.mdp':ancestry/'em.mdp',
            'topol.runtime.top':collected/'topol.runtime.top',
        }
        source_matches={}
        for rel, source in source_map.items():
            candidate=root/rel
            source_matches[rel]=(source.is_file() and candidate.is_file() and
                not source.is_symlink() and not candidate.is_symlink() and
                sha256(source)==sha256(candidate))
        facts['historical_native_source_matches']=source_matches
        checks['historical_native_source_bytes_match']=all(source_matches.values())

        # Verify the 9806 newly generated 200 ps NVT rethermalization and its
        # random stream, then verify the native production handoff used nvt.gro
        # plus nvt.cpt as shown by the protected batch and grompp log.
        nvt_dump=_run([gmx,'dump','-s',str(collected/'nvt.tpr')])
        nvt_settings=_tpr_settings(nvt_dump); facts['9806_nvt_tpr_settings']=nvt_settings
        nvt_mdp=_mdp(collected/'nvt.mdp')
        nvt_log=(collected/'nvt.log').read_text(errors='replace')
        nvt_finished='Finished mdrun' in nvt_log
        nvt_ended=bool(re.search(r'\b100000\s+200\.0{2,}',nvt_log))
        nvt_protocol=(nvt_settings.get('integrator','').lower()=='md' and
            nvt_settings.get('nsteps')==100000 and _near(nvt_settings.get('dt_ps',-1),.002,1e-9) and
            nvt_settings.get('tcoupl','').lower()=='v-rescale' and
            _near(nvt_settings.get('ref_t_K',-1),300,1e-4) and _near(nvt_settings.get('tau_t_ps',-1),.5,1e-5) and
            nvt_settings.get('pcoupl','').lower() in ('no','none') and nvt_settings.get('ld_seed')==20261007 and
            nvt_mdp.get('gen-seed')=='20261007' and nvt_mdp.get('gen-vel')=='yes' and
            nvt_mdp.get('nsteps')=='100000' and float(nvt_mdp.get('dt','nan'))==.002 and
            nvt_mdp.get('ld-seed')=='20261007' and nvt_finished and nvt_ended and
            (collected/'nvt.cpt').is_file() and (collected/'nvt.gro').is_file())
        facts['9806_nvt_log']={'finished':nvt_finished,'ended_at_200ps':nvt_ended}
        checks['9806_nvt_rethermalization_200ps_seed20261007']=bool(nvt_protocol)
        batch=(collected/'run_reference_replicate.sbatch').read_text(errors='replace')
        grompp=(collected/'logs/production-grompp.log').read_text(errors='replace')
        handoff_command='grompp -f production.mdp -c nvt.gro -t nvt.cpt -p topol.runtime.top -o production.tpr' in batch
        handoff_log=('gmx grompp -f production.mdp -c nvt.gro -t nvt.cpt -p topol.runtime.top -o production.tpr' in grompp)
        production_dump=_run([gmx,'dump','-s',str(collected/'production.tpr')])
        prod_settings=_tpr_settings(production_dump); facts['9806_production_tpr_settings']=prod_settings
        prod_mdp=_mdp(collected/'production.mdp')
        prod_handoff=(prod_settings.get('nsteps')==10_000_000 and
            _near(prod_settings.get('dt_ps',-1),.002,1e-9) and
            prod_settings.get('ld_seed')==20261007 and
            prod_mdp.get('ld-seed')=='20261007' and
            prod_mdp.get('gen-vel')=='no' and prod_mdp.get('continuation')=='yes')
        checks['9806_nvt_gro_cpt_to_production_tpr_handoff']=bool(
            handoff_command and handoff_log and prod_handoff and
            'Finished mdrun' in (collected/'production.log').read_text(errors='replace'))
        facts['9806_production_handoff']={'batch_command_present':handoff_command,
            'grompp_log_command_present':handoff_log,'compiled_tpr_matches_rethermalized_stream':bool(prod_handoff)}

        em_log=(ancestry/'preflight-em.log').read_text(errors='replace')
        checks['em_finished']='Finished mdrun' in em_log
        checks['em_converged']='Steepest Descents converged' in em_log
        emdump=_run([gmx,'dump','-s',str(ancestry/'preflight-em.tpr')])
        emset=_tpr_settings(emdump); facts['em_tpr_settings']=emset
        embox=_gro_box(ancestry/'solvated.gro'); facts['initial_gro']=embox
        checks['initial_27099_atom_65A_box']=(embox['atoms']==27099 and
            max(abs(x-65.) for x in embox['lengths_A'])<.01 and
            max(abs(x-90.) for x in embox['angles_deg'])<.01)
        em_match=re.search(r'box\s*\(3x3\):\s*\n\s*box\[\s*0\]=\{\s*([\d.eE+-]+),\s*0',emdump)
        checks['compiled_em_box_6p5nm']=bool(em_match and _near(float(em_match.group(1)),6.5,1e-5))
        checks['em_steepest_descent']=str(emset.get('integrator','')).lower()=='steep'
        stage_facts={}
        for stage in ('nvt','npt'):
            dump=_run([gmx,'dump','-s',str(ancestry/f'{stage}.tpr')])
            settings=_tpr_settings(dump)
            log=(ancestry/f'{stage}.log').read_text(errors='replace')
            end=bool(re.search(r'\b100000\s+200\.0{2,}',log))
            ok=(settings.get('nsteps')==100000 and _near(settings.get('dt_ps',-1),.002,1e-9)
                and str(settings.get('tcoupl','')).lower()=='v-rescale'
                and _near(settings.get('ref_t_K',-1),300,1e-4)
                and _near(settings.get('tau_t_ps',-1),.5,1e-5)
                and 'Finished mdrun' in log and end)
            if stage=='nvt': ok=ok and str(settings.get('pcoupl','')).lower() in ('no','none')
            else:
                refp=re.search(r'ref-p\[\s*0\]=\{\s*([\d.eE+-]+)',dump)
                ok=ok and str(settings.get('pcoupl','')).lower()=='berendsen' and bool(refp and _near(float(refp.group(1)),1.,1e-6))
            stage_facts[stage]={'settings':settings,'log_finished':'Finished mdrun' in log,
                                'log_ended_at_200ps':end,'pass':bool(ok)}
            checks[f'{stage}_ancestry_200ps_protocol']=bool(ok)
        facts['stage_facts']=stage_facts
        manifest=json.loads((ancestry/'equilibration-manifest.json').read_text())
        batch=(ancestry/'run_corrected_case01.sbatch').read_text(errors='replace')+'\n'+(ancestry/'resume_case01_from_npt.sbatch').read_text(errors='replace')
        required=('solvated.gro','topol.runtime.top','preflight-em.tpr','preflight-em.log',
                  'nvt.tpr','nvt.log','npt.tpr','npt.log')
        checks['ancestry_scripts_reference_native_stage_roles']=all(name.split('.')[0] in batch for name in required)
        facts['manifest_schema']=manifest.get('schema')
    except Exception as exc:
        errors.append(f'{type(exc).__name__}: {exc}')
    facts['checks']=checks
    facts['errors']=errors
    facts['status']='PASS' if checks and all(checks.values()) and not errors else 'FAIL'
    return facts

def _tpr_water_lj(dump):
    """Inspect compiled atom identities and the complete compiled LJ type matrix."""
    starts=list(re.finditer(r'^\s*moltype\s*\((\d+)\):',dump,re.M))
    if not starts: return {'pass':False,'reason':'compiled molecule type blocks unavailable'}
    models=[]; otypes=set(); htypes=set()
    for i,st in enumerate(starts):
        end=starts[i+1].start() if i+1<len(starts) else len(dump); chunk=dump[st.start():end]
        block=re.search(r'\n\s*atoms:\s*\n\s*atom \(3\):\s*\n(.*?)(?=\n\s*atom \(3\):)',chunk,re.S)
        if not block: return {'pass':False,'reason':f'moltype {st.group(1)} has no three-atom molecule record'}
        atoms=[]
        for m in re.finditer(r'atom\[\s*\d+\]=\{type=\s*(\d+),\s*typeB=\s*(\d+),\s*ptype=\s*\w+,\s*m=\s*([\d.eE+-]+),\s*q=\s*([\d.eE+-]+).*?atomnumber=\s*(\d+)',block.group(1)):
            atoms.append({'type':int(m.group(1)),'typeB':int(m.group(2)),'mass':float(m.group(3)),'charge':float(m.group(4)),'element':int(m.group(5))})
        oxy=[a for a in atoms if a['element']==8 and _near(a['mass'],15.9994,.002) and _near(a['charge'],-.8476,2e-4)]
        hyd=[a for a in atoms if a['element']==1 and _near(a['mass'],1.008,.002) and _near(a['charge'],.4238,2e-4)]
        identity=(len(atoms)==3 and len(oxy)==1 and len(hyd)==2 and all(a['type']==a['typeB'] for a in atoms))
        models.append({'moltype':int(st.group(1)),'atoms':atoms,'water_identity':identity})
        if len(oxy)==1: otypes.add(oxy[0]['type'])
        htypes.update(a['type'] for a in hyd)
    lj={int(i):(float(c6),float(c12)) for i,c6,c12 in re.findall(r'functype\[(\d+)\]=LJ_SR,\s*c6=\s*([\d.eE+-]+),\s*c12=\s*([\d.eE+-]+)',dump,re.I)}
    atnr_m=re.search(r'\batnr\s*=\s*(\d+)',dump); atnr=int(atnr_m.group(1)) if atnr_m else 0
    def pair(i,j): return lj.get(i*atnr+j)
    oo_terms=[pair(i,j) for i in otypes for j in otypes]
    oh_terms=[pair(i,j) for i in otypes for j in htypes]+[pair(i,j) for i in htypes for j in otypes]
    hh_terms=[pair(i,j) for i in htypes for j in htypes]
    oo=pair(min(otypes),min(otypes)) if otypes else None
    if oo and oo[0]>0 and oo[1]>0:
        sigma=(oo[1]/oo[0])**(1/6); epsilon=oo[0]*oo[0]/(4*oo[1])
    else: sigma=epsilon=float('nan')
    zero=lambda p: p is not None and abs(p[0])<1e-12 and abs(p[1])<1e-12
    o_pass=len(oo_terms)>0 and all(p is not None and p[0]>0 and p[1]>0 and _near((p[1]/p[0])**(1/6),.316557,2e-5) and _near(p[0]**2/(4*p[1]),.650194,2e-5) for p in oo_terms)
    pass_all=all(m['water_identity'] for m in models) and o_pass and all(zero(p) for p in oh_terms+hh_terms) and len(lj)==atnr*atnr
    return {'pass':pass_all,'moltype_count':len(models),'moltypes':models,'oxygen_types':sorted(otypes),'hydrogen_types':sorted(htypes),'lj_matrix_count':len(lj),
            'oo_c6_c12':oo,'oh_c6_c12':oh_terms,'hh_c6_c12':hh_terms,'sigma_nm':sigma,'epsilon_kj_mol':epsilon}

def _tpr_constraint_audit(dump):
    settle_defs=[]
    for m in re.finditer(r'functype\[\d+\]=SETTLE,\s*doh=\s*([\d.eE+-]+),\s*dhh=\s*([\d.eE+-]+)',dump,re.I):
        settle_defs.append(tuple(map(float,m.groups())))
    funcs={}
    for m in re.finditer(r'functype\[(\d+)\]=CONSTR(?:NC)?,([^\n]+)',dump,re.I):
        params=m.group(2); vals=re.search(r'(?:dA|b0|length)\s*=\s*([\d.eE+-]+)',params,re.I); bval=re.search(r'dB\s*=\s*([\d.eE+-]+)',params,re.I)
        if vals: funcs[int(m.group(1))]=(float(vals.group(1)),float(bval.group(1)) if bval else float(vals.group(1)))
    starts=list(re.finditer(r'^\s*moltype\s*\((\d+)\):',dump,re.M))
    if not starts: return {'pass':False,'kind':'unknown','reason':'no compiled moltypes'}
    models=[]; all_ok=True
    for i,st in enumerate(starts):
        chunk=dump[st.start():starts[i+1].start() if i+1<len(starts) else len(dump)]
        atblock=re.search(r'\n\s*atoms:\s*\n\s*atom \(3\):\s*\n(.*?)(?=\n\s*atom \(3\):)',chunk,re.S)
        elems=[]
        if atblock:
            elems=[int(x) for x in re.findall(r'atom\[\s*\d+\]=\{.*?atomnumber=\s*(\d+)',atblock.group(1))]
        settle_sec=re.search(r'^\s*Settle:\s*\n\s*nr:\s*(\d+)\s*\n\s*iatoms:\s*\n(.*?)(?=^\s*[A-Z][^\n]*:\s*$|\Z)',chunk,re.M|re.S)
        settle_used=bool(settle_sec and int(settle_sec.group(1))>0 and re.search(r'\(SETTLE\)',settle_sec.group(2)))
        if settle_used:
            ok=len(settle_defs)>0 and all(_near(a,.1,2e-5) and _near(b,.1633,2e-5) for a,b in settle_defs)
            models.append({'moltype':int(st.group(1)),'kind':'SETTLE','pass':ok})
            all_ok &= ok; continue
        constr_sec=re.search(r'^\s*Constraints?:\s*\n\s*nr:\s*(\d+)\s*\n\s*iatoms:\s*\n(.*?)(?=^\s*[A-Z][^\n]*:\s*$|\Z)',chunk,re.M|re.S)
        rows=[]
        if constr_sec:
            for cm in re.finditer(r'^\s*\d+\s+type=(\d+)\s*\(CONSTR(?:NC)?\)\s+(\d+)\s+(\d+)\s*$',constr_sec.group(2),re.M|re.I):
                rows.append((int(cm.group(1)),int(cm.group(2)),int(cm.group(3))))
        lengths=[]; pairtypes=[]
        for typ,a,b in rows:
            length=funcs.get(typ); pairtypes.append((a,b,length))
            if length is not None:
                el={elems[a],elems[b]} if len(elems)>max(a,b) else set()
                want=.1633 if el=={1} else .1 if el=={1,8} else float('nan')
                lengths.append(_near(length[0],want,2e-5) and _near(length[1],want,2e-5))
            else: lengths.append(False)
        pairs={(min(a,b),max(a,b)) for _,a,b in rows}
        rigid_count=bool(constr_sec and int(constr_sec.group(1)) in (9,))
        ok=(rigid_count and len(rows)==3 and pairs=={(0,1),(0,2),(1,2)} and len(elems)==3 and all(lengths)
            and all(_near(a,.1,2e-5) and _near(b,.1633,2e-5) for a,b in settle_defs))
        models.append({'moltype':int(st.group(1)),'kind':'3-distance-constraints','compiled_nr':int(constr_sec.group(1)) if constr_sec else None,
                       'constraint_pairs':pairtypes,'pass':ok})
        all_ok &= ok
    alg=re.search(r'constraint-algorithm\s*=\s*(\S+)',dump,re.I)
    alg_ok=bool(alg and alg.group(1).lower() in ('lincs','shake'))
    has_settle=any(m['kind']=='SETTLE' for m in models)
    has_lincs=any(m['kind']=='3-distance-constraints' for m in models)
    return {'pass':bool(all_ok and (has_settle or (has_lincs and alg_ok))),
            'kind':'mixed' if has_settle and has_lincs else 'SETTLE' if has_settle else alg.group(1).lower() if alg else 'unknown',
            'constraint_algorithm':alg.group(1).lower() if alg else None,'moltypes':models,'settle_geometry_nm':settle_defs}

def _protected_receipt_file(receipt_path:Path, candidate_root:Path, receipt:dict, role:str)->Path:
    item=receipt.get('source_files',{}).get(role)
    if not isinstance(item,dict) or not re.fullmatch(r'[0-9a-fA-F]{64}',str(item.get('sha256',''))):
        raise ValueError(f'replica controller receipt lacks hashed {role}')
    raw=item.get('relative_path',item.get('path'))
    if not isinstance(raw,str): raise ValueError(f'replica receipt lacks exact relative path for {role}')
    rel=Path(raw)
    if rel.is_absolute() or '..' in rel.parts or not rel.parts: raise ValueError(f'unsafe protected replica path for {role}')
    base=receipt_path.parent.resolve(); p=base/rel; cur=base
    for part in rel.parts:
        cur=cur/part
        if cur.is_symlink(): raise ValueError(f'protected replica symlink is not accepted: {role}')
    resolved=p.resolve()
    if not resolved.is_file() or resolved.is_relative_to(candidate_root.resolve()): raise ValueError(f'protected replica file missing or inside candidate root: {role}')
    if sha256(resolved).lower()!=item['sha256'].lower(): raise ValueError(f'protected replica hash mismatch: {role}')
    if 'size' in item and resolved.stat().st_size!=int(item['size']): raise ValueError(f'protected replica size mismatch: {role}')
    return resolved

def _protected_relative_file(base:Path, raw:str, candidate_root:Path, label:str)->Path:
    """Resolve a protected bundle path without accepting traversal or links."""
    if not isinstance(raw,str): raise ValueError(f'missing protected relative path for {label}')
    rel=Path(raw)
    if rel.is_absolute() or '..' in rel.parts or not rel.parts: raise ValueError(f'unsafe protected relative path for {label}')
    base=base.resolve(); path=base/rel; cur=base
    for part in rel.parts:
        cur=cur/part
        if cur.is_symlink(): raise ValueError(f'protected symlink is not accepted: {label}')
    resolved=path.resolve(strict=True)
    if not resolved.is_file() or resolved.is_relative_to(candidate_root.resolve()):
        raise ValueError(f'protected file missing or inside candidate root: {label}')
    return resolved

def _grompp_handoff(batch:Path,nvt_gro:Path,nvt_cpt:Path,production_mdp:Path,production_tpr:Path|None=None)->dict:
    text=batch.read_text(errors='replace').replace('\\\n',' ')
    found=[]
    for line in text.splitlines():
        try: tokens=shlex.split(line,comments=True)
        except ValueError: continue
        if 'grompp' not in [Path(t).name for t in tokens]: continue
        i=next(j for j,t in enumerate(tokens) if Path(t).name=='grompp'); args=tokens[i+1:]
        opts={}
        j=0
        while j<len(args):
            if args[j] in ('-c','-t','-f','-o') and j+1<len(args): opts[args[j]]=args[j+1]; j+=2
            else: j+=1
        found.append(opts)
    match=next((x for x in found if Path(x.get('-c','')).name==nvt_gro.name and
                Path(x.get('-t','')).name==nvt_cpt.name and Path(x.get('-f','')).name==production_mdp.name and
                (production_tpr is None or Path(x.get('-o','')).name==production_tpr.name)),None)
    return {'grompp_commands':found,'matched_nvt_cpt_handoff':bool(match),'command':match}

def _batch_runs_tpr(batch:Path,tpr:Path)->bool:
    text=batch.read_text(errors='replace').replace('\\\n',' ')
    for line in text.splitlines():
        try: tokens=shlex.split(line,comments=True)
        except ValueError: continue
        names=[Path(t).name for t in tokens]
        if 'mdrun' not in names: continue
        i=names.index('mdrun'); args=tokens[i+1:]
        for j,arg in enumerate(args[:-1]):
            if arg=='-s' and Path(args[j+1]).name==tpr.name: return True
            if arg=='-deffnm' and Path(args[j+1]).name==tpr.stem: return True
    return False

def _registered_seed_binding(receipt:dict, nvt_mdp:dict, production_mdp:dict, nvt_dump:str, production_dump:str)->dict:
    declared=receipt.get('registered_seed')
    if declared is None and isinstance(receipt.get('registered_seeds'),dict):
        declared=receipt['registered_seeds'].get('production')
    try: declared_i=int(declared)
    except (ValueError,TypeError): declared_i=None
    def as_int(value):
        try: return int(value)
        except (ValueError,TypeError): return None
    nvt_gen=as_int(nvt_mdp.get('gen-seed')); nvt_ld=as_int(nvt_mdp.get('ld-seed'))
    prod_ld=as_int(production_mdp.get('ld-seed'))
    nvt_settings=_tpr_settings(nvt_dump); prod_settings=_tpr_settings(production_dump)
    nvt_tpr_ld=nvt_settings.get('ld_seed'); prod_tpr_ld=prod_settings.get('ld_seed')
    values={'replica_nvt_mdp_gen_seed':nvt_gen,'replica_nvt_mdp_ld_seed':nvt_ld,
            'production_mdp_ld_seed':prod_ld,'replica_nvt_tpr_ld_seed':nvt_tpr_ld,
            'production_tpr_ld_seed':prod_tpr_ld}
    available=[v for v in values.values() if v is not None]
    ok=(declared_i is not None and declared_i>0 and nvt_gen==declared_i and nvt_ld==declared_i and prod_ld==declared_i
        and all(v==declared_i for v in available))
    return {'registered_seed':declared_i,**values,'pass':ok}

def _match_replica_production_hashes(receipt:dict, canonical:dict[str,Path])->dict:
    source_files=receipt.get('source_files',{})
    artifact_hashes=receipt.get('production_artifact_hashes',receipt.get('canonical_production_sha256',{}))
    matches={}
    for role in ('production.tpr','production.xtc','production.edr','production.log'):
        alt=role.replace('.','_')
        record=artifact_hashes.get(role,artifact_hashes.get(alt,source_files.get(role,source_files.get(alt)))) if isinstance(artifact_hashes,dict) else source_files.get(role,source_files.get(alt))
        digest=record.get('sha256') if isinstance(record,dict) else record
        path=canonical['production_log'] if role=='production.log' else canonical[role.split('.')[1]]
        matches[role]=isinstance(digest,str) and digest.lower()==sha256(path).lower()
    return matches

def _audit_replica_evidence(root:Path, manifest_path:Path, gmx:str, ancestor_npt_gro:Path|None,
                            canonical:dict[str,Path], expected_job_id:str|None=None)->dict:
    path=Path(manifest_path).absolute()
    if path.is_symlink(): raise ValueError('replica controller receipt may not be a symlink')
    receipt_path=path.resolve()
    if receipt_path.is_relative_to(root.resolve()) or not receipt_path.is_file(): raise ValueError('replica controller receipt must be a readable file outside candidate root')
    receipt=json.loads(receipt_path.read_text())
    if receipt.get('schema') not in ('case01-trusted-replica-evidence-v1','case01-replica-execution-receipt-v1'):
        raise ValueError('unsupported protected replica receipt schema')
    controller_ok=(receipt.get('accounting_verified') is True and receipt.get('job_state')=='COMPLETED'
                   and receipt.get('exit_code')=='0:0' and bool(receipt.get('job_id')))
    roles=('starting_npt_gro','replica_nvt_tpr','replica_nvt_log','replica_nvt_gro','replica_nvt_cpt',
           'replica_batch','replica_nvt_mdp','production_grompp_log','production_mdp',
           )
    resolved={role:_protected_receipt_file(receipt_path,root,receipt,role) for role in roles}
    checks={'controller_accounting':controller_ok,
            'replica_job_matches_primary_receipt':expected_job_id is None or str(receipt.get('job_id'))==str(expected_job_id),
            'ancestor_npt_state_hash':bool(ancestor_npt_gro and sha256(ancestor_npt_gro)==sha256(resolved['starting_npt_gro']))}
    checks['replica_nvt_log_matches_canonical_alias']=sha256(resolved['replica_nvt_log'])==sha256(canonical['nvt_log'])
    nvt_dump=_run([gmx,'dump','-s',str(resolved['replica_nvt_tpr'])]); ns=_tpr_settings(nvt_dump)
    nvt_log=resolved['replica_nvt_log'].read_text(errors='replace')
    finish=bool(re.search(r'Finished mdrun',nvt_log))
    ended=bool(re.search(r'\b100000\s+200\.0{2,}',nvt_log))
    nvt_ok=(ns.get('nsteps')==100000 and _near(ns.get('dt_ps',-1),.002,1e-9)
        and str(ns.get('tcoupl','')).lower()=='v-rescale' and _near(ns.get('ref_t_K',-1),300,1e-4)
        and _near(ns.get('tau_t_ps',-1),.5,1e-5) and str(ns.get('pcoupl','')).lower() in ('no','none')
        and finish and ended)
    checks['replica_nvt_200ps_executed']=nvt_ok
    checks['replica_nvt_finished_200ps']=finish and ended
    nvt_mdp=_mdp(resolved['replica_nvt_mdp']); prod_mdp=_mdp(resolved['production_mdp'])
    checks['replica_nvt_mdp_matches_tpr']=(nvt_mdp.get('integrator')=='md' and int(nvt_mdp.get('nsteps','-1'))==100000
        and _near(float(nvt_mdp.get('dt','nan')),.002,1e-9) and nvt_mdp.get('tcoupl')=='v-rescale'
        and nvt_mdp.get('pcoupl','no') in ('no','none'))
    checks['replica_nvt_batch_executes_compiled_tpr']=_batch_runs_tpr(resolved['replica_batch'],resolved['replica_nvt_tpr'])
    handoff=_grompp_handoff(resolved['replica_batch'],resolved['replica_nvt_gro'],resolved['replica_nvt_cpt'],resolved['production_mdp'],canonical['tpr'])
    checks['production_grompp_uses_replica_nvt_gro_and_cpt']=handoff['matched_nvt_cpt_handoff']
    grompp_log=resolved['production_grompp_log'].read_text(errors='replace')
    checks['production_grompp_log_success']=bool(re.search(r'(Generated|Writing|Successfully)',grompp_log,re.I))
    production_dump=_run([gmx,'dump','-s',str(canonical['tpr'])])
    production_settings=_tpr_settings(production_dump)
    # The controller registers a seed per job; compare it with the submitted
    # NVT velocity seed, NVT stochastic coupling seed, and production coupling seed.
    seed_binding=_registered_seed_binding(receipt,nvt_mdp,prod_mdp,nvt_dump,production_dump)
    checks['registered_seed_matches_tpr_and_mdps']=seed_binding['pass']
    production_ok=(production_settings.get('integrator','').lower()=='md' and production_settings.get('nsteps')==10_000_000
       and _near(production_settings.get('dt_ps',-1),.002,1e-9) and str(production_settings.get('tcoupl','')).lower()=='v-rescale'
       and _near(production_settings.get('ref_t_K',-1),300,1e-4) and _near(production_settings.get('tau_t_ps',-1),.5,1e-5)
       and str(production_settings.get('pcoupl','')).lower() in ('no','none'))
    checks['replica_production_tpr_protocol']=production_ok
    canonical_match=_match_replica_production_hashes(receipt,canonical)
    canonical_match['replica_nvt_log']=sha256(resolved['replica_nvt_log'])==sha256(canonical['nvt_log'])
    checks['replica_production_matches_canonical_submission']=all(canonical_match.values())
    facts={'receipt_schema':receipt.get('schema'),'job_id':receipt.get('job_id'),'replica_batch':str(resolved['replica_batch']),
        'registered_seed_binding':seed_binding,'replica_nvt_settings':ns,
        'replica_nvt_log_finished':finish,'replica_nvt_log_ended_at_200ps':ended,'production_tpr_settings':production_settings,
        'production_grompp_handoff':handoff,'canonical_production_hash_matches':canonical_match,'checks':checks,
        'resolved_artifacts':{k:str(v) for k,v in resolved.items()},'status':'PASS' if all(checks.values()) else 'FAIL'}
    return facts

def audit_native(root: Path, gmx: str='gmx', output: Path|None=None, trusted_execution_receipt: Path|None=None,
                 replica_evidence_manifest: Path|None=None, historical_archive:dict|None=None) -> dict:
    root_arg=Path(root).absolute()
    if root_arg.is_symlink():
        result={'status':'ERROR','errors':['submission root is a symlink'],'native_facts':{},'resolved_artifacts':{}}
        if output: Path(output).write_text(json.dumps(result,indent=2)+'\n')
        return result
    root=root_arg.resolve(); errors=[]; facts={}; resolved={}
    try:
        if historical_archive is not None and trusted_execution_receipt is not None:
            raise ValueError('historical author archive route cannot be combined with a fresh trusted-execution receipt')
        provenance,metadata_origin=_submission_metadata(root,trusted_execution_receipt)
        facts['native_metadata_origin']=metadata_origin
        files=provenance.get('native_source_files',{})
        aliases={'tpr':'production.tpr','xtc':'production.xtc','edr':'production.edr','production_log':'production.log','npt_gro':'npt.gro','nvt_log':'nvt.log','npt_log':'npt.log'}
        for key,alias in aliases.items():
            if alias not in files: raise ValueError(f'provenance lacks native_source_files.{alias}')
            resolved[key]=_artifact(root,files[alias],key)
        # Resolve and verify topology and executed MDPs where declared. Filenames
        # are agent choices; semantic provenance roles are the stable interface.
        pinputs=provenance.get('protocol_input_files',{})
        for role in ('production.mdp','nvt.mdp','npt.mdp','em.mdp'):
            if role in pinputs: resolved[role]=_artifact(root,pinputs[role],role)
        topology=next((v for k,v in pinputs.items() if 'topol' in k.lower() or 'topology' in k.lower()),None)
        if topology: resolved['topology']=_artifact(root,topology,'topology')
        stage_checks={}
        for stage,required in {
          'em.mdp':{'integrator':'steep'},
          'nvt.mdp':{'tcoupl':'v-rescale'},
          'npt.mdp':{'tcoupl':'v-rescale','pcoupl':'berendsen'}
        }.items():
            if stage not in resolved: continue
            m=_mdp(resolved[stage]); dt=float(m.get('dt','nan')); steps=int(m.get('nsteps','-1')) if m.get('nsteps','').isdigit() else -1
            stage_checks[stage]={'parameters_match':all(m.get(k)==v for k,v in required.items()),'duration_ps':dt*steps}
            if stage in ('nvt.mdp','npt.mdp'):
                stage_checks[stage]['duration_match']=abs(dt*steps-200)<=1e-6
            if stage=='npt.mdp': stage_checks[stage]['one_bar']=_near(float(m.get('ref-p','nan')),1,1e-6)
            if stage=='nvt.mdp':
                stage_checks[stage]['target_300K']=_near(float((m.get('ref-t','nan').split()[0])),300,1e-4)
        dump=_run([gmx,'dump','-s',str(resolved['tpr'])])
        settings=_tpr_settings(dump); facts['tpr_settings']=settings
        n_atoms=re.search(r'\bnatoms\s*=\s*(\d+)',dump)
        if n_atoms: facts['atoms']=int(n_atoms.group(1))
        facts['equilibration_input_checks']=stage_checks
        checks={
          'production_duration':settings.get('integrator','').lower()=='md' and settings.get('nsteps')==10_000_000 and _near(settings.get('dt_ps',-1),.002,1e-9),
          'temperature_coupling':str(settings.get('tcoupl','')).lower()=='v-rescale' and _near(settings.get('ref_t_K',-100),300,1e-4) and _near(settings.get('tau_t_ps',-1),.5,1e-5),
          'periodic_spme_cutoffs':str(settings.get('pbc','')).lower()=='xyz' and str(settings.get('coulombtype','')).lower() in ('pme','spme') and _near(settings.get('rvdw_nm',-1),.9,1e-5),
          'potential_shift':str(settings.get('vdw_modifier','')).lower() in ('potential-shift','potential shift'),
          'production_nvt':str(settings.get('pcoupl','')).lower() in ('no','none'),
          'atoms':facts.get('atoms')==27099}
        if stage_checks:
            checks['equilibration_inputs']=all(x.get('parameters_match') and x.get('duration_match',True) and x.get('one_bar',True) and x.get('target_300K',True) for x in stage_checks.values())
        lj_audit=_tpr_water_lj(dump); facts['compiled_water_lj_audit']=lj_audit
        facts['oxygen_lj_sigma_nm']=lj_audit.get('sigma_nm'); facts['oxygen_lj_epsilon_kj_mol']=lj_audit.get('epsilon_kj_mol')
        checks['spce_compiled_atom_types_and_lj_matrix']=lj_audit['pass']
        constraint_audit=_tpr_constraint_audit(dump); facts['compiled_rigid_constraint_audit']=constraint_audit
        # Inspect the native TPR topology with MDAnalysis; reject force-field/name assumptions.
        try:
            import MDAnalysis as mda
            u=mda.Universe(str(resolved['tpr']))
            facts['molecules']=len(u.residues)
            names=u.atoms.names.tolist(); charges=u.atoms.charges
            water=(len(u.atoms)==27099 and len(u.residues)==9033 and len(u.residues[0].atoms)==3 and all(len(r.atoms)==3 for r in u.residues))
            # Atom labels are not protocol requirements: recognize each residue by its one negative O and two positive H charges.
            charge_ok=water and all(sorted(round(float(q),4) for q in r.atoms.charges)==[-.8476,.4238,.4238] and
                       sorted(round(float(m),3) for m in r.atoms.masses)==[1.008,1.008,15.999] for r in u.residues)
            facts['spce_charge_layout_pass']=bool(charge_ok)
            checks['molecule_count_and_charges']=bool(charge_ok)
            checks['rigid_constraint_definition']=constraint_audit['pass']
            # Enumerate non-bonded intramolecular exclusions directly from TPR blocka for strict water sets.
            from MDAnalysis.topology.tpr import utils
            blocks=[]; old=utils.do_blocka
            def capture(data):
                n=data.unpack_int(); total=data.unpack_int(); idx=list(map(int,utils.ndo_int(data,n+1))); ex=list(map(int,utils.ndo_int(data,total))); blocks.append((idx,ex)); return n,total
            utils.do_blocka=capture
            try: mda.Universe(str(resolved['tpr']))
            finally: utils.do_blocka=old
            exclusion=True
            for idx,ex in blocks:
                if len(idx)!=4 or idx[-1]!=len(ex): exclusion=False; break
                rows=[set(ex[idx[i]:idx[i+1]]) for i in range(3)]
                if not all(j in rows[i] for i in range(3) for j in range(3) if i!=j): exclusion=False; break
            # LINCS constrained water has the same required exclusions; geometry is checked via topology bonds/constraints below.
            facts['intramolecular_exclusions_pass']=bool(blocks and exclusion)
            checks['intramolecular_exclusions']=bool(blocks and exclusion)
            # Check topology O LJ values and rigid geometry from bond/constraint records when exposed.
            facts['atom_names_sample']=names[:3]
        except Exception as e:
            checks['molecule_count_and_charges']=False; checks['intramolecular_exclusions']=False
            errors.append('TPR topology inspection failed: '+str(e))
        # Open actual XTC in MDAnalysis, bind its first frame to TPR; inspect every saved time and box.
        try:
            u=mda.Universe(str(resolved['tpr']),str(resolved['xtc']))
            times=[]; boxes=[]; angles=[]; max_geom_error=0.0
            # Residue grouping comes from the native TPR. Identify O/H by mass
            # and charge so no atom-name/order convention is imposed.
            if len(u.residues)==9033:
                groups=[r.atoms.indices for r in u.residues]
                if not all(len(x)==3 for x in groups): raise ValueError('non-three-site molecule in trajectory TPR')
                import numpy as np
                groups=np.asarray(groups,dtype=int)
                masses=u.atoms.masses[groups]; charges=u.atoms.charges[groups]
                oi=np.where((masses>12)&(charges<0))[1]; hs=np.where((masses<2)&(charges>0))
                if len(oi)!=9033 or len(hs[0])!=18066: raise ValueError('cannot identify every water O/H from native mass/charge')
                # Within each residue derive the two hydrogen slots without names.
                oidx=groups[np.arange(9033),oi]
                hmask=(masses<2)&(charges>0); hidx=np.stack([groups[i,np.flatnonzero(hmask[i])] for i in range(9033)])
            else: raise ValueError('native TPR does not contain 9033 three-site waters')
            for ts in u.trajectory:
                times.append(float(ts.time)); boxes.append(tuple(float(x) for x in ts.dimensions[:3])); angles.append(tuple(float(x) for x in ts.dimensions[3:6]))
                pos=ts.positions
                d1=pos[oidx]-pos[hidx[:,0]]; d2=pos[oidx]-pos[hidx[:,1]]; dHH=pos[hidx[:,0]]-pos[hidx[:,1]]
                cell=np.asarray(ts.dimensions[:3]); d1-=np.round(d1/cell)*cell; d2-=np.round(d2/cell)*cell; dHH-=np.round(dHH/cell)*cell
                geom=np.stack((np.linalg.norm(d1,axis=1),np.linalg.norm(d2,axis=1),np.linalg.norm(dHH,axis=1)),axis=1)
                max_geom_error=max(max_geom_error,float(np.max(np.abs(geom-np.asarray([1.,1.,1.633])))))
            facts.update(frame_count=len(times),time_first_ps=times[0],time_last_ps=times[-1],
                         saved_cadence_ps=(times[-1]-times[0])/(len(times)-1) if len(times)>1 else None,
                         box_A=list(boxes[-1]),box_angles_deg=list(angles[-1]))
            diffs=[b-a for a,b in zip(times,times[1:])]
            cadence=sum(diffs)/len(diffs) if diffs else float('nan')
            facts['time_grid_uniform']=bool(diffs and all(x>0 for x in diffs) and all(abs(x-cadence)<=.01 for x in diffs))
            facts['box_constant_orthorhombic']=bool(boxes and all(max(b)-min(b)<1e-3 for b in boxes) and all(max(abs(v-boxes[0][i]) for v in b)<1e-3 for i in range(3) for b in boxes) and all(max(abs(x-90) for x in a)<1e-3 for a in angles))
            checks['trajectory_coverage']=bool(len(times)>=2 and abs(times[0])<=.01 and abs(times[-1]-20000)<=.01 and facts['time_grid_uniform'])
            checks['trajectory_box']=facts['box_constant_orthorhombic']
            densities=[9033*18.01528/6.02214076e23/(a*b*c*1e-24) for a,b,c in boxes]
            facts['density_g_cm3']={'mean':sum(densities)/len(densities),'min':min(densities),'max':max(densities)}
            checks['density_range']=all(.9<=x<=1.1 for x in densities)
            precision=re.search(r'compressed-x-precision\s*=\s*([\d.eE+-]+)',dump)
            prec=float(precision.group(1)) if precision else 0.0
            quant_bound=math.sqrt(3)*(10.0/prec)+1e-4 if prec>0 else None
            facts['max_water_geometry_error_A']=max_geom_error
            facts['xtc_coordinate_rounding_bound_A']=quant_bound
            facts['xtc_compressed_x_precision']=prec or None
            checks['rigid_water_geometry']=bool(quant_bound is not None and max_geom_error<=quant_bound)
        except Exception as e: errors.append('XTC/Tpr trajectory inspection failed: '+str(e)); checks['trajectory_coverage']=checks['trajectory_box']=False
        # Extract temperature from binary EDR with GROMACS and calculate its
        # full-run and half-run means independently from the exported samples.
        try:
            with tempfile.TemporaryDirectory(prefix='case01-native-') as td:
                xv=Path(td)/'temperature.xvg'
                _run([gmx,'energy','-f',str(resolved['edr']),'-o',str(xv),'-b','0','-e','20000'],stdin='Temperature\n0\n')
                values=[]
                for line in xv.read_text().splitlines():
                    line=line.strip()
                    if not line or line.startswith(('#','@')): continue
                    p=line.split()
                    if len(p)>=2: values.append((float(p[0]),float(p[1])))
            if not values: raise ValueError('GROMACS returned no temperature samples')
            et=[t for t,_ in values]
            e_dt=[b-a for a,b in zip(et,et[1:])]
            facts['edr_time_grid']={'first_ps':et[0],'last_ps':et[-1],'records':len(values),
                                    'monotonic':bool(e_dt and all(x>0 for x in e_dt)),
                                    'uniform':bool(e_dt and all(abs(x-sum(e_dt)/len(e_dt))<=.01 for x in e_dt))}
            checks['edr_coverage']=bool(len(values)>=100 and abs(et[0])<=.01 and abs(et[-1]-20000)<=.01 and facts['edr_time_grid']['monotonic'] and facts['edr_time_grid']['uniform'])
            halves=[[v for t,v in values if (t<10000 if i==0 else t>=10000)] for i in range(2)]
            means=[sum(x)/len(x) for x in halves]
            facts['temperature_K']={'mean':sum(v for _,v in values)/len(values),'half_means':means,'samples':len(values)}
            checks['temperature_range']=abs(facts['temperature_K']['mean']-300)<=5
            checks['temperature_half_drift']=abs(means[0]-means[1])<=3
        except Exception as e: errors.append('EDR temperature extraction failed: '+str(e)); checks['edr_coverage']=checks['temperature_range']=checks['temperature_half_drift']=False
        facts['checks']=checks
        # Candidate-supplied resume claims do not prove fresh execution. Only an
        # out-of-root trusted controller/HPC receipt can establish that binding.
        facts['fresh_execution_status']='UNVERIFIED'
        trusted_execution_verified=False
        declared_replica_path=None
        primary_job_id=None
        for name in ('em_completed_and_converged','initial_6p5nm_box','initial_coordinates_6p5nm',
                     'em_nvt_npt_equilibration','nvt_executed_200ps_protocol','npt_executed_200ps_protocol','equilibration_ancestry_chain'):
            checks.setdefault(name,False)
        if trusted_execution_receipt:
            tr=Path(trusted_execution_receipt).resolve()
            if tr.is_relative_to(root): raise ValueError('trusted execution receipt must be outside submission root')
            rec=json.loads(tr.read_text())
            primary_job_id=str(rec.get('job_id')) if rec.get('job_id') is not None else None
            role_to_name={'tpr':'production.tpr','xtc':'production.xtc','edr':'production.edr',
                          'production_log':'production.log','npt_gro':'npt.gro','nvt_log':'nvt.log','npt_log':'npt.log'}
            src=rec.get('source_files',{})
            matches=all(isinstance(src.get(n),dict) and src[n].get('sha256')==sha256(resolved[k])
                        for k,n in role_to_name.items())
            facts['trusted_execution_receipt_match']=matches
            controller_ok=(rec.get('schema')=='case01-trusted-execution-receipt-v1' and rec.get('accounting_verified') is True
                           and rec.get('job_state')=='COMPLETED' and rec.get('exit_code')=='0:0'
                           and float(rec.get('production_length_ns',0))>=20 and bool(rec.get('job_id')))
            facts['trusted_execution_receipt_controller_checks']=controller_ok
            # Supplementary equilibration files are retrieved from the protected
            # evaluator evidence bundle, whose manifest and per-file hashes are
            # controller generated; candidate paths cannot redirect these reads.
            manifest_ref=rec.get('equilibration_evidence_manifest')
            if manifest_ref:
                project_root=tr.parents[2]
                manifest_path=_protected_relative_file(project_root,manifest_ref,root,'equilibration manifest')
                em=json.loads(manifest_path.read_text())
                if em.get('schema')!='case01-obtained-equilibration-evidence-v1': raise ValueError('untrusted equilibration manifest schema')
                supplemental=em.get('files',{})
                for role in ('em_tpr','em_log','em_gro','em_edr','nvt_tpr','nvt_gro','nvt_log','npt_tpr','npt_gro','npt_log','initial_gro','initial_topology','initial_batch'):
                    info=supplemental.get(role); rec_info=src.get(role)
                    if not isinstance(info,dict) or not isinstance(rec_info,dict) or info.get('sha256')!=rec_info.get('sha256'):
                        raise ValueError(f'protected execution receipt lacks matching {role} evidence')
                    ep=_protected_relative_file(manifest_path.parent,info.get('relative_path'),root,role)
                    if sha256(ep)!=info['sha256']: raise ValueError(f'protected evidence hash mismatch for {role}')
                    _store_ancestor_artifact(resolved,role,ep)
                if 'resume_batch' in supplemental and 'resume_batch' in src:
                    info=supplemental['resume_batch']; rec_info=src['resume_batch']
                    if info.get('sha256')!=rec_info.get('sha256'): raise ValueError('invalid protected resume batch evidence')
                    ep=_protected_relative_file(manifest_path.parent,info.get('relative_path'),root,'resume_batch')
                    if sha256(ep)!=info['sha256']: raise ValueError('protected resume batch hash mismatch')
                    _store_ancestor_artifact(resolved,'resume_batch',ep)
                # Both logs and executed stage TPRs must substantiate the three
                # equilibration stages. EM uses a steepest-descent convergence
                # record; NVT/NPT expose actual inputrec settings and end times.
                emlog=resolved['ancestor_em_log'].read_text(errors='replace')
                facts['em_execution']={'finished':('Finished mdrun' in emlog),'converged':('Steepest Descents converged' in emlog),
                                       'settle_warning_present':('cannot be settled' in emlog or 'can not be settled' in emlog)}
                facts['em_execution']['converged_steps']=int(re.search(r'Steepest Descents converged to Fmax < \S+ in (\d+) steps',emlog).group(1)) if re.search(r'Steepest Descents converged to Fmax < \S+ in (\d+) steps',emlog) else None
                checks['em_completed_and_converged']=facts['em_execution']['finished'] and facts['em_execution']['converged']
                emdump=_run([gmx,'dump','-s',str(resolved['ancestor_em_tpr'])]); initial_box=re.search(r'box \(3x3\):\s*\n\s*box\[\s*0\]=\{\s*([\d.eE+-]+),\s*0',emdump)
                facts['initial_box_nm']=float(initial_box.group(1)) if initial_box else None
                checks['initial_6p5nm_box']=bool(initial_box and _near(float(initial_box.group(1)),6.5,1e-5))
                initial_gro=_gro_box(resolved['ancestor_initial_gro']); facts['initial_gro']=initial_gro
                checks['initial_coordinates_6p5nm']=initial_gro['atoms']==27099 and max(abs(x-65) for x in initial_gro['lengths_A'])<.01 and max(abs(x-90) for x in initial_gro['angles_deg'])<.01
                checks['initial_box_nm']=checks['initial_6p5nm_box'] and checks['initial_coordinates_6p5nm']
                stage_facts={}
                for stage in ('nvt','npt'):
                    dump_stage=_run([gmx,'dump','-s',str(resolved['ancestor_'+stage+'_tpr'])]); sett=_tpr_settings(dump_stage)
                    log=resolved['ancestor_'+stage+'_log'].read_text(errors='replace'); sset=_tpr_settings(log)
                    stage_facts[stage]={'settings':sett,'log_finished':'Finished mdrun' in log,
                        'log_ended_at_200ps':bool(re.search(r'\b100000\s+200\.0{2,}',log))}
                    stage_ok=(sett.get('nsteps')==100000 and _near(sett.get('dt_ps',-1),.002,1e-9)
                        and str(sett.get('tcoupl','')).lower()=='v-rescale' and _near(sett.get('ref_t_K',-1),300,1e-4)
                        and _near(sett.get('tau_t_ps',-1),.5,1e-5) and stage_facts[stage]['log_finished'] and stage_facts[stage]['log_ended_at_200ps'])
                    if stage=='nvt': stage_ok=stage_ok and str(sett.get('pcoupl','')).lower() in ('no','none')
                    else:
                        refp=re.search(r'ref-p\[\s*0\]=\{\s*([\d.eE+-]+)',dump_stage)
                        stage_ok=stage_ok and str(sett.get('pcoupl','')).lower()=='berendsen' and bool(refp and _near(float(refp.group(1)),1,1e-6))
                    checks[stage+'_executed_200ps_protocol']=stage_ok
                facts['equilibration_execution']=stage_facts
                scripts=[resolved['ancestor_initial_batch'].read_text(errors='replace')]
                if 'ancestor_resume_batch' in resolved: scripts.append(resolved['ancestor_resume_batch'].read_text(errors='replace'))
                script_text='\n'.join(scripts)
                roles=('initial_gro','initial_topology','em_tpr','em_log','em_gro','nvt_tpr','nvt_log','nvt_gro','npt_tpr','npt_log','npt_gro')
                referenced={role:(Path(rec['source_files'][role]['relative_path']).name.split('.')[0] in script_text if rec['source_files'].get(role,{}).get('relative_path') else False) for role in roles}
                for name in ('production.tpr','production.xtc','production.edr','production.log'):
                    item=src.get(name,{})
                    referenced[name]=Path(item.get('relative_path',item.get('path',''))).name.split('.')[0] in script_text if item.get('relative_path') or item.get('path') else False
                # A single-job workflow is valid; the controller receipt binds
                # the fresh job, and the actual stage TPRs/logs plus run script
                # references establish input/state handoffs without a resume id.
                facts['batch_lineage']={'role_stems_referenced':referenced,'resume_script_present':'ancestor_resume_batch' in resolved}
                checks['equilibration_ancestry_chain']=bool(rec.get('job_id') and all(referenced.values()))
                checks['em_nvt_npt_equilibration']=checks['em_completed_and_converged'] and checks['nvt_executed_200ps_protocol'] and checks['npt_executed_200ps_protocol'] and checks['equilibration_ancestry_chain']
            else:
                checks['em_nvt_npt_equilibration']=False; errors.append('protected equilibration evidence manifest is missing')
            replica_ref=rec.get('replica_evidence_manifest')
            if replica_ref:
                rel=Path(replica_ref)
                if rel.is_absolute() or '..' in rel.parts or not rel.parts: raise ValueError('unsafe protected replica manifest reference')
                project_root=tr.parents[2].resolve(); candidate_manifest=project_root/rel; cur=project_root
                for part in rel.parts:
                    cur=cur/part
                    if cur.is_symlink(): raise ValueError('protected replica manifest may not traverse symlinks')
                declared_replica_path=candidate_manifest.resolve()
                if not declared_replica_path.is_relative_to(project_root): raise ValueError('protected replica manifest escapes the evaluator evidence root')
                expected_sha=rec.get('replica_evidence_manifest_sha256')
                if not isinstance(expected_sha,str) or not re.fullmatch(r'[0-9a-fA-F]{64}',expected_sha): raise ValueError('main trusted receipt lacks replica manifest SHA-256')
                if declared_replica_path.is_symlink() or not declared_replica_path.is_file() or sha256(declared_replica_path).lower()!=expected_sha.lower():
                    raise ValueError('protected replica manifest reference/hash mismatch')
            trusted_execution_verified=matches and controller_ok
            facts['trusted_execution_receipt_match']=matches
        if declared_replica_path is not None:
            if replica_evidence_manifest is not None and Path(replica_evidence_manifest).resolve()!=declared_replica_path:
                raise ValueError('explicit replica manifest differs from the controller receipt reference')
            replica_evidence_manifest=declared_replica_path
        ancestor_nvt_log=resolved.get('ancestor_nvt_log')
        nvt_log_changed=bool(ancestor_nvt_log and sha256(resolved['nvt_log'])!=sha256(ancestor_nvt_log))
        facts['candidate_nvt_log_differs_from_ancestral_nvt_log']=nvt_log_changed
        if nvt_log_changed:
            checks['replica_nvt_reexecution_evidence_present']=bool(replica_evidence_manifest)
        replica_verified=False
        if replica_evidence_manifest:
            replica_facts=_audit_replica_evidence(root,Path(replica_evidence_manifest),gmx,resolved.get('ancestor_npt_gro'),
                {'tpr':resolved['tpr'],'xtc':resolved['xtc'],'edr':resolved['edr'],'production_log':resolved['production_log'],'nvt_log':resolved['nvt_log']},
                expected_job_id=primary_job_id)
            facts['replica_execution']=replica_facts
            checks['replica_execution']=replica_facts['status']=='PASS'
            replica_verified=checks['replica_execution']
        if historical_archive is not None:
            ancestry_audit=_historical_ancestry_audit(root,historical_archive,gmx)
            facts['historical_ancestry_audit']=ancestry_audit
            facts['fresh_execution_status']='NOT_APPLICABLE_HISTORICAL_REFERENCE'
            facts['historical_archive_status']='VERIFIED'
            facts['historical_reference_job_id']='9806'
            facts['agent_reward']=None
            facts['agent_fresh']=False
            hc=ancestry_audit.get('checks',{})
            checks['em_completed_and_converged']=bool(hc.get('em_finished') and hc.get('em_converged'))
            checks['initial_6p5nm_box']=bool(hc.get('compiled_em_box_6p5nm'))
            checks['initial_coordinates_6p5nm']=bool(hc.get('initial_27099_atom_65A_box'))
            checks['nvt_executed_200ps_protocol']=bool(hc.get('9806_nvt_rethermalization_200ps_seed20261007'))
            checks['npt_executed_200ps_protocol']=bool(hc.get('npt_ancestry_200ps_protocol'))
            checks['equilibration_ancestry_chain']=bool(hc.get('ancestry_scripts_reference_native_stage_roles') and
                                                       hc.get('historical_native_source_bytes_match') and
                                                       hc.get('9806_nvt_gro_cpt_to_production_tpr_handoff'))
            checks['em_nvt_npt_equilibration']=bool(checks['em_completed_and_converged'] and
                checks['initial_6p5nm_box'] and checks['initial_coordinates_6p5nm'] and
                checks['nvt_executed_200ps_protocol'] and checks['npt_executed_200ps_protocol'] and
                checks['equilibration_ancestry_chain'])
            facts['fresh_execution_checks_status']='NOT_APPLICABLE_HISTORICAL_AUTHOR_REFERENCE'
            checks.pop('replica_nvt_reexecution_evidence_present',None)
            checks.pop('replica_execution',None)
            if ancestry_audit['status']!='PASS': errors.append('protected 9136 historical ancestry audit failed')
        else:
            facts['fresh_execution_status']='VERIFIED' if (trusted_execution_verified or replica_verified) else 'FAILED'
            if facts['fresh_execution_status']!='VERIFIED': errors.append('fresh production execution is not established by trusted external receipt')
        if not all(type(value) is bool for value in checks.values()):
            errors.append('native audit check map contains a non-boolean status')
        errors.extend(k+' failed' for k,v in checks.items() if v is False)
        facts['checks']=checks
        result={'status':'ERROR' if any('failed:' in e or 'inspection failed' in e for e in errors) else ('FAIL' if errors else 'PASS'), 'errors':errors,'native_facts':facts,'resolved_artifacts':{k:str(v) for k,v in resolved.items()}}
    except Exception as e:
        result={'status':'ERROR','errors':[str(e)],'native_facts':facts,'resolved_artifacts':{k:str(v) for k,v in resolved.items()}}
    if output:
        Path(output).parent.mkdir(parents=True,exist_ok=True); Path(output).write_text(json.dumps(result,indent=2)+'\n')
    return result

if __name__=='__main__':
    ap=argparse.ArgumentParser(); ap.add_argument('root',type=Path); ap.add_argument('--gmx',default='gmx'); ap.add_argument('--output',type=Path); ap.add_argument('--trusted-execution-receipt',type=Path); ap.add_argument('--replica-evidence-manifest',type=Path)
    a=ap.parse_args(); r=audit_native(a.root,a.gmx,a.output,a.trusted_execution_receipt,a.replica_evidence_manifest); print(json.dumps(r,indent=2)); raise SystemExit(0 if r['status']=='PASS' else 2)
