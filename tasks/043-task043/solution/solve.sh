#!/usr/bin/env bash
set -euo pipefail
APP="${APP:-/app}"
export APP
exec python3 - <<'PY_ANALYZE'
#!/usr/bin/env python3
"""Recompute a finite audit and allocation exercise from public native files."""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
import statistics
from pathlib import Path

APP = Path(os.environ.get('APP', '/app'))
NATIVE = APP / 'inputs/native'
MANIFEST_PATH = APP / 'inputs/source-manifest.json'
MASS_TO_DENSITY = 1.660538921
EXPECTED_TEMPERATURES = (323, 333, 343, 353, 363, 373)
LIMITATION_CODES = [
    'single_short_segment_per_temperature',
    'eleven_frames_do_not_establish_independence',
    'stationarity_not_established',
    'correlation_time_and_ess_not_established',
    'equilibrium_density_precision_not_established',
    'equilibrium_temperature_response_not_established',
]


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def finite(value: float) -> float:
    value = float(value)
    if not math.isfinite(value):
        raise ValueError('non-finite numeric input')
    return value


def load_pinned_inputs() -> tuple[dict[str, str], str]:
    manifest = json.loads(MANIFEST_PATH.read_text(encoding='utf-8'))
    if manifest.get('schema') != 'reline02-public-native-inputs/v1':
        raise ValueError('unsupported public input manifest')
    expected = {}
    for row in manifest.get('files', []):
        rel = Path(row['path'])
        if rel.is_absolute() or '..' in rel.parts or rel.as_posix() != row['path']:
            raise ValueError('unsafe manifest path')
        if row['path'] in expected:
            raise ValueError('duplicate manifest path')
        path = NATIVE / rel
        if path.is_symlink() or not path.is_file():
            raise ValueError(f'missing or unsafe input: {row["path"]}')
        if path.stat().st_size != row['size_bytes'] or sha256(path) != row['sha256']:
            raise ValueError(f'input hash mismatch: {row["path"]}')
        expected[row['path']] = row['sha256']
    actual = {p.relative_to(NATIVE).as_posix() for p in NATIVE.rglob('*') if p.is_file()}
    if actual != set(expected):
        raise ValueError('native input tree differs from the declared manifest')
    return expected, sha256(MANIFEST_PATH)


def parse_masses(native_in: str) -> tuple[dict[int, float], int, float]:
    masses = {int(t): finite(m) for t, m in re.findall(r'^\s*mass\s+(\d+)\s+([0-9.eE+-]+)', native_in, re.M)}
    temp = re.search(r'^\s*fix\s+\S+\s+\S+\s+npt\s+temp\s+([0-9.eE+-]+)', native_in, re.M)
    timestep = re.search(r'^\s*timestep\s+([0-9.eE+-]+)', native_in, re.M)
    run = re.search(r'^\s*run\s+(\d+)', native_in, re.M)
    thermo = re.search(r'^\s*thermo\s+(\d+)', native_in, re.M)
    if not masses or not temp or not timestep or not run or not thermo:
        raise ValueError('native.in is missing required run settings')
    return masses, int(float(temp.group(1))), finite(timestep.group(1))


def run_settings(native_in: str) -> dict[str, float | int]:
    masses, target, timestep = parse_masses(native_in)
    pressure = re.search(r'\biso\s+([0-9.eE+-]+)\s+([0-9.eE+-]+)', native_in)
    if 'units metal' not in native_in or pressure is None or abs(float(pressure.group(1))-float(pressure.group(2))) > 1e-12:
        raise ValueError('native.in units or isotropic target pressure are unsupported')
    return {
        'masses_u': masses,
        'target_temperature_K': target,
        'target_pressure_bar': finite(pressure.group(1)),
        'timestep_ps': timestep,
        'requested_steps': int(re.search(r'^\s*run\s+(\d+)', native_in, re.M).group(1)),
        'thermo_stride_steps': int(re.search(r'^\s*thermo\s+(\d+)', native_in, re.M).group(1)),
    }


