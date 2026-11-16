#!/usr/bin/env python3
# L1 Deliverables: Check required deliverables for completeness and parseability (including audit.json, decision.json, report.md).
# L2 Execution: No separate execution attestation is implied by checks of submitted results.
# L3 Science: Analyse temperature-dependent behaviour in archived short NPT trajectories.
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

def _make_case43_science():
    #!/usr/bin/env python3
    """Independent stdlib verifier for the public Case02 audit contract."""

    import hashlib
    import json
    import math
    import os
    import re
    import statistics
    import sys
    from pathlib import Path


    APP = Path(os.environ.get('APP', '/app'))
    TESTS = Path(os.environ.get('TESTS', '/tests'))
    INPUTS = APP / 'inputs'
    NATIVE = INPUTS / 'native'
    _NUMERIC_REFS = json.loads((TESTS/'refs.json').read_text())
    TEMPERATURES = tuple(_NUMERIC_REFS['temperature_grid_K'])
    CONVERSION = _NUMERIC_REFS['amu_angstrom3_to_g_cm3']
    TOL = _NUMERIC_REFS['density_relative_tolerance']


    def digest(path: Path) -> str:
        h = hashlib.sha256()
        with path.open('rb') as f:
            for chunk in iter(lambda: f.read(1024 * 1024), b''):
                h.update(chunk)
        return h.hexdigest()


    def check(condition: bool, name: str, detail: str = '') -> dict:
        return {'name': name, 'passed': bool(condition), 'detail': detail[:500]}


    def close(a, b, tol=TOL) -> bool:
        if isinstance(a, bool) or isinstance(b, bool):
            return type(a) is type(b) and a == b
        if isinstance(a, (int, float)) and isinstance(b, (int, float)):
            return math.isfinite(float(a)) and math.isfinite(float(b)) and abs(float(a) - float(b)) <= tol * max(1.0, abs(float(b)))
        if isinstance(a, list) and isinstance(b, list):
            return len(a) == len(b) and all(close(x, y, tol) for x, y in zip(a, b))
        if isinstance(a, dict) and isinstance(b, dict):
            return set(a) == set(b) and all(close(a[k], b[k], tol) for k in a)
        return a == b


    def json_integer(value) -> bool:
        """Accept JSON integer values regardless of a redundant decimal point."""
        return (type(value) in (int, float) and abs(value) <= 2**53 - 1
                and math.isfinite(value) and value == int(value))


    def close_abs(a, b, tol: float) -> bool:
        """Compare density-valued outputs with a narrow absolute SI-equivalence tolerance."""
        if isinstance(a, bool) or isinstance(b, bool):
            return type(a) is type(b) and a == b
        if isinstance(a, (int, float)) and isinstance(b, (int, float)):
            try:
                return math.isfinite(float(a)) and math.isfinite(float(b)) and abs(float(a)-float(b)) <= tol
            except OverflowError:
                return False
        if isinstance(a, list) and isinstance(b, list):
            return len(a)==len(b) and all(close_abs(x,y,tol) for x,y in zip(a,b))
        if isinstance(a, dict) and isinstance(b, dict):
            return set(a)==set(b) and all(close_abs(a[k],b[k],tol) for k in a)
        return a==b


    def parse_input_native(folder: Path) -> dict:
        raw = (folder / 'native.in').read_text()
        masses = {}
        for line in raw.splitlines():
            m = re.match(r'^\s*mass\s+(\d+)\s+([0-9.eE+-]+)', line)
            if m:
                masses[int(m.group(1))] = float(m.group(2))
        temp_line = next((x.split() for x in raw.splitlines() if re.match(r'^\s*fix\s+\S+\s+\S+\s+npt\s+temp\s+', x)), None)
        step_line = next((x.split() for x in raw.splitlines() if re.match(r'^\s*timestep\s+', x)), None)
        run_line = next((x.split() for x in raw.splitlines() if re.match(r'^\s*run\s+\d+', x)), None)
        thermo_line = next((x.split() for x in raw.splitlines() if re.match(r'^\s*thermo\s+\d+', x)), None)
        pressure = re.search(r'\biso\s+([0-9.eE+-]+)\s+([0-9.eE+-]+)', raw)
        if not masses or temp_line is None or step_line is None or run_line is None or thermo_line is None or pressure is None or 'units metal' not in raw:
            raise ValueError('incomplete native.in')
        if abs(float(pressure.group(1))-float(pressure.group(2))) > _NUMERIC_REFS['pressure_endpoint_tolerance_bar']:
            raise ValueError('isotropic pressure endpoints differ')
        return {'masses': masses, 'target': int(float(temp_line[5])), 'target_pressure': float(pressure.group(1)), 'dt': float(step_line[1]),
                'run': int(run_line[1]), 'stride': int(thermo_line[1])}


    def parse_thermo(path: Path) -> list[dict[str, float]]:
        data = path.read_text().splitlines()
        result = []
        columns = None
        for line in data:
            f = line.split()
            lower = [v.lower() for v in f]
            if all(v in lower for v in ('step', 'time', 'temp', 'press', 'volume', 'density')):
                columns = lower
                continue
            if columns is None or len(f) != len(columns):
                continue
            try:
                values = [float(v) for v in f]
            except ValueError:
                continue
            if not all(math.isfinite(v) for v in values):
                raise ValueError('nonfinite thermo value')
            row = dict(zip(columns, values))
            if row['step'].is_integer():
                result.append(row)
        if len(result) != 11:
            raise ValueError(f'expected 11 thermo rows, found {len(result)}')
        return result


    def parse_dump(path: Path) -> list[dict]:
        lines = path.read_text().splitlines()
        frames = []
        pos = 0
        while pos < len(lines):
            if lines[pos].strip() != 'ITEM: TIMESTEP':
                pos += 1
                continue
            step = int(lines[pos + 1]); n = int(lines[pos + 3])
            if lines[pos + 2].strip() != 'ITEM: NUMBER OF ATOMS' or not lines[pos + 4].startswith('ITEM: BOX BOUNDS'):
                raise ValueError('malformed trajectory header')
            bounds = []
            for row in lines[pos + 5:pos + 8]:
                nums = [float(v) for v in row.split()]
                if len(nums) not in (2, 3) or not all(math.isfinite(x) for x in nums) or (len(nums) == 3 and nums[2] != 0):
                    raise ValueError('unsupported or nonfinite box')
                bounds.append(nums[:2])
            vol = math.prod(b - a for a, b in bounds)
            atom_header = lines[pos + 8].split()[2:]
            ids_at, types_at = atom_header.index('id'), atom_header.index('type')
            records = [lines[k].split() for k in range(pos + 9, pos + 9 + n)]
            ids = [int(r[ids_at]) for r in records]
            atom_types = [int(r[types_at]) for r in records]
            if len(set(ids)) != n or not all(len(r) == len(atom_header) for r in records):
                raise ValueError('atom identity or row shape invalid')
            counts = {t: atom_types.count(t) for t in sorted(set(atom_types))}
            frames.append({'step': step, 'n': n, 'volume': vol, 'counts': counts})
            pos += 9 + n
        if len(frames) != 11:
            raise ValueError(f'expected 11 trajectory frames, found {len(frames)}')
        return frames


    def avg(x: list[float]) -> float:
        return statistics.mean(x)


    def lin_slope(x: list[float], y: list[float]) -> float:
        mx, my = avg(x), avg(y)
        return sum((a-mx)*(b-my) for a,b in zip(x,y)) / sum((a-mx)**2 for a in x)


    def blocks(values: list[float], width: int) -> dict:
        n = len(values) // width
        means = [avg(values[k*width:(k+1)*width]) for k in range(n)]
        return {'block_length_rows': width, 'complete_blocks': n,
                'discarded_trailing_rows': len(values)-n*width,
                'block_means_g_cm3': means,
                'block_mean_range_g_cm3': max(means)-min(means),
                'sample_sd_of_block_means_g_cm3': statistics.stdev(means) if len(means)>1 else None}


    def recompute() -> tuple[dict[str, str], str, list[dict]]:
        manifest_path = INPUTS / 'source-manifest.json'
        manifest = json.loads(manifest_path.read_text())
        rows = manifest['files']
        expected = {x['path']: x['sha256'] for x in rows}
        actual_paths = {x.relative_to(NATIVE).as_posix() for x in NATIVE.rglob('*') if x.is_file()}
        if actual_paths != set(expected):
            raise ValueError('public native file inventory differs from manifest')
        input_hashes = {}
        for item in rows:
            p = NATIVE / item['path']
            if p.is_symlink() or p.stat().st_size != item['size_bytes'] or digest(p) != item['sha256']:
                raise ValueError(f'input hash/size mismatch: {item["path"]}')
            input_hashes[item['path']] = item['sha256']
        calculated = []
        for target in TEMPERATURES:
            folder = NATIVE / f'T{target}'
            settings = parse_input_native(folder)
            runtime = json.loads((folder/'native-runtime.json').read_text())
            log = parse_thermo(folder/'log.lammps')
            dump = parse_dump(folder/'trajectory.lmp')
            if settings['target'] != target or runtime.get('T_K') != target or runtime.get('status') != 'COMPLETE':
                raise ValueError(f'T{target}: run temperature/status mismatch')
            if runtime.get('requested_steps') != settings['run'] or runtime.get('executed_steps') != settings['run']:
                raise ValueError(f'T{target}: run step metadata mismatch')
            if abs(runtime.get('dt_fs', -1) - settings['dt']*1000) > 1e-9:
                raise ValueError(f'T{target}: timestep metadata mismatch')
            if [int(r['step']) for r in log] != [f['step'] for f in dump] or [int(r['step']) for r in log] != list(range(0,settings['run']+1,settings['stride'])):
                raise ValueError(f'T{target}: log/dump chronology mismatch')
            type_counts = dump[0]['counts']
            if runtime.get('natoms') != dump[0]['n'] or any(f['n'] != dump[0]['n'] or f['counts'] != type_counts for f in dump):
                raise ValueError(f'T{target}: atom identity mismatch')
            mass = sum(type_counts[t] * settings['masses'][t] for t in type_counts)
            rho, time, temp, pressure, errors = [], [], [], [], []
            for x, frame in zip(log, dump):
                if abs(x['time'] - x['step']*settings['dt']) > 1e-8 or abs(x['volume']-frame['volume']) > 0.002:
                    raise ValueError(f'T{target}: time/volume mismatch')
                density = mass * CONVERSION / frame['volume']
                rho.append(density); time.append(x['time']); temp.append(x['temp']); pressure.append(x['press'])
                errors.append(abs(density-x['density']))
            if max(errors)>_NUMERIC_REFS['mass_volume_crosscheck_tolerance_g_cm3']:
                raise ValueError(f'T{target}: recomputed density differs from LAMMPS thermo beyond the public tolerance')
            if abs(float(runtime.get('temperature_K',float('nan')))-temp[-1]) > 0.005 or abs(float(runtime.get('volume_A3',float('nan')))-dump[-1]['volume']) > 0.002 or abs(float(runtime.get('density_g_cm3',float('nan')))-log[-1]['density']) > 1e-5:
                raise ValueError(f'T{target}: terminal native-runtime summary differs from raw thermo/trajectory')
            delta = avg(rho[-5:])-avg(rho[:5]); trend = lin_slope(time,rho)
            centered = [v-avg(rho) for v in rho]
            lag = sum(a*b for a,b in zip(centered,centered[1:]))/((len(rho)-1)*statistics.pvariance(rho))
            m = re.search(r'^\s*fix\s+\S+\s+\S+\s+npt\s+temp\s+([0-9.eE+-]+)', (folder/'native.in').read_text(), re.M)
            target_temp = float(m.group(1))
            early_temp, late_temp = avg(temp[:5]), avg(temp[-5:])
            d_rho = max(abs(trend)*(time[-1]-time[0]), abs(delta))/0.005
            d_temp = abs(late_temp-target_temp)/5.0
            calculated.append({
                'temperature_K': target, 'target_temperature_K': target_temp, 'target_pressure_bar':settings['target_pressure'], 'rows':len(log),
                'step_range':[int(log[0]['step']),int(log[-1]['step'])], 'time_ps_range':[time[0],time[-1]],
                'observed_duration_ps':time[-1]-time[0], 'timestep_fs':settings['dt']*1000,
                'thermo_stride_steps':settings['stride'],'requested_steps':settings['run'],'atoms':dump[0]['n'],
                'atom_type_counts':{str(k):v for k,v in type_counts.items()},
                'mean_density_g_cm3':avg(rho),'sample_sd_density_g_cm3':statistics.stdev(rho),
                'density_slope_g_cm3_ps_descriptive':trend,
                'early5_mean_density_g_cm3':avg(rho[:5]),'late5_mean_density_g_cm3':avg(rho[-5:]),
                'early5_mean_temperature_K':early_temp,'late5_mean_temperature_K':late_temp,
                'window_delta_density_g_cm3':delta,'mean_pressure_bar':avg(pressure),
                'block_sensitivity':[blocks(rho,2),blocks(rho,3)],'lag1_descriptive_only':lag,
                'density_mass_volume_max_abs_error_g_cm3':max(errors),
                'series':{'time_ps':time,'temperature_K':temp,'pressure_bar':pressure,
                          'volume_A3':[f['volume'] for f in dump],'density_g_cm3':rho},
                'source_hashes':{name:digest(folder/name) for name in ('native.in','native-runtime.json','log.lammps','trajectory.lmp')},
                'priority_components':{'D_rho':d_rho,'D_T':d_temp,'score':max(d_rho,d_temp)}
            })
        return input_hashes, digest(manifest_path), calculated


    def largest_remainder(rows: list[dict], seats: int) -> dict[str, int]:
        scores = {str(x['temperature_K']):x['priority_components']['score'] for x in rows}
        total = sum(scores.values())
        if total == 0:
            base, rem = divmod(seats, len(scores)); result = {k:base for k in scores}
            for key in sorted(scores, key=int)[:rem]: result[key] += 1
            return result
        exact = {k:seats*v/total for k,v in scores.items()}
        base = {k:math.floor(v) for k,v in exact.items()}
        leftovers = seats - sum(base.values())
        for key in sorted(scores, key=lambda k:(-(exact[k]-base[k]),int(k)))[:leftovers]:
            base[key] += 1
        return base


    def main() -> int:
        checks = []
        try:
            refs = json.loads((TESTS/'reference-hashes.json').read_text())
            for name, wanted in refs.items():
                path = (APP/name) if name.startswith('inputs/') or name == 'output-contract.json' else (TESTS/name.removeprefix('tests/'))
                if path.is_symlink() or not path.is_file() or digest(path) != wanted:
                    raise RuntimeError(f'trusted asset pin mismatch: {name}')
            expected_hashes, manifest_sha, expected_rows = recompute()
            audit = json.loads((APP/'audit.json').read_text())
            decision = json.loads((APP/'decision.json').read_text())
            report = (APP/'report.md').read_text(encoding='utf-8')
            audit_keys={'schema','source_manifest_sha256','source_hashes','temperature_audits','cross_temperature','limitation_codes'}
            decision_keys={'schema','claim_status','historical_replay_status','sampling_scenario','pilot_priority','limitation_codes','stage_one_recheck','stop_rule','execution_status'}
            checks.append(check(isinstance(audit,dict) and audit_keys <= set(audit) and audit.get('schema')=='reline02-density-audit/v2' and audit.get('source_manifest_sha256')==manifest_sha and audit.get('source_hashes')==expected_hashes,'native_input_provenance'))
            observed = audit.get('temperature_audits')
            checks.append(check(isinstance(observed,list) and [x.get('temperature_K') for x in observed]==list(TEMPERATURES),'six_temperature_coverage'))
            if not isinstance(observed,list) or len(observed)!=6:
                observed=[]
            per_temp_ok = len(observed)==len(expected_rows)
            if per_temp_ok:
                for got, want in zip(observed, expected_rows):
                    if not isinstance(got,dict):
                        per_temp_ok=False
                        break
                    for key, value in want.items():
                        if key == 'priority_components':
                            continue
                        if key == 'pilot_priority':
                            continue
                        density_fields={'mean_density_g_cm3','sample_sd_density_g_cm3','density_slope_g_cm3_ps_descriptive',
                                        'early5_mean_density_g_cm3','late5_mean_density_g_cm3','window_delta_density_g_cm3',
                                        'density_mass_volume_max_abs_error_g_cm3'}
                        if key not in got:
                            per_temp_ok=False
                            break
                        if key in density_fields:
                            matches=close_abs(got[key],value,_NUMERIC_REFS['density_absolute_tolerance_g_cm3'])
                        elif key=='series':
                            matches=isinstance(got[key],dict) and set(got[key])==set(value)
                            if matches:
                                matches=all(close_abs(got[key][name],value[name],_NUMERIC_REFS['density_absolute_tolerance_g_cm3']) if name=='density_g_cm3' else close(got[key][name],value[name]) for name in value)
                        elif key=='block_sensitivity':
                            matches=isinstance(got[key],list) and len(got[key])==len(value)
                            if matches:
                                density_block_fields={'block_means_g_cm3','block_mean_range_g_cm3','sample_sd_of_block_means_g_cm3'}
                                matches=all(set(actual)==set(expected) and all(close_abs(actual[k],expected[k],_NUMERIC_REFS['density_absolute_tolerance_g_cm3']) if k in density_block_fields else close(actual[k],expected[k]) for k in expected) for actual,expected in zip(got[key],value))
                        else:
                            matches=close(got[key],value)
                        if not matches:
                            per_temp_ok=False
                            break
                    integer_fields=('temperature_K','rows','thermo_stride_steps','requested_steps','atoms')
                    per_temp_ok &= all(type(got.get(key)) is int for key in integer_fields)
                    per_temp_ok &= isinstance(got.get('step_range'),list) and len(got['step_range'])==2 and all(json_integer(v) for v in got['step_range'])
                    counts=got.get('atom_type_counts')
                    per_temp_ok &= isinstance(counts,dict) and all(type(v) is int for v in counts.values())
                    blocks_obj=got.get('block_sensitivity')
                    per_temp_ok &= isinstance(blocks_obj,list) and len(blocks_obj)==2
                    if isinstance(blocks_obj,list):
                        for block in blocks_obj:
                            per_temp_ok &= isinstance(block,dict) and type(block.get('block_length_rows')) is int and type(block.get('complete_blocks')) is int and type(block.get('discarded_trailing_rows')) is int
                    pp=got.get('pilot_priority')
                    per_temp_ok &= isinstance(pp,dict) and all(type(pp.get(k)) is int for k in ('stage_one_units','stage_two_units','total_units'))
                    if not per_temp_ok: break
            checks.append(check(per_temp_ok,'trajectory_reconstruction_and_window_sensitivity'))
            density_ok=len(expected_rows)==6 and all(x['density_mass_volume_max_abs_error_g_cm3']<=_NUMERIC_REFS['mass_volume_crosscheck_tolerance_g_cm3'] for x in expected_rows)
            checks.append(check(density_ok,'mass_volume_density_crosscheck_tolerance'))
            cross=audit.get('cross_temperature',{})
            fitted=lin_slope([float(x['temperature_K']) for x in expected_rows],[x['mean_density_g_cm3'] for x in expected_rows])
            cross_ok=set(cross)=={'descriptive_mean_density_slope_g_cm3_per_K','status','limitation_codes'}
            cross_ok &= cross.get('status')=='descriptive_only_not_equilibrium_thermal_response'
            cross_ok &= close(cross.get('descriptive_mean_density_slope_g_cm3_per_K'),fitted)
            cross_ok &= cross.get('limitation_codes')==['single_short_segment_per_temperature','within_window_drift_remains_relevant']
            expected_limits=['single_short_segment_per_temperature','eleven_frames_do_not_establish_independence','stationarity_not_established','correlation_time_and_ess_not_established','equilibrium_density_precision_not_established','equilibrium_temperature_response_not_established']
            cross_ok &= audit.get('limitation_codes')==expected_limits
            checks.append(check(cross_ok,'descriptive_thermal_fit_and_limitations'))
            extras = largest_remainder(expected_rows,6)
            allocation_ok = True
            if len(observed)==6:
                for got in observed:
                    expected_row_keys=set(expected_rows[0])-{'priority_components'}
                    expected_row_keys.add('pilot_priority')
                    allocation_ok &= set(got)==expected_row_keys
                    key=str(got['temperature_K']); components=got.get('pilot_priority',{})
                    want=next(r for r in expected_rows if r['temperature_K']==got['temperature_K'])['priority_components']
                    allocation_ok &= close_abs(components.get('D_rho'),want['D_rho'],_NUMERIC_REFS['priority_density_tolerance_g_cm3'])
                    allocation_ok &= close(components.get('D_T'),want['D_T'])
                    allocation_ok &= close(components.get('score'),max(components.get('D_rho'),components.get('D_T')))
                    allocation_ok &= set(components)=={'stage_one_units','stage_two_units','total_units','D_rho','D_T','score'}
                    allocation_ok &= all(type(components.get(k)) is int for k in ('stage_one_units','stage_two_units','total_units'))
                    allocation_ok &= components.get('stage_one_units')==1 and components.get('stage_two_units')==extras[key] and components.get('total_units')==extras[key]+1
            scenario=decision.get('sampling_scenario',{})
            scenario_keys={'status','unit_duration_ps','units_total','stage_one_units_per_temperature','stage_two_units','stage_two_allocations_by_temperature','total_allocations_by_temperature','total_planned_duration_ps','allocation_rule','trigger_scales'}
            required_decision_keys = decision_keys - {'historical_replay_status'}
            allocation_ok &= isinstance(decision,dict) and required_decision_keys <= set(decision) and decision.get('schema')=='reline02-density-decision/v2'
            allocation_ok &= set(scenario)==scenario_keys
            allocation_ok &= type(scenario.get('units_total')) is int and type(scenario.get('stage_one_units_per_temperature')) is int and type(scenario.get('stage_two_units')) is int
            allocation_ok &= scenario.get('status')=='planned_only' and scenario.get('units_total')==12 and scenario.get('unit_duration_ps')==0.5
            allocation_ok &= type(scenario.get('stage_one_units_per_temperature')) is int and scenario.get('stage_one_units_per_temperature')==1
            allocation_ok &= scenario.get('allocation_rule')=='proportional_largest_remainder_with_temperature_tiebreak_and_equal_allocation_if_zero'
            stage_two_allocations=scenario.get('stage_two_allocations_by_temperature')
            total_allocations=scenario.get('total_allocations_by_temperature')
            allocation_ok &= isinstance(stage_two_allocations,dict) and set(stage_two_allocations)==set(extras) and all(type(v) is int for v in stage_two_allocations.values())
            allocation_ok &= isinstance(total_allocations,dict) and set(total_allocations)==set(extras) and all(type(v) is int for v in total_allocations.values())
            allocation_ok &= scenario.get('stage_two_allocations_by_temperature')==extras
            allocation_ok &= scenario.get('total_allocations_by_temperature')=={k:v+1 for k,v in extras.items()}
            allocation_ok &= scenario.get('total_planned_duration_ps')==6.0 and scenario.get('stage_two_units')==6
            triggers=scenario.get('trigger_scales',{})
            allocation_ok &= set(triggers)=={'density_g_cm3','temperature_K','meaning'}
            allocation_ok &= triggers.get('density_g_cm3')==0.005 and triggers.get('temperature_K')==5.0
            allocation_ok &= triggers.get('meaning')=='planning_only_not_confidence_or_equilibrium_threshold'
            recheck_obj=decision.get('stage_one_recheck',{})
            allocation_ok &= set(recheck_obj)=={'required','recompute_before_stage_two','diagnostics','historical_stage_two_allocation_is_adaptive','if_stationarity_or_correlation_unidentified'}
            allocation_ok &= recheck_obj.get('required') is True and recheck_obj.get('recompute_before_stage_two') is True
            allocation_ok &= recheck_obj.get('diagnostics')==['density_and_temperature_series','window_sensitivity','block_sensitivity','pilot_priority_scores']
            allocation_ok &= recheck_obj.get('historical_stage_two_allocation_is_adaptive') is False
            allocation_ok &= recheck_obj.get('if_stationarity_or_correlation_unidentified')=='diagnostic_continuation_only'
            stop=decision.get('stop_rule',{})
            allocation_ok &= isinstance(stop,dict) and set(stop)=={'maximum_units','if_stationarity_or_correlation_unidentified_at_cap','production_equilibrium_claim_allowed_if_unresolved'}
            allocation_ok &= type(stop.get('maximum_units')) is int and stop.get('maximum_units')==12
            allocation_ok &= stop.get('if_stationarity_or_correlation_unidentified_at_cap')=='stop_and_leave_claims_unresolved'
            allocation_ok &= stop.get('production_equilibrium_claim_allowed_if_unresolved') is False
            allocation_ok &= decision.get('execution_status')=='planned_only'
            priority=decision.get('pilot_priority') if isinstance(decision,dict) else None
            priority_rows=[]
            expected_temperatures=set(TEMPERATURES)
            if isinstance(priority,list):
                if len(priority)==len(TEMPERATURES) and all(isinstance(row,dict) for row in priority):
                    row_temperatures=[row.get('temperature_K') for row in priority]
                    if (all(type(temp) is int for temp in row_temperatures)
                            and len(set(row_temperatures))==len(TEMPERATURES)
                            and set(row_temperatures)==expected_temperatures):
                        priority_rows=priority
                    else:
                        allocation_ok=False
                else:
                    allocation_ok=False
            elif isinstance(priority,dict):
                expected_keys={str(temp) for temp in TEMPERATURES}
                if set(priority)==expected_keys:
                    for temp in TEMPERATURES:
                        row=priority.get(str(temp))
                        if not isinstance(row,dict):
                            allocation_ok=False
                            continue
                        if ('temperature_K' in row
                                and (type(row['temperature_K']) is not int or row['temperature_K']!=temp)):
                            allocation_ok=False
                            continue
                        normalized=dict(row)
                        normalized['temperature_K']=temp
                        priority_rows.append(normalized)
                else:
                    allocation_ok=False
            else:
                allocation_ok=False
            allocation_ok &= len(priority_rows)==len(TEMPERATURES)
            for got in priority_rows:
                match=next((r for r in expected_rows if r['temperature_K']==got.get('temperature_K')),None)
                if match is None:
                    allocation_ok=False; continue
                expected_fields={**match['priority_components'],'stage_one_units':1,
                                 'stage_two_units':extras[str(match['temperature_K'])],
                                 'total_units':extras[str(match['temperature_K'])]+1}
                allocation_ok &= set(got)=={'temperature_K',*expected_fields.keys()}
                allocation_ok &= type(got.get('temperature_K')) is int and all(type(got.get(k)) is int for k in ('stage_one_units','stage_two_units','total_units'))
                d_rho=got.get('D_rho'); d_temp=got.get('D_T'); score=got.get('score')
                numeric_priority=all(type(value) in (int,float) and math.isfinite(float(value))
                                     for value in (d_rho,d_temp,score))
                allocation_ok &= numeric_priority
                allocation_ok &= close_abs(d_rho,expected_fields['D_rho'],_NUMERIC_REFS['priority_density_tolerance_g_cm3'])
                allocation_ok &= close(d_temp,expected_fields['D_T'])
                if numeric_priority:
                    allocation_ok &= close(score,max(d_rho,d_temp))
                allocation_ok &= all(close(got[k],expected_fields[k]) for k in ('stage_one_units','stage_two_units','total_units'))
            checks.append(check(allocation_ok,'bounded_input_driven_integer_allocation'))
            claims=decision.get('claim_status',{})
            honest=decision.get('execution_status')=='planned_only'
            honest &= claims.get('finite_window_density_and_drift')=='supported_observation'
            honest &= set(claims)=={'finite_window_density_and_drift','stationarity','equilibrium_density_precision','correlation_time_and_ess','equilibrium_temperature_response'}
            honest &= all(claims.get(k)=='not_identifiable' for k in ('stationarity','equilibrium_density_precision','correlation_time_and_ess','equilibrium_temperature_response'))
            # Older submissions may carry release-history metadata. It is not a
            # scientific deliverable, but any supplied historical record must be true.
            if 'historical_replay_status' in decision:
                replay=decision['historical_replay_status']
                honest &= isinstance(replay,dict) and set(replay)=={'status','reward','contract'}
                honest &= isinstance(replay,dict) and replay.get('status')=='FAIL' and type(replay.get('reward')) is int and replay.get('reward')==0
            honest &= decision.get('limitation_codes')==audit.get('limitation_codes')==expected_limits
            checks.append(check(honest,'claim_scope_and_historical_status'))
            report_ok=bool(report.strip()) and all(str(t) in report for t in TEMPERATURES)
            checks.append(check(report_ok,'human_report_present_and_temperature_specific'))
            status='PASS' if all(x['passed'] for x in checks) else 'FAIL'
            result={'schema':'reline02-verification/v2','status':status,'reward':1.0 if status=='PASS' else 0.0,'checks':checks}
            print(json.dumps(result,sort_keys=True,allow_nan=False))
            return 0 if status=='PASS' else 1
        except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError, RuntimeError, IndexError, AttributeError, OverflowError, UnicodeError) as exc:
            result={'schema':'reline02-verification/v2','status':'FAIL','reward':0.0,
                    'checks':checks+[check(False,'candidate_artifacts_valid',str(exc))]}
            print(json.dumps(result,sort_keys=True,allow_nan=False))
            return 1
    return SimpleNamespace(main=main)

