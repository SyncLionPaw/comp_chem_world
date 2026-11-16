#!/usr/bin/env bash
set -euo pipefail
app_root="${APP:-/app}"
output_dir="$app_root/final"
mkdir -p "$output_dir"
cat > "$output_dir/analysis.py" <<'CCB_ANALYSIS'
"""Executable author reference for the three frozen analysis tasks.

Only public input arrays are used. A numeric verifier pass still requires the
separate execution and interpretation review under the task scientific contract.
"""
from pathlib import Path
import argparse
import hashlib
import json
import math
import shutil
import sys
import time

DATA='raw_data/unpacked/amset-supporting-data-v1.0.2-ec2fb88a3a9c/amset-supporting-data-v1.0.2'
DEFAULT_CASE='case-02-mechanism-diagnosis'  # Set in the package copy, never inferred by basename searches.

def scientific_report(case_id,result):
    rows=result['rows'];materials=sorted({row['material'] for row in rows})
    statement={'schema':'carrier-scientific-report/v1','case_id':case_id,
               'scope':{'calculation':'analysis_of_author_arrays','new_dft_or_scattering':False,
                        'reproduces_full_paper_statistics':False},'physics':{},'evidence':[]}
    code=case_id.split('-')[1]
    if code=='02':
        statement['physics']={'limiting_proxy':'minimum_single_mechanism_mobility','proxy_is_microscopic_rate_fraction':False,
            'matthiessen_domain':'same_state_inverse_lifetime','mobility_harmonic_sum_exact':False,
            'averaging':'velocity_energy_and_state_weighted','axes':'native_xx_yy_zz_not_assumed_crystal_abc'}
        for material in materials:
            observed=[x for x in rows if x['material']==material];levels=sorted({x['doping_cm3'] for x in observed},key=abs)
            t=min(x['temperature_K'] for x in observed);n=levels[0]
            endpoints=[]
            for level in levels:
                trace=[x for x in observed if x['doping_cm3']==level and x['axis']=='xx']
                ts=sorted({x['temperature_K'] for x in trace})
                for temp in [ts[0]] if len(ts)==1 else [ts[0],ts[-1]]:
                    point=next(x for x in trace if x['temperature_K']==temp)
                    endpoints.append({'doping_cm3':level,'temperature_K':temp,'limiting_proxy':point['limiting_proxy']})
            axes=[next(x['overall'] for x in observed if x['doping_cm3']==n and x['temperature_K']==t and x['axis']==axis) for axis in ['xx','yy','zz']]
            errors=[x['relative_deviation'] for x in observed]
            statement['evidence'].append({'material':material,'proxy_endpoints_xx':endpoints,'deviation_range':[min(errors),max(errors)],
                'directional_sample':{'doping_cm3':n,'temperature_K':t,'overall_xx_yy_zz':axes}})
    elif code=='03':
        statement['physics']={'error_reference':'author_AMSET_not_experiment','CRT_lifetime_fs':10,
            'SRT_temperature_scale':{'reference_K':300,'power':-1,'equals_CRT_at_reference':True},
            'SRT_guarantees_accuracy_improvement':False,'invent_missing_300K_point':False,'full_paper_MSE_or_Spearman_inferred':False}
        for material in materials:
            for metric in sorted([m for m in result['metrics'] if m['material']==material],key=lambda m:(abs(m['doping_cm3']),m['axis'])):
                statement['evidence'].append({**metric,'SRT_log_RMSE_assessment':'improves' if metric['log_rmse_srt']<metric['log_rmse_crt'] else 'does_not_improve'})
        statement['scaling_max_relative_deviation']=max(abs(row['mu_srt']/row['mu_crt']*row['temperature_K']/300-1) for row in rows)
        statement['available_temperatures_K']={mat:sorted({x['temperature_K'] for x in rows if x['material']==mat}) for mat in materials}
    else:
        statement['physics']={'negative_doping':'electrons','positive_doping':'holes',
            'constant_lifetime_scale_cancels_in_Seebeck':True,'energy_dependent_lifetime_cancels':False,
            'reason':'energy_dependence_changes_Onsager_moment_weights','diffusive_only_materials':['CdS','Si'],
            'phonon_drag_included':False,'unit_factors':{'n_cm3_to_m3':1e6,'mu_cm2_to_m2':1e-4,'e_C':1.602176634e-19},
            'nominal_net_doping_residual_forced_zero':False}
        for mat in materials:
            obs=[r for r in rows if r['material']==mat];n=min({r['doping_cm3'] for r in obs},key=abs);t=min(r['temperature_K'] for r in obs)
            statement['evidence'].append({'material':mat,'carrier':'electrons' if n<0 else 'holes',
                'S_range_microvolt_K':[min(x['S_amset'] for x in obs),max(x['S_amset'] for x in obs)],
                'delta_S_range_microvolt_K':[min(x['delta_S'] for x in obs),max(x['delta_S'] for x in obs)],
                'max_abs_conductivity_residual':max(abs(x['relative_residual']) for x in obs),
                'directional_sample':{'doping_cm3':n,'temperature_K':t,
                    'S_xx_yy_zz':[next(x['S_amset'] for x in obs if x['doping_cm3']==n and x['temperature_K']==t and x['axis']==a) for a in ['xx','yy','zz']]}})
    return '# 科学分析\n\n```json\n'+json.dumps(statement,ensure_ascii=False,indent=2,allow_nan=False)+'\n```\n'