def parse_log(path: Path) -> list[dict[str, float | int]]:
    lines = path.read_text(encoding='utf-8', errors='strict').splitlines()
    rows = []
    header = None
    for line in lines:
        tokens = line.split()
        lower = [x.lower() for x in tokens]
        if {'step', 'time', 'temp', 'press', 'volume', 'density'}.issubset(lower):
            header = lower
            continue
        if header is None:
            continue
        if len(tokens) != len(header):
            if rows:
                header = None
            continue
        try:
            row = {key: finite(value) for key, value in zip(header, tokens)}
        except ValueError:
            if rows:
                header = None
            continue
        if row['step'].is_integer():
            row['step'] = int(row['step'])
            rows.append(row)
    if len(rows) != 11:
        raise ValueError(f'{path}: expected exactly 11 thermo rows, found {len(rows)}')
    return rows


def parse_trajectory(path: Path) -> list[dict]:
    lines = path.read_text(encoding='utf-8', errors='strict').splitlines()
    frames = []
    i = 0
    while i < len(lines):
        if lines[i] != 'ITEM: TIMESTEP':
            i += 1
            continue
        step = int(lines[i + 1]); i += 2
        if lines[i] != 'ITEM: NUMBER OF ATOMS':
            raise ValueError(f'{path}: missing atom-count marker')
        n_atoms = int(lines[i + 1]); i += 2
        if not lines[i].startswith('ITEM: BOX BOUNDS'):
            raise ValueError(f'{path}: missing box marker')
        bounds = []
        for boxline in lines[i + 1:i + 4]:
            vals = [finite(v) for v in boxline.split()]
            if len(vals) not in (2, 3) or (len(vals) == 3 and vals[2] != 0):
                raise ValueError(f'{path}: unsupported non-orthogonal box')
            bounds.append((vals[0], vals[1]))
        volume = math.prod(hi - lo for lo, hi in bounds)
        i += 4
        if not lines[i].startswith('ITEM: ATOMS '):
            raise ValueError(f'{path}: missing atom table')
        columns = lines[i].split()[2:]
        id_col, type_col = columns.index('id'), columns.index('type')
        i += 1
        atoms = []
        for line in lines[i:i + n_atoms]:
            fields = line.split()
            if len(fields) != len(columns):
                raise ValueError(f'{path}: malformed atom row')
            atoms.append((int(fields[id_col]), int(fields[type_col])))
        if len(atoms) != n_atoms or len({atom_id for atom_id, _ in atoms}) != n_atoms:
            raise ValueError(f'{path}: duplicate or missing atom identity')
        frames.append({'step': step, 'n_atoms': n_atoms, 'volume_A3': volume,
                       'type_counts': {str(t): sum(1 for _, typ in atoms if typ == t)
                                       for t in sorted({typ for _, typ in atoms})}})
        i += n_atoms
    if len(frames) != 11:
        raise ValueError(f'{path}: expected exactly 11 trajectory frames, found {len(frames)}')
    return frames


def mean(values: list[float]) -> float:
    return statistics.mean(values)


def slope(xs: list[float], ys: list[float]) -> float:
    xm, ym = mean(xs), mean(ys)
    denom = sum((x - xm) ** 2 for x in xs)
    if denom <= 0:
        raise ValueError('OLS requires distinct times')
    return sum((x - xm) * (y - ym) for x, y in zip(xs, ys)) / denom


def block_sensitivity(values: list[float], lengths=(2, 3)) -> list[dict]:
    rows = []
    for width in lengths:
        count = len(values) // width
        blocks = [mean(values[i * width:(i + 1) * width]) for i in range(count)]
        rows.append({'block_length_rows': width, 'complete_blocks': count,
                     'discarded_trailing_rows': len(values) - count * width,
                     'block_means_g_cm3': blocks,
                     'block_mean_range_g_cm3': max(blocks) - min(blocks) if blocks else None,
                     'sample_sd_of_block_means_g_cm3': statistics.stdev(blocks) if len(blocks) > 1 else None})
    return rows


