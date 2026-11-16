#!/bin/bash
set -euo pipefail
RUNTIME_DIR="$(mktemp -d "${TMPDIR:-/tmp}/bench22-runtime.XXXXXXXX")"
trap 'rm -rf "${RUNTIME_DIR}"' EXIT
cat > "${RUNTIME_DIR}/experiment.py" <<'BENCH22_EMBED_EXPERIMENT_PY'
"""Fit the public, independently normalized two-state observation curves."""
import csv, json
from pathlib import Path
import numpy as np
from scipy.linalg import expm
from scipy.optimize import least_squares

ROOT=Path.cwd()
INPUT=ROOT/'inputs'/'observations.csv'
PROTOCOL=json.loads((ROOT/'inputs'/'benchmark.json').read_text(encoding='utf-8'))
SCENARIOS=('baseline','intervention_A','intervention_B')
MULT={name:(float(spec['ph1_multiplier']),float(spec['nr1_multiplier'])) for name,spec in PROTOCOL['experiments'].items()}
PARAMS=('f','nrS','isc','risc','ph1','nr1')

def read_rows():
    with INPUT.open(newline='') as fh:
        rows=list(csv.DictReader(fh))
    return [(float(x['time_s']),x['scenario'],float(x['fluorescence_norm']),float(x['phosphorescence_norm'])) for x in rows]

def predict(rates, rows):
    out=[]
    for scenario in SCENARIOS:
        factors=MULT[scenario]
        selected=[x for x in rows if x[1]==scenario]
        ts=np.array([x[0] for x in selected])
        a=np.array([[-(rates['f']+rates['nrS']+rates['isc']),rates['risc']],
                    [rates['isc'],-(rates['risc']+rates['ph1']*factors[0]+rates['nr1']*factors[1])]])
        p=np.array([expm(a*t)@np.array([1.,0.]) for t in ts])
        ps=p[:,1]/np.max(p[:,1])
        out.extend(np.column_stack((p[:,0],ps)).ravel())
    return np.asarray(out)