def decode(value):
    if isinstance(value,dict):
        if value.get('@class')=='array':return decode(value['data'])
        return {k:decode(v) for k,v in value.items()}
    if isinstance(value,list):return [decode(v) for v in value]
    return value

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--case',default=DEFAULT_CASE)
    parser.add_argument('--inputs',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();started=time.perf_counter()
    number=args.case.split('-')[1]
    if number=='02':
        category='mobility';materials=['GaAs','GaN','Si','SnSe'];models=['AMSET']
    elif number=='03':
        category='mobility';materials=['GaAs','GaN','SnSe'];models=['AMSET','CRT','SRT']
    elif number=='04':
        category='seebeck';materials=['GaAs','p-GaAs','SnSe','Si','CdS'];models=['AMSET','CRT']
    else:raise ValueError('Unsupported frozen case')
    data={};sources=[]
    for mat in materials:
        for model in models:
            rel=f'{DATA}/{category}/{mat}/{model}_transport.json'
            path=args.inputs/rel;blob=path.read_bytes()
            data[mat,model]=decode(json.loads(blob))
            sources.append({'path':rel,'sha256':hashlib.sha256(blob).hexdigest()})
    rows=[];metrics=[]
    for mat in materials:
        d=data[mat,'AMSET'];ns=d['doping'];ts=d['temperatures']
        for model in models:
            other=data[mat,model]
            if len(other['doping'])!=len(ns) or any(not math.isclose(a,b,rel_tol=1e-12) for a,b in zip(other['doping'],ns)):
                raise ValueError('Concentration grids differ')
            if other['temperatures']!=ts:raise ValueError('Temperature grids differ')
        for i,n in enumerate(ns):
            for j,t in enumerate(ts):
                for ax,axis in enumerate(['xx','yy','zz']):
                    row={'material':mat,'doping_cm3':n,'temperature_K':t,'axis':axis}
                    mu=d['mobility']['overall'][i][j][ax][ax]
                    if number=='02':
                        mechanisms={k:v[i][j][ax][ax] for k,v in d['mobility'].items() if k!='overall'}
                        proxy=1/math.fsum(1/v for v in mechanisms.values())
                        row.update(overall=mu,mechanisms=mechanisms,limiting_proxy=min(mechanisms,key=mechanisms.get),
                                   harmonic_proxy=proxy,relative_deviation=(proxy-mu)/mu)
                    elif number=='03':
                        row.update(mu_amset=mu,mu_crt=data[mat,'CRT']['mobility']['overall'][i][j][ax][ax],
                                   mu_srt=data[mat,'SRT']['mobility']['overall'][i][j][ax][ax])
                    else:
                        s=d['seebeck'][i][j][ax][ax];sc=data[mat,'CRT']['seebeck'][i][j][ax][ax]
                        sigma=d['conductivity'][i][j][ax][ax]
                        prediction=abs(n)*1e6*1.602176634e-19*mu*1e-4
                        row.update(S_amset=s,S_crt=sc,delta_S=s-sc,sigma_S_m=sigma,mu_cm2_Vs=mu,
                                   sigma_from_mu_S_m=prediction,relative_residual=(prediction-sigma)/sigma)
                    rows.append(row)
            if number=='03':
                for ax,axis in enumerate(['xx','yy','zz']):
                    curves={k:[y[ax][ax] for y in data[mat,k]['mobility']['overall'][i]] for k in models}
                    low=min(range(len(ts)),key=ts.__getitem__);high=max(range(len(ts)),key=ts.__getitem__)
                    metric={'material':mat,'doping_cm3':n,'axis':axis}
                    for model in ['CRT','SRT']:
                        metric['log_rmse_'+model.lower()]=math.sqrt(math.fsum(math.log10(a/b)**2 for a,b in zip(curves[model],curves['AMSET']))/len(ts))
                    for model,v in curves.items():
                        metric['slope_'+model.lower()]=math.log(v[high]/v[low])/math.log(ts[high]/ts[low])
                    metrics.append(metric)
    result={'rows':rows,**({'metrics':metrics} if metrics else {})}
    args.output.mkdir(parents=True,exist_ok=True)
    (args.output/'results.json').write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False)+'\n')
    (args.output/'report.md').write_text(scientific_report(args.case,result))
    if Path(__file__).resolve()!=(args.output/'analysis.py').resolve():shutil.copy2(__file__,args.output/'analysis.py')
    provenance={'case_id':args.case,'command':[sys.executable,*sys.argv], 'python_version':sys.version,
                'inputs':sources,'script_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                'row_count':len(rows),'elapsed_seconds':time.perf_counter()-started,
                'scope':'actual array analysis; no new DFT/scattering execution'}
    (args.output/'run.log').write_text(json.dumps(provenance,ensure_ascii=False,indent=2)+'\n')
    print(f'{args.case}: analyzed {len(rows)} conditions/directions')

if __name__=='__main__':main()
CCB_ANALYSIS
exec python3 "$output_dir/analysis.py" --inputs "$app_root/environment/assets" --output "$output_dir"