def lag1_descriptive(values: list[float]) -> float | None:
    m = mean(values); var = statistics.pvariance(values)
    if len(values) < 3 or var == 0:
        return None
    return sum((a - m) * (b - m) for a, b in zip(values, values[1:])) / ((len(values) - 1) * var)


def largest_remainder(scores: list[tuple[int, float]], seats: int) -> dict[str, int]:
    total = sum(score for _, score in scores)
    if total == 0:
        q, rem = divmod(seats, len(scores))
        alloc = {str(t): q for t, _ in scores}
        for t, _ in sorted(scores)[:rem]:
            alloc[str(t)] += 1
        return alloc
    exact = {str(t): seats * score / total for t, score in scores}
    alloc = {t: math.floor(value) for t, value in exact.items()}
    remainder = seats - sum(alloc.values())
    ranked = sorted(scores, key=lambda row: (-(exact[str(row[0])] - alloc[str(row[0])]), row[0]))
    for t, _ in ranked[:remainder]:
        alloc[str(t)] += 1
    return alloc


def analyze_temperature(temperature: int) -> dict:
    folder = NATIVE / f'T{temperature}'
    native_in = (folder / 'native.in').read_text(encoding='utf-8')
    settings = run_settings(native_in)
    runtime = json.loads((folder / 'native-runtime.json').read_text(encoding='utf-8'))
    log = parse_log(folder / 'log.lammps')
    frames = parse_trajectory(folder / 'trajectory.lmp')
    if runtime.get('status') != 'COMPLETE':
        raise ValueError(f'{folder}: native runtime not COMPLETE')
    if runtime.get('T_K') != temperature or settings['target_temperature_K'] != temperature:
        raise ValueError(f'{folder}: temperature identity mismatch')
    if runtime.get('requested_steps') != settings['requested_steps'] or runtime.get('executed_steps') != settings['requested_steps']:
        raise ValueError(f'{folder}: run length mismatch')
    if abs(float(runtime.get('dt_fs')) - settings['timestep_ps'] * 1000.0) > 1e-9:
        raise ValueError(f'{folder}: timestep metadata mismatch')
    if runtime.get('natoms') != frames[0]['n_atoms']:
        raise ValueError(f'{folder}: atom count mismatch')
    masses = settings['masses_u']
    types = {int(t): count for t, count in frames[0]['type_counts'].items()}
    if set(types) - set(masses):
        raise ValueError(f'{folder}: atom type lacks a mass')
    total_mass_u = sum(count * masses[t] for t, count in types.items())
    if any(frame['n_atoms'] != frames[0]['n_atoms'] or frame['type_counts'] != frames[0]['type_counts'] for frame in frames):
        raise ValueError(f'{folder}: atom identity/type population changes between frames')
    if [r['step'] for r in log] != [f['step'] for f in frames]:
        raise ValueError(f'{folder}: log and trajectory steps differ')
    stride = settings['thermo_stride_steps']
    if [r['step'] for r in log] != list(range(0, settings['requested_steps'] + 1, stride)):
        raise ValueError(f'{folder}: unexpected thermo step sequence')
    densities = []
    errors = []
    times = []
    temperatures = []
    pressures = []
    for row, frame in zip(log, frames):
        if abs(row['time'] - row['step'] * settings['timestep_ps']) > 1e-8:
            raise ValueError(f'{folder}: log time does not follow timestep settings')
        if abs(row['volume'] - frame['volume_A3']) > 0.002:
            raise ValueError(f'{folder}: log and trajectory volume differ')
        rho = total_mass_u * MASS_TO_DENSITY / frame['volume_A3']
        errors.append(abs(rho - row['density']))
        densities.append(rho); times.append(row['time']); temperatures.append(row['temp']); pressures.append(row['press'])
    duration = times[-1] - times[0]
    early_rho, late_rho = densities[:5], densities[-5:]
    early_temp, late_temp = temperatures[:5], temperatures[-5:]
    rho_slope = slope(times, densities)
    return {
        'temperature_K': temperature,
        'target_temperature_K': settings['target_temperature_K'],
        'target_pressure_bar': settings['target_pressure_bar'],
        'rows': len(log),
        'step_range': [log[0]['step'], log[-1]['step']],
        'time_ps_range': [times[0], times[-1]],
        'observed_duration_ps': duration,
        'timestep_fs': settings['timestep_ps'] * 1000.0,
        'thermo_stride_steps': stride,
        'requested_steps': settings['requested_steps'],
        'atoms': frames[0]['n_atoms'],
        'atom_type_counts': types,
        'mean_density_g_cm3': mean(densities),
        'sample_sd_density_g_cm3': statistics.stdev(densities),
        'density_slope_g_cm3_ps_descriptive': rho_slope,
        'early5_mean_density_g_cm3': mean(early_rho),
        'late5_mean_density_g_cm3': mean(late_rho),
        'early5_mean_temperature_K': mean(early_temp),
        'late5_mean_temperature_K': mean(late_temp),
        'window_delta_density_g_cm3': mean(late_rho) - mean(early_rho),
        'mean_pressure_bar': mean(pressures),
        'block_sensitivity': block_sensitivity(densities),
        'lag1_descriptive_only': lag1_descriptive(densities),
        'density_mass_volume_max_abs_error_g_cm3': max(errors),
        'series': {'time_ps': times, 'temperature_K': temperatures, 'pressure_bar': pressures,
                   'volume_A3': [f['volume_A3'] for f in frames], 'density_g_cm3': densities},
        'source_hashes': {name: sha256(folder / name) for name in ('native.in', 'native-runtime.json', 'log.lammps', 'trajectory.lmp')},
        'priority_components': None,
    }


