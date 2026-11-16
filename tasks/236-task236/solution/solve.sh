#!/usr/bin/env bash
# Reproducible static and finite-window dynamic susceptibility/fit analysis.
set -euo pipefail
WORK="${1:-/app/final}"
PKG="${APP:-/app}"
mkdir -p "$WORK"
PYTHONPATH="$PKG/public${PYTHONPATH:+:$PYTHONPATH}" python3 - "$PKG" "$WORK" <<'PY'
import json, sys
from pathlib import Path
from canonical import compute, dipole_spectrum, dipole_real_spectrum, compare_oscillators
pkg,work=map(Path,sys.argv[1:])
p=pkg/'inputs'
d=compute(p/'Cubic_6x6x6_supercell_dipoles.txt',p/'Cubic_6x6x6_cell_volumes.txt')
m=__import__('numpy').loadtxt(p/'Cubic_6x6x6_supercell_dipoles.txt',dtype=float)
freq,response=dipole_spectrum(m,max_lag_ps=4.0)
freq_r,real_shape=dipole_real_spectrum(m,max_lag_ps=4.0)
if not __import__('numpy').allclose(freq,freq_r): raise ValueError('real/imaginary susceptibility grids differ')
fit=compare_oscillators(freq,response)
centered=m-m.mean(axis=0)
acf0=float(__import__('numpy').mean(__import__('numpy').einsum('ij,ij->i',centered,centered)))
chi_bohr=(d['epsilon_if_eBohr']-1.0)*response/acf0
chi_ang=(d['epsilon_if_eAngstrom']-1.0)*response/acf0
chi_real_bohr=(d['epsilon_if_eBohr']-1.0)*real_shape
chi_real_ang=(d['epsilon_if_eAngstrom']-1.0)*real_shape
sens={}
for window in (2.0,4.0,6.0):
    fw,rw=dipole_spectrum(m,max_lag_ps=window)
    sens[str(window)]=compare_oscillators(fw,rw)
__import__('numpy').savetxt(work/'chi_spectrum_4ps.csv',__import__('numpy').column_stack([freq,real_shape,response,chi_real_bohr,chi_bohr,chi_real_ang,chi_ang]),delimiter=',',header='frequency_cm-1,chi_real_normalized_shape,chi_loss_raw_dipole_units2,chi_real_if_eBohr,chi_loss_if_eBohr,chi_real_if_eAngstrom,chi_loss_if_eAngstrom',comments='')
out={**d,
  'static_dielectric_constant':None,
  'static_dielectric_status':'INCONCLUSIVE',
  'static_dielectric_conditional_values':{'eBohr':d['epsilon_if_eBohr'],'eAngstrom':d['epsilon_if_eAngstrom']},
  'static_dielectric_unit_basis':'INFERRED_eBohr_from_model_source_README_not_explicit_on_MD_timeseries',
  'autocorrelation_time_ps':d['tau_vector_M']['tau_int_ps'],
  'dynamic_spectrum_method':'vector dot-product ACF; unbiased finite-record correction; 4 ps cosine lag window; trapezoidal endpoint weights; Eq. (6) imaginary response; amplitude reported conditionally under each dipole-unit hypothesis',
  'chi_imaginary_if_eBohr':chi_bohr.tolist(),
  'chi_imaginary_if_eAngstrom':chi_ang.tolist(),
  'chi_real_if_eBohr':chi_real_bohr.tolist(),
  'chi_real_if_eAngstrom':chi_real_ang.tolist(),
  'frequencies_cm1':freq.tolist(),
  'complex_response_convention':'REAL_MINUS_I_POSITIVE_LOSS',
  'chi_sign_convention':'chi_complex=chi_prime-i*chi_loss; reported positive chi_loss equals -Im(chi_complex)',
  'frequency_resolution_cm1':float(freq[1]-freq[0]),
  'max_reported_frequency_cm1':float(freq[-1]),
  'frequency_convention':'positive frequencies only; f_THz=fftfreq(1/dt_ps); wavenumber_cm^-1=f_THz*33.3564095198; angular frequency=2*pi*f_THz; Nyquist=1/(2*dt_ps)=416.955 cm^-1 at 0.04 ps',
  'oscillator_fit_status':'INCONCLUSIVE' if fit['model_preference']=='inconclusive' else 'DESCRIPTIVE_FIT_ONLY',
  'single_oscillator_rss':fit['one_oscillator']['rss'],
  'two_oscillator_rss':fit['two_oscillator']['rss'],
  'two_oscillator_omega1_cm1':fit['two_oscillator']['parameters'][0]['omega0_cm1'],
  'two_oscillator_gamma1_cm1':fit['two_oscillator']['parameters'][0]['gamma_cm1'],
  'two_oscillator_omega2_cm1':fit['two_oscillator']['parameters'][1]['omega0_cm1'],
  'two_oscillator_gamma2_cm1':fit['two_oscillator']['parameters'][1]['gamma_cm1'],
  'rss_improvement_ratio':fit['rss_improvement_ratio'],
  'single_oscillator_sufficient':None,'two_oscillator_statistically_necessary':None,
  'oscillator_fits':fit,'window_sensitivity':sens,
  'legacy_reference_values_unaccepted':{'author_json':238.0,'retired_verifier_center':128.5},
  'reference_conflict_resolved':False}
