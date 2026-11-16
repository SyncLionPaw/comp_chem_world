#!/usr/bin/env bash
set -euo pipefail
work=$(mktemp -d "${TMPDIR:-/tmp}/bench06-oracle.XXXXXXXX")
trap 'rm -rf "$work"' EXIT
ASSETS=${ASSETS_DIR:-/app/assets}
OUT=${OUTPUT_DIR:-/app/final}
[ -d "$ASSETS" ] || { echo "missing public assets: $ASSETS" >&2; exit 2; }
mkdir -p "$OUT"
cat > "$work/analysis.py" <<'BENCH06_PY_39_0'
#!/usr/bin/env python3
"""Rebuild Case 04 statistics from recovered native results and the approved task table."""
from __future__ import annotations
import csv, json, math
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
TASKS = ROOT / 'runtimes/hpc/case04/review-v3/tasks.json'
NATIVE = HERE / 'native'
OUT = HERE
KB_EV_K = 8.617333262145e-5
T_K = json.loads((ROOT / 'inputs/methods.json').read_text())['OS']['temperature_K']


def load():
    tasks = json.loads(TASKS.read_text())
    raw_files = sorted(NATIVE.glob('attempt-*/result.json'))
    if len(raw_files) != 20:
        raise ValueError(f'raw-only replay requires exactly 20 native result.json records; found {len(raw_files)}')
    records = [json.loads(p.read_text()) for p in raw_files]
    source = 'recovered-native-result.json'
    by_task = {}
    for r in records:
        if r['task_index'] not in range(len(tasks)):
            raise ValueError(f"unexpected task_index: {r.get('task_index')}")
        bucket = by_task.setdefault(r['task_index'], {})
        if r['state'] in bucket:
            raise ValueError(f"duplicate result for task={r['task_index']} state={r['state']}")
        bucket[r['state']] = r
        for key in ('E_PBE_TS09_eV', 'TS09_correction_eV',
                    'E_DFT_without_constraint_potential_eV', 'residual_e',
                    'local_charge_e', 'local_charge_tolerance_e'):
            if key not in r or not isinstance(r[key], (int, float)) or not math.isfinite(r[key]):
                raise ValueError(f"missing/non-finite/non-numeric {key} in task={r['task_index']} state={r['state']}")
        if r.get('status') != 'CONVERGED':
            raise ValueError(f"non-converged result in task={r['task_index']} state={r['state']}; refusing HT estimation")
    expected = {(t['index'], state) for t in tasks for state in (0, -1)}
    actual = {(i, s) for i, states in by_task.items() for s in states}
    if actual != expected:
        raise ValueError(f"result key coverage mismatch: missing={sorted(expected-actual)} extra={sorted(actual-expected)}")
    return tasks, by_task, source


def analyze():
    tasks, states, source_quality = load()
    plan = json.loads((ROOT/'runtimes/hpc/case04/review-v3/sampling_plan.json').read_text())
    output = []
    for task in tasks:
        pair = states.get(task['index'], {})
        neutral, anion = pair.get(0), pair.get(-1)
        converged = bool(neutral and anion and neutral['status'] == anion['status'] == 'CONVERGED')
        if not converged:
            raise ValueError(f"task {task['index']} is incomplete or non-converged; refusing to apply original inclusion probability")
        gap = (anion['E_PBE_TS09_eV'] - neutral['E_PBE_TS09_eV']) if converged else None
        output.append({
            'system': task['system'], 'ensemble': task['ensemble'],
            'frame': task['frame_zero_based'], 'stage': task['stage'],
            'stratum': task['stratum'], 'inclusion_probability': task['inclusion_probability'],
            'setting': task['setting'],
            'E_neutral_eV': neutral['E_PBE_TS09_eV'] if neutral else None,
            'E_neutral_DFT_eV': neutral.get('E_DFT_without_constraint_potential_eV') if neutral else None,
            'E_neutral_TS09_eV': neutral.get('TS09_correction_eV') if neutral else None,
            'E_anion_eV': anion['E_PBE_TS09_eV'] if anion else None,
            'E_anion_DFT_eV': anion.get('E_DFT_without_constraint_potential_eV') if anion else None,
            'E_anion_TS09_eV': anion.get('TS09_correction_eV') if anion else None,
            'gap_eV': gap, 'converged': converged,
            'native_id': f"task-{task['index']:02d}/{neutral['id'] if neutral else 'MISSING'}+{anion['id'] if anion else 'MISSING'}",
            'geometry_id': task['geometry_id'],
            'neutral_local_charge_e': neutral.get('local_charge_e') if neutral else None,
            'anion_local_charge_e': anion.get('local_charge_e') if anion else None,
            'neutral_residual_e': neutral.get('residual_e') if neutral else None,
            'anion_residual_e': anion.get('residual_e') if anion else None,
            'source_quality': source_quality
        })
    with (OUT/'energy_gaps.csv').open('w', newline='') as f:
        w = csv.DictWriter(f, fieldnames=list(output[0]))
        w.writeheader(); w.writerows(output)

    base = [r for r in output if r['stage'] == 'production' and r['converged']]
    summary = {}
    for ens in sorted({r['ensemble'] for r in base}):
        rows = [r for r in base if r['ensemble'] == ens]
        N = next(e['target_population_size'] for e in plan['ensembles'] if e['ensemble'] == ens)
        mean_ht = sum(r['gap_eV']/r['inclusion_probability'] for r in rows)/N
        raw2_ht = sum(r['gap_eV']**2/r['inclusion_probability'] for r in rows)/N
        descriptive_mean = sum(r['gap_eV'] for r in rows)/len(rows)
        descriptive_var_n = sum((r['gap_eV']-descriptive_mean)**2 for r in rows)/len(rows)
        summary[ens] = {
            'target_population_size': N,
            'observed_base_gaps_eV': [r['gap_eV'] for r in rows],
            'observed_strata': [r['stratum'] for r in rows],
            'marginal_inclusion_probabilities': [r['inclusion_probability'] for r in rows],
            'HT_mean_gap_eV': mean_ht,
            'HT_raw_second_moment_eV2': raw2_ht,
            'empirical_two_point_mean_eV': descriptive_mean,
            'empirical_two_point_variance_ddof0_eV2': descriptive_var_n,
            'variance_status': 'proof:design-var-'+ens
        }
    sensitivity = []
    for task in tasks:
        if task['stage'] != 'sensitivity': continue
        base_task = next(t for t in tasks if t['stage']=='production' and t['geometry_id']==task['geometry_id'])
        states_t, states_b = states[task['index']], states[base_task['index']]
        e0_t,e1_t=states_t[0]['E_PBE_TS09_eV'],states_t[-1]['E_PBE_TS09_eV']
        e0_b,e1_b=states_b[0]['E_PBE_TS09_eV'],states_b[-1]['E_PBE_TS09_eV']
        b0,b1=states_b[0],states_b[-1]; a0,a1=states_t[0],states_t[-1]
        sensitivity.append({'ensemble':task['ensemble'],'geometry_id':task['geometry_id'],
          'base_gap_eV':e1_b-e0_b,'tight_gap_eV':e1_t-e0_t,'gap_change_eV':(e1_t-e0_t)-(e1_b-e0_b),
          'neutral_total_energy_change_eV':e0_t-e0_b,'anion_total_energy_change_eV':e1_t-e1_b,
          'neutral_DFT_change_eV':a0['E_DFT_without_constraint_potential_eV']-b0['E_DFT_without_constraint_potential_eV'],
          'neutral_TS09_change_eV':a0['TS09_correction_eV']-b0['TS09_correction_eV'],
          'anion_DFT_change_eV':a1['E_DFT_without_constraint_potential_eV']-b1['E_DFT_without_constraint_potential_eV'],
          'anion_TS09_change_eV':a1['TS09_correction_eV']-b1['TS09_correction_eV'],
          'neutral_local_charge_base_e':b0['local_charge_e'],'neutral_local_charge_tight_e':a0['local_charge_e'],
          'anion_local_charge_base_e':b1['local_charge_e'],'anion_local_charge_tight_e':a1['local_charge_e'],
          'energy_component_split':'proof:settings-local'})
    neutral_contrast = summary['2K_neutral']['HT_mean_gap_eV'] - summary['water_neutral']['HT_mean_gap_eV']
    anion_contrast = summary['2K_anion']['HT_mean_gap_eV'] - summary['water_anion']['HT_mean_gap_eV']
    delta_sensitivity = sensitivity[1]['gap_change_eV'] - sensitivity[0]['gap_change_eV']
    marcus_by_system = {}
    for system, initial_ensemble, final_ensemble in [
        ('water', 'water_neutral', 'water_anion'),
        ('2K', '2K_neutral', '2K_anion')
    ]:
        marcus_by_system[system] = {
            'initial_state_I_ensemble': initial_ensemble,
            'final_state_F_ensemble': final_ensemble,
            'lambda_I_eV': None, 'lambda_F_eV': None, 'lambda_eV': None,
            'deltaA_I_eV': None, 'deltaA_F_eV': None,
            'barrier_I_eV': None, 'barrier_F_eV': None,
            'status': 'not_established',
            'reason_null': 'proof:marcus-limits'
        }
    marcus = {
      'energy_convention':'R3_native_E_PBE_TS09',
      'estimand':'frozen_finite_trajectory_population',
      'temperature_K':T_K,
      'ensembles':summary,
      'Marcus_conventions_from_inputs_methods_json':['proof:marcus-limits'],
      'marcus_by_system':marcus_by_system,
      'lambda_I_eV':None,'lambda_F_eV':None,'lambda_eV':None,
      'deltaA_I_eV':None,'deltaA_F_eV':None,
      'barrier_eV':None,'barrier_I_eV':None,'barrier_F_eV':None,
      'reason_null':'proof:marcus-limits',
      'between_system_point_contrasts': {'neutral_ensemble_2K_minus_water_eV':neutral_contrast,'anion_ensemble_2K_minus_water_eV':anion_contrast,'warning':'proof:rank-nonid'},
      'setting_sensitivity': sensitivity,
      'design_probabilities': {'per_frame':'proof:design-var-2K_neutral','distinct_frames_same_stratum':'proof:design-var-2K_neutral','distinct_strata_h_and_k':'proof:design-var-2K_neutral','interpretation':'proof:design-var-2K_neutral'},
      'contrast_flip_thresholds': {
        'neutral_2K_minus_water_HT_point_contrast_eV':neutral_contrast,
        'neutral_differential_contrast_bias_to_reverse_sign_eV':abs(neutral_contrast),
        'neutral_equal_opposite_bias_per_system_to_reverse_sign_eV':abs(neutral_contrast)/2,
        'anion_2K_minus_water_HT_point_contrast_eV':anion_contrast,
        'anion_differential_contrast_bias_to_reverse_sign_eV':abs(anion_contrast),
        'anion_equal_opposite_bias_per_system_to_reverse_sign_eV':abs(anion_contrast)/2,
        'anion_setting_correction_if_two_single_geometry_shifts_were_generalizable_eV':delta_sensitivity,
        'anion_contrast_after_that_explicit_unverified_setting_scenario_eV':anion_contrast+delta_sensitivity,
        'warning':'proof:settings-local'},
      'status':'not_established',
      'inference_limits':['proof:rank-nonid','proof:design-var-2K_neutral','proof:all-protocols','proof:state-limit-unique_physical_energy','proof:settings-local','proof:marcus-limits']}
    (OUT/'marcus.json').write_text(json.dumps(marcus,indent=2,ensure_ascii=False)+'\n')
    return output, summary, sensitivity