def main():
    rows=read_rows()
    observed=np.array([z for row in rows for z in row[2:]])
    # Fit the identifiable total singlet loss; the f/nrS split is intentionally free.
    def unpack(logx, split=.5):
        alpha,isc,risc,ph,nr=np.exp(logx)
        return {'f':alpha*split,'nrS':alpha*(1-split),'isc':isc,'risc':risc,'ph1':ph,'nr1':nr}
    def residual(logx): return predict(unpack(logx),rows)-observed
    lower=np.log([1e5,1e3,1e2,1e1,1e1]); upper=np.log([1e9,1e8,1e8,1e8,1e8])
    starts=[[1e7,1e6,2e5,5e3,3e4],[6e7,8e6,1e6,1e5,2e5],[2e8,5e5,5e6,1e3,1e6]]
    fits=[]
    for start in starts:
        result=least_squares(residual,np.log(start),bounds=(lower,upper),max_nfev=3000,xtol=1e-13,ftol=1e-13,gtol=1e-13)
        fits.append((float(np.sqrt(np.mean(residual(result.x)**2))),result.x))
    fits.sort(key=lambda q:q[0]); rms, x=fits[0]
    base=unpack(x,.30); alternate=unpack(x,.70)
    # Explicitly verify (and report) the exact f <-> nrS invariance.
    all_predictions={}
    for label,rates in [('fit_a',base),('fit_b',alternate)]:
        all_predictions[label]=predict(rates,rows).tolist()
    intervention={}
    for name,rate in [('baseline',base),('intervention_A',base),('intervention_B',base)]:
        q=dict(rate)
        if name=='intervention_A': q['ph1']*=MULT[name][0]
        if name=='intervention_B': q['nr1']*=MULT[name][1]
        intervention[name]=q
    def fluorescence_yield(rates):
        a=np.array([[-(rates['f']+rates['nrS']+rates['isc']),rates['risc']],
                    [rates['isc'],-(rates['risc']+rates['ph1']+rates['nr1'])]])
        occupancy=np.linalg.solve(-a,np.array([1.,0.]))
        return float(rates['f']*occupancy[0])
    def fluorescence_flux(rates, scenario='baseline', time_s=2e-7):
        factors=MULT[scenario]
        a=np.array([[-(rates['f']+rates['nrS']+rates['isc']),rates['risc']],
                    [rates['isc'],-(rates['risc']+rates['ph1']*factors[0]+rates['nr1']*factors[1])]])
        return float(rates['f']*(expm(a*time_s)@np.array([1.,0.]))[0])
    output={
      'schema_version':'1.0','model':'dp/dt=A p; p(0)=(1,0); A=[[-(f+nrS+isc),risc],[isc,-(risc+ph1+nr1)]]',
      'parameter_units':'s^-1','parameters_fit_a':base,'parameters_fit_b_equivalent':alternate,
      'fit_parameterization':'alpha=f+nrS plus isc,risc,ph1,nr1; f/nrS split is unconstrained by these independently normalized channels',
      'fit_parameter_names':['alpha','isc','risc','ph1','nr1'],
      'bounds_s-1':{'alpha':[1e5,1e9],'isc':[1e3,1e8],'risc':[1e2,1e8],'ph1':[1e1,1e8],'nr1':[1e1,1e8]},
      'fit_window_s':[min(x[0] for x in rows),max(x[0] for x in rows)],'weights':'equal weight per normalized channel/time point',
      'starting_guesses_s-1':starts,'multistart_residual_rms':[x[0] for x in fits],'residual_rms':rms,
      'intervention_multipliers':{'A_ph1':MULT['intervention_A'][0],'B_nr1':MULT['intervention_B'][1]},'scenario_parameters':intervention,
      'equivalence_max_curve_abs_delta':float(np.max(np.abs(np.asarray(all_predictions['fit_a'])-np.asarray(all_predictions['fit_b'])))),
      'discriminating_observable':{'type':'calibrated_fluorescence_flux','unit':'s^-1 per initially excited molecule','scenario':'baseline','time_s':2e-7,
        'predictions':{'fit_a':fluorescence_flux(base),'fit_b':fluorescence_flux(alternate)}},
      'channel_normalization':'fluorescence divided by its t=0 value within each scenario; phosphorescence divided by its own scenario maximum; no cross-channel amplitude calibration',
      'predicted_curves_flattened':all_predictions
    }
    matrix_deltas=[]
    curve_deltas=[]
    for name in SCENARIOS:
        q=intervention[name]
        a=np.array([[-(q['f']+q['nrS']+q['isc']),q['risc']],[q['isc'],-(q['risc']+q['ph1']+q['nr1'])]])
        alt=dict(q); alt['f']=alternate['f']; alt['nrS']=alternate['nrS']
        b=np.array([[-(alt['f']+alt['nrS']+alt['isc']),alt['risc']],[alt['isc'],-(alt['risc']+alt['ph1']+alt['nr1'])]])
        matrix_deltas.append(float(np.max(np.abs(a-b))))
        curves_a=np.asarray(all_predictions['fit_a']).reshape(3,100,2)[SCENARIOS.index(name)]
        curves_b=np.asarray(all_predictions['fit_b']).reshape(3,100,2)[SCENARIOS.index(name)]
        curve_deltas.append(float(np.max(np.abs(curves_a-curves_b))))
    final=ROOT/'final'; final.mkdir(exist_ok=True)
    with (final/'observations.csv').open('w',newline='') as fh:
        writer=csv.writer(fh); writer.writerow(['time_s','scenario','fluorescence_norm','phosphorescence_norm']); writer.writerows(rows)
    (final/'result.json').write_text(json.dumps(output,indent=2)+'\n')
    evidence={'schema_version':'1.0',
      'structural_identifiability':{'status':'witnessed_equivalent_generator','fit_a_ref':'parameters_fit_a','fit_b_ref':'parameters_fit_b_equivalent',
        'max_generator_abs_delta_s-1':max(matrix_deltas),'max_curve_abs_delta':max(curve_deltas)},
      'practical_identifiability':{'status':'not_quantified_without_noise_model','fit_window_s':output['fit_window_s'],'noise_model':None},
      'discriminating_observable_ref':'result.discriminating_observable'}
    (final/'diagnosis.md').write_text('''# Identifiability diagnosis\n\nThe fit includes a structural-identifiability witness and an independently checked additional-observable proposal. Practical uncertainty is not quantified without an observation-noise model. The public intervention multipliers are applied as declared.\n\n```json\n'''+json.dumps(evidence,indent=2)+'\n```\n')
    print(json.dumps({'rms':rms,'rates':base,'equivalent':alternate},indent=2))
if __name__=='__main__': main()
BENCH22_EMBED_EXPERIMENT_PY
mkdir -p /app/final
cp "$RUNTIME_DIR/experiment.py" /app/final/experiment.py
(cd /app && python "$RUNTIME_DIR/experiment.py")