def main() -> None:
    source_hashes, manifest_sha = load_pinned_inputs()
    audits = [analyze_temperature(t) for t in EXPECTED_TEMPERATURES]
    for row in audits:
        drho = max(abs(row['density_slope_g_cm3_ps_descriptive']) * row['observed_duration_ps'],
                   abs(row['window_delta_density_g_cm3'])) / 0.005
        dtemp = abs(row['late5_mean_temperature_K'] - row['target_temperature_K']) / 5.0
        row['priority_components'] = {'D_rho': drho, 'D_T': dtemp, 'score': max(drho, dtemp)}
    extra = largest_remainder([(r['temperature_K'], r['priority_components']['score']) for r in audits], 6)
    for row in audits:
        row['pilot_priority'] = {'stage_one_units': 1, 'stage_two_units': extra[str(row['temperature_K'])],
                                 'total_units': 1 + extra[str(row['temperature_K'])],
                                 **row.pop('priority_components')}
    means = [r['mean_density_g_cm3'] for r in audits]
    temps = [float(r['temperature_K']) for r in audits]
    thermal_slope = slope(temps, means)
    audit = {
        'schema': 'reline02-density-audit/v2',
        'source_manifest_sha256': manifest_sha,
        'source_hashes': source_hashes,
        'temperature_audits': audits,
        'cross_temperature': {
            'descriptive_mean_density_slope_g_cm3_per_K': thermal_slope,
            'status': 'descriptive_only_not_equilibrium_thermal_response',
            'limitation_codes': ['single_short_segment_per_temperature', 'within_window_drift_remains_relevant']
        },
        'limitation_codes': LIMITATION_CODES
    }
    claims = {
        'finite_window_density_and_drift': 'supported_observation',
        'stationarity': 'not_identifiable',
        'equilibrium_density_precision': 'not_identifiable',
        'correlation_time_and_ess': 'not_identifiable',
        'equilibrium_temperature_response': 'not_identifiable'
    }
    allocations = {str(r['temperature_K']): r['pilot_priority']['total_units'] for r in audits}
    decision = {
        'schema': 'reline02-density-decision/v2',
        'claim_status': claims,
        'historical_replay_status': {'status': 'FAIL', 'reward': 0,
                                     'contract': 'prior full-science contract; preserved historical result'},
        'sampling_scenario': {
            'status': 'planned_only', 'unit_duration_ps': 0.5, 'units_total': 12,
            'stage_one_units_per_temperature': 1, 'stage_two_units': 6,
            'stage_two_allocations_by_temperature': {t: allocations[t] - 1 for t in allocations},
            'total_allocations_by_temperature': allocations,
            'total_planned_duration_ps': 6.0,
            'allocation_rule': 'proportional_largest_remainder_with_temperature_tiebreak_and_equal_allocation_if_zero',
            'trigger_scales': {'density_g_cm3': 0.005, 'temperature_K': 5.0,
                               'meaning': 'planning_only_not_confidence_or_equilibrium_threshold'}
        },
        'pilot_priority': [{'temperature_K': r['temperature_K'], **r['pilot_priority']} for r in audits],
        'limitation_codes': LIMITATION_CODES,
        'stage_one_recheck': {'required': True,
                              'recompute_before_stage_two': True,
                              'diagnostics': ['density_and_temperature_series', 'window_sensitivity', 'block_sensitivity', 'pilot_priority_scores'],
                              'historical_stage_two_allocation_is_adaptive': False,
                              'if_stationarity_or_correlation_unidentified': 'diagnostic_continuation_only'},
        'stop_rule': {'maximum_units': 12,
                      'if_stationarity_or_correlation_unidentified_at_cap': 'stop_and_leave_claims_unresolved',
                      'production_equilibrium_claim_allowed_if_unresolved': False},
        'execution_status': 'planned_only'
    }
    (APP / 'audit.json').write_text(json.dumps(audit, sort_keys=True, indent=2, allow_nan=False) + '\n')
    (APP / 'decision.json').write_text(json.dumps(decision, sort_keys=True, indent=2, allow_nan=False) + '\n')
    report = [
        '# Case02 evidence audit and sampling decision', '',
        '## Observed evidence', '',
        f"The audit independently parsed {len(audits)} temperature runs and {sum(r['rows'] for r in audits)} thermo rows. The full-window mean density range is {min(means):.9f}–{max(means):.9f} g/cm³. The fitted cross-temperature slope is descriptive only ({thermal_slope:.6g} g/cm³/K); each temperature has one short trajectory and within-window drift remains relevant.", '',
        'Temperature table: T_K | mean_density_g_cm3 | density_slope_g_cm3_ps | stage1_units | stage2_units',
        *[f"{r['temperature_K']} | {r['mean_density_g_cm3']:.9f} | {r['density_slope_g_cm3_ps_descriptive']:.9f} | {r['pilot_priority']['stage_one_units']} | {r['pilot_priority']['stage_two_units']}" for r in audits], '',
        '## What is not identified', '',
        'These traces do not establish stationarity, a reliable correlation time or ESS, equilibrium-density precision, or an equilibrium temperature response. The lag-1 and block summaries are finite-window sensitivity diagnostics, not independent-sample confidence estimates. The historical full-science replay remains FAIL/reward 0 under its original contract.', '',
        '## Bounded sampling proposal', '',
        'The 12-unit / 6-ps menu is planned only and not executed: stage one assigns one 0.5-ps unit to each temperature, and the six stage-two units are allocated from the recomputed published score. After stage one, recompute the diagnostics before stage two; stop at the budget cap and leave unsupported claims unresolved.', '',
        'Per-temperature calculations and exact pilot allocations are in `audit.json` and `decision.json`.'
    ]
    (APP / 'report.md').write_text('\n'.join(report) + '\n', encoding='utf-8')


if __name__ == '__main__':
    main()
PY_ANALYZE