(work/'dielectric_spectrum_summary.json').write_text(json.dumps(out,indent=2),encoding='utf-8')
single=fit['one_oscillator']['parameters'][0]
two=fit['two_oscillator']['parameters']
tau_m=d['tau_vector_M']
text=f'''# 6×6×6 dielectric-response analysis

The author `Sims_6x6x6/NST/Atmo_press/README.docx` states a 0.04 ps sampling interval. The supplied dipole and volume files contain {d['n_frames']} aligned samples ({d['sampled_duration_ps']:.1f} ps between first and last sample), at 250 K by the author XML; mean instantaneous cell volume is {d['mean_volume_angstrom3']:.3f} Å³ for 216 formula units. The paper's Eq. (4) requires the total dipole in SI units, uses cubic-phase ⟨M⟩=0, and neglects ε∞.

The separate author polarization `Source_data/README.docx` states that extensive total dipoles are in atomic units e·Bohr. The 6×6×6 time-series README does not restate that unit, so this remains an explicit model-provenance inference rather than a direct tag. Therefore no unconditional static dielectric value is reported: the finite-record mean-subtracted, sample-wise M²/V estimates are εᵣ≈{d['epsilon_if_eBohr']:.3f} under e·Bohr and {d['epsilon_if_eAngstrom']:.3f} under e·Å. The absolute real and positive-loss imaginary susceptibility spectra are also emitted conditionally for each unit hypothesis in `chi_spectrum_4ps.csv` and the JSON arrays.

These calculations do not reconcile historical context values 238 and 128.5; neither is an acceptance target. The centered-vector-M integrated autocorrelation estimate is {tau_m['tau_int_ps']:.4f} ps (ESS≈{tau_m['ess']:.0f}; delete-one 10-block jackknife 95% interval [{tau_m['jackknife_ci95_ps'][0]:.4f}, {tau_m['jackknife_ci95_ps'][1]:.4f}] ps). Separately, the derived M²/V series gives {d['tau_M2_over_V']['tau_int_ps']:.4f} ps (ESS≈{d['tau_M2_over_V']['ess']:.0f}); it is not the dipole relaxation time.

The complex response was evaluated from the centered vector-M dot-product ACF with an unbiased finite-record estimator, a 4 ps cosine lag window, and trapezoidal half weights at both finite integration endpoints. Positive frequencies are used; at Δt=0.04 ps, Nyquist is {d['nyquist_frequency_cm1']:.3f} cm⁻¹. The grid spacing is {freq[1]-freq[0]:.3f} cm⁻¹, and the reported maximum is {freq[-1]:.3f} cm⁻¹. The convention is χ=χ′−iχ_loss with χ_loss≥0. The one-oscillator fit RSS is {fit['one_oscillator']['rss']:.6g} (ω₀={single['omega0_cm1']:.3f}, γ={single['gamma_cm1']:.3f} cm⁻¹); the two-oscillator fit RSS is {fit['two_oscillator']['rss']:.6g} (ω₀,γ={two[0]['omega0_cm1']:.3f},{two[0]['gamma_cm1']:.3f} and {two[1]['omega0_cm1']:.3f},{two[1]['gamma_cm1']:.3f} cm⁻¹), with relative RSS reduction {fit['rss_improvement_ratio']:.4f}. The actual descriptive model preference is {fit['model_preference']}; upper-bound flags are one={fit['one_oscillator']['fit_touches_upper_bound']}, two={fit['two_oscillator']['fit_touches_upper_bound']}. A boundary-limited fit is INCONCLUSIVE despite any RSS decrease. Fits over 2, 4, and 6 ps lag windows are retained for sensitivity review. Across 2/4/6 ps windows the descriptive preferences are {', '.join(k+':'+v['model_preference'] for k,v in sens.items())}; these are perturbations of the same record, not independent replicas or parameter confidence intervals. Correlated frequency bins and one finite trajectory do not establish statistical necessity; no physical assignment is claimed. A broad overdamped relaxation and a second overlapping mode remain competing descriptions. A discriminating follow-up would fit one mode on independent contiguous time blocks and inspect held-out residual peaks at a predeclared frequency: a reproducible second component predicts a consistent residual peak and stable two-mode frequencies across blocks/windows, while truncation artifacts predict movement with the lag cutoff or disappearance in held-out blocks. The existing window comparison constrains robustness but cannot alone distinguish physical modes. New independent trajectories would be needed to treat reproducibility as independent sampling evidence. The tau jackknife concatenates retained pieces; its intervals are descriptive, may include artificial cross-gap adjacency, and are not a validated confidence interval for dielectric amplitude or fit parameters.
'''
(work/'harmonic_oscillator_selection.md').write_text(text,encoding='utf-8')
PY

PYTHONPATH="$PKG/public${PYTHONPATH:+:$PYTHONPATH}" "${PYTHON_BIN:-python3}" - "$PKG" "$WORK" <<'CONTROL_PY'
import json,sys
from pathlib import Path
from autonomous_controls import calculate
pkg,work=map(Path,sys.argv[1:])
spec={'split_fraction': 0.5, 'lag_windows_ps': [2.0, 6.0]}
(work/'constructive_controls.json').write_text(json.dumps({'spec':spec,'results':calculate(pkg/'inputs',spec)},indent=2))
CONTROL_PY
