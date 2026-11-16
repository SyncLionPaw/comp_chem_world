#!/usr/bin/env python3
# L1 Deliverables: Check required deliverables for completeness and parseability (including audit.json, decision.md).
# L2 Execution: Check the use of supplied data or archived evidence where required.
# L3 Science: Audit historical CP2K, prediction, and execution records without launching new calculations.
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

def _make_case44_science():
    #!/usr/bin/env python3
    """Private verifier: independently reparses raw CP2K and recomputes audit values."""
    import hashlib,json,math,re,sys,os
    from pathlib import Path
    import numpy as np

    APP=Path(os.environ.get('APP','/app')).resolve(); AUDIT=APP/'audit.json'
    TESTS=Path(os.environ.get('TESTS','/tests')).resolve(); LOGS=Path(os.environ.get('LOGS','/logs/verifier')).resolve()
    NUMERIC_REFS=json.loads((TESTS/'refs.json').read_text())
    TH=NUMERIC_REFS['ensemble_hit_force_component_rmse_eV_A']
    H2EV=NUMERIC_REFS['hartree_to_eV']; F2EVA=H2EV/NUMERIC_REFS['bohr_to_Angstrom']

    def close(actual, expected, abs_tol=NUMERIC_REFS['absolute_tolerance'], rel_tol=NUMERIC_REFS['relative_tolerance']):
     try:
      a=float(actual); e=float(expected)
      return math.isfinite(a) and math.isfinite(e) and math.isclose(a,e,abs_tol=abs_tol,rel_tol=rel_tol)
     except (TypeError,ValueError,OverflowError): return False

    def same_cp2k_settings(left, right):
        """Compare native settings, accepting only the documented D3 synonym."""
        if not isinstance(left, dict) or not isinstance(right, dict) or set(left) != set(right):
            return False
        aliases = {"DFTD3": "DFTD3", "D3 ZERO DAMPING": "DFTD3"}
        normalized = []
        for setting in (left, right):
            copy = dict(setting)
            value = copy.get("dispersion")
            if not isinstance(value, str):
                return False
            token = " ".join(value.upper().split())
            copy["dispersion"] = aliases.get(token, token)
            normalized.append(copy)
        return normalized[0] == normalized[1]


    def parse_input(path, xyz):
     text=path.read_text(errors='strict')
     def one(pattern, cast=str):
      found=re.findall(pattern,text,re.I|re.M)
      if len(found)!=1: raise ValueError(f'{path.name}: expected one match for {pattern}')
      return cast(found[0])
     cell=re.search(r'&CELL\b(.*?)&END\s+CELL',text,re.I|re.S)
     if not cell: raise ValueError(f'{path.name}: missing unique CELL block')
     vec={}
     for axis in ('A','B','C'):
      rows=re.findall(r'^\s*'+axis+r'\s+([-+0-9.eEdD]+)\s+([-+0-9.eEdD]+)\s+([-+0-9.eEdD]+)\s*$',cell.group(1),re.I|re.M)
      if len(rows)!=1: raise ValueError(f'{path.name}: invalid CELL {axis}')
      vec[axis]=[float(x.replace('D','E').replace('d','e')) for x in rows[0]]
     xc=re.search(r'&XC_FUNCTIONAL\s+([A-Za-z0-9_-]+)',text,re.I)
     vdW=re.search(r'&PAIR_POTENTIAL\s+(.*?)&END\s+PAIR_POTENTIAL',text,re.I|re.S)
     if not xc or not vdW: raise ValueError(f'{path.name}: XC/dispersion method not parseable')
     dispersion=re.search(r'^\s*TYPE\s+(\S+)',vdW.group(1),re.I|re.M)
     ref=re.search(r'^\s*REFERENCE_FUNCTIONAL\s+(\S+)',vdW.group(1),re.I|re.M)
     inc=one(r'^\s*@INCLUDE\s+(\S+)\s*$')
     coord=path.parent/inc
     if not coord.is_file() or coord.resolve().parent!=path.parent.resolve(): raise ValueError(f'{path.name}: coordinate include missing or escapes attempt directory')
     xyz_lines=[x.split() for x in xyz.read_text().splitlines()[2:] if x.split()]
     coords=[[float(x) for x in row[1:4]] for row in xyz_lines]
     return {'method':one(r'^\s*METHOD\s+(Quickstep)\s*$'), 'xc_functional':xc.group(1).upper(),
      'dispersion':dispersion.group(1).upper() if dispersion else None,'dispersion_reference':ref.group(1).upper() if ref else None,
      'cutoff_Ry':one(r'^\s* CUTOFF\s+(\S+)\s*$',float),'rel_cutoff_Ry':one(r'^\s* REL_CUTOFF\s+(\S+)\s*$',float),
      'eps_scf':one(r'^\s* EPS_SCF\s+(\S+)\s*$',float),'max_scf':one(r'^\s* MAX_SCF\s+(\d+)\s*$',int),
      'cell_vectors_A':vec,'periodic':'XYZ' if re.search(r'^\s*PERIODIC\s+XYZ\s*$',text,re.I|re.M) else 'other',
      'coordinate_include_sha256':sha(coord),'ordered_coordinate_sha256':sha(xyz),'atom_count':len(coords)}

    def scheduler_receipt(path):
     files=sorted(path.glob('slurm-sacct*.txt'))
     if not files:return None
     lines=[x.strip() for x in files[0].read_text(errors='replace').splitlines() if x.strip()]
     if len(lines)<2:return {'receipt':files[0].name,'status':'unparsed'}
     header,row=lines[0].split('|'),lines[1].split('|')
     if len(header)!=len(row):return {'receipt':files[0].name,'status':'unparsed'}
     data=dict(zip(header,row))
     return {'receipt':files[0].name,'state':data.get('State'),'exit_code':data.get('ExitCode')}

    def workflow_scheduler_matches(actual, aid, population, attempt_path, operator_events, science_events):
     if population=='original_v1':
      return actual==scheduler_receipt(attempt_path)
     if population!='later_v2' or not isinstance(actual,dict) or 'state' not in actual:return False
     if set(actual)-{'state','exit_code','receipt'}:return False
     attempt_events=[event for event in operator_events if event.get('attempt_id')==aid]
     observed=[event for event in attempt_events if event.get('scheduler_state') not in (None,'') or event.get('scheduler_exit_code') not in (None,'')]
     source=observed[-1] if observed else None
     expected_state=(source.get('scheduler_state') or 'not_recorded_in_terminal_projection') if source else 'not_recorded_in_terminal_projection'
     expected_exit=source.get('scheduler_exit_code') if source else None
     if actual.get('state')!=expected_state:return False
     if expected_exit is not None:
      if actual.get('exit_code')!=expected_exit:return False
     elif source is not None:
      if 'exit_code' in actual:return False
     elif actual.get('exit_code') not in (None,'unknown'):
      return False
     if 'receipt' not in actual:return True
     receipt=actual['receipt']
     if not isinstance(receipt,str):return False
     match=re.fullmatch(r'([^#\s]+)#(seq=?[0-9]+|[A-Za-z][A-Za-z0-9_-]*)(?:\s+.*)?',receipt)
     if not match:return False
     source_name,locator=match.groups()
     allowed_sources={
      'v2-operator-budget-events-public.jsonl',
      'inputs/ledgers/v2-operator-budget-events-public.jsonl',
      'v2-attempt-events-public.jsonl',
      'inputs/ledgers/v2-attempt-events-public.jsonl',
     }
     if source_name not in allowed_sources:return False
     operator_source=source_name.endswith('v2-operator-budget-events-public.jsonl')
     if operator_source:
      seq_locator=re.fullmatch(r'seq=?([0-9]+)',locator)
      if seq_locator:
       matches=[event for event in attempt_events if event.get('seq')==int(seq_locator.group(1))]
      else:
       matches=[event for event in attempt_events if event.get('event')==locator]
      if len(matches)!=1:return False
      event=matches[0]
      if source is not None:return event is source
      if not seq_locator and not locator.endswith('TERMINAL') and 'TERMINAL_' not in locator and locator!='FINISH':return False
      return event.get('scheduler_state') in (None,'') and event.get('scheduler_exit_code') in (None,'')
     science_matches=[event for event in science_events if event.get('attempt_id')==aid and event.get('event')==locator]
     if len(science_matches)!=1 or locator!='FINISH' or source is not None:return False
     return science_matches[0].get('scheduler_state') in (None,'') and science_matches[0].get('scheduler_exit_code') in (None,'')

    def sha(p):
     h=hashlib.sha256()
     with p.open('rb') as f:
      for b in iter(lambda:f.read(1<<20),b''):h.update(b)
     return h.hexdigest()

    def geometry_hash(xyz):
     return hashlib.sha256(('\n'.join(x.strip() for x in xyz.read_text().splitlines()[2:])+'\n').encode()).hexdigest()

    def native_identity_valid(row, aid, attempt, xyz):
     result=attempt['result']
     expected_status='native_valid' if result is not None else 'native_failed_or_unusable'
     if row.get('native_status')!=expected_status:return False
     if result is not None:
      if row.get('geometry_hash')!=result['g']:return False
     elif row.get('geometry_hash') not in (None,geometry_hash(xyz)):
      return False
     return row.get('population')==('original_v1' if aid.startswith('L') or aid.startswith('R') else 'later_v2')

    def pair_eligibility(left, right):
     native_valid=left['result'] is not None and right['result'] is not None
     process_verified=native_valid and left['process']=='verified_success' and right['process']=='verified_success'
     return native_valid,process_verified

    def geometry_hashes_valid(actual, left_hash, right_hash, unique_count):
     if not isinstance(actual,list) or len(actual) not in (1,2) or any(not isinstance(value,str) for value in actual):return False
     if not isinstance(unique_count,int) or isinstance(unique_count,bool):return False
     expected={left_hash,right_hash}
     return set(actual)==expected and unique_count==len(expected)

    def counted_hit_flag_valid(value, eligible, hit):
     if not isinstance(value,bool):return False
     return value is eligible or value is (eligible and hit)

    def evidence_references_cover(actual, expected):
     # Required scientific bindings must be present; extra citations and order
     # do not change facts already checked against the native records.
     return isinstance(actual,list) and all(isinstance(item,str) and item.strip() for item in actual) and set(actual).issuperset(expected)

    def summary_row_eligible(expected_frame):
     return expected_frame.get('native_status')=='native_valid' and expected_frame.get('process_status')=='verified_success'

    def eligible_summary_frames(candidate_frames, expected_frames):
     return [(candidate,expected) for candidate,expected in zip(candidate_frames,expected_frames) if summary_row_eligible(expected)]

    def fail(msg):
     print(json.dumps({'status':'FAIL','reason':msg}));raise SystemExit(1)

    def reject_constant(value):
     raise ValueError('non-standard JSON numeric constant: '+value)

    def validate_schema(value, schema, path='$'):
     expected=schema.get('type')
     expected_types=expected if isinstance(expected,list) else [expected]
     def matches(kind):
      return {'object':lambda:isinstance(value,dict),'array':lambda:isinstance(value,list),'string':lambda:isinstance(value,str),
              'boolean':lambda:isinstance(value,bool),'integer':lambda:isinstance(value,int) and not isinstance(value,bool),
              'number':lambda:isinstance(value,(int,float)) and not isinstance(value,bool),'null':lambda:value is None}[kind]()
     if expected and not any(matches(kind) for kind in expected_types):raise ValueError(f'{path}: expected type {expected}')
     if 'enum' in schema and value not in schema['enum']:raise ValueError(f'{path}: value outside public enum')
     if isinstance(value,dict):
      absent=set(schema.get('required',[]))-set(value)
      if absent:raise ValueError(f'{path}: missing required fields {sorted(absent)}')
      if len(value)<schema.get('minProperties',0):raise ValueError(f'{path}: too few object properties')
      props=schema.get('properties',{})
      for key,child in value.items():
       if key in props:validate_schema(child,props[key],path+'.'+key)
       elif isinstance(schema.get('additionalProperties'),dict):validate_schema(child,schema['additionalProperties'],path+'.'+key)
     elif isinstance(value,list):
      if len(value)<schema.get('minItems',0) or ('maxItems' in schema and len(value)>schema['maxItems']):raise ValueError(f'{path}: array length outside public schema')
      for i,child in enumerate(value):validate_schema(child,schema.get('items',{}),f'{path}[{i}]')

    def finite_tree(value,path='$'):
     if isinstance(value,bool) or value is None:return
     if isinstance(value,(int,float)):
      if not math.isfinite(float(value)):raise ValueError(f'{path}: non-finite number')
     elif isinstance(value,dict):
      for key,child in value.items():finite_tree(child,f'{path}.{key}')
     elif isinstance(value,list):
      for i,child in enumerate(value):finite_tree(child,f'{path}[{i}]')

    def parse_native(log,xyz):
     text=log.read_text(errors='replace'); atoms=[x.split()[0] for x in xyz.read_text().splitlines()[2:] if x.split()]
     es=re.findall(r'^\s*ENERGY\|\s+Total FORCE_EVAL\s*\(\s*QS\s*\)\s+energy\s+\[a\.u\.\]\s*:\s*([^\s]+)',text,re.M)
     if len(es)!=1 or text.count('ATOMIC FORCES in [a.u.]')!=1 or text.count('SCF run converged')!=1 or text.count('PROGRAM ENDED AT')!=1 or re.search(r'SCF run NOT converged|ABORT|FATAL ERROR',text,re.I):return None
     rows=[]; tail=text.split('ATOMIC FORCES in [a.u.]',1)[1].splitlines()[1:]
     for line in tail:
      f=line.split()
      if len(f)>=6 and f[0].isdigit() and f[1].isdigit():
       try: rows.append((int(f[0]),f[2],*[float(v) for v in f[3:6]]))
       except ValueError:return None
       if len(rows)>304:return None
      elif rows:break
     if len(rows)!=304 or [x[0] for x in rows]!=list(range(1,305)) or [x[1] for x in rows]!=atoms:return None
     fs=np.asarray([x[2:] for x in rows])*F2EVA
     return {'e':float(es[0])*H2EV,'f':fs,'elements':atoms,'g':geometry_hash(xyz)}

    def pair(a,b):
     d=b['f']-a['f']; return [abs(b['e']-a['e'])/304,float(np.sqrt(np.mean(d*d))),float(np.max(np.linalg.norm(d,axis=1))) ]

    def decision_from_evidence(rows, verified_frames, cross_setting_geometry_count, policy=None):
     policy=policy or {'eligibility':{'valid':True,'process_verified':True,'settings_differ':True},
      'local_finding':{'if_any_eligible_pair_fails_any_numeric_gate':'REFERENCE_SENSITIVE','otherwise':'NO_COUNTEREXAMPLE'},
      'sufficiency':{'no_eligible_pair_gate_failure':True,'minimum_eligible_pairs':2,'minimum_process_verified_selected_labels':20,'minimum_distinct_geometry_hashes_among_eligible_pair_endpoints':2,'otherwise':'INSUFFICIENT_EVIDENCE','if_all_satisfied':'REFERENCE_ADEQUATE'},
      'numeric_gate_fields':['energy_abs_eV_per_atom','force_component_rmse_eV_A','max_atom_force_vector_delta_eV_A']}
     eligibility=policy['eligibility'];local_rule=policy['local_finding'];sufficient_rule=policy['sufficiency']
     cross=[r for r in rows if all(r.get(k) is True for k,enabled in eligibility.items() if enabled)]
     sensitive=any(any(r.get('gates',{}).get(k) is not True for k in policy['numeric_gate_fields']) for r in cross)
     local=local_rule['if_any_eligible_pair_fails_any_numeric_gate'] if sensitive else local_rule['otherwise']
     sufficient=((not sensitive or not sufficient_rule['no_eligible_pair_gate_failure']) and
                 len(cross)>=sufficient_rule['minimum_eligible_pairs'] and
                 verified_frames>=sufficient_rule['minimum_process_verified_selected_labels'] and
                 cross_setting_geometry_count>=sufficient_rule['minimum_distinct_geometry_hashes_among_eligible_pair_endpoints'])
     return (local if sensitive else sufficient_rule['if_all_satisfied'] if sufficient else sufficient_rule['otherwise'],
             sufficient_rule['if_all_satisfied'] if sufficient else sufficient_rule['otherwise'],local)

    def main():
     if not AUDIT.is_file() or not (APP/'decision.md').is_file():fail('required artifacts missing')
     try:out=json.loads(AUDIT.read_text(encoding='utf-8'),parse_constant=reject_constant)
     except (OSError,UnicodeDecodeError,json.JSONDecodeError,ValueError) as exc:fail('audit.json is missing or invalid JSON: '+str(exc))
     if not isinstance(out,dict):fail('audit.json must be an object')
     try:finite_tree(out)
     except ValueError as exc:fail(str(exc))
     manifest=json.loads((APP/'inputs/public-input-manifest.json').read_text()); refs=json.loads((TESTS/'reference-hashes.json').read_text())
     contract=json.loads((APP/'inputs/output-contract.json').read_text())
     selection_doc=json.loads((APP/'inputs/pool/selection.json').read_text()); selected={r['selection_id']:r for r in selection_doc['selected_20']}; focus_frame=int(selected['L01']['frame_index'])
     semantics=contract.get('semantic_rules',{})
     if semantics.get('geometry_identity')!={'format':'XYZ','exclude_header_lines':2,'strip_each_remaining_line':True,'join_with':'LF','append_final_lf':True,'encoding':'UTF-8','digest':'SHA-256'}:fail('public geometry identity rule does not match the implementation')
     if semantics.get('cell_key')!={'fields':['temperature_K','trajectory','category'],'separator':'|','frames_order':'selection.json selected_20 order'}:fail('public cell key/order rule does not match the implementation')
     if semantics.get('risk_ranking')!={'score_field':'risk_score_eV_A','direction':'descending','tie_break_field':'selection_id','tie_break_direction':'ascending_lexicographic'}:fail('public risk rank tie rule does not match the implementation')
     if semantics.get('scheduler_missing')!={'v1_absent_receipt':'null','v1_unparseable_receipt':'status=unparsed','v2_state_absent':'not_recorded_in_terminal_projection','raw_state_fields':['State','ExitCode']}:fail('public scheduler-status rule does not match the implementation')
     if semantics.get('unit_conversions')!={'hartree_to_eV':H2EV,'bohr_to_Angstrom':0.529177210903}:fail('public unit conversion constants do not match the implementation')
     if semantics.get('settings_differ_fields')!=contract.get('calculation_definitions',{}).get('settings_differ_keys'):fail('public CP2K setting comparison definitions disagree')
     if contract.get('schema')!=out.get('schema') or contract.get('required_pair_order')!=[['D1','L01'],['D1','R01'],['B01','S01']]:fail('public output contract mismatch')
     try:validate_schema(out,contract['audit_schema'])
     except (KeyError,ValueError) as exc:fail('audit.json does not match complete public output schema: '+str(exc))
     numeric_rules=contract.get('numeric_rules',{})
     thresholds=numeric_rules.get('thresholds',{})
     if thresholds!={'energy_abs_eV_per_atom':1e-4,'force_component_rmse_eV_A':.01,'max_atom_force_vector_delta_eV_A':.05,'ensemble_hit_force_component_rmse_eV_A':TH}:fail('public thresholds do not match scoring rules')
     expected_units={'energy_abs_eV_per_atom':'eV/atom','force_component_rmse_eV_A':'eV/Angstrom','max_atom_force_vector_delta_eV_A':'eV/Angstrom','max_atom_vector_eV_A':'eV/Angstrom','cutoff_Ry':'Ry','rel_cutoff_Ry':'Ry','eps_scf':'Ha','temperature_K':'K','cell_vectors_A':'Angstrom'}
     if numeric_rules.get('units')!=expected_units or numeric_rules.get('absolute_tolerance')!=1e-10 or numeric_rules.get('relative_tolerance')!=1e-9 or numeric_rules.get('finite_numbers_required') is not True or numeric_rules.get('hit_missingness_bound')!='[h/n, (h+m)/n]':fail('public numeric units, tolerance, finite-number or missingness rule mismatch')
     policy=contract.get('decision_policy',{})
     if not isinstance(policy.get('eligibility'),dict) or not isinstance(policy.get('local_finding'),dict) or not isinstance(policy.get('sufficiency'),dict):fail('public decision policy is incomplete')
     manifest_paths=[x.get('path') for x in manifest.get('files',[]) if isinstance(x,dict)]
     if len(manifest_paths)!=len(manifest.get('files',[])) or len(set(manifest_paths))!=len(manifest_paths):fail('public input manifest paths are malformed or duplicated')
     input_refs={rel:expected for rel,expected in refs.items() if rel.startswith('inputs/')}
     private_refs={rel:expected for rel,expected in refs.items() if rel.startswith('tests/')}
     if len(input_refs)+len(private_refs)!=len(refs):fail('private reference map contains an unsupported path')
     if set(input_refs)!=(set(manifest_paths)|{'inputs/public-input-manifest.json'}):fail('private reference map and public manifest do not describe the same input set')
     for rel,expected in input_refs.items():
      p=APP/rel
      if not p.is_file() or sha(p)!=expected:fail('input hash mismatch: '+rel)
     for rel,expected in private_refs.items():
      p=TESTS/rel.removeprefix('tests/')
      if not p.is_file() or p.is_symlink() or sha(p)!=expected:fail('private verifier hash mismatch: '+rel)
     if out.get('schema')!='case03-finite-evidence-audit/v1' or out.get('input_integrity',{}).get('all_verified') is not True:fail('input integrity declaration invalid')
     if out.get('ledger_disclosure')!=contract.get('ledger_disclosure_enum') or not isinstance(out.get('ledger_disclosure_note'),str) or not out['ledger_disclosure_note'].strip():fail('ledger projection disclosure missing or misleading')
     if out['input_integrity'].get('file_count')!=len(manifest['files']) or out['input_integrity'].get('verified_files')!=len(manifest['files']):fail('not every manifested input was verified')
     for item in manifest['files']:
      p=APP/item['path']
      if not p.is_file() or p.stat().st_size!=item.get('size_bytes') or item.get('sha256')!=input_refs.get(item['path']):fail('manifest size/hash closure mismatch: '+item['path'])
     # Independent native attempt parsing and process-state checks.
     native={}; attempt_paths={}
     v1_events=[json.loads(x) for x in (APP/'inputs/ledgers/v1-attempt-ledger.jsonl').read_text().splitlines()]
     v1_by={}
     for row in v1_events: v1_by.setdefault(row.get('attempt_id'),[]).append(row)
     v2_events=[json.loads(x) for x in (APP/'inputs/ledgers/v2-attempt-events-public.jsonl').read_text().splitlines()]
     v2_by={}
     for row in v2_events: v2_by.setdefault(row.get('attempt_id'),[]).append(row)
     operator_events=[json.loads(x) for x in (APP/'inputs/ledgers/v2-operator-budget-events-public.jsonl').read_text().splitlines()]
     for p in sorted((APP/'inputs/native/v1/attempts').iterdir()):
      if not p.is_dir() or not (p/'attempt.json').exists():continue
      aid=p.name; meta=json.loads((p/'attempt.json').read_text()); result=parse_native(p/(aid+'.out'),p/(aid+'.xyz')); setting=parse_input(p/(aid+'.inp'),p/(aid+'.xyz'))
      if meta.get('attempt_id')!=aid or meta.get('input_sha256')!=sha(p/(aid+'.inp')):fail('attempt identity/input hash mismatch: '+aid)
      declared=meta.get('setting',{})
      if any(key not in declared or not close(declared[key],setting[key],abs_tol=0,rel_tol=0) for key in ('cutoff_Ry','rel_cutoff_Ry','eps_scf','max_scf')):fail('attempt metadata/CP2K input setting mismatch: '+aid)
      if meta.get('geometry_sha256')!=sha(p/(aid+'.xyz')):fail('attempt frozen-XYZ hash mismatch: '+aid)
      ex=list(p.glob('engine-exit*.txt')); engine=int(ex[0].read_text().strip()) if len(ex)==1 and ex[0].read_text().strip() in {'0','1','2'} else None
      events=v1_by.get(aid,[]); starts=[x for x in events if x.get('event')=='START']; finishes=[x for x in events if x.get('event')=='FINISH']
      coord_sources=[x['coordinate_include_sha256'] for x in events if x.get('coordinate_include_sha256')]
      if len(starts)!=1 or len(finishes)>1 or starts[0].get('attempt_input_sha256')!=meta.get('input_sha256') or (coord_sources and any(x!=setting['coordinate_include_sha256'] for x in coord_sources)) or meta.get('coordinate_include_sha256')!=setting['coordinate_include_sha256']:
       fail('v1 ledger identity/source binding mismatch: '+aid)
      if finishes and (finishes[0].get('engine_exit_code')!=engine or finishes[0].get('engine_exit_record_sha256')!=sha(p/next(iter(p.glob('engine-exit*.txt'))).name)):
       fail('v1 terminal engine evidence mismatch: '+aid)
      process='verified_success' if finishes and engine==0 else 'verified_failure' if finishes else 'unknown'
      native[aid]={'result':result,'engine':engine,'process':process,'frame':meta.get('frame_index'),'category':meta.get('category'),'setting':setting};attempt_paths[aid]=(p,meta)
     for aid in ('D1','D2','B01','S01'):
      p=APP/'inputs/native/v2'/aid;meta=json.loads((p/'attempt.json').read_text());result=parse_native(p/(aid+'.out'),p/(aid+'.xyz'));setting=parse_input(p/(aid+'.inp'),p/(aid+'.xyz'));ex=list(p.glob('engine-exit*.txt'));engine=int(ex[0].read_text().strip()) if len(ex)==1 and ex[0].read_text().strip() in {'0','1','2'} else None
      if meta.get('attempt_id')!=aid or meta.get('input_sha256')!=sha(p/(aid+'.inp')):fail('attempt identity/input hash mismatch: '+aid)
      declared=meta.get('setting',{})
      if any(key not in declared or not close(declared[key],setting[key],abs_tol=0,rel_tol=0) for key in ('cutoff_Ry','rel_cutoff_Ry','eps_scf','max_scf')):fail('attempt metadata/CP2K input setting mismatch: '+aid)
      if meta.get('geometry_sha256')!=sha(p/(aid+'.xyz')):fail('attempt frozen-XYZ hash mismatch: '+aid)
      events=v2_by.get(aid,[]); starts=[x for x in events if x.get('event')=='START']; finishes=[x for x in events if x.get('event')=='FINISH']
      if len(starts)!=1 or len(finishes)!=1 or starts[0].get('v2_input_sha256')!=meta.get('input_sha256') or starts[0].get('coordinate_include_sha256')!=setting['coordinate_include_sha256']:
       fail('v2 ledger identity/source binding mismatch: '+aid)
      if finishes[0].get('engine_exit_code')!=engine or finishes[0].get('engine_exit_record_sha256')!=sha(p/next(iter(p.glob('engine-exit*.txt'))).name):
       fail('v2 terminal engine evidence mismatch: '+aid)
      process='verified_success' if engine==0 else 'verified_failure'
      native[aid]={'result':result,'engine':engine,'process':process,'frame':meta.get('frame_index'),'category':meta.get('category'),'setting':setting};attempt_paths[aid]=(p,meta)
     if len(native)!=28 or set(native)!={*[f'L{i:02d}' for i in range(1,21)],*[f'R{i:02d}' for i in range(1,5)],'D1','D2','B01','S01'}:fail('attempt ledger does not preserve all 28 unique attempts')
     if native['L01']['process']!='unknown' or any(native[f'L{i:02d}']['process']!='verified_success' for i in range(2,21)):fail('original process status was erased or misclassified')
     if any(native[f'R{i:02d}']['result'] is not None for i in (2,3,4)):fail('strict SCF failures were accepted as labels')
     expected_geometry_count=len({x['result']['g'] for x in native.values() if x['result'] is not None})
     if out.get('attempt_count')!=len(native) or out.get('unique_native_geometry_count')!=expected_geometry_count:fail('native attempt or unique-geometry count was not recomputed')
     original_pop=out.get('original_population',{})
     if original_pop.get('ids')!=[f'L{i:02d}' for i in range(1,21)] or original_pop.get('unknown_process_ids')!=['L01']:fail('original intent population or unknown status was changed')
     if original_pop.get('process_verified_n')!=19:fail('original verified process count mismatch')
     posthoc=out.get('retrospective_population',{})
     if posthoc.get('ids')!=[f'L{i:02d}' for i in range(2,21)]+['D1'] or posthoc.get('process_verified_n')!=20 or posthoc.get('retrospective') is not True or posthoc.get('prospective_freeze_claim') is not False:fail('retrospective subset was misrepresented')
     ledger_rows=out.get('attempt_ledger',[]);ledger={x['attempt_id']:x for x in ledger_rows if isinstance(x,dict) and isinstance(x.get('attempt_id'),str)}
     if len(ledger_rows)!=28 or len(ledger)!=28 or set(ledger)!=set(native):fail('output attempt ledger must contain each unique attempt exactly once')
     for aid,n in native.items():
      row=ledger.get(aid)
      if row is None or row.get('process_status')!=n['process'] or row.get('engine_status')!=('exit_0' if n['engine']==0 else 'nonzero_exit' if n['engine'] is not None else 'no_exit_record'):fail('attempt status mismatch: '+aid)
      attempt_path,_=attempt_paths[aid]
      if not native_identity_valid(row,aid,n,attempt_path/(aid+'.xyz')):fail('attempt native identity/provenance binding mismatch: '+aid)
      if not same_cp2k_settings(row.get('setting'),n['setting']):fail('parsed CP2K setting mismatch: '+aid)
      if row.get('frame_index')!=n['frame'] or row.get('category')!=n['category']:fail('attempt frame/category mapping mismatch: '+aid)
      if not workflow_scheduler_matches(row.get('workflow_scheduler_status'),aid,row.get('population'),attempt_path,operator_events,v2_events):fail('workflow scheduler axis mismatch: '+aid)
      if n['engine'] is not None and row.get('engine_status') not in {'exit_0','nonzero_exit'}:fail('engine status field is malformed: '+aid)
     # Verify frame identity and ordered atom mapping against pool bytes.
     pool=np.load(APP/'inputs/pool/candidate-pool.npz',allow_pickle=False); pred=np.load(APP/'inputs/pool/predictions.npz',allow_pickle=False)
     pm=json.loads((APP/'inputs/pool/predictions.json').read_text()); typemap=pm['deepmd_type_map']; sel=selection_doc
     poolmeta=json.loads((APP/'inputs/pool/candidate-pool.json').read_text()); poolsha=sha(APP/'inputs/pool/candidate-pool.npz'); predsha=sha(APP/'inputs/pool/predictions.npz')
     manifest_pool=next(x for x in manifest['files'] if x['path']=='inputs/pool/candidate-pool.json')
     canonical=json.dumps({k:v for k,v in sel.items() if k!='selection_sha256'},ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()
     if poolmeta.get('npz_sha256')!=poolsha or pm.get('candidate_pool_sha256')!=poolsha or pm.get('npz_sha256')!=predsha:fail('archived pool/prediction metadata hashes do not agree')
     if sel.get('pool_sha256')!=poolsha or sel.get('predictions_sha256')!=predsha or sel.get('pool_metadata_sha256')!=manifest_pool.get('source_sha256'):fail('selection is not bound to exact historical pool metadata and prediction arrays')
     if hashlib.sha256(canonical).hexdigest()!=sel.get('selection_sha256') or len(selected)!=20:fail('selection canonical integrity/identity mismatch')
     if len({r.get('selection_id') for r in sel['selected_20']})!=20:fail('selected IDs are not unique')
     for aid,r in selected.items():
      if aid not in native or native[aid]['frame']!=r.get('frame_index') or native[aid]['category']!=r.get('category'):
       fail('selected attempt does not map uniquely to its archived frame/category: '+aid)
     for aid,n in native.items():
      r=n['result']
      if r is None:continue
      p,meta=attempt_paths[aid]; ix=int(meta['frame_index']); xyz=p/(aid+'.xyz'); coords=np.asarray([[float(v) for v in z.split()[1:4]] for z in xyz.read_text().splitlines()[2:]])
      if not np.allclose(coords,pool['coords_A'][ix],atol=1e-8,rtol=0):fail('coordinate map mismatch: '+aid)
      if r['elements']!=[typemap[int(t)] for t in pool['type_ids_0based']]:fail('atom-type order mismatch: '+aid)
     # Independently bind every original selected-frame row to the selected metadata.
     if set(out.get('frame_metrics_by_original_process_verified_attempt',{}))!={f'L{i:02d}' for i in range(2,21)}:fail('original verified-frame table has missing or extra attempts')
     # Three predeclared comparisons, independently recomputed from native log text.
     F=pred['force_eV_A']
     expected_pairs=[]
     settings_keys=semantics['settings_differ_fields']
     for a,b in [('D1','L01'),('D1','R01'),('B01','S01')]:
      x=pair(native[a]['result'],native[b]['result']);different=any(native[a]['setting'][k]!=native[b]['setting'][k] for k in settings_keys);native_valid,process_verified=pair_eligibility(native[a],native[b]);expected_pairs.append((a,b,x,different,native_valid,process_verified))
     rows=out.get('pair_comparisons',[])
     if len(rows)!=3:fail('required pair comparison set incomplete')
     lim=[1e-4,.01,.05]
     for row,(a,b,vals,different,native_valid,process_verified) in zip(rows,expected_pairs):
      if (row.get('left'),row.get('right'))!=(a,b) or row.get('valid') is not native_valid or row.get('process_verified') is not process_verified:fail('pair identities/order/validity changed')
      if row.get('left_native_status')!=('native_valid' if native[a]['result'] is not None else 'native_failed_or_unusable') or row.get('right_native_status')!=('native_valid' if native[b]['result'] is not None else 'native_failed_or_unusable') or row.get('left_process_status')!=native[a]['process'] or row.get('right_process_status')!=native[b]['process'] or row.get('comparison_scope')!=('process_verified_native_pair' if process_verified else 'native_diagnostic_process_unverified'):fail('pair process/native evidence axes mismatch')
      left_geometry=native[a]['result']['g'];right_geometry=native[b]['result']['g']
      if not geometry_hashes_valid(row.get('geometry_hashes'),left_geometry,right_geometry,row.get('unique_geometry_count')):fail('pair geometry binding/count mismatch')
      if not same_cp2k_settings(row.get('left_setting'),native[a]['setting']) or not same_cp2k_settings(row.get('right_setting'),native[b]['setting']):fail('pair settings not bound to parsed native inputs')
      actual=row.get('metrics',{}); got=[actual.get('energy_abs_eV_per_atom'),actual.get('force_component_rmse_eV_A'),actual.get('max_atom_force_vector_delta_eV_A')]
      if any(not close(v,e) for v,e in zip(got,vals)):fail('pair recomputation mismatch '+a+'/'+b)
      gates=row.get('gates',{}); keys=['energy_abs_eV_per_atom','force_component_rmse_eV_A','max_atom_force_vector_delta_eV_A']
      if [gates.get(k) for k in keys]!=[v<=t for v,t in zip(vals,lim)]:fail('pair gate flags mismatch '+a+'/'+b)
      if row.get('same_geometry') is not (native[a]['result']['g']==native[b]['result']['g']):fail('pair geometry identity mismatch')
      if row.get('settings_differ') is not different or row.get('unique_geometry_count')!=(1 if native[a]['result']['g']==native[b]['result']['g'] else 2):fail('pair setting/geometry-derived fields mismatch '+a+'/'+b)
     l01=out.get('L01_numeric_only_metrics',{})
     if l01.get('attempt_id')!='L01' or l01.get('selection_id')!=selected['L01'].get('selection_id') or l01.get('frame_index')!=selected['L01'].get('frame_index') or l01.get('process_status')!=native['L01']['process'] or l01.get('counted_as_verified_hit') is not False:fail('L01 numeric-only scope/status mismatch')
     for m in range(4):
      d=F[m,focus_frame]-native['L01']['result']['f']; em=float(np.sqrt(np.mean(d*d)));mx=float(np.max(np.linalg.norm(d,axis=1)))
      if not close(l01.get('per_model',[{}]*4)[m].get('force_component_rmse_eV_A'),em) or not close(l01.get('per_model',[{}]*4)[m].get('max_atom_vector_eV_A'),mx):fail('L01 model metric mismatch')
     d=F.mean(axis=0)[focus_frame]-native['L01']['result']['f'];em=float(np.sqrt(np.mean(d*d)));mx=float(np.max(np.linalg.norm(d,axis=1)))
     if not close(l01.get('ensemble',{}).get('force_component_rmse_eV_A'),em) or not close(l01.get('ensemble',{}).get('max_atom_vector_eV_A'),mx):fail('L01 ensemble metric mismatch')
     # Independently recompute model/ensemble errors for the post-hoc verified subset.
     F=pred['force_eV_A']; ens=F.mean(axis=0); metrics=out.get('frame_metrics_by_retrospective_attempt',{})
     if len(metrics)!=20 or sorted(metrics)!=sorted([f'L{i:02d}' for i in range(2,21)]+['D1']):fail('post-hoc frame metrics missing or include wrong labels')
     for aid,row in metrics.items():
      ix=int(native[aid]['frame']); ref=native[aid]['result']['f']
      for m in range(4):
       d=F[m,ix]-ref; rmse=float(np.sqrt(np.mean(d*d))); mx=float(np.max(np.linalg.norm(d,axis=1))); got=row['per_model'][m]
       if not close(got['force_component_rmse_eV_A'],rmse) or not close(got['max_atom_vector_eV_A'],mx):fail('per-model metric mismatch '+aid)
      d=ens[ix]-ref; rmse=float(np.sqrt(np.mean(d*d)));mx=float(np.max(np.linalg.norm(d,axis=1)))
      if not close(row['ensemble']['force_component_rmse_eV_A'],rmse) or not close(row['ensemble']['max_atom_vector_eV_A'],mx):fail('ensemble metric mismatch '+aid)
     # Missingness and hit denominators are checked for both original and post-hoc samples.
     for key in ('original_four_strata_category_metrics','posthoc_four_strata_category_metrics'):
      cells=out.get(key,{})
      if len(cells)!=8:fail('four-stratum random/risk cells missing: '+key)
      for s in cells.values():
       if s['selected_n'] not in (2,3) or s['hits']>s.get('verified_n',s.get('process_verified_n',0)):fail('invalid stratum denominator')
       bounds=s['conditional_selected_set_hit_bounds']
       if not isinstance(bounds,list) or len(bounds)!=2 or not all(close(x,x) for x in bounds) or bounds[0]<0 or bounds[1]>1 or bounds[0]>bounds[1]:fail('invalid hit missingness bound')
     # Recalculate original and post-hoc stratum denominators, hits, summaries, and risk-vs-random deltas.
     ensemble=F.mean(axis=0); original_hits=0
     for group_name,posthoc in [('original_four_strata_category_metrics',False),('posthoc_four_strata_category_metrics',True)]:
      cells=out[group_name]; expected_cells={}
      for r in sel['selected_20']:
       cell_key=f"{r['temperature_K']}|{r['trajectory']}|{r['category']}";cell=cells[cell_key]
       aid=('D1' if r['selection_id']=='L01' else r['selection_id']) if posthoc else r['selection_id']
       native_available=native[aid]['result'] is not None
       expected_valid=native_available and native[aid]['process']=='verified_success'
       ix=int(r['frame_index']);per=None;ensemble_row=None;hit=False
       if native_available:
        ref=native[aid]['result']['f'];per=[]
        for m in range(4):
         delta=F[m,ix]-ref;per.append({'force_component_rmse_eV_A':float(np.sqrt(np.mean(delta*delta))),'max_atom_vector_eV_A':float(np.max(np.linalg.norm(delta,axis=1)))})
        delta=ens[ix]-ref;ensemble_row={'force_component_rmse_eV_A':float(np.sqrt(np.mean(delta*delta))),'max_atom_vector_eV_A':float(np.max(np.linalg.norm(delta,axis=1)))};hit=ensemble_row['force_component_rmse_eV_A']>=TH
       if expected_valid and not posthoc:original_hits+=int(hit)
       exp=expected_cells.setdefault(cell_key,{'n':0,'valid':0,'hits':0,'missing':0,'frames':[]});exp['n']+=1;exp['valid']+=int(expected_valid);exp['hits']+=int(hit and expected_valid);exp['missing']+=int(not expected_valid)
       exp['frames'].append({'attempt_id':aid,'selection_id':r['selection_id'],'frame_index':ix,'temperature_K':r['temperature_K'],'trajectory':r['trajectory'],'category':r['category'],'native_status':'native_valid' if native_available else 'native_failed_or_unusable','process_status':native[aid]['process'],'per_model':per,'ensemble':ensemble_row,'hit':hit,'counted_as_verified_hit':expected_valid})
       if cell['selected_n']!=(3 if r['category']=='random' else 2):fail('selection denominator mismatch')
      if set(cells)!=set(expected_cells):fail('stratum cell identities differ from selected population')
      for key,cell in cells.items():
        exp=expected_cells[key]
        valid_key='process_verified_n'
        if cell['selected_n']!=exp['n'] or cell[valid_key]!=exp['valid'] or cell['hits']!=exp['hits'] or cell.get('missing_status_n')!=exp['missing']:fail('stratum validity or hit count mismatch')
        expected_bounds=[exp['hits']/exp['n'],(exp['hits']+exp['missing'])/exp['n']]
        if len(cell.get('conditional_selected_set_hit_bounds',[]))!=2 or any(not close(a,b) for a,b in zip(cell['conditional_selected_set_hit_bounds'],expected_bounds)):fail('cell hit-missingness bounds do not match h/n and (h+m)/n')
        expected_frames=exp['frames'];got_frames=cell.get('frames',[])
        if len(got_frames)!=len(expected_frames):fail('cell per-frame rows are incomplete or duplicated')
        for gotrow,exprow in zip(got_frames,expected_frames):
         for name in ('attempt_id','selection_id','frame_index','temperature_K','trajectory','category','native_status','process_status','hit'):
          if gotrow.get(name)!=exprow[name]:fail('cell frame binding mismatch: '+name)
         expected_eligible=exprow['native_status']=='native_valid' and exprow['process_status']=='verified_success'
         if not counted_hit_flag_valid(gotrow.get('counted_as_verified_hit'),expected_eligible,exprow['hit']):fail('counted_as_verified_hit conflicts with native/process eligibility or hit status')
         if exprow['native_status']=='native_valid':
          for m,(gm,em) in enumerate(zip(gotrow.get('per_model',[]),exprow['per_model'])):
           if not close(gm.get('force_component_rmse_eV_A'),em['force_component_rmse_eV_A']) or not close(gm.get('max_atom_vector_eV_A'),em['max_atom_vector_eV_A']):fail('per-frame model metrics mismatch')
          if len(gotrow.get('per_model',[]))!=4 or any(not close(gotrow.get('ensemble',{}).get(k),v) for k,v in exprow['ensemble'].items()):fail('per-frame ensemble metrics mismatch')
         elif gotrow.get('per_model') is not None or gotrow.get('ensemble') is not None:fail('native-invalid frame must not report force metrics')
        got=cell['summary']; frames=eligible_summary_frames(got_frames,expected_frames)
        if got['valid_n']!=len(frames):
         excluded=[row['attempt_id'] for row in expected_frames if not summary_row_eligible(row)]
         fail(f"stratum summary denominator mismatch: {key}; reported valid_n={got['valid_n']}, expected native-valid/process-verified n={len(frames)}; excluded={excluded}")
        if got['frame_hit_count']!=sum(bool(exprow['hit']) for _,exprow in frames):fail('stratum summary hit count mismatch: '+key)
        for m in range(4):
         vals=[gotrow['per_model'][m]['force_component_rmse_eV_A'] for gotrow,_ in frames]
         maxes=[gotrow['per_model'][m]['max_atom_vector_eV_A'] for gotrow,_ in frames]
         expected_mean=float(np.mean(vals)) if vals else None; expected_max=max(maxes) if maxes else None
         if expected_mean is None or not close(got['per_model_mean_rmse_eV_A'][m],expected_mean) or not close(got['per_model_max_frame_vector_eV_A'][m],expected_max):fail('stratum per-model summary mismatch')
        vals=[gotrow['ensemble']['force_component_rmse_eV_A'] for gotrow,_ in frames]; maxes=[gotrow['ensemble']['max_atom_vector_eV_A'] for gotrow,_ in frames]
        if not vals or not close(got['ensemble_mean_rmse_eV_A'],float(np.mean(vals))) or not close(got['ensemble_max_frame_vector_eV_A'],max(maxes)):fail('stratum ensemble summary mismatch')
     original_cells=out['original_four_strata_category_metrics'];original_n=sum(x['selected_n'] for x in original_cells.values());original_missing=sum(x['missing_status_n'] for x in original_cells.values())
     if original_n!=20 or out['original_population'].get('process_verified_n')!=20-original_missing or len(out['original_population'].get('missingness_hit_bounds',[]))!=2 or not close(out['original_population']['missingness_hit_bounds'][0],original_hits/original_n) or not close(out['original_population']['missingness_hit_bounds'][1],(original_hits+original_missing)/original_n):fail('original population hit-missingness bound mismatch')
     comparisons=out.get('random_risk_within_stratum_comparison',[])
     comparison_by_id={(row['temperature_K'],row['trajectory']):row for row in comparisons}
     if len(comparison_by_id)!=len(comparisons):fail('random/risk paired comparison identities are duplicated')
     declarations=[row.get('population') for row in comparisons]
     if any(value is not None for value in declarations) and (any(value is None for value in declarations) or len(set(declarations))!=1):fail('random/risk comparisons must declare one consistent population for every row')
     declared_population=declarations[0] if declarations else None
     comparison_population_matches=[]
     population_tables=contract['calculation_definitions']['random_risk_comparison']['population_tables']
     for population,table_name in population_tables.items():
      random_means={};risk_means={}
      for cell in out[table_name].values():
       identity=(cell['temperature_K'],cell['trajectory'])
       (risk_means if cell['category']=='risk' else random_means)[identity]=cell['summary']['ensemble_mean_rmse_eV_A']
      if set(random_means)!=set(risk_means):fail('risk/random strata are not paired by trajectory')
      if len(comparisons)!=len(random_means) or set(comparison_by_id)!=set(random_means):fail('random/risk paired comparison identities are missing or unexpected')
      if declared_population is not None and declared_population!=population:continue
      consistent=True
      for identity,random_mean in random_means.items():
       row=comparison_by_id[identity];risk_mean=risk_means[identity]
       values={'random_mean_rmse_eV_A':random_mean,'risk_mean_rmse_eV_A':risk_mean,'risk_minus_random_eV_A':risk_mean-random_mean}
       if any(not close(row.get(key),value) for key,value in values.items()):consistent=False;break
      if consistent:comparison_population_matches.append(population)
     if not comparison_population_matches:fail('random/risk paired comparison is not derived consistently from a single permitted population')
     original_table=out['frame_metrics_by_original_process_verified_attempt']; posthoc_table=out['frame_metrics_by_retrospective_attempt']
     if set(original_table)!={f'L{i:02d}' for i in range(2,21)} or set(posthoc_table)!={f'L{i:02d}' for i in range(2,21)}|{'D1'}:fail('top-level frame metric tables have wrong attempt identities')
     original_cell_rows={r['attempt_id']:r for c in out['original_four_strata_category_metrics'].values() for r in c['frames']}
     posthoc_cell_rows={r['attempt_id']:r for c in out['posthoc_four_strata_category_metrics'].values() for r in c['frames']}
     for table,cellrows in ((original_table,original_cell_rows),(posthoc_table,posthoc_cell_rows)):
      for aid,got in table.items():
       cellrow=cellrows.get(aid)
       if cellrow is None or any(got.get(k)!=cellrow[k] for k in ('attempt_id','selection_id','frame_index','temperature_K','trajectory','category','native_status','process_status')):fail('top-level frame record not bound to its selected stratum row')
       if len(got.get('per_model',[]))!=4:fail('top-level per-model frame metrics are incomplete')
       for m in range(4):
        if not close(got['per_model'][m].get('force_component_rmse_eV_A'),cellrow['per_model'][m]['force_component_rmse_eV_A']) or not close(got['per_model'][m].get('max_atom_vector_eV_A'),cellrow['per_model'][m]['max_atom_vector_eV_A']):fail('top-level frame model metrics mismatch')
       if got.get('hit')!=cellrow['hit'] or any(not close(got.get('ensemble',{}).get(k),cellrow['ensemble'][k]) for k in cellrow['ensemble']):fail('top-level frame ensemble metrics mismatch')
     alt=out.get('alternative_label_sensitivity',{});d1=native['D1']['result']['f'];r01=native['R01']['result']['f']
     d1ens=F.mean(axis=0)[focus_frame]-d1;d1rmse=float(np.sqrt(np.mean(d1ens*d1ens)));d1max=float(np.max(np.linalg.norm(d1ens,axis=1)))
     r01ens=F.mean(axis=0)[focus_frame]-r01;r01rmse=float(np.sqrt(np.mean(r01ens*r01ens)));r01max=float(np.max(np.linalg.norm(r01ens,axis=1)))
     expected_same_geometry=all(native[aid]['result']['g']==native['D1']['result']['g'] for aid in ('L01','R01','B01','S01'))
     if native['D1']['frame']!=focus_frame or native['R01']['frame']!=focus_frame:fail('label-sensitivity inputs do not map to the selected L01 frame')
     if alt.get('frame_index')!=focus_frame or alt.get('same_geometry') is not expected_same_geometry or alt.get('hit_flip')!=((d1rmse>=TH)!=(r01rmse>=TH)):fail('alternative reference hit comparison mismatch')
     if alt.get('hit_threshold_eV_A')!=TH or alt.get('D1_hit')!=(d1rmse>=TH) or alt.get('R01_hit')!=(r01rmse>=TH):fail('alternative hit threshold fields mismatch')
     if not isinstance(alt.get('D1_model_metrics'),list) or not isinstance(alt.get('R01_model_metrics'),list) or len(alt['D1_model_metrics'])!=4 or len(alt['R01_model_metrics'])!=4:fail('alternative per-model metrics missing')
     for m in range(4):
      for dest,ref in ((alt['D1_model_metrics'][m],d1),(alt['R01_model_metrics'][m],r01)):
       delta=F[m,focus_frame]-ref;rm=float(np.sqrt(np.mean(delta*delta)));mx=float(np.max(np.linalg.norm(delta,axis=1)))
       if not close(dest.get('force_component_rmse_eV_A'),rm) or not close(dest.get('max_atom_vector_eV_A'),mx):fail('alternative per-model metric mismatch')
     if not close(alt.get('D1_ensemble',{}).get('force_component_rmse_eV_A'),d1rmse) or not close(alt.get('R01_ensemble',{}).get('force_component_rmse_eV_A'),r01rmse):fail('alternative reference error magnitudes mismatch')
     if not close(alt.get('D1_ensemble',{}).get('max_atom_vector_eV_A'),d1max) or not close(alt.get('R01_ensemble',{}).get('max_atom_vector_eV_A'),r01max) or not close(alt.get('ensemble_rmse_change_eV_A'),r01rmse-d1rmse):fail('alternative reference maximum/change mismatch')
     d1_order=sorted(((row['ensemble']['force_component_rmse_eV_A'],aid) for aid,row in out['frame_metrics_by_retrospective_attempt'].items()),key=lambda z:(-z[0],z[1]))
     alt_order=sorted([(rmse,aid) for rmse,aid in d1_order if aid!='D1']+[(r01rmse,'D1/R01-counterfactual')],key=lambda z:(-z[0],z[1]))
     if alt.get('selected_frame_error_rank_descending_D1')!=next(i+1 for i,x in enumerate(d1_order) if x[1]=='D1') or alt.get('selected_frame_error_rank_descending_R01_counterfactual')!=next(i+1 for i,x in enumerate(alt_order) if x[1]=='D1/R01-counterfactual'):fail('empirical error-rank counterfactual mismatch')
     risk_order=sorted(((x['risk_score_eV_A'],x['selection_id']) for x in sel['selected_20']),key=lambda z:(-z[0],z[1]))
     if alt.get('frozen_selection_risk_rank_descending')!=next(i+1 for i,x in enumerate(risk_order) if x[1]=='L01') or alt.get('frozen_selection_rank_changes_with_reference') is not False:fail('frozen risk-score rank was changed by label alternative')
     # Budget axes are checked from the public original budget rule and projected events.
     rule=(APP/'inputs/policy/original-compute-budget.yaml').read_text();cap=int(re.search(r'quantum_label_intents:\s*(\d+)',rule).group(1))
     if cap!=28 or out['accounting']['original_quantum_label_intent_cap']!=cap:fail('original budget rule mismatch')
     v1=v1_events; starts={x.get('attempt_id') for x in v1 if x.get('event')=='START'};v1_fin=[x for x in v1 if x.get('event')=='FINISH'];v1_recovery=[x for x in v1 if x.get('event')=='RECOVERY']
     v2=v2_events; v2starts={x.get('attempt_id') for x in v2 if x.get('event')=='START'};v2_fin=[x for x in v2 if x.get('event')=='FINISH']
     op=operator_events; jobs={x.get('job_id') for x in op if x.get('job_id')};charged={x.get('job_id') for x in op if x.get('job_id') and x.get('operator_slot_charged')==1}
     op_counts={event:sum(x.get('event')==event for x in op) for event in sorted({x.get('event') for x in op})}
     unknown_charge={x.get('job_id') for x in op if x.get('job_id') and x.get('operator_slot_charged') is None and x.get('event') in {'SUBMISSION_ACCEPTED','POSTHOC_SUBMISSION_DISCOVERED'}}
     if len(starts)!=24 or len(v2starts)!=4 or len(jobs)!=5 or len(charged)!=3 or len(unknown_charge)!=2:fail('budget event reconciliation mismatch')
     accounting=out['accounting']
     expected_counts={'v1_quantum_starts':len(starts),'v1_finish_events':len(v1_fin),'v1_nonzero_engine_finish_events':sum(x.get('engine_exit_code') not in (None,0) for x in v1_fin),'v1_recovery_events':len(v1_recovery),'v1_recovery_wrapper_failure_events':sum(x.get('wrapper_exit_code') not in (None,0) for x in v1_recovery),'v2_science_starts':len(v2starts),'v2_finish_events':len(v2_fin),'combined_science_starts':len(starts|v2starts),'operator_event_counts':op_counts,'operator_prestart_failure_events':op_counts.get('SUBMISSION_TERMINAL_PRESTART_FAILURE',0),'operator_slot_charge_event_count':sum(x.get('operator_slot_charged')==1 for x in op),'operator_slot_charged_unique_jobs':len(charged),'operator_slot_charge_unknown_unique_jobs':len(unknown_charge),'operator_slot_charge_unique_job_bounds':[len(charged),len(charged)+len(unknown_charge)],'operator_jobs_with_id':len(jobs)}
     if any(accounting.get(k)!=v for k,v in expected_counts.items()) or accounting.get('operator_event_counts')!=op_counts:fail('reported event accounting does not match projected ledgers')
     if accounting.get('accounting_axes_separate') is not True or accounting.get('prospective_compliance_claim') is not False:fail('budget evidence axes or scope were conflated')
     later_rule=(APP/'inputs/policy/later-operator-budget-rule.md').read_text(); later_cap=re.search(r'ceiling was (\d+) cumulative attempts',later_rule)
     if not later_cap or out['accounting']['later_operator_budget_cap']!=int(later_cap.group(1)) or int(later_cap.group(1))!=54:fail('later operator budget rule mismatch')
     s01=ledger['S01'].get('workflow_scheduler_status')
     if native['S01']['process']!='verified_success' or native['S01']['engine']!=0 or not workflow_scheduler_matches(s01,'S01','later_v2',attempt_paths['S01'][0],operator_events,v2_events):fail('S01 engine and scheduler status were conflated or omitted')
     for aid in ('D2','B01'):
      if not workflow_scheduler_matches(ledger[aid].get('workflow_scheduler_status'),aid,'later_v2',attempt_paths[aid][0],operator_events,v2_events):fail('missing terminal scheduler state was inferred for '+aid)
     if out['unique_native_geometry_count']!=expected_geometry_count:fail('native geometry count mismatch')
     qualifying=[r for r in rows if r.get('valid') is True and r.get('process_verified') is True and r.get('settings_differ') is True]
     cross_geometries={g for r in qualifying for g in r['geometry_hashes']}
     if out.get('cross_setting_unique_geometry_count')!=len(cross_geometries):fail('cross-setting geometry support count mismatch')
     if out['accounting']['accounting_axes_separate'] is not True or out['accounting']['prospective_compliance_claim'] is not False:fail('budget scope claim invalid')
     dec=out.get('decision',{}); expected,overall,local=decision_from_evidence(rows,len(metrics),len(cross_geometries),policy)
     if dec.get('type')!=expected or dec.get('overall_reference_sufficiency')!=overall or dec.get('local_numerical_finding')!=local:fail('decision is not consistent with recomputed evidence')
     required_reasons={'cross_setting_pair_failure' if expected=='REFERENCE_SENSITIVE' else 'no_cross_setting_pair_failure','retrospective_selection'}
     if len(cross_geometries)<2:required_reasons.add('shared_or_limited_geometry')
     if native['L01']['process']=='unknown':required_reasons.add('l01_process_status_unknown')
     reasons=dec.get('reasons',[])
     if not isinstance(reasons,list) or {x.get('code') for x in reasons if isinstance(x,dict)}!=required_reasons:fail('decision reason codes do not match recomputed evidence')
     if any(not isinstance(x.get('summary'),str) or not x['summary'].strip() or not isinstance(x.get('evidence'),list) for x in reasons):fail('decision reasons need evidence references and readable summaries')
     by_reason={x['code']:x for x in reasons}
     expected_pair_evidence=([p['left']+'/'+p['right'] for p in rows if p['settings_differ'] and p['process_verified'] and not all(p['gates'].values())] if expected=='REFERENCE_SENSITIVE' else [p['left']+'/'+p['right'] for p in rows if p['settings_differ'] and p['process_verified']])
     if not evidence_references_cover(by_reason.get('cross_setting_pair_failure' if expected=='REFERENCE_SENSITIVE' else 'no_cross_setting_pair_failure',{}).get('evidence'),expected_pair_evidence):fail('decision sensitivity reason is not bound to parsed setting pairs')
     if not evidence_references_cover(by_reason.get('l01_process_status_unknown',{}).get('evidence'),['L01']):fail('decision does not preserve L01 unknown process evidence')
     plan=out.get('next_evidence_plan',[])
     if len(plan)!=3 or [x.get('rank') for x in plan]!=contract.get('next_evidence_plan_policy',{}).get('rank_order'):fail('finite next-evidence plan ranks incomplete')
     if len({x.get('action') for x in plan})!=len(plan):fail('next-evidence priorities must name distinct actions')
     for x in plan:
      if any(not isinstance(x.get(k),str) or not x[k].strip() for k in ('action','gap','stop','budget_axis','reason')) or not isinstance(x.get('evidence_basis'),list) or not x['evidence_basis'] or not isinstance(x.get('gap_codes'),list):fail('next-evidence plan is missing structured rationale/budget axis')
      if x['budget_axis'] not in {'analysis_only','existing_evidence_only','separate_authorization_required'}:fail('next-evidence budget axis is outside the public enum')
     expected_plan1={'cross_setting_sensitivity' if expected=='REFERENCE_SENSITIVE' else 'cross_setting_comparison'}
     if len(cross_geometries)<policy['sufficiency']['minimum_distinct_geometry_hashes_among_eligible_pair_endpoints']:expected_plan1.add('limited_geometry_support')
     plan1_pairs=[p['left']+'/'+p['right'] for p in qualifying if any(p['gates'].get(k) is not True for k in policy['numeric_gate_fields'])] if expected=='REFERENCE_SENSITIVE' else [p['left']+'/'+p['right'] for p in qualifying]
     if set(plan[0]['gap_codes'])!=expected_plan1 or not set(plan[0]['evidence_basis']).issuperset(set(plan1_pairs)|{'cross_setting_unique_geometry_count'}):fail('first evidence priority codes/references do not match eligible pair evidence')
     expected_plan2={'stratum_coverage'}
     if original_missing:expected_plan2.add('missing_label_uncertainty')
     if set(plan[1]['gap_codes'])!=expected_plan2 or not {'original_four_strata_category_metrics','posthoc_four_strata_category_metrics','missingness_bounds'}.issubset(plan[1]['evidence_basis']):fail('second evidence priority does not bind cell and missingness evidence')
     if plan[2]['gap_codes']!=['budget_authorization_boundary'] or not {'original_28_intent_cap','later_54_operator_cap'}.issubset(plan[2]['evidence_basis']):fail('third evidence priority does not bind both budget axes')
     if [x['budget_axis'] for x in plan]!=['analysis_only','existing_evidence_only','separate_authorization_required']:fail('next-evidence budget axes are not distinct and ordered')
     expected_limits={'retrospective_evidence','prediction_arrays_not_replayed','no_pool_wide_accuracy_claim'}
     if len(sel['selected_20'])<pool['coords_A'].shape[0]:expected_limits.add('selected_panel_smaller_than_pool')
     if len(cross_geometries)<policy['sufficiency']['minimum_distinct_geometry_hashes_among_eligible_pair_endpoints']:expected_limits.add('limited_cross_setting_geometry_support')
     if original_missing:expected_limits.add('selected_process_status_incomplete')
     limitations=out.get('limitations',[]);limitation_codes={x['code'] for x in limitations}
     if limitation_codes!=expected_limits or len(limitation_codes)!=len(limitations):fail('limitation codes do not match observed data scope or contain duplicates')
     for item in limitations:
      if item['code']=='retrospective_evidence' and not evidence_references_cover(item['evidence'],['original_population','retrospective_population']):fail('retrospective limitation has invalid evidence references')
      if item['code']=='prediction_arrays_not_replayed' and not evidence_references_cover(item['evidence'],['inputs/pool/predictions.npz']):fail('prediction-array limitation has invalid evidence references')
      if item['code']=='selected_panel_smaller_than_pool' and not evidence_references_cover(item['evidence'],['inputs/pool/selection.json','inputs/pool/candidate-pool.npz']):fail('selected-panel limitation has invalid evidence references')
      if item['code']=='no_pool_wide_accuracy_claim' and not evidence_references_cover(item['evidence'],['inputs/pool/selection.json']):fail('pool-wide limitation has invalid evidence references')
      if item['code']=='limited_cross_setting_geometry_support' and not evidence_references_cover(item['evidence'],['cross_setting_unique_geometry_count']):fail('geometry limitation has invalid evidence references')
      if item['code']=='selected_process_status_incomplete' and not evidence_references_cover(item['evidence'],[x['attempt_id'] for x in ledger_rows if x['population']=='original_v1' and x['attempt_id'] in {r['selection_id'] for r in sel['selected_20']} and x['process_status']!='verified_success']):fail('process limitation has invalid evidence references')
     md=(APP/'decision.md').read_text(encoding='utf-8')
     if not md.strip():fail('decision.md must contain a concise explanation consistent with the audit')
     print(json.dumps({'status':'PASS','random_risk_comparison_populations':comparison_population_matches,'verified_sections':['public_input_integrity','native_attempt_and_setting_binding','three_declared_pair_metrics','selected_frame_and_stratum_recomputation','budget_reconciliation','data_derived_decision_and_plan'],'attempts':len(native),'native_valid_pairs':3,'process_verified_cross_setting_pairs':sum(bool(r.get('process_verified') and r.get('settings_differ')) for r in rows),'native_diagnostic_unverified_pairs':sum(bool(r.get('valid') and not r.get('process_verified')) for r in rows),'posthoc_frames':len(metrics)}))
    return SimpleNamespace(main=main, decision_from_evidence=decision_from_evidence,
                           geometry_hash=geometry_hash, native_identity_valid=native_identity_valid,
                           pair_eligibility=pair_eligibility, geometry_hashes_valid=geometry_hashes_valid,
                           counted_hit_flag_valid=counted_hit_flag_valid, summary_row_eligible=summary_row_eligible,
                           eligible_summary_frames=eligible_summary_frames,
                           workflow_scheduler_matches=workflow_scheduler_matches,
                           scheduler_receipt=scheduler_receipt)

def _make_case44_runner(_science_factory):
    def _decision_controls(science):
        gates={"energy_abs_eV_per_atom":True,"force_component_rmse_eV_A":True,"max_atom_force_vector_delta_eV_A":True}
        passing={"settings_differ":True,"valid":True,"process_verified":True,"gates":dict(gates)}
        failing={"settings_differ":True,"valid":True,"process_verified":True,"gates":{**gates,"force_component_rmse_eV_A":False}}
        expected=[
            ([passing,dict(passing)],20,20,('REFERENCE_ADEQUATE','REFERENCE_ADEQUATE','NO_COUNTEREXAMPLE')),
            ([passing,dict(passing)],20,1,('INSUFFICIENT_EVIDENCE','INSUFFICIENT_EVIDENCE','NO_COUNTEREXAMPLE')),
            ([failing,dict(passing)],20,20,('REFERENCE_SENSITIVE','INSUFFICIENT_EVIDENCE','REFERENCE_SENSITIVE')),
            ([],0,0,('INSUFFICIENT_EVIDENCE','INSUFFICIENT_EVIDENCE','NO_COUNTEREXAMPLE')),
            ([passing,dict(passing)],19,20,('INSUFFICIENT_EVIDENCE','INSUFFICIENT_EVIDENCE','NO_COUNTEREXAMPLE')),
        ]
        for rows,verified,geometries,want in expected:
            if science.decision_from_evidence(rows,verified,geometries)!=want:
                raise RuntimeError('synthetic verifier decision-function controls failed')
        flags=[
            (False,True,False,True),
            (True,True,False,True),
            (True,True,True,True),
            (False,True,True,False),
            (True,False,True,False),
            (1,True,False,False),
        ]
        for value,eligible,hit,want in flags:
            if science.counted_hit_flag_valid(value,eligible,hit) is not want:
                raise RuntimeError('synthetic counted-hit flag controls failed')
        unknown={'native_status':'native_valid','process_status':'unknown'}
        verified={'native_status':'native_valid','process_status':'verified_success'}
        flagged_unknown={'counted_as_verified_hit':True}
        unflagged_verified={'counted_as_verified_hit':False}
        summary_frames=science.eligible_summary_frames([flagged_unknown,unflagged_verified],[unknown,verified])
        if len(summary_frames)!=1 or summary_frames[0][0] is not unflagged_verified:
            raise RuntimeError('summary eligibility must come from independent native/process evidence')
        flag_cases=[
            (False,True,False,True), # literal eligibility-and-hit flag for eligible non-hit
            (True,True,False,True),  # legacy eligible-row flag for the same frame
            (True,True,True,True),
            (False,True,True,False),
            (True,False,True,False),
            (1,True,False,False),
        ]
        for value,eligible,hit,want in flag_cases:
            if science.counted_hit_flag_valid(value,eligible,hit) is not want:
                raise RuntimeError('synthetic counted-hit flag controls failed')
        unknown_l01={'native_status':'native_valid','process_status':'unknown'}
        eligible_row={'native_status':'native_valid','process_status':'verified_success'}
        candidates=[{'counted_as_verified_hit':True},{'counted_as_verified_hit':False}]
        summary_frames=science.eligible_summary_frames(candidates,[unknown_l01,eligible_row])
        if len(summary_frames)!=1 or summary_frames[0][0] is not candidates[1]:
            raise RuntimeError('summary eligibility must come from independent native/process evidence')

    #!/usr/bin/env python3
    """Fail-closed adapter for the current generic runner's private-tests interface."""
    import hashlib
    import importlib.util
    import json
    import os
    from pathlib import Path
    import subprocess
    import sys

    APP = Path(os.environ.get("APP", "/app")).resolve()
    TESTS = Path(os.environ.get("TESTS", "/tests")).resolve()
    LOGS = Path(os.environ.get("LOGS", "/logs/verifier")).resolve()
    REPORT = LOGS / "verification.json"


    def sha(path):
        h = hashlib.sha256()
        with path.open("rb") as stream:
            for block in iter(lambda: stream.read(1 << 20), b""):
                h.update(block)
        return h.hexdigest()


    def emit(status, reward, detail):
        LOGS.mkdir(parents=True, exist_ok=True)
        payload = {"status": status, "reward": reward, **detail}
        REPORT.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        reward_path = LOGS / "reward.txt"
        if reward is None:
            reward_path.unlink(missing_ok=True)
        else:
            reward_path.write_text(f"{reward}\n", encoding="utf-8")


    def main():
        LOGS.mkdir(parents=True, exist_ok=True)
        for name in ("reward.txt", "verification.json"):
            p = LOGS / name
            if p.is_symlink():
                raise RuntimeError(f"unsafe verifier output path: {name}")
            p.unlink(missing_ok=True)
        refs_path = TESTS / "reference-hashes.json"
        refs = json.loads(refs_path.read_text(encoding="utf-8"))
        if not isinstance(refs, dict) or not refs:
            raise RuntimeError("private reference hash map is empty or malformed")
        for rel, expected in refs.items():
            if not isinstance(rel, str):
                raise RuntimeError(f"unsupported private reference path: {rel!r}")
            if rel.startswith("inputs/"):
                path = APP / rel
            elif rel.startswith("tests/") and ".." not in Path(rel).parts:
                path = TESTS / rel.removeprefix("tests/")
            else:
                raise RuntimeError(f"unsupported private reference path: {rel!r}")
            if path.is_symlink() or not path.is_file() or sha(path) != expected:
                raise RuntimeError(f"trusted public input mismatch: {rel}")
        _decision_controls(_science_factory())
        numpy_spec = importlib.util.find_spec("numpy")
        if numpy_spec is None or not numpy_spec.origin:
            raise RuntimeError("NumPy is unavailable in the grader image")
        isolated_env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": "/tmp",
                        "APP": str(APP), "TESTS": str(TESTS), "LOGS": str(LOGS),
                        "PYTHONDONTWRITEBYTECODE": "1", "OPENBLAS_NUM_THREADS": "1",
                        "OMP_NUM_THREADS": "1", "PYTHONPATH": str(Path(numpy_spec.origin).parent.parent)}
        proc = subprocess.run(
            [sys.executable, str(TESTS / "verify.py"), "--submission", str(APP)],
            cwd=APP, capture_output=True, text=True, timeout=600,
            env=isolated_env,
        )
        try:
            diagnostic = json.loads(proc.stdout)
        except (json.JSONDecodeError, TypeError) as exc:
            raise RuntimeError(f"verifier did not return JSON (rc={proc.returncode}): {proc.stderr[-1000:]}") from exc
        if not isinstance(diagnostic, dict) or diagnostic.get("status") not in {"PASS", "FAIL"}:
            raise RuntimeError("verifier returned an unsupported or malformed status")
        if proc.returncode == 0 and diagnostic["status"] == "PASS":
            emit("PASS", 1, {"diagnostics": diagnostic})
            return 0
        if proc.returncode == 1 and diagnostic["status"] == "FAIL":
            emit("FAIL", 0, {"diagnostics": diagnostic})
            return 1
        raise RuntimeError(f"verifier exit/status mismatch: rc={proc.returncode}, status={diagnostic['status']}")


    def _runner_entry():
        try:
            raise SystemExit(main())
        except Exception as exc:
            emit("INFRA_ERROR", None, {"error": f"{type(exc).__name__}: {exc}"})
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
            logs, report_name = _prepare_runner_logs(44)
            sys.argv = [sys.argv[0]]
            runner = _make_case44_runner(_make_case44_science)
            runner.entry()
        except SystemExit:
            raise
        except Exception as exc:
            _runner_initialization_error(44, logs, report_name, exc)
    try:
        science = _make_case44_science()
        return science.main()
    except SystemExit:
        raise
    except Exception as exc:
        return _diagnostic_initialization_error(exc)


if __name__ == "__main__":
    raise SystemExit(_main_dispatch())