def _make_case43_runner():
    #!/usr/bin/env python3
    """Check trusted pins, run the isolated deterministic verifier, and record reward."""

    import hashlib
    import json
    import os
    from pathlib import Path
    import subprocess
    import sys

    APP=Path(os.environ['APP']); TESTS=Path(os.environ['TESTS']); LOGS=Path(os.environ['LOGS'])
    LOGS.mkdir(parents=True,exist_ok=True)
    REPORT=LOGS/'scoring-report.json'; REWARD=LOGS/'reward.txt'


    def sha(path:Path)->str:
        h=hashlib.sha256()
        with path.open('rb') as f:
            for b in iter(lambda:f.read(1024*1024),b''):h.update(b)
        return h.hexdigest()


    def infra(message:str)->int:
        REWARD.unlink(missing_ok=True)
        REPORT.write_text(json.dumps({'schema':'reline02-scoring-report/v1','status':'INFRA_ERROR','reward':None,'error':message},sort_keys=True,indent=2)+'\n')
        print('INFRA_ERROR: '+message,file=sys.stderr)
        return 2


    def main()->int:
        try:
            REWARD.unlink(missing_ok=True)
            REPORT.unlink(missing_ok=True)
            refs=json.loads((TESTS/'reference-hashes.json').read_text())
            if not isinstance(refs,dict) or not refs:
                return infra('trusted reference-hashes.json is malformed')
            for rel,wanted in refs.items():
                if rel.startswith('inputs/') or rel=='output-contract.json': path=APP/rel
                elif rel.startswith('tests/'): path=TESTS/rel.removeprefix('tests/')
                else: return infra(f'unsupported trusted asset path: {rel}')
                if path.is_symlink() or not path.is_file() or sha(path)!=wanted:
                    return infra(f'trusted asset pin mismatch: {rel}')
            p=subprocess.run([sys.executable,'-B',str(TESTS/'verify.py')],cwd=APP,capture_output=True,text=True,timeout=90,
                             env={'PATH':os.environ.get('PATH','/usr/bin:/bin'),'HOME':'/tmp','APP':str(APP),'TESTS':str(TESTS),'LOGS':str(LOGS),'PYTHONDONTWRITEBYTECODE':'1'})
            try: diagnostic=json.loads(p.stdout)
            except json.JSONDecodeError: return infra(f'verifier returned no JSON (exit={p.returncode})')
            checks=diagnostic.get('checks')
            if not isinstance(checks,list) or not checks or any(not isinstance(x,dict) or type(x.get('passed')) is not bool for x in checks):
                return infra('verifier returned malformed checks')
            status=str(diagnostic.get('status','')).upper()
            if p.returncode not in (0,1) or status not in ('PASS','FAIL'):
                return infra(f'verifier returned unsupported status/exit: {status}/{p.returncode}')
            if (status=='PASS') != all(x['passed'] for x in checks):
                return infra('verifier status conflicts with checks')
            reward=1.0 if status=='PASS' else 0.0
            result={'schema':'reline02-scoring-report/v1','status':status,'reward':reward,'checks':checks,
                    'trusted_reference_sha256':sha(TESTS/'reference-hashes.json')}
            REPORT.write_text(json.dumps(result,sort_keys=True,indent=2,ensure_ascii=False)+'\n')
            REWARD.write_text(f'{reward:g}\n')
            print(f'{status}: reward={reward:g}')
            return 0 if status=='PASS' else 1
        except Exception as exc:
            return infra(f'{type(exc).__name__}: {exc}')


    def _runner_entry():
        raise SystemExit(main())
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
            logs, report_name = _prepare_runner_logs(43)
            sys.argv = [sys.argv[0]]
            runner = _make_case43_runner()
            runner.entry()
        except SystemExit:
            raise
        except Exception as exc:
            _runner_initialization_error(43, logs, report_name, exc)
    try:
        science = _make_case43_science()
        return science.main()
    except SystemExit:
        raise
    except Exception as exc:
        return _diagnostic_initialization_error(exc)


if __name__ == "__main__":
    raise SystemExit(_main_dispatch())
