#!/bin/sh
set -eu
app=${APP:-/app}
input=${INPUT_DIR:-$app/inputs}
output=$app/final
mkdir -p "$output"
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT HUP INT TERM
cat > "$work/analysis.py" <<'ORACLE_PY'
"""Author-side native audit using correlation-series calculation, no gold imports."""
import argparse,csv,json,shutil
from pathlib import Path
import numpy as np,parmed
from scipy.io import netcdf_file
p=argparse.ArgumentParser();p.add_argument('--input-dir',type=Path);p.add_argument('--output-dir',type=Path);a=p.parse_args()
mass=np.sum([atom.mass for atom in parmed.load_file(str(a.input_dir/'neutral.prmtop')).atoms]);datasets={}
for name,file in [('legacy','legacy-qmmm.nc'),('short_npt','short-npt.nc')]:
 with netcdf_file(str(a.input_dir/file),mmap=False) as f:
  assert f.variables['time'].units==b'picosecond' and f.variables['coordinates'].units==b'angstrom'
  t=np.asarray(f.variables['time'][:],float).copy();volume=np.prod(f.variables['cell_lengths'][:],axis=1);atoms=f.variables['coordinates'].shape[1]
 density=mass*1.66053906660/volume;n=len(t);delta=density-density.mean()
 if np.ptp(density)<1e-12:g=None;neff=1.
 else:
  corr=np.correlate(delta,delta,'full')[n-1:]/np.dot(delta,delta)
  positive=[]
  for value in corr[1:]:
   if value<=0:break
   positive.append(value)
  g=float(np.clip(1+2*sum(positive),1,n));neff=n/g
 reasons=['observation_too_short_for_independent_equilibrium_ensemble']
 if g is None:reasons.append('constant_density_does_not_establish_uncorrelated_frames')
 if neff<10:reasons.append('fewer_than_ten_effective_density_observations')
 if n<5:reasons.append('too_few_frames_for_stationarity_and_uncertainty')
 datasets[name]={'frames':n,'atoms':atoms,'start_time_ps':float(t[0]),'end_time_ps':float(t[-1]),'duration_ps':float(t[-1]-t[0]),'interval_ps':float(np.mean(np.diff(t))),'box_source':'trajectory_cell_lengths','volumes_A3':volume.tolist(),'densities_g_ml':density.tolist(),'density_statistical_inefficiency':g,'effective_density_samples':neff,'density_relative_change':float(density[-1]/density[0]-1),'supports_ten_independent_equilibrium_clusters':False,'reason_codes':reasons}
temperatures=[float(row['temperature_K']) for row in csv.DictReader((a.input_dir/'short-npt-diagnostics.csv').open())]
datasets['short_npt'].update(temperature_mean_K=float(np.mean(temperatures)),temperature_sd_K=float(np.std(temperatures,ddof=1)))
index=json.loads((a.input_dir/'controls/index.json').read_text());policy=index['policy'];control_results={}
for item in index['datasets']:
 records=list(csv.DictReader((a.input_dir/'controls'/item['file']).open()));n=len(records);clock=np.array([float(row['time']) for row in records])*({'ps':1,'ns':1000}[item['time_unit']]);valid=bool((np.diff(clock)>0).all());metrics={};reasons=[]
 if item.get('native_time_reference'):
  with netcdf_file(str(a.input_dir/item['native_time_reference']),mmap=False) as f:original_clock=f.variables['time'][:].copy()
  valid=valid and len(clock)==len(original_clock) and bool(np.allclose(clock,original_clock,atol=1e-6,rtol=0))
 if not valid:reasons.append('time_metadata_disagrees_with_native_reference')
 if n<policy['minimum_frames']:reasons.append('too_few_observations_for_declared_audit')
 for observable in item['observables']:
  values=np.asarray([float(row[observable]) for row in records]);centered=values-values.mean()
  if np.ptp(values)<1e-12:g=None;neff=1.;spread=None;stable=False
  else:
   correlation=np.correlate(centered,centered,'full')[n-1:]/np.dot(centered,centered);total=0.
   for value in correlation[1:]:
    if value<=0:break
    total+=value
   g=float(np.clip(1+2*total,1,n));neff=n/g
   block_means=[part.mean() for part in np.array_split(values,min(n,policy['stationarity_blocks']))];spread=None if n<policy['stationarity_blocks'] else float((max(block_means)-min(block_means))/values.std(ddof=1));stable=spread is not None and n>=policy['minimum_frames'] and spread<=policy['maximum_block_mean_range_in_sample_sd']
  metrics[observable]={'statistical_inefficiency':g,'effective_observations':neff,'block_mean_range_in_sample_sd':spread,'passes_declared_stationarity_screen':bool(stable)}
  if neff<policy['minimum_effective_observations']:reasons.append('insufficient_effective_observations:'+observable)
  if not stable:reasons.append('stationarity_not_supported:'+observable)
 eligible=valid and n>=policy['minimum_frames'] and all(v['effective_observations']>=policy['minimum_effective_observations'] and v['passes_declared_stationarity_screen'] for v in metrics.values())
 if eligible:reasons.append('declared_observable_summary_requirements_met')
 control_results[item['dataset_id']]={'observations':n,'declared_duration_ps':float(clock[-1]-clock[0]),'metadata_consistent':bool(valid),'observables':metrics,'eligible_for_declared_observable_summary':bool(eligible),'establishes_molecular_equilibrium':False,'verdict':'metadata_inconsistent' if not valid else ('eligible_observable_summary' if eligible else 'insufficient_sampling_evidence'),'reason_codes':reasons}
native_limits=[f"{name}: duration={item['duration_ps']:.6g} ps, effective density samples={item['effective_density_samples']:.6g}" for name,item in datasets.items() if name in ('legacy','short_npt') and not item['supports_ten_independent_equilibrium_clusters']]
control_limits=[f"{name}: {', '.join(item['reason_codes'])}" for name,item in control_results.items() if not item['eligible_for_declared_observable_summary']]
extend_sampling=bool(native_limits or control_limits)
reason_parts=[]
if native_limits:reason_parts.append('The native density records do not support ten independent equilibrium clusters ('+'; '.join(native_limits)+').')
if control_limits:reason_parts.append('The diagnostic screens also fail for '+'; '.join(control_limits)+'.')
reason_parts.append('These controls assess declared observables and do not establish molecular equilibrium.')
result={'datasets':datasets,'diagnostic_controls':control_results,'duration_ratio_short_to_legacy':datasets['short_npt']['duration_ps']/datasets['legacy']['duration_ps'],'recommendation':{'extend_sampling':extend_sampling,'location':'a longer molecular-dynamics trajectory under the intended production conditions','reason':' '.join(reason_parts)}}
a.output_dir.mkdir(parents=True,exist_ok=True);(a.output_dir/'audit.json').write_text(json.dumps(result,indent=2)+'\n')
(a.output_dir/'analysis.md').write_text("Native trajectory and control audit calculated from topology masses, frame cells, timestamps, and observables. Constant density is not evidence for independent configurations. The control screen concerns declared observables and cannot establish molecular equilibrium.\n\n"+json.dumps(result,indent=2)+"\n")
if Path(__file__).resolve()!=(a.output_dir/'analysis.py').resolve():shutil.copyfile(__file__,a.output_dir/'analysis.py')
ORACLE_PY
cp "$work/analysis.py" "$output/analysis.py"
python3 "$work/analysis.py" --input-dir "$input" --output-dir "$output"