if __name__=='__main__':
    rows, summary, sens = analyze()
    print(json.dumps({'gap_rows':len(rows),'base_rows':sum(r['stage']=='production' for r in rows),'summary':summary,'sensitivity':sens},indent=2))
BENCH06_PY_39_0
cat > "$work/replay_reference.py" <<'BENCH06_PY_39_1'
#!/usr/bin/env python3
"""Recompute Case 04 outputs from public inputs and archived native evidence."""
from __future__ import annotations

import csv
import hashlib
import json
import math
import shutil
import subprocess
import sys
import tarfile
import tempfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath


def readj(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def digest(path):
    h = hashlib.sha256()
    with open(path, 'rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def check_public_hashes(assets, source_record):
    """Check every pinned public file that exists in this workspace."""
    expected = source_record['public_source_inputs_sha256']
    checked = {}
    for source, sha in expected.items():
        if source.startswith('packages/case-04-outer-sphere-budgeted/environment/assets/'):
            rel = source.split('/environment/assets/', 1)[1]
            candidate = assets / rel
        elif source.startswith('inputs/'):
            candidate = assets / source.removeprefix('inputs/')
        else:
            continue
        if candidate.is_file():
            actual = digest(candidate)
            if actual != sha:
                raise ValueError(f'public source SHA-256 mismatch: {source}')
            checked[source] = actual
    required = {
        'packages/case-04-outer-sphere-budgeted/environment/assets/OS_budget.json',
        'packages/case-04-outer-sphere-budgeted/environment/assets/methods.json',
        'packages/case-04-outer-sphere-budgeted/environment/assets/computegaps.py',
    }
    if not required.issubset(checked):
        raise ValueError('required public inputs are missing or not hash-verified: ' + ', '.join(sorted(required-set(checked))))
    return checked


def extract_archive(archive, native_root, expected_native_hashes):
    seen = set()
    native_root.mkdir(parents=True, exist_ok=True)
    with tarfile.open(archive, 'r:gz') as tf:
        for member in tf.getmembers():
            rel = PurePosixPath(member.name)
            if rel.is_absolute() or '..' in rel.parts or not rel.parts or rel.parts[0] != 'native':
                raise ValueError('unsafe archive member: ' + member.name)
            if member.issym() or member.islnk() or not (member.isfile() or member.isdir()):
                raise ValueError('unsupported archive member: ' + member.name)
            dest = native_root.joinpath(*rel.parts[1:])
            if member.isdir():
                dest.mkdir(parents=True, exist_ok=True)
                continue
            key = 'analysis/revision3/native/' + '/'.join(rel.parts[1:])
            if key in seen:
                raise ValueError('duplicate archive member: ' + member.name)
            seen.add(key)
            dest.parent.mkdir(parents=True, exist_ok=True)
            src = tf.extractfile(member)
            if src is None:
                raise ValueError('unreadable archive member: ' + member.name)
            dest.write_bytes(src.read())
    if seen != set(expected_native_hashes):
        raise ValueError('archive native member set differs from the source manifest')
    actual = {}
    for key, expected in expected_native_hashes.items():
        path = native_root / key.removeprefix('analysis/revision3/native/')
        found = digest(path)
        if found != expected:
            raise ValueError('native evidence SHA-256 mismatch: ' + key)
        actual[key] = found
    return actual


def sampling_audit(plan, tasks):
    result = {
        'schema': 'case04-sampling-design-audit/v1',
        'derivation': 'proof:native-audit',
        'stratum_partition_rule': 'proof:design-var-water_neutral',
        'marginal_inclusion_formula': 'proof:design-var-water_neutral',
        'joint_inclusion_formula': 'proof:design-var-water_neutral',
        'ensembles': {},
    }
    for ens in plan['ensembles']:
        name = ens['ensemble']
        lo, hi = ens['target_population']
        n = ens['target_population_size']
        q, r = divmod(n, 4)
        prod = [t for t in tasks if t['ensemble'] == name and t['stage'] == 'production']
        entry = {'source_frame_count': ens['source_frame_count'],
                 'target_population_bounds_zero_based_inclusive': [lo, hi],
                 'target_population_size_N': n,
                 'selection_design': 'proof:design-var-'+name, 'layers': [],
                 'distinct_frame_pair_inclusion_probability_matrix': []}
        first = lo
        for h in range(4):
            size = q + (h < r)
            last = first + size - 1
            observed = next((t for t in prod if t['stratum'] == h), None)
            entry['layers'].append({'stratum': h, 'frame_first_zero_based_inclusive': first,
                                    'frame_last_zero_based_inclusive': last,
                                    'stratum_size_Nh': size, 'marginal_pi_i': 1/(2*size),
                                    'selected_by_frozen_plan': h in plan['selected_strata'][name],
                                    'observed_frame_zero_based': observed['frame_zero_based'] if observed else None,
                                    'observed_frame_within_declared_bounds': bool(observed and first <= observed['frame_zero_based'] <= last)})
            first = last + 1
        for h in range(4):
            row = []
            for k in range(4):
                a = entry['layers'][h]['stratum_size_Nh']
                b = entry['layers'][k]['stratum_size_Nh']
                row.append({'stratum_pair': [h, k], 'pi_ij_distinct_frames': 0.0 if h == k else 1/(6*a*b)})
            entry['distinct_frame_pair_inclusion_probability_matrix'].append(row)
        result['ensembles'][name] = entry
    return result


def standard_diagnostics(tasks, energy_audit, plan):
    states = {(r['task_index'], r['state']): r for r in energy_audit['states']}
    rows = []
    for task in tasks:
        neutral, anion = states[(task['index'], 0)], states[(task['index'], -1)]
        nfree = neutral['printed_free_minus_external_eV'] + neutral['TS09_eV']
        afree = anion['printed_free_minus_external_eV'] + anion['TS09_eV']
        nextp = neutral['printed_extrapolated_minus_external_eV'] + neutral['TS09_eV']
        aexp = anion['printed_extrapolated_minus_external_eV'] + anion['TS09_eV']
        rows.append({'task_index': task['index'], 'ensemble': task['ensemble'], 'geometry_id': task['geometry_id'],
                     'stage': task['stage'], 'setting': task['setting'],
                     'free_minus_external_neutral_plus_TS09_eV': nfree,
                     'free_minus_external_anion_plus_TS09_eV': afree,
                     'free_minus_external_gap_plus_state_specific_TS09_eV': afree-nfree,
                     'extrapolated_minus_external_neutral_plus_TS09_eV': nextp,
                     'extrapolated_minus_external_anion_plus_TS09_eV': aexp,
                     'extrapolated_minus_external_gap_plus_state_specific_TS09_eV': aexp-nextp})
    ht = {}
    for convention, field in [('free_minus_external_gap_plus_state_specific_TS09_eV', 'free_minus_external_gap_plus_state_specific_TS09_eV'),
                              ('extrapolated_minus_external_gap_plus_state_specific_TS09_eV', 'extrapolated_minus_external_gap_plus_state_specific_TS09_eV')]:
        ht[convention] = {}
        for ens in sorted({t['ensemble'] for t in tasks if t['stage'] == 'production'}):
            selected = [r for r in rows if r['ensemble'] == ens and r['stage'] == 'production']
            n = next(e['target_population_size'] for e in plan['ensembles'] if e['ensemble'] == ens)
            ht[convention][ens] = {'HT_mean_eV': sum(r[field]/next(t['inclusion_probability'] for t in tasks if t['index'] == r['task_index']) for r in selected)/n,
                                   'observed_gaps_eV': [r[field] for r in selected]}
    return {'schema': 'case04-standard-electronic-gap-diagnostics/v1',
            'source': 'printed_gpaw_energy_components',
            'printed_component_precision_eV': 1e-6, 'printed_SIC_all_zero': energy_audit['all_printed_SIC_zero'],
            'definitions': {'free': 'proof:source-conventions-free',
                            'extrapolated': 'proof:source-conventions-extrapolated',
                            'scope': 'proof:source-conventions-free'},
            'limitations': 'proof:source-conventions-free',
            'rows': rows, 'HT_diagnostics': ht}


def emit_csv(rows, path):
    with open(path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def build_proof_claims(assets,marcus,tasks,plan,diagnostics,energy_audit,native,energy_rows):
    ensembles=sorted(marcus['ensembles'])
    claims=[]; proofs=[]; quantities=[]
    def proof(pid,kind,inputs,reported): proofs.append({'id':pid,'kind':kind,'inputs':inputs,'reported':reported})
    def claim(cid,topic,predicate,scope,status,proof_ids): claims.append({'id':cid,'topic':topic,'predicate':predicate,'scope':scope,'status':status,'proof_ids':proof_ids})
    def q(qid,expr,unit,scope,value): quantities.append({'id':qid,'expression':expr,'unit':unit,'scope':scope,'value':value})
    for row in energy_rows:
        t=next(x for x in tasks if x['ensemble']==row['ensemble'] and x['frame_zero_based']==int(row['frame']) and x['stage']==row['stage'] and x['setting']==row['setting'] and x['geometry_id']==row['geometry_id'])
        key=f"sample_gap/{t['index']}/{t['setting']}"
        q(key,{'op':'source','id':key},'eV',{'kind':'geometry','id':t['geometry_id']},float(row['gap_eV']))
    conventions={'R3':{e:marcus['ensembles'][e]['HT_mean_gap_eV'] for e in ensembles}}
    for name,field in [('free','free_minus_external_gap_plus_state_specific_TS09_eV'),('extrapolated','extrapolated_minus_external_gap_plus_state_specific_TS09_eV')]:
        conventions[name]={e:diagnostics['HT_diagnostics'][field][e]['HT_mean_eV'] for e in ensembles}
    for conv in conventions:
        for ens in ensembles:
            key=f'convention_ht/{conv}/{ens}'; value=conventions[conv][ens]
            q(key,{'op':'source','id':key},'eV',{'kind':'energy_convention','id':conv+'/'+ens},value)
    for ens in ensembles:
        key='ht_gap/'+ens; value=marcus['ensembles'][ens]['HT_mean_gap_eV']
        q(key,{'op':'source','id':key},'eV',{'kind':'ensemble_ht','id':ens},value)
    proof('native-audit','source_audit',{'audit_scope':'native_r3_source_reconstruction'},
          {'reported_ledger_records':len(list(Path(native).glob('attempt-*/result.json'))),'reported_unique_state_records':len(list(Path(native).glob('attempt-*/result.json'))),'reported_valid_pairs':len({t['index'] for t in tasks}),'reported_base_geometries':len({t['geometry_id'] for t in tasks if t['stage']=='production'}),'reported_tight_replays':len({t['geometry_id'] for t in tasks if t['stage']=='sensitivity'}),'reported_source_hashes_verified':True,'reported_geometry_pairs_verified':True,'reported_state_charge_and_convergence_verified':True,'reported_energy_decomposition_verified':True})
    for c in claims: pass
    for ens in ensembles:
        N=next(x['target_population_size'] for x in plan['ensembles'] if x['ensemble']==ens); qsize,rem=divmod(N,4); h=0; Nh=qsize+(h<rem)
        proof('design-var-'+ens,'design_variance_nonidentifiability',{'ensemble':ens,'stratum':h},
              {'target_population_size':N,'stratum_size':Nh,'marginal_inclusion_probability':1/(2*Nh),'distinct_frame_joint_inclusion_probability':0.0})
    # Two deliberately different completions preserve every observed frame.
    completion_means={}
    observed_gaps=[float(v) for ens in ensembles for v in marcus['ensembles'][ens]['observed_base_gaps_eV']]
    span=max(observed_gaps)-min(observed_gaps)+1.0
    low=min(observed_gaps)-span; high=max(observed_gaps)+span
    for pid,water_x,k_x in [('completion-A',high,low),('completion-B',low,high)]:
        assignments=[]; reported=[]
        for ens in ensembles:
            unseen=water_x if ens.startswith('water_') else k_x
            assignments.append({'ensemble':ens,'value_expr':{'op':'literal','value':unseen,'unit':'eV'}})
            obs=[float(v) for v in marcus['ensembles'][ens]['observed_base_gaps_eV']]; N=marcus['ensembles'][ens]['target_population_size']; vals=obs+[unseen]*(N-len(obs)); mean=sum(vals)/N; variance=sum((v-mean)**2 for v in vals)/N
            reported.append({'ensemble':ens,'computed_population_mean_eV':mean,'computed_population_variance_eV2':variance})
        proof(pid,'finite_population_completion',{'assignments':assignments},{'assignments':reported}); completion_means[pid]={e:next(x for x in reported if x['ensemble']==e) for e in ensembles}
    moment=[]
    for ens in ensembles:
        a,b=completion_means['completion-A'][ens],completion_means['completion-B'][ens]
        moment.append({'ensemble':ens,'mean_diff_eV':b['computed_population_mean_eV']-a['computed_population_mean_eV'],'variance_diff_eV2':b['computed_population_variance_eV2']-a['computed_population_variance_eV2']})
    proof('moments-nonid','population_moment_nonidentifiability',{'completion_proof_ids':['completion-A','completion-B'],'ensembles':ensembles},{'reported_moment_changes':moment})
    rank_rows=[]
    for left,right in [('2K_neutral','water_neutral'),('2K_anion','water_anion')]:
        differences=[]; ordering=[]
        for pid in ('completion-A','completion-B'):
            d=completion_means[pid][left]['computed_population_mean_eV']-completion_means[pid][right]['computed_population_mean_eV']; differences.append(d); ordering.append('left_lower' if d<0 else 'right_lower' if d>0 else 'equal')
        rank_rows.append({'left_ensemble':left,'right_ensemble':right,'left_minus_right_eV_by_completion':differences,'ordering_by_completion':ordering})
    proof('rank-nonid','ranking_nonidentifiability',{'completion_proof_ids':['completion-A','completion-B'],'contrast_pairs':[{'left_ensemble':'2K_neutral','right_ensemble':'water_neutral'},{'left_ensemble':'2K_anion','right_ensemble':'water_anion'}]},{'contrast_pairs':rank_rows})
    contrast_pairs=[{'left_ensemble':'2K_neutral','right_ensemble':'water_neutral'},{'left_ensemble':'2K_anion','right_ensemble':'water_anion'}]
    for alternative in ('free','extrapolated'):
        conv_rows=[]
        for pair in contrast_pairs:
            left,right=pair['left_ensemble'],pair['right_ensemble']
            bl,br=conventions['R3'][left],conventions['R3'][right]; al,ar=conventions[alternative][left],conventions[alternative][right]
            ls,rs=al-bl,ar-br; bc,ac=bl-br,al-ar
            conv_rows.append({'left_ensemble':left,'right_ensemble':right,'base_left_HT_eV':bl,'base_right_HT_eV':br,'alternative_left_HT_eV':al,'alternative_right_HT_eV':ar,'left_shift_eV':ls,'right_shift_eV':rs,'base_contrast_eV':bc,'alternative_contrast_eV':ac,'differential_shift_eV':ls-rs,'flip':abs(bc)>1e-8 and abs(ac)>1e-8 and bc*ac<0})
        proof('source-conventions-'+alternative,'source_convention_comparison',{'base_convention':'R3','alternative_convention':alternative,'contrast_pairs':contrast_pairs},{'contrast_pairs':conv_rows})
    # Protocol facts are extracted from the pinned scripts and native inputs below.
    # The helper emits facts in the same public normalized representation, but the
    # oracle derives its own values from source rather than reusing candidate output.
    import ast, re
    assets=Path(assets); catalog={}
    def tree(rel): return ast.parse((assets/rel).read_text(encoding='utf-8'))
    def calls(tr,name): return [n for n in ast.walk(tr) if isinstance(n,ast.Call) and isinstance(n.func,ast.Name) and n.func.id==name]
    def attrcalls(tr,name): return [n for n in ast.walk(tr) if isinstance(n,ast.Call) and isinstance(n.func,ast.Attribute) and n.func.attr==name]
    def literal(n):
        try: return ast.literal_eval(n) if n is not None else None
        except Exception: return None
    def kw(call,key): return literal(next((x.value for x in call.keywords if x.arg==key),None)) if call else None
    def first(tr,name):
        rows=calls(tr,name); return rows[0] if rows else None
    def protocol_method(tr):
        g=first(tr,'GPAW')
        xc=kw(g,'xc') if g else None
        if isinstance(xc,dict): xc=xc.get('name')
        return {'calculator':'GPAW' if g else None,'xc':xc,'mode':kw(g,'mode') if g else None,
                'basis':kw(g,'basis') if g else None,'grid_spacing_A':kw(g,'h') if g else None}
    def protocol_geometry(tr):
        rc=first(tr,'read')
        selector=ast.unparse(rc.args[0]) if rc and rc.args else None
        pbc=None; vacuum=None
        for c in attrcalls(tr,'set_pbc'):
            if c.args:
                pbc=literal(c.args[0]); break
        for c in attrcalls(tr,'center'):
            vacuum=kw(c,'vacuum')
            if vacuum is not None: break
        return {'input_selector':selector,'pbc':pbc,'vacuum_A':vacuum}
    def protocol_sampling(tr):
        lc=first(tr,'Langevin')
        if not lc: return {'kind':'vertical-single-point'},None
        args=[]
        for i,arg in enumerate(lc.args):
            val=literal(arg)
            args.append(val if i==len(lc.args)-1 and isinstance(val,(int,float)) else ast.unparse(arg))
        return {'langevin_arguments':args},literal(lc.args[-1]) if lc.args else None
    def protocol_energy(tr, reported_ts=False):
        binding=attrcalls(tr,'set_calculator')
        bound=binding[-1].args[0].id if binding and binding[-1].args and isinstance(binding[-1].args[0],ast.Name) else None
        source_text=ast.unparse(tr)
        return {'cdft_applied':bool(calls(tr,'CDFT')),'ts09_constructed':bool(calls(tr,'vdWTkatchenko09prl')),
                'ts09_final_calculator_binding':bool(bound=='cc'),'ts09_in_reported_energy':reported_ts and 'E_PBE_TS09_eV' in source_text}
    mdpaths={'water_neutral':'water_CO2/calc.py','water_anion':'water_CO2anion/calc.py','2K_neutral':'2K_CO2/calc.py','2K_anion':'2K_CO2anion/calc.py'}
    for label,rel in mdpaths.items():
        tr=tree(rel); g=first(tr,'GPAW'); occ=(kw(g,'occupations') or {}) if g else {}; cd=first(tr,'CDFT')
        charges=kw(cd,'charges') if cd else None; regions=kw(cd,'charge_regions') if cd else None
        state=float(charges[0]) if isinstance(charges,list) and len(charges)==1 else None
        region=sorted(regions[0]) if isinstance(regions,list) and len(regions)==1 and isinstance(regions[0],list) else None
        sampling,raw_friction=protocol_sampling(tr)
        pid='author_md/'+label
        catalog[pid]={'state':state,'spin':{'spinpol':kw(g,'spinpol') if g else None,'fixmagmom':occ.get('fixmagmom'),'anion_initial_moment_mu_B':None},
          'method':protocol_method(tr),'energy':protocol_energy(tr),'geometry':protocol_geometry(tr),'sampling':sampling,
          'raw_langevin_api_argument':raw_friction,'physical_friction_rate':None,
          'charge_region_index_set':region,'charge_region_mapped_elements':None}
    vtr=tree('computegaps.py'); vcd=first(vtr,'CDFT'); vcharges=kw(vcd,'charges') if vcd else None; vregions=kw(vcd,'charge_regions') if vcd else None
    vanion=float(vcharges[0]) if isinstance(vcharges,list) and len(vcharges)==1 else None
    vregion=sorted(vregions[0]) if isinstance(vregions,list) and len(vregions)==1 and isinstance(vregions[0],list) else None
    vg=first(vtr,'GPAW'); vocc=(kw(vg,'occupations') or {}) if vg else {}
    vgeometry=protocol_geometry(vtr)
    for state,value in [('neutral',None),('anion',vanion)]:
        pid='author_vertical/'+state; catalog[pid]={'state':value,'spin':{'spinpol':kw(vg,'spinpol') if vg else None,'fixmagmom':vocc.get('fixmagmom'),'anion_initial_moment_mu_B':None},
          'energy':{'cdft_applied':state=='anion' and value is not None,'ts09_constructed':bool(calls(vtr,'vdWTkatchenko09prl')),'ts09_final_calculator_binding':False,'ts09_in_reported_energy':False},
          'method':protocol_method(vtr),'geometry':vgeometry,'sampling':{'kind':'vertical-single-point'},
          'raw_langevin_api_argument':None,'physical_friction_rate':None,
          'charge_region_index_set':vregion if state=='anion' else None,'charge_region_mapped_elements':None}
    native_rows=[]
    for result_path in Path(native).glob('attempt-*/result.json'):
        folder=result_path.parent; result=readj(result_path); inp=readj(folder/'input.json')
        task=next(t for t in tasks if t['index']==result['task_index'])
        native_rows.append((task,result,inp,folder))
    for state,stateval in [('neutral',0),('anion',-1)]:
      for setting in ('base','tight'):
        chosen=[(t,result,inp,folder) for t,result,inp,folder in native_rows if t['setting']==setting and result['state']==stateval]
        # Each state-setting proof is scoped by the exact frozen source records.
        if not chosen: continue
        inp=chosen[0][2]; opts=inp['calculator_options']; occ=opts.get('occupations') or {}; pid=f'revision3/{state}/{setting}'
        regions={t['geometry_id']:sorted(inp0['CO2_indices_zero_based']) for t,result0,inp0,folder in chosen}
        mapped={}
        for t,result0,inp0,folder in chosen:
            geom=readj(folder/'geometry.json'); indices=sorted(inp0['CO2_indices_zero_based']); nums=geom['numbers']
            carbon=[i for i in indices if nums[i]==6]; oxy=[i for i in indices if nums[i]==8]
            mapped[t['geometry_id']]={'C':carbon[0],'O':sorted(oxy)} if len(carbon)==1 and len(oxy)==2 else None
        run_tree=ast.parse((chosen[0][3]/'run_pair.py').read_text(encoding='utf-8'))
        code=ast.unparse(run_tree)
        init_value=None
        for node in ast.walk(run_tree):
            if isinstance(node,ast.Assign) and isinstance(node.value,ast.Constant) and type(node.value.value) in (int,float):
                if any(isinstance(target,ast.Subscript) and isinstance(target.value,ast.Name) and target.value.id=='moments' for target in node.targets): init_value=float(node.value.value)
        sampling={t['geometry_id']:{'stage':t['stage'],'frame_zero_based':t['frame_zero_based'],'stratum':t['stratum']} for t,result0,inp0,folder in chosen}
        xc=opts.get('xc'); xc=xc.get('name') if isinstance(xc,dict) else xc
        catalog[pid]={'state':float(inp['target_local_charge']),'spin':{'spinpol':opts.get('spinpol'),'fixmagmom':occ.get('fixmagmom'),'anion_initial_moment_mu_B':init_value if state=='anion' else None},
          'method':{'calculator':'GPAW','xc':xc,'mode':opts.get('mode'),'basis':opts.get('basis'),'grid_spacing_A':opts.get('h')},
          'energy':{'cdft_applied':bool(calls(run_tree,'CDFT')),'ts09_constructed':bool(calls(run_tree,'vdWTkatchenko09prl')),'ts09_final_calculator_binding':False,'ts09_in_reported_energy':'E_PBE_TS09_eV' in code},
          'geometry':{'input_selector':'task geometry JSON','pbc':None,'vacuum_A':None},'sampling':sampling,
          'raw_langevin_api_argument':None,'physical_friction_rate':None,
          'charge_region_index_set':regions,'charge_region_mapped_elements':mapped}
    protocol_ids=sorted(catalog)
    protocol_fields=['method','state','spin','energy','geometry','sampling','raw_langevin_api_argument','physical_friction_rate','charge_region_index_set','charge_region_mapped_elements']
    protocol_rows=[]
    for field in protocol_fields:
        values={pid:catalog[pid][field] for pid in protocol_ids}
        def known(v):
            if isinstance(v,dict): return all(known(x) for x in v.values())
            if isinstance(v,list): return all(known(x) for x in v)
            return v is not None
        comparable=[v for v in values.values() if field in {'state','charge_region_index_set'} or known(v)]
        different=(len(comparable)==len(values) and len({json.dumps(v,sort_keys=True,separators=(',',':')) for v in comparable})>1)
        protocol_rows.append({'field':field,'values_by_protocol':values,'different':different})
    proof('all-protocols','protocol_comparison',{'protocol_ids':protocol_ids,'compared_fields':protocol_fields},{'reported_comparisons':protocol_rows})
    state_rows=[]
    for d in sorted(Path(native).glob('attempt-*')):
        result=readj(d/'result.json'); text=(d/'gpaw.txt').read_text(); match=re.findall(r'Total magnetic moment: \(([^)]*)\)',text)
        comps=[float(x.strip()) for x in match[-1].split(',')]
        state_rows.append({'state_record_id':d.name,'magnetization_components_mu_B':comps,'local_charge_e':result['local_charge_e']})
    state_ids=[x['state_record_id'] for x in state_rows]
    for target in ('spin_ground_state','radical_identity','global_minimum','unique_physical_energy'):
        proof('state-limit-'+target,'state_inference_limit',{'state_record_ids':state_ids,'target_predicate':target},{'reported_observations':state_rows,'inference_limit':'does_not_establish'})
    prereq=[{'ensemble':e,'within_ensemble_variance_identified':False,'equilibrium_response_identified':False} for e in ensembles]
    proof('marcus-limits','marcus_identifiability',{'ensembles':ensembles,'required_population_quantity':'both'},{'reported_prerequisites':prereq})
    setting_rows=[]
    sens=marcus['setting_sensitivity']
    for x in sens:
        setting_rows.append({'geometry_id':x['geometry_id'],'base_gap_eV':x['base_gap_eV'],'tight_gap_eV':x['tight_gap_eV'],'delta_eV':x['gap_change_eV']})
    gids=sorted(x['geometry_id'] for x in sens)
    proof('settings-local','setting_scope',{'geometry_ids':gids,'claim_scope':'those_geometries'},{'reported_effects':setting_rows})
    choices=[{'ensemble':e,'k':2,'m':2} for e in ensembles]
    reuse=[t['index'] for e in ensembles for t in sorted((x for x in tasks if x['ensemble']==e and x['stage']=='production'),key=lambda x:x['stratum'])]
    design_rows=[]; total=0
    for e in ensembles:
        N=next(x['target_population_size'] for x in plan['ensembles'] if x['ensemble']==e); qn,rem=divmod(N,4); sizes=[qn+(h<rem) for h in range(4)]; k,m=2,2
        for h,Nh in enumerate(sizes):
            j=(h+1)%4
            design_rows.append({'ensemble':e,'stratum':h,'cross_stratum':j,'H':4,'N_h':Nh,'k':k,'m':m,'marginal_pi_i':(k/4)*(m/Nh),'same_stratum_pi_ij':(k/4)*m*(m-1)/(Nh*(Nh-1)),'cross_stratum_pi_ij':(k*(k-1)/12)*(m/Nh)*(m/sizes[j])})
        total+=2*k*m
    proof('followup-design-info','design_information_gain',{'target_uncertainty':'finite_population_sampling','strata':choices,'reuse_source_task_ids':reuse},{'strata':design_rows,'new_paired_state_attempts':total-2*len(reuse)})
    proof('followup-relevance','follow_up_relevance',{'target_uncertainty':'finite_population_sampling','observable':'additional_within_stratum_gaps','calculation_class':'additional_vertical_state_pairs'},{'expected_distinguishing_result':'positive_second_order_information','missing_source_quantity':'within_stratum_joint_moments'})
    claim('execution','budgeted_numerical_execution','reconstructed_from_native',{'kind':'native_ledger','id':'native_r3_source_reconstruction'},'supported',['native-audit'])
    for row in energy_rows:
        t=next(x for x in tasks if x['ensemble']==row['ensemble'] and x['frame_zero_based']==int(row['frame']) and x['stage']==row['stage'] and x['setting']==row['setting'] and x['geometry_id']==row['geometry_id'])
        claim('local-gap-'+str(t['index']),'calculated_geometry_local_gaps','reconstructed_state_pairs',{'kind':'geometry','id':t['geometry_id']},'supported',['native-audit'])
    claim('population-ranking','finite_population_K_water_ranking','not_identified',{'kind':'finite_population','id':';'.join(ensembles)},'not_established',['moments-nonid','rank-nonid']+['design-var-'+e for e in ensembles])
    claim('equilibrium','equilibrium_or_thermodynamic_claim','not_identified',{'kind':'finite_population','id':';'.join(ensembles)},'not_established',['all-protocols']+['design-var-'+e for e in ensembles])
    claim('marcus','marcus_parameters_and_barriers','not_identified',{'kind':'finite_population','id':';'.join(ensembles)},'not_established',['marcus-limits'])
    for g in gids:
        claim('setting-local-'+g,'numerical_setting_generalization','local_effect_only',{'kind':'geometry','id':g},'supported',['settings-local'])
    claim('setting-error-bound','numerical_setting_generalization','no_total_error_bound',{'kind':'geometry_set','id':';'.join(gids)},'supported',['settings-local'])
    contrast_scope=';'.join(f"{x['left_ensemble']}-minus-{x['right_ensemble']}" for x in sorted(contrast_pairs,key=lambda x:(x['left_ensemble'],x['right_ensemble'])))
    claim('convention-comparison','energy_convention_ranking_effect','source_comparison',{'kind':'cross_ensemble_contrast','id':contrast_scope},'supported',['source-conventions-free','source-conventions-extrapolated'])
    claim('convention-no-flip','energy_convention_ranking_effect','no_source_flip',{'kind':'cross_ensemble_contrast','id':contrast_scope},'supported',['source-conventions-free','source-conventions-extrapolated'])
    claim('follow-up','follow_up_design','targets_named_uncertainty',{'kind':'future_design','id':'finite_population_sampling'},'supported',['followup-design-info','followup-relevance'])
    claim('state-identity','chemical_state_identity','not_established_from_state_observables',{'kind':'state_pair_set','id':';'.join(state_ids)},'not_established',['state-limit-spin_ground_state','state-limit-radical_identity','state-limit-global_minimum'])
    claim('physical-energy','physical_energy_interpretation','no_unique_diabatic_or_free_energy_established',{'kind':'energy_convention','id':'R3-minus-extrapolated;R3-minus-free'},'not_established',['source-conventions-free','source-conventions-extrapolated','state-limit-unique_physical_energy','all-protocols'])
    claim('protocol-distinction','method_protocol_distinction','protocols_distinct',{'kind':'protocol_record_set','id':';'.join(protocol_ids)},'supported',['all-protocols'])
    return {'schema':'case04-scientific-claims/v2.2',
      'status_layers':{'budgeted_numerical_execution':'supported','calculated_geometry_local_gaps':'supported','chemical_state_and_physical_energy_interpretation':'not_established','finite_population_K_water_ranking':'not_established','equilibrium_or_thermodynamic_claim':'not_established','marcus_parameters_and_barriers':'not_established'},
      'quantities':quantities,'assumptions':[],'proofs':proofs,'claims':claims,
      'follow_up':{'target_uncertainty':'finite_population_sampling','observable':'additional_within_stratum_gaps','calculation_class':'additional_vertical_state_pairs','design':{'proof_id':'followup-design-info'},'proposal_details':{'design_proof_id':'followup-design-info'},'missing_prerequisites':['within_stratum_joint_moments'],'distinguishable_outcomes':['within_stratum_variance_is_heterogeneous','within_stratum_variance_is_similar'],'resource_estimate':{'additional_state_attempts':total-2*len(reuse),'planned_trajectory_steps':None,'estimated_cpu_hours':None,'estimated_wall_hours':None,'cost_basis':'not_estimated'},'proof_ids':['followup-design-info','followup-relevance']}}

def run(assets, out, solution):
    assets, out, solution = Path(assets), Path(out), Path(solution)
    tasks_path = assets/'revision3/tasks.json'
    plan_path = assets/'revision3/sampling_plan.json'
    budget_path = assets/'OS_budget.json'
    tasks, plan, budget = readj(tasks_path), readj(plan_path), readj(budget_path)
    # Immutable source-identity hashes are provenance inputs, never scientific answer values.
    source_record = {'schema': 'case04-source-manifest/v1', 'case_id': 'case-04-outer-sphere-budgeted', 'budget_revision': 3, 'source_identity': 'frozen revision-3 tasks, sampling plan, geometry inputs, recovered native results/logs, and public source assets', 'new_scientific_calculations': 0, 'runtime_inputs_sha256': {'runtimes/hpc/case04/review-v3/geometries/2K_anion-frame-3617.json': 'ad73486fe36f84434d8108f11917a6164acb3f4e24a3ea140584649a0926298d', 'runtimes/hpc/case04/review-v3/geometries/2K_anion-frame-8357.json': '5d13f289e9c3db80591bdea0d86b69239386bd908bde366179cb3a00064ced6f', 'runtimes/hpc/case04/review-v3/geometries/2K_neutral-frame-3775.json': '2c35f8e589e45429ec700afc8299f6516a7aea04d89cee63be426b514f0717dc', 'runtimes/hpc/case04/review-v3/geometries/2K_neutral-frame-6103.json': 'ae1865e7f55254ccf573c4f2304b22f779c1b212aee3768693cdc78c36b39f5c', 'runtimes/hpc/case04/review-v3/geometries/water_anion-frame-2620.json': '4c4e22446720a0fceff4eaa69a7f22840c361ef4619b3b916b5fa01020e7ad0e', 'runtimes/hpc/case04/review-v3/geometries/water_anion-frame-4274.json': 'c2f611aea460078337f85350abe6feb3e30f9df91f73f345d06ecb09a94beb74', 'runtimes/hpc/case04/review-v3/geometries/water_neutral-frame-2557.json': '7801f4a0f0704147d76dcf65e3635e39dc1ec3f2b3ef848527a58d33a55b8b68', 'runtimes/hpc/case04/review-v3/geometries/water_neutral-frame-9627.json': '821bea8809de8be9cab0ad57244a09f06d1817db28e404d2a56ccd4312f3f355', 'runtimes/hpc/case04/review-v3/sampling_plan.json': 'a68634338e8a278e1b2412a9795983ad06b0ea7193581d40715a59231db0645a', 'runtimes/hpc/case04/review-v3/tasks.json': '89b32d3b6b1056b569d7fbb8da2a5db10724ad09ea00d8a0a7d233a09ec3887c'}, 'public_source_inputs_sha256': {'inputs/OS_budget.json': 'db96c1eff87bf2e743de85ddcafa397945ee0c2556873a38be0c7674383d43bf', 'inputs/methods.json': '5b20ce1f3cc3cd0b8d80948a1651d6178e2f14f58364b0b05e95638c523f3a3c', 'packages/case-04-outer-sphere-budgeted/environment/assets/2K_CO2/10ps.traj': '32c2068d54decc14405242701748414546f31bab8f10d5da03b3d5757bcc740e', 'packages/case-04-outer-sphere-budgeted/environment/assets/2K_CO2/calc.py': '75e6bf7194c11015d1a9f2731b2f806637ac45bc2fafaf08f8a80bde3d0f1026', 'packages/case-04-outer-sphere-budgeted/environment/assets/2K_CO2anion/10ps.traj': '91c9adc9623aac21d5e88cd4e9b68d8c585cae4dba8d8d195c011c1ac85f1fca', 'packages/case-04-outer-sphere-budgeted/environment/assets/2K_CO2anion/calc.py': '068bb22c7828c3d177a3427a2ffefd9cacf4e989c8762a1748e77009934e0d93', 'packages/case-04-outer-sphere-budgeted/environment/assets/OS_budget.json': 'db96c1eff87bf2e743de85ddcafa397945ee0c2556873a38be0c7674383d43bf', 'packages/case-04-outer-sphere-budgeted/environment/assets/computegaps.py': 'feb976d3628dfb07a1fd8d8585ad28aeb020a3abd1030e5313422073638b6f69', 'packages/case-04-outer-sphere-budgeted/environment/assets/methods.json': '5b20ce1f3cc3cd0b8d80948a1651d6178e2f14f58364b0b05e95638c523f3a3c', 'packages/case-04-outer-sphere-budgeted/environment/assets/water_CO2/10ps.traj': '5f631a450d42ff048ed678facfe696833679ef5a99cb85aec329d771cc372ce5', 'packages/case-04-outer-sphere-budgeted/environment/assets/water_CO2/calc.py': '34c8679393f7ac839d7c42df8cfb6f0714b458f3980a56574e9b36a2ca2e3d77', 'packages/case-04-outer-sphere-budgeted/environment/assets/water_CO2anion/10ps.traj': '98c407cd2dd7457891488ffb95fae666dad9a6f7ec7490e2f3dfedf5ccd91b28', 'packages/case-04-outer-sphere-budgeted/environment/assets/water_CO2anion/calc.py': '4b0702b9040b2645d70647b4f98dd2a2383d52c18139a77dc28515bfba64b48c', 'raw_data/downloads/computegaps.py': 'feb976d3628dfb07a1fd8d8585ad28aeb020a3abd1030e5313422073638b6f69', 'raw_data/unpacked/2K_CO2_cDFTMD-d52c3d4cdd06/2K_CO2_cDFTMD/calc.py': '75e6bf7194c11015d1a9f2731b2f806637ac45bc2fafaf08f8a80bde3d0f1026', 'raw_data/unpacked/2K_CO2anion_cDFTMD-c80cc01a8b9c/2K_CO2anion_cDFTMD/calc.py': '068bb22c7828c3d177a3427a2ffefd9cacf4e989c8762a1748e77009934e0d93', 'raw_data/unpacked/water_CO2_cDFTMD-037c1b15361b/water_CO2_cDFTMD/calc.py': '34c8679393f7ac839d7c42df8cfb6f0714b458f3980a56574e9b36a2ca2e3d77', 'raw_data/unpacked/water_CO2anion_cDFTMD-fa649a71de58/water_CO2anion_cDFTMD/calc.py': '4b0702b9040b2645d70647b4f98dd2a2383d52c18139a77dc28515bfba64b48c', 'analysis/revision3/spin-audit/energy-convention-audit.json': '9ce35347c4d137e4288812af3e2741542831666b5574904781832d46eb5a3d1b'}, 'native_evidence_sha256': {'analysis/revision3/native/attempts.jsonl': '4e8764e1dc568b0a2a71d137e7e3029f37d9796f05b3da0731f03b9da5d80d5e', 'analysis/revision3/native/README.md': '323917aab452043b23d6f895461a52b53ea861534c2d264aae6868a0c78bf557', 'analysis/revision3/native/attempt-001/cdft.txt': '7e933b931008dc6e360b336492fc4291053942572844059b8d8ee5530fbbfa5f', 'analysis/revision3/native/attempt-001/geometry.json': '7801f4a0f0704147d76dcf65e3635e39dc1ec3f2b3ef848527a58d33a55b8b68', 'analysis/revision3/native/attempt-001/gpaw.txt': '8ef4b1cb6c5b9f133c4e84781393ab6b771ea1d60075f1e216c156e3c28953f6', 'analysis/revision3/native/attempt-001/input.json': '664261ac5f5d00a1830f49188e73c89be82a6ee10b5eba507d0bb22c58430468', 'analysis/revision3/native/attempt-001/result.json': 'fa7833668d7203bb0df1c3302bf3edcdbc004e8cb5c88790d9688ba731b3bfd3', 'analysis/revision3/native/attempt-001/run_pair.py': '81484a0f64849458483997b9642908796db27db62d238e888aa0ac6092f3202c', 'analysis/revision3/native/attempt-001/ts09.txt': '0cb12e6945800a0d91ac051ba729576c742b18d194f3480380f6f12734bdbde8', 'analysis/revision3/native/attempt-002/cdft.txt': 'd1faa3e250a9e2bd531c3affd2d9ba2a91f3bc6ddd9a1754bedcbfe3d6246d82', 'analysis/revision3/native/attempt-002/geometry.json': '821bea8809de8be9cab0ad57244a09f06d1817db28e404d2a56ccd4312f3f355', 'analysis/revision3/native/attempt-002/gpaw.txt': 'd083bc1fe1b22b30caa94eb0da36e0a379ba62053571f7706249c5c624e8b023', 'analysis/revision3/native/attempt-002/input.json': '92ea528d6c73b5c2900f77724fc265e4b47faefba31179f34c64b520cab7a335', 'analysis/revision3/native/attempt-002/result.json': '18a9721c1d89487cbf299d97d2a9844ee52a55b1d5ef4a02efae54d549c3b67d', 'analysis/revision3/native/attempt-002/run_pair.py': '81484a0f64849458483997b9642908796db27db62d238e888aa0ac6092f3202c', 'analysis/revision3/native/attempt-002/ts09.txt': '9b2add2c6737f705a56fdb7a228817e821f3b9ffcb8f2914dc7259b34995584e', 'analysis/revision3/native/attempt-003/cdft.txt': 'a6cb22f901940508a945dc7e08bbf51f37eb5638fe62e9a084d3bf087eb94f8c', 'analysis/revision3/native/attempt-003/geometry.json': '7801f4a0f0704147d76dcf65e3635e39dc1ec3f2b3ef848527a58d33a55b8b68', 'analysis/revision3/native/attempt-003/gpaw.txt': '0cd4aee6aae110064d4b06115853c7f66ad373e002693f9f591fb7f4cc27fb79', 'analysis/revision3/native/attempt-003/input.json': '938e4e86e8a532d7c61904ccb60095eb1fa63f2b66dd3c8dba229869c99b9d1c', 'analysis/revision3/native/attempt-003/result.json': 'd6706debdb21b3e7db543f56db97a00f54ac4a325e2571ddc6ba9c5b2075453b', 'analysis/revision3/native/attempt-003/run_pair.py': '81484a0f64849458483997b9642908796db27db62d238e888aa0ac6092f3202c', 'analysis/revision3/native/attempt-003/ts09.txt': '6ec6b287a520bcba7428199d09aad43c32dfe855dced98efc19aba15dbecf941', 'analysis/revision3/native/attempt-004/cdft.txt': '610fd54c9da909b73d48b8379726f3d9085d8fc910dd9606d10e97316dcb45e9', 'analysis/revision3/native/attempt-004/geometry.json': '821bea8809de8be9cab0ad57244a09f06d1817db28e404d2a56ccd4312f3f355', 'analysis/revision3/native/attempt-004/gpaw.txt': '370a3d298fa1d392ab8d724d4f11789832778eb207b39fd5fe05fafeb355fcaf', 'analysis/revision3/native/attempt-004/input.json': '6f7bddd6f00b25b7ccd78f599efd38ce8e71eea505966e6d7968054fa841a5b7', 'analysis/revision3/native/attempt-004/result.json': 'd06301946f911d7a18e6284e53610cbe91b0e07e82e19ea0b4f3eda39b336eb3', 'analysis/revision3/native/attempt-004/run_pair.py': '81484a0f64849458483997b9642908796db27db62d238e888aa0ac6092f3202c', 'analysis/revision3/native/attempt-004/ts09.txt': '78eea28f8579c024477f9747c4b8e3eaff406f94ffb42a9b16604cee2381a2fa', 'analysis/revision3/native/attempt-005/cdft.txt': '9d7f95086a81f9b7470507a8a58182454bd16e8e15fbf468ced8af134580e7e2', 'analysis/revision3/native/attempt-005/geometry.json': '4c4e22446720a0fceff4eaa69a7f22840c361ef4619b3b916b5fa01020e7ad0e', 'analysis/revision3/native/attempt-005/gpaw.txt': '76f6af90e235e203636b70f2fe780090be9c0baa5d9c21d369a8e635643285f3', 'analysis/revision3/native/attempt-005/input.json': 'bad09ac0decf99438a946c92e1d1b415f0f73c7b773c13415aa66f79172d7934', 'analysis/revision3/native/attempt-005/result.json': '92be4021e1c1a830fb1299baa45341b3889cf62941d995f16a8e8381b98a84c1', 'analysis/revision3/native/attempt-005/run_pair.py': '81484a0f64849458483997b9642908796db27db62d238e888aa0ac6092f3202c', 'analysis/revision3/native/attempt-005/ts09.txt': '0eaf3e7d4b55d24e1216286214f648cc6ce8f528717bdc90803a4541dd901bca', 'analysis/revision3/native/attempt-006/cdft.txt': '305b434fc2405f095049436ac8b7a1478871650b64a4657bcc169875f3c1969c', 'analysis/revision3/native/attempt-006/geometry.json': 'c2f611aea460078337f85350abe6feb3e30f9df91f73f345d06ecb09a94beb74', 'analysis/revision3/native/attempt-006/gpaw.txt': '55e39e0b53d2e18ec323009831dde9d073908585f515e43cca59c501ff11a0ae', 'analysis/revision3/native/attempt-006/input.json': '5a3676e6f3918cd8d936110aab2171de4d0e3dd30f150cf6ffa7151ba6f0a504', 'analysis/revision3/native/attempt-006/result.json': '3360318dd3107a38c6910d5f783da424be00f14207f064b72bea2d37ef24805f', 'analysis/revision3/native/attempt-006/run_pair.py': '81484a0f64849458483997b9642908796db27db62d238e888aa0ac6092f3202c', 'analysis/revision3/native/attempt-006/ts09.txt': '29aaccaeb2a77d319908dc868fb8fe9205f65a6935b9a48f5c62ea80ddea65aa', 'analysis/revision3/native/attempt-007/cdft.txt': 'ad7f9709681c12d7b2ce47cba59bdc33a0a6a9af84b98f1e36f5c63d0178bab7', 'analysis/revision3/native/attempt-007/geometry.json': 'c2f611aea460078337f85350abe6feb3e30f9df91f73f345d06ecb09a94beb74', 'analysis/revision3/native/attempt-007/gpaw.txt': 'a3aab4b5fc469df067fbd6af3b2ec0e14172f7b20f965e381db830a5d3a928a8', 'analysis/revision3/native/attempt-007/input.json': 'cd5e1b787bc976b6323ff83bfe1fa8c911b2e16a780fe62232b99b3ccd30ecb5', 'analysis/revision3/native/attempt-007/result.json': '8ec9463f80a553e8cc72d359a34ae6bd3d3314845702a88409e010e41c6f4188', 'analysis/revision3/native/attempt-007/run_pair.py': '81484a0f64849458483997b9642908796db27db62d238e888aa0ac6092f3202c', 'analysis/revision3/native/attempt-007/ts09.txt': '276b7d1224d26706cb8fa6180462425832b3394ec343f4a3fbfc08c247ef399e', 'analysis/revision3/native/attempt-008/cdft.txt': 'db7190fc4e9fc43bead7b5e20dc24ab552b43e652c313b84c30b7504dc7be5d8', 'analysis/revision3/native/attempt-008/geometry.json': '4c4e22446720a0fceff4eaa69a7f22840c361ef4619b3b916b5fa01020e7ad0e', 'analysis/revision3/native/attempt-008/gpaw.txt': '0dbc85c8067c86a0fd97897afc91c7bdb35585b61ea4c889a134e55369c2f0ef', 'analysis/revision3/native/attempt-008/input.json': 'c44f27d12a765989dd31b4b26336246494581cc91087feddaec7faca2e375b9c', 'analysis/revision3/native/attempt-008/result.json': 'af895aa6b6a2ccdb2e37fd491242d635a09a2c6dcf3891293cc727ff80708648', 'analysis/revision3/native/attempt-008/run_pair.py': '81484a0f64849458483997b9642908796db27db62d238e888aa0ac6092f3202c', 'analysis/revision3/native/attempt-008/ts09.txt': '87acd0c67b02ede71a0fffda5fca4cf2ed27c0694dd1c127cb1a421c3afb8e93', 'analysis/revision3/native/attempt-009/cdft.txt': '738e1179675ca68f24ead0dc38ddd29dafe5d5871c9c647fdf8771a166a27f39', 'analysis/revision3/native/attempt-009/geometry.json': '2c35f8e589e45429ec700afc8299f6516a7aea04d89cee63be426b514f0717dc', 'analysis/revision3/native/attempt-009/gpaw.txt': '9917f75f681d97389b6bb61aa17bb2d49e3c05394053af6ab9a28ad2206dc95c', 'analysis/revision3/native/attempt-009/input.json': 'aebe1df78cfaf85bd53393f7fd82b2f07e2a85e7392c75e5cd7db1f70269ac8d', 'analysis/revision3/native/attempt-009/result.json': 'f1a36d4d1b91013278efdcd1ee1986f431d3ec4ff29019ac626be1b4ee760af6', 'analysis/revision3/native/attempt-009/run_pair.py': '81484a0f64849458483997b9642908796db27db62d238e888aa0ac6092f3202c', 'analysis/revision3/native/attempt-009/ts09.txt': 'b4ae44b75b50a99810758f279c1cd76fdacd53e74844dd2405fe18c57a18fe61', 'analysis/revision3/native/attempt-010/cdft.txt': '3d58fe2b31ac3ce78c85c47db2fac358425b2774b757f193be562bb93e90f3e8', 'analysis/revision3/native/attempt-010/geometry.json': 'ae1865e7f55254ccf573c4f2304b22f779c1b212aee3768693cdc78c36b39f5c', 'analysis/revision3/native/attempt-010/gpaw.txt': '0aecb0627a5418af8543e00bb178d6750f8b7a6b9060ea9f3ef504d995854096', 'analysis/revision3/native/attempt-010/input.json': 'd3ad95d5cebabd0319910014300a1107772c75d9d336c3065a1a728458b709b3', 'analysis/revision3/native/attempt-010/result.json': '987a40de210def1f3b553c28c0356b37aac38f1d7a39d503753fe14a4b8426a1', 'analysis/revision3/native/attempt-010/run_pair.py': '81484a0f64849458483997b9642908796db27db62d238e888aa0ac6092f3202c', 'analysis/revision3/native/attempt-010/ts09.txt': 'a4c2f9ccf037cef71b5b4e2f176a56cd3829f6e7cf04b13795b83f92e5d1066f', 'analysis/revision3/native/attempt-011/cdft.txt': 'a613a708c8dc08bffd6d04f71b758b612258f17643b55c8b8eeb5e7c8778e1bd', 'analysis/revision3/native/attempt-011/geometry.json': 'ae1865e7f55254ccf573c4f2304b22f779c1b212aee3768693cdc78c36b39f5c', 'analysis/revision3/native/attempt-011/gpaw.txt': 'e5b2a1ab81ae981ef5b35e6030f957d71d558f6ec901c2cb28154514dc0042af', 'analysis/revision3/native/attempt-011/input.json': 'd830b977649755f48a0971ea4b694307fac96a0a828abb137a32ea5f5d64e9a9', 'analysis/revision3/native/attempt-011/result.json': '8239f4cf7151bff9bc794c86c07d9cf2549513bc6c432474f80bd27900f54c7e', 'analysis/revision3/native/attempt-011/run_pair.py': '81484a0f64849458483997b9642908796db27db62d238e888aa0ac6092f3202c', 'analysis/revision3/native/attempt-011/ts09.txt': '2d2837386a0bc7aec22e2d10446714c3edc747c903942e56f3191960dc84c12c', 'analysis/revision3/native/attempt-012/cdft.txt': '29325fb630483e88ebabc27b4de613ef4384a20b341c02386d2f7e6f7e5c1dda', 'analysis/revision3/native/attempt-012/geometry.json': '2c35f8e589e45429ec700afc8299f6516a7aea04d89cee63be426b514f0717dc', 'analysis/revision3/native/attempt-012/gpaw.txt': 'c8a9c2f48dc2ed260e5fa36623d46b68e45ad816db867a32af9445a3a7ace3d8', 'analysis/revision3/native/attempt-012/input.json': 'f5cfc2d80bd81314b54fc86b1bb5123ce53f98725ae0ec39cbfc25c5aeab0da3', 'analysis/revision3/native/attempt-012/result.json': '65ddc3f9e6529d49bab3498f05a74bd6df5feaf0aab2b942ba5d9de2f64cd832', 'analysis/revision3/native/attempt-012/run_pair.py': '81484a0f64849458483997b9642908796db27db62d238e888aa0ac6092f3202c', 'analysis/revision3/native/attempt-012/ts09.txt': '089d5628408e9c99eded3f015871c5832f2f9fbb19018a6315d49f8e9bc35e1e', 'analysis/revision3/native/attempt-013/cdft.txt': '759b13a263389705f312fd3cd32ef6a7cccd2940b7cd7e536156938bc9b1c89d', 'analysis/revision3/native/attempt-013/geometry.json': 'ad73486fe36f84434d8108f11917a6164acb3f4e24a3ea140584649a0926298d', 'analysis/revision3/native/attempt-013/gpaw.txt': 'bd477aee1b48f310bf92d1cb4e5a70a9257e168d96037c7df68a9ba38709c86c', 'analysis/revision3/native/attempt-013/input.json': '3ec8f08fad35bb9e02ce2c86b6d9996234b881ad986848e7f9587bac0d2bd559', 'analysis/revision3/native/attempt-013/result.json': '9c35cebcda3d8ab2f4a117f053f9ffe01f0ac1290309a7c46a37e95ed7c2dbf8', 'analysis/revision3/native/attempt-013/run_pair.py': '81484a0f64849458483997b9642908796db27db62d238e888aa0ac6092f3202c', 'analysis/revision3/native/attempt-013/ts09.txt': '5e9445b86c19d23609c6afbabf33cec62c43a40704c892472585f8bce76ea148', 'analysis/revision3/native/attempt-014/cdft.txt': '9ccae9c436b34ecec54789c2d775a4b47f350f3ddcd6f2ea24d1990a75db24f9', 'analysis/revision3/native/attempt-014/geometry.json': '5d13f289e9c3db80591bdea0d86b69239386bd908bde366179cb3a00064ced6f', 'analysis/revision3/native/attempt-014/gpaw.txt': '6f059dd5079aed883e723d55d311df79e6e14584117017e63f9d76609f4c079a', 'analysis/revision3/native/attempt-014/input.json': '88cd50a7ae8b2d818bc774c71b542176147077b53f02b027cfca7becff6268b4', 'analysis/revision3/native/attempt-014/result.json': 'd080a3e0712304dc98f5461d1261cd66306b50ae4846407fc91acc247cab1d3a', 'analysis/revision3/native/attempt-014/run_pair.py': '81484a0f64849458483997b9642908796db27db62d238e888aa0ac6092f3202c', 'analysis/revision3/native/attempt-014/ts09.txt': '0028d04d2dbfc45c8b32edc9caf5bc639cdea7b19b15def4865c35dfd6a4f151', 'analysis/revision3/native/attempt-015/cdft.txt': 'b52b8f19d52caadf4cacf25e2b9331833edca94323833d5e4839ecf3bd00293f', 'analysis/revision3/native/attempt-015/geometry.json': 'ad73486fe36f84434d8108f11917a6164acb3f4e24a3ea140584649a0926298d', 'analysis/revision3/native/attempt-015/gpaw.txt': '42434eb885ab3138aa36d5084509240beb3d24fcead32a227d43474d39b0f449', 'analysis/revision3/native/attempt-015/input.json': '45733ca1585b97d7d3f605b2ed35ed2f7fbc413fdc6a0c481562dcfeca7a8a39', 'analysis/revision3/native/attempt-015/result.json': 'aabef5c191638cfc9c39dc666b8d91a8c9784ea64c161be758de7a0a1cd33ab0', 'analysis/revision3/native/attempt-015/run_pair.py': '81484a0f64849458483997b9642908796db27db62d238e888aa0ac6092f3202c', 'analysis/revision3/native/attempt-015/ts09.txt': '98ee79ca2ec8acbe41174267a7df8fc00ece6aa41becf381fbdd3f46c008bfc9', 'analysis/revision3/native/attempt-016/cdft.txt': '52b845e6adb60f7f226c55dee3ad9d42e432ab5501b2ea6b6abf4f26836168b7', 'analysis/revision3/native/attempt-016/geometry.json': '5d13f289e9c3db80591bdea0d86b69239386bd908bde366179cb3a00064ced6f', 'analysis/revision3/native/attempt-016/gpaw.txt': '6204298a33155ef668130bb7cc429654026e0faa05a37819ac3b8123756ad516', 'analysis/revision3/native/attempt-016/input.json': 'e3fe87ab024e1ef553cd2651896c9a1135cb65f8ff3613742270d934367eddb1', 'analysis/revision3/native/attempt-016/result.json': '6887e1370b619aaf5aa027fd3ef89ff24f72d70b0b5fca2ae1af131704aa62f9', 'analysis/revision3/native/attempt-016/run_pair.py': '81484a0f64849458483997b9642908796db27db62d238e888aa0ac6092f3202c', 'analysis/revision3/native/attempt-016/ts09.txt': '69d47f5a9e453ba39ea355e0fa469c90b9cf75873b3cc5b359b80ecf23035c2c', 'analysis/revision3/native/attempt-017/cdft.txt': 'e6b50ff5447bf460063d3c3929b1cb80e0611cbf706cdd8a7dd1699a659ce4f1', 'analysis/revision3/native/attempt-017/geometry.json': '4c4e22446720a0fceff4eaa69a7f22840c361ef4619b3b916b5fa01020e7ad0e', 'analysis/revision3/native/attempt-017/gpaw.txt': '5e19abac5d027d8174e016ad03e027b0d968af0a6faadd84bad2225ae340527b', 'analysis/revision3/native/attempt-017/input.json': '0ed9175ff199f0d82cb49d11c9b0722de54572b7283238309014e64e7123102c', 'analysis/revision3/native/attempt-017/result.json': '57b9f32954cf678afaa6a4d3828ca4c7db2906c1ae7535145b6a161ed7e21ce0', 'analysis/revision3/native/attempt-017/run_pair.py': '81484a0f64849458483997b9642908796db27db62d238e888aa0ac6092f3202c', 'analysis/revision3/native/attempt-017/ts09.txt': 'd0135abc5e18bb94a8534c66326b759f09deb22deabe56ebb718c94eb701e363', 'analysis/revision3/native/attempt-018/cdft.txt': '45c89018acc7a59f700d336f1a8f598050675d26566b54b2cc8395b765676d24', 'analysis/revision3/native/attempt-018/geometry.json': 'ad73486fe36f84434d8108f11917a6164acb3f4e24a3ea140584649a0926298d', 'analysis/revision3/native/attempt-018/gpaw.txt': 'eca8e94b5f4add8eccb71bb15c1d651a53632def9d0b57cbec162ef7acb58134', 'analysis/revision3/native/attempt-018/input.json': '5c36bd165c2f008f4773db66dff8b5772f93886ddbe512dcf746455f62013b99', 'analysis/revision3/native/attempt-018/result.json': '14992ca7cff309b6c0ca79ea06e7ea514d382ab459a966ac43ab662a8390a2b8', 'analysis/revision3/native/attempt-018/run_pair.py': '81484a0f64849458483997b9642908796db27db62d238e888aa0ac6092f3202c', 'analysis/revision3/native/attempt-018/ts09.txt': '849b7d5ff5f6933d95594d98d72d6e9021c08518cb1bb8e29ccc02a6be00849d', 'analysis/revision3/native/attempt-019/cdft.txt': '706cd21a2f9ccc1ce87053bd6ffd6d7f75c578e9fc372b9b470b437dcf7d08ba', 'analysis/revision3/native/attempt-019/geometry.json': '4c4e22446720a0fceff4eaa69a7f22840c361ef4619b3b916b5fa01020e7ad0e', 'analysis/revision3/native/attempt-019/gpaw.txt': 'ea23fe8cf690272fae59b9dfc5e9ce8c7ca29d151c9bd3f5c317b5aa73a897a9', 'analysis/revision3/native/attempt-019/input.json': 'd867bc84a4533d7d095694b9ab6b5b799ddf6af8f03184172507ce06196c84c0', 'analysis/revision3/native/attempt-019/result.json': 'b4cff0da96afe18424f6b557f6dd7b720309019c5284bdcca7950816431b594c', 'analysis/revision3/native/attempt-019/run_pair.py': '81484a0f64849458483997b9642908796db27db62d238e888aa0ac6092f3202c', 'analysis/revision3/native/attempt-019/ts09.txt': '4a81a282d3294ae1feaebefe7cab2c67b8b307a7be0a4359e02a55900bc196e5', 'analysis/revision3/native/attempt-020/cdft.txt': '23f3923817eeb102b1b5f4f3e8fe0a60c512e89f08639498a65f7d98416672cf', 'analysis/revision3/native/attempt-020/geometry.json': 'ad73486fe36f84434d8108f11917a6164acb3f4e24a3ea140584649a0926298d', 'analysis/revision3/native/attempt-020/gpaw.txt': 'f2e2fed6515be15418c28cd8c3522fbced30e2548b5a716205d092cd452cc6ba', 'analysis/revision3/native/attempt-020/input.json': '3ccc15b1ea3f0e5d3e80c54b8088c8bfb682374c048e39cd16a3304a91bcd92d', 'analysis/revision3/native/attempt-020/result.json': '604ea3478d94a7e12266910ce6bd4cdaafacfd1775c1e3f9bf98f517690f7a35', 'analysis/revision3/native/attempt-020/run_pair.py': '81484a0f64849458483997b9642908796db27db62d238e888aa0ac6092f3202c', 'analysis/revision3/native/attempt-020/ts09.txt': 'ade1860fa1535d08fab4d2cf8a46358af54ddd2d7a6d04bd505f40b3fdb6df20'}, 'native_attempt_records': 20, 'geometry_count': 8, 'paired_rows': 10, 'author_trajectory_frame_audit_sha256': '424fe896fdb7c08b4b0a182629c5e084b37ae0d39227ffe094db1aa3237308c4', 'source_binding': 'project-local pinned sources; portable only within this project evidence bundle'}
    public_hashes = check_public_hashes(assets, source_record)
    out.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='case04-source-recompute-') as tmp_s:
        tmp = Path(tmp_s)
        work = tmp/'analysis/revision3'
        native = work/'native'
        native_hashes = extract_archive(assets/'r3-native-raw.tar.gz', native, source_record['native_evidence_sha256'])
        runtime = tmp/'runtimes/hpc/case04/review-v3'
        runtime.mkdir(parents=True)
        shutil.copy2(tasks_path, runtime/'tasks.json')
        shutil.copy2(plan_path, runtime/'sampling_plan.json')
        (tmp/'inputs').mkdir(exist_ok=True)
        shutil.copy2(assets/'methods.json',tmp/'inputs/methods.json')
        shutil.copy2(solution/'analysis.py', work/'analysis.py')
        run_analysis = subprocess.run([sys.executable, str(work/'analysis.py')], cwd=tmp, capture_output=True, text=True, timeout=120)
        if run_analysis.returncode:
            raise RuntimeError('native gap analysis failed: '+run_analysis.stderr[-1600:])
        audit_dir = work/'spin-audit'
        audit_dir.mkdir()
        shutil.copy2(solution/'reference/audit_energy_convention.py', audit_dir/'audit_energy_convention.py')
        run_audit = subprocess.run([sys.executable, str(audit_dir/'audit_energy_convention.py')], cwd=tmp, capture_output=True, text=True, timeout=120)
        if run_audit.returncode:
            raise RuntimeError('printed-energy audit failed: '+run_audit.stderr[-1600:])
        energy_audit = readj(audit_dir/'energy-convention-audit.json')
        design = sampling_audit(plan, tasks)
        diagnostics = standard_diagnostics(tasks, energy_audit, plan)
        marcus = readj(work/'marcus.json')
        energy_rows=list(csv.DictReader((work/'energy_gaps.csv').open(newline='')))
        claims = build_proof_claims(assets, marcus, tasks, plan, diagnostics, energy_audit, native, energy_rows)
        # Verify all frozen frame geometries against task hashes and any present public source.
        verified_geometry_hashes = {}
        for task in tasks:
            result_path = next((p for p in native.glob('attempt-*/result.json')
                                if readj(p).get('task_index') == task['index']), None)
            if result_path is None:
                raise ValueError('native geometry/task evidence missing')
            geometry = result_path.parent/'geometry.json'
            if digest(geometry) != task['geometry_sha256']:
                raise ValueError('task geometry SHA-256 mismatch: '+task['geometry_id'])
            verified_geometry_hashes[task['geometry_path']] = digest(geometry)
        shutil.copytree(native, out/'native', dirs_exist_ok=True)
        for name in ('energy_gaps.csv', 'marcus.json'):
            shutil.copy2(work/name, out/name)
        shutil.copy2(solution/'analysis.py', out/'analysis.py')
        (out/'sampling_plan.json').write_text(json.dumps(plan, indent=2, ensure_ascii=False)+'\n')
        (out/'sampling-design-audit.json').write_text(json.dumps(design, indent=2, ensure_ascii=False)+'\n')
        (out/'standard-electronic-gap-diagnostics.json').write_text(json.dumps(diagnostics, indent=2, ensure_ascii=False)+'\n')
        emit_csv(diagnostics['rows'], out/'standard-electronic-gap-diagnostics.csv')
        native_results = [readj(p) for p in native.glob('attempt-*/result.json')]
        attempts = len(native_results)
        stages = {name: sum(t['stage'] == name for t in tasks) for name in ('production', 'sensitivity')}
        budget_doc = {'schema': 'case04-budget-interpretation/v1', 'budget_revision': budget['budget_revision'],
            'approved_attempt_cap': budget['max_electronic_state_attempts'], 'ledger_state_attempt_reservations': attempts,
            'base_attempts': stages['production']*2, 'tight_replay_attempts': stages['sensitivity']*2,
            'unconsumed_reserved_attempts': budget['max_electronic_state_attempts']-attempts,
            'counting_rule': 'proof:native-audit',
            'native_ledger_records': attempts, 'unique_task_state_records': attempts,
            'interpretation': 'proof:native-audit',
            'source_attempt_accounting_wording': budget['attempt_accounting'], 'source_approved_scope': 'proof:native-audit',
            'accounting_interpretation': 'proof:native-audit'}
        (out/'budget-interpretation.json').write_text(json.dumps(budget_doc, indent=2, ensure_ascii=False)+'\n')
        decisions = [
          ('proof:rank-nonid', 'proof:moments-nonid'),
          ('proof:native-audit', 'proof:native-audit'),
          ('proof:design-var-2K_neutral', 'proof:design-var-2K_neutral'),
          ('proof:native-audit', 'proof:native-audit'),
          ('proof:all-protocols', 'proof:all-protocols'),
          ('proof:source-conventions-free', 'proof:source-conventions-free')]
        latest_result = max(native_results, key=lambda r: r.get('completed_utc', 0))
        decision_doc = {'case_id': budget['case_id'], 'budget_revision': budget['budget_revision'], 'job_id': str(latest_result['slurm_job_id']),
            'analysis_date': datetime.fromtimestamp(latest_result['completed_utc'],timezone.utc).date().isoformat(), 'new_calculations_submitted': 0,
            'sampling_design': 'stratified_equal_probability_two_of_four', 'observed_results': attempts,
            'valid_pair_summaries': len(tasks), 'base_geometries': stages['production'], 'tight_replays': stages['sensitivity'],
            'attempt_cap': budget['max_electronic_state_attempts'], 'attempts_recorded': attempts,
            'decisions': [{'step': i+1, 'decision': d, 'reason': r} for i, (d, r) in enumerate(decisions)],
            'stopping_rule': 'proof:native-audit',
            'current_status': 'offline_reanalysis_complete'}
        (out/'decision_log.json').write_text(json.dumps(decision_doc, indent=2, ensure_ascii=False)+'\n')
        (out/'scientific-claims.json').write_text(json.dumps(claims, indent=2, ensure_ascii=False)+'\n')
        report = '# Overview\n\n' + '\n'.join('{{claim:'+c['id']+'}}' for c in claims['claims']) + '\n'
        (out/'report.md').write_text(report, encoding='utf-8')
        # Preserve the canonical historical alias map after checking the actual public/native bytes.
        manifest = source_record.copy()
        if native_hashes != manifest['native_evidence_sha256']:
            raise ValueError('native source identity mapping differs')
        (out/'source-manifest.json').write_text(json.dumps(manifest, indent=2, ensure_ascii=False)+'\n')
    print(json.dumps({'status': 'RECOMPUTED_FROM_PUBLIC_INPUTS', 'native_files': len(native_hashes),
                      'native_records': attempts, 'tasks': len(tasks), 'HT_recomputed': True,
                      'printed_energy_diagnostics_recomputed': True, 'new_calculations': 0}, ensure_ascii=False))


if __name__ == '__main__':
    if len(sys.argv) != 4:
        raise SystemExit('usage: replay_reference.py ASSET_DIR OUTPUT_DIR SOLUTION_DIR')
    try:
        run(sys.argv[1], sys.argv[2], sys.argv[3])
    except Exception as exc:
        print(json.dumps({'status': 'FAIL', 'error': f'{type(exc).__name__}: {exc}'}, ensure_ascii=False), file=sys.stderr)
        raise SystemExit(1)
BENCH06_PY_39_1
mkdir -p "$work/reference"
cat > "$work/reference/audit_energy_convention.py" <<'BENCH06_PY_39_2'
#!/usr/bin/env python3
"""Audit printed final GPAW energy components; no scientific calculator calls."""
import csv
import hashlib
import json
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent
NATIVE = HERE.parent / 'native'
LABELS = ['Kinetic', 'Potential', 'External', 'XC', 'Entropy (-ST)',
          'Local', 'SIC', 'Free energy', 'Extrapolated']


def audit():
    rows = []
    for folder in sorted(NATIVE.glob('attempt-*')):
        result = json.loads((folder / 'result.json').read_text())
        log = (folder / 'gpaw.txt').read_text()
        blocks = log.split('Energy contributions relative to reference atoms:')
        if len(blocks) < 2:
            raise ValueError(f'{folder}: missing energy block')
        energies = {}
        for label in LABELS:
            matches = re.findall(r'^' + re.escape(label) +
                                 r':\s*([+-]?[0-9]+\.[0-9]+)', blocks[-1], re.M)
            if not matches:
                raise ValueError(f'{folder}: missing {label}')
            energies[label] = float(matches[0])
        parts = sum(energies[k] for k in ['Kinetic', 'Potential', 'XC', 'Local'])
        helper = result['E_DFT_without_constraint_potential_eV']
        entropy = energies['Entropy (-ST)']
        residual = helper - (parts - entropy)
        if abs(residual) > 1e-5:
            raise ValueError(f'{folder}: helper and final block disagree: {residual}')
        if abs(energies['SIC']) > 1e-12:
            raise ValueError(f'{folder}: nonzero SIC requires separate convention review')
        rows.append({
            'attempt': result['id'], 'task_index': result['task_index'],
            'state': result['state'], 'geometry_id': result['geometry_id'],
            'setting': result['setting'], 'recorded_helper_DFT_eV': helper,
            'printed_entropy_minus_ST_eV': entropy,
            'helper_minus_reconstructed_helper_eV': residual,
            'printed_free_minus_external_eV': energies['Free energy'] - energies['External'],
            'printed_extrapolated_minus_external_eV': energies['Extrapolated'] - energies['External'],
            'sum_four_parts_candidate_eV': helper + entropy,
            'sum_four_parts_plus_entropy_candidate_eV': helper + 2 * entropy,
            'TS09_eV': result['TS09_correction_eV'],
            'gpaw_log_sha256': hashlib.sha256((folder / 'gpaw.txt').read_bytes()).hexdigest(),
        })
    pairs = []
    for task_index in sorted({r['task_index'] for r in rows}):
        states = {r['state']: r for r in rows if r['task_index'] == task_index}
        n, f = states[0], states[-1]
        correction = f['TS09_eV'] - n['TS09_eV']
        gap = f['recorded_helper_DFT_eV'] - n['recorded_helper_DFT_eV'] + correction
        entropy_difference = f['printed_entropy_minus_ST_eV'] - n['printed_entropy_minus_ST_eV']
        pairs.append({
            'task_index': task_index, 'geometry_id': n['geometry_id'], 'setting': n['setting'],
            'recorded_helper_plus_TS09_gap_eV': gap,
            'entropy_difference_minus_ST_eV': entropy_difference,
            'sum_four_parts_plus_TS09_candidate_gap_eV': gap + entropy_difference,
            'sum_four_parts_plus_entropy_plus_TS09_candidate_gap_eV': gap + 2 * entropy_difference,
        })
    output = {
        'schema': 'case04-printed-energy-convention-audit/v1',
        'new_scientific_calculations': 0,
        'source': 'Final printed GPAW energy blocks and archived native result.json; GPAW 25.7 source review recorded separately.',
        'convention': 'Legacy CDFT helper returns sum(Kinetic, Potential, XC, Local) minus e_entropy; printed e_entropy is labeled Entropy (-ST).',
        'limits': 'Printed terms have six decimal places. Candidate transformations are arithmetic diagnostics, not a replacement of archived results or a choice of the correct thermodynamic/diabatic energy convention. SIC and other omitted terms must be checked before applying these identities to other systems.',
        'all_reconstructed_helpers_match_within_1e-5eV': True,
        'all_printed_SIC_zero': True,
        'states': rows, 'paired_diagnostics': pairs,
    }
    (HERE / 'energy-convention-audit.json').write_text(json.dumps(output, indent=2) + '\n')
    with (HERE / 'energy-convention-paired-diagnostics.csv').open('w', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=list(pairs[0]))
        writer.writeheader()
        writer.writerows(pairs)
    return output


if __name__ == '__main__':
    data = audit()
    print(json.dumps({'state_records': len(data['states']),
                      'paired_diagnostics': len(data['paired_diagnostics']),
                      'max_abs_entropy_gap_shift_eV': max(abs(p['entropy_difference_minus_ST_eV']) for p in data['paired_diagnostics'])}, indent=2))
BENCH06_PY_39_2
python3 "$work/replay_reference.py" "$ASSETS" "$OUT" "$work"
